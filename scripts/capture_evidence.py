"""Captura interfaces y tarjetas de evidencia desde una ejecución real."""
from __future__ import annotations

import html
import json
import os
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ARTIFACTS = Path("artifacts")
EVIDENCE = ARTIFACTS / "evidence"


def wait_for_server(url: str, seconds: int = 40):
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url}/health", timeout=2) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(1)
    raise RuntimeError("La aplicación no respondió dentro del tiempo esperado.")


def evidence_html(summary: dict) -> str:
    cards = []
    for item in summary["results"]:
        inputs = html.escape(str(item["inputs"]))
        observed = html.escape(str(item["observed"]))
        requirements = " · ".join(item["requirements"])
        cards.append(
            f"""
            <article class="evidence" id="{item['evidence']}">
              <header><span>{item['evidence']}</span><b>{item['status']}</b></header>
              <p class="case">{item['case']} · {html.escape(item['title'])}</p>
              <div class="line"><strong>Entrada / acción</strong><p>{inputs}</p></div>
              <div class="line result"><strong>Resultado observado</strong><p>{observed}</p></div>
              <footer><span>Requisitos: {requirements}</span><span>pytest · MongoDB · ejecución CI</span></footer>
            </article>
            """
        )
    return f"""<!doctype html>
    <html lang="es"><head><meta charset="utf-8"><style>
      *{{box-sizing:border-box}} body{{margin:0;padding:36px;background:#edf3ef;color:#10272b;font-family:Arial,sans-serif}}
      .evidence{{width:1120px;min-height:480px;margin:0 auto 34px;padding:34px;border:1px solid #cbded6;border-radius:24px;background:white;box-shadow:0 20px 55px rgba(13,58,50,.12)}}
      header{{display:flex;justify-content:space-between;align-items:center;padding-bottom:22px;border-bottom:1px solid #dce8e2}}
      header span{{font-size:38px;font-weight:900;color:#0f756b}} header b{{padding:10px 16px;border-radius:99px;color:#156a5b;background:#dff6ed;font-size:15px}}
      .case{{font-size:25px;font-weight:800;margin:28px 0}} .line{{padding:18px;border-radius:14px;background:#f4f7f4;margin:12px 0}}
      .line.result{{background:#e9f8f3}} .line strong{{display:block;color:#55706c;text-transform:uppercase;font-size:12px;letter-spacing:1.5px}}
      .line p{{font-size:18px;line-height:1.45;margin:8px 0 0}} footer{{display:flex;justify-content:space-between;margin-top:28px;color:#617773;font-size:13px}}
    </style></head><body>{''.join(cards)}</body></html>"""


def capture_crud_evidence(page):
    """Capturas reales de altas, consultas, ediciones y bajas en la base de demostracion."""
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:5000")
    page.goto(f"{base_url}/admin")

    def record(section_title, text):
        panel = page.locator("section.panel").filter(
            has=page.get_by_role("heading", name=section_title)
        )
        result = panel.locator(".crud-item").filter(has_text=text)
        if result.count() != 1:
            raise RuntimeError(f"Registro de prueba no encontrado: {text}")
        return result

    def screenshot(item, name):
        item.screenshot(path=EVIDENCE / name)

    def deactivate(item):
        page.once("dialog", lambda dialog: dialog.accept())
        item.get_by_role("button", name="Eliminar / desactivar").click()

    user_form = page.locator('form[action="/admin/usuarios"]')
    user_form.locator('input[name="nombre"]').fill("Operador Evidencia CI")
    user_form.locator('input[name="email"]').fill("evidencia.crud@agrovic.demo")
    user_form.locator('input[name="password"]').fill("EvidenciaAq9!2026")
    user_form.get_by_role("button", name="Crear cuenta").click()
    name = "Gestionar usuarios y operadores"
    item = record(name, "evidencia.crud@agrovic.demo")
    screenshot(item, "UI06_crud_usuarios_crear_leer.png")
    item.locator("summary").click()
    item.locator('input[name="nombre"]').fill("Operador Evidencia Modificado")
    screenshot(item, "UI07_crud_usuarios_edicion.png")
    item.get_by_role("button", name="Guardar usuario").click()
    item = record(name, "evidencia.crud@agrovic.demo")
    assert "Operador Evidencia Modificado" in item.inner_text()
    deactivate(item)
    item = record(name, "evidencia.crud@agrovic.demo")
    assert "Inactivo" in item.inner_text()
    screenshot(item, "UI08_crud_usuarios_desactivado.png")

    zone_form = page.locator('form[action="/admin/zonas"]')
    zone_form.locator('input[name="nombre"]').fill("Sector Evidencia CI")
    zone_form.locator('input[name="cultivo"]').fill("Hortalizas")
    zone_form.locator('input[name="ubicacion"]').fill("Sector experimental")
    zone_form.get_by_role("button", name="Incorporar zona").click()
    name = "Gestionar zonas de cultivo"
    item = record(name, "Sector Evidencia CI")
    screenshot(item, "UI09_crud_zonas_crear_leer.png")
    item.locator("summary").click()
    item.locator('input[name="cultivo"]').fill("Cultivo experimental")
    screenshot(item, "UI10_crud_zonas_edicion.png")
    item.get_by_role("button", name="Guardar zona").click()
    item = record(name, "Sector Evidencia CI")
    assert "Cultivo experimental" in item.inner_text()
    deactivate(item)
    item = record(name, "Sector Evidencia CI")
    assert "Inactiva" in item.inner_text()
    screenshot(item, "UI11_crud_zonas_desactivada.png")

    device_form = page.locator('form[action="/admin/dispositivos"]')
    device_form.locator('input[name="nombre"]').fill("ESP32 Evidencia CI")
    device_form.locator('input[name="modelo"]').fill("ESP32-S3")
    device_form.locator('select[name="zona_id"]').select_option(index=0)
    device_form.locator('input[name="intervalo_segundos"]').fill("300")
    device_form.get_by_role("button", name="Agregar dispositivo").click()
    assert page.get_by_role("heading", name="Token de provisión").is_visible()
    # La credencial de aprovisionamiento no se captura ni se publica.
    page.get_by_role("link", name="Volver a Administración").click()
    name = "Gestionar dispositivos ESP32"
    item = record(name, "ESP32 Evidencia CI")
    screenshot(item, "UI12_crud_dispositivos_crear_leer.png")
    item.locator("summary").click()
    item.locator('input[name="nombre"]').fill("ESP32 Evidencia Modificado")
    item.locator('input[name="intervalo_segundos"]').fill("180")
    screenshot(item, "UI13_crud_dispositivos_edicion.png")
    item.get_by_role("button", name="Guardar dispositivo").click()
    item = record(name, "ESP32 Evidencia Modificado")
    deactivate(item)
    item = record(name, "ESP32 Evidencia Modificado")
    assert "Inactivo" in item.inner_text()
    screenshot(item, "UI14_crud_dispositivos_desactivado.png")


def main():
    base_url = os.getenv("BASE_URL", "http://127.0.0.1:5000")
    runtime = json.loads((ARTIFACTS / "runtime_credentials.json").read_text(encoding="utf-8"))
    summary = json.loads((ARTIFACTS / "test_results.json").read_text(encoding="utf-8"))
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    report_path = EVIDENCE / "index.html"
    report_path.write_text(evidence_html(summary), encoding="utf-8")
    wait_for_server(base_url)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        admin = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = admin.new_page()
        page.goto(f"{base_url}/login")
        page.get_by_label("Correo electrónico").fill(runtime["admin_email"])
        page.get_by_label("Contraseña").fill(runtime["admin_password"])
        page.get_by_role("button", name="Ingresar").click()
        page.wait_for_url(f"{base_url}/")
        page.screenshot(path=EVIDENCE / "UI01_panel_administrador.png", full_page=True)
        page.goto(f"{base_url}/admin")
        page.screenshot(path=EVIDENCE / "UI02_formularios_administracion.png", full_page=True)
        page.goto(f"{base_url}/alertas")
        page.screenshot(path=EVIDENCE / "UI03_centro_alertas.png", full_page=True)
        page.goto(f"{base_url}/reportes")
        page.screenshot(path=EVIDENCE / "UI04_balance_hidrico.png", full_page=True)
        capture_crud_evidence(page)
        admin.close()

        operator = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        page = operator.new_page()
        page.goto(f"{base_url}/login")
        page.get_by_label("Correo electrónico").fill(runtime["operator_email"])
        page.get_by_label("Contraseña").fill(runtime["operator_password"])
        page.get_by_role("button", name="Ingresar").click()
        page.wait_for_url(f"{base_url}/")
        page.screenshot(path=EVIDENCE / "UI05_panel_operador_movil.png", full_page=True)
        operator.close()

        cards = browser.new_context(viewport={"width": 1280, "height": 720})
        page = cards.new_page()
        page.goto(report_path.resolve().as_uri())
        for item in summary["results"]:
            locator = page.locator(f"#{item['evidence']}")
            locator.screenshot(path=EVIDENCE / f"{item['evidence']}_{item['case']}.png")
        cards.close()
        browser.close()

    print(f"Evidencias capturadas: {len(summary['results'])} casos y 5 vistas de interfaz y 9 capturas CRUD.")


if __name__ == "__main__":
    main()
