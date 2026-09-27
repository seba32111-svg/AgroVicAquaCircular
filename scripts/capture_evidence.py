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

    print(f"Evidencias capturadas: {len(summary['results'])} casos y 5 vistas de interfaz.")


if __name__ == "__main__":
    main()
