from __future__ import annotations

import secrets
import time
from datetime import timedelta

from bson import ObjectId

from backend.app import enforce_watchdog, utcnow
from database.seed import IDS


def login(client, runtime, role="admin"):
    prefix = "admin" if role == "admin" else "operator"
    return client.post(
        "/api/v1/auth/login",
        json={
            "email": runtime[f"{prefix}_email"],
            "password": runtime[f"{prefix}_password"],
        },
    )


def measurement(key, **changes):
    payload = {
        "timestamp": utcnow().isoformat(),
        "idempotency_key": key,
        "humedad_suelo_pct": 31.5,
        "lluvia": False,
        "nivel_principal_pct": 76.0,
        "nivel_recuperada_pct": 58.0,
        "caudal_l_min": 2.8,
        "turbidez_ntu": 2.4,
        "conductividad_us_cm": 760.0,
        "volumen_recuperado_l": 0.5,
    }
    payload.update(changes)
    return payload


def device_headers(runtime):
    return {"X-Device-Token": runtime["device_token"]}


def test_cp01_valid_login_and_dashboard(client, database, runtime, record):
    response = login(client, runtime, "admin")
    dashboard = client.get("/")
    assert response.status_code == 200
    assert response.json["usuario"]["rol"] == "administrador"
    assert dashboard.status_code == 200
    assert "Panel hídrico".encode() in dashboard.data
    assert database.auditoria.count_documents({"evento": "inicio_sesion_api", "resultado": "exitoso"}) == 1
    record(
        "CP01",
        "Inicio de sesión válido",
        "Cuenta Administrador activa",
        "HTTP 200, sesión creada, panel visible y auditoría registrada",
        ["RF01", "RF15", "RNF01"],
    )


def test_cp02_invalid_login_and_rate_control(client, database, runtime, record):
    statuses = []
    for _ in range(5):
        statuses.append(
            client.post(
                "/api/v1/auth/login",
                json={"email": runtime["admin_email"], "password": secrets.token_urlsafe(16)},
            ).status_code
        )
    statuses.append(
        client.post(
            "/api/v1/auth/login",
            json={"email": runtime["admin_email"], "password": secrets.token_urlsafe(16)},
        ).status_code
    )
    assert statuses == [401, 401, 401, 401, 401, 429]
    assert database.auditoria.count_documents({"evento": "inicio_sesion", "resultado": "fallido"}) == 5
    record(
        "CP02",
        "Credenciales inválidas y control de intentos",
        "Cinco contraseñas aleatorias y un sexto intento",
        f"Estados observados: {statuses}; sexto intento bloqueado",
        ["RF01", "RNF01", "RNF03"],
    )


def test_cp03_role_permissions(client, app, runtime, record):
    operator_login = login(client, runtime, "operator")
    operator_dashboard = client.get("/")
    denied = client.get("/admin")
    admin_client = app.test_client()
    admin_login = login(admin_client, runtime, "admin")
    allowed = admin_client.get("/admin")
    assert operator_login.status_code == 200
    assert operator_dashboard.status_code == 200
    assert denied.status_code == 403
    assert admin_login.status_code == 200
    assert allowed.status_code == 200
    record(
        "CP03",
        "Permisos diferenciados",
        "Operador consulta panel y administración; Administrador consulta administración",
        "Operador: panel 200 y administración 403. Administrador: administración 200",
        ["RF02", "RNF03"],
    )


def test_cp04_secure_recovery_one_use(client, database, runtime, record):
    requested = client.post(
        "/api/v1/auth/recuperaciones", json={"email": runtime["operator_email"]}
    )
    token = requested.json["test_token"]
    replacement = f"NuevaAq9!{secrets.token_urlsafe(10)}"
    changed = client.post(
        f"/api/v1/auth/recuperaciones/{token}", json={"password": replacement}
    )
    reused = client.post(
        f"/api/v1/auth/recuperaciones/{token}", json={"password": replacement}
    )
    assert requested.status_code == 202
    assert changed.status_code == 200
    assert reused.status_code == 410
    assert database.tokens_recuperacion.find_one({"usado_en": {"$ne": None}})
    record(
        "CP04",
        "Recuperación segura",
        "Solicitud válida, cambio de contraseña y reutilización del mismo enlace",
        "Solicitud 202, cambio 200 y segundo uso rechazado con 410",
        ["RF01", "RNF01", "RNF03"],
    )


def test_cp05_manage_users_zones_sources_devices_rules(client, database, runtime, record):
    assert login(client, runtime, "admin").status_code == 200
    user_password = f"TemporalAq9!{secrets.token_urlsafe(8)}"
    user_response = client.post(
        "/admin/usuarios",
        data={
            "nombre": "Operador Temporal",
            "email": "operador.temporal@example.test",
            "rol": "operador",
            "password": user_password,
            "activo": "on",
            "control_manual": "on",
        },
    )
    zone_response = client.post(
        "/admin/zonas",
        data={"nombre": "Parcela Experimental", "cultivo": "Tomate", "ubicacion": "Sector C"},
    )
    zone = database.zonas_cultivo.find_one({"nombre": "Parcela Experimental"})
    rule_response = client.post(
        "/admin/reglas",
        data={
            "zona_id": str(zone["_id"]),
            "humedad_inicio_pct": "34",
            "humedad_detencion_pct": "46",
            "nivel_recuperada_min_pct": "18",
            "turbidez_max_ntu": "4.5",
            "conductividad_max_us_cm": "1100",
            "duracion_max_min": "10",
            "prioridad_fuente": "recuperada",
            "horario_inicio": "06:30",
        },
    )
    source_response = client.post(
        "/api/v1/fuentes",
        json={
            "zona_id": str(zone["_id"]),
            "tipo": "recuperada",
            "nombre": "Estanque Experimental",
            "capacidad_l": 250,
        },
    )
    device_response = client.post(
        "/api/v1/dispositivos",
        json={"zona_id": str(zone["_id"]), "nombre": "ESP32 Experimental", "modelo": "ESP32"},
    )
    device_id = device_response.json["dispositivo_id"]
    patch_response = client.patch(
        f"/api/v1/dispositivos/{device_id}", json={"estado": "conectado"}
    )
    invalid_zone = client.post(
        "/admin/zonas", data={"nombre": "", "cultivo": "", "ubicacion": ""}
    )
    assert user_response.status_code == 302
    assert zone_response.status_code == 302
    assert rule_response.status_code == 302
    assert source_response.status_code == 201
    assert device_response.status_code == 201
    assert patch_response.status_code == 200
    assert invalid_zone.status_code == 400
    assert database.usuarios.find_one({"email": "operador.temporal@example.test"})
    record(
        "CP05",
        "Gestión de maestros y formularios",
        "Alta de usuario, zona, regla, fuente y dispositivo; zona vacía",
        "Cinco operaciones válidas persistidas y entrada vacía rechazada con 400",
        ["RF03", "RF04", "RF05", "RF11", "RNF04"],
    )


def test_cp06_valid_measurement_and_idempotency(client, database, runtime, record):
    before = database.lecturas_sensor.count_documents({})
    first = client.post(
        "/api/v1/lecturas",
        json=measurement("cp06-idempotente"),
        headers=device_headers(runtime),
    )
    second = client.post(
        "/api/v1/lecturas",
        json=measurement("cp06-idempotente"),
        headers=device_headers(runtime),
    )
    after = database.lecturas_sensor.count_documents({})
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json["duplicada"] is True
    assert after == before + 1
    record(
        "CP06",
        "Lectura válida e idempotencia",
        "La misma medición se envía dos veces con igual clave",
        f"Primera 201, repetición 200 marcada duplicada; conteo {before}→{after}",
        ["RF06", "RF07", "RNF04", "RNF09"],
    )


def test_cp07_invalid_measurement_rejected(client, database, runtime, record):
    before = database.lecturas_sensor.count_documents({})
    response = client.post(
        "/api/v1/lecturas",
        json=measurement("cp07-invalida", humedad_suelo_pct=145),
        headers=device_headers(runtime),
    )
    after = database.lecturas_sensor.count_documents({})
    assert response.status_code == 422
    assert response.json["error"] == "lectura_invalida"
    assert after == before
    record(
        "CP07",
        "Lectura fuera de rango",
        "Humedad de suelo = 145%",
        f"HTTP 422; base permanece en {after} lecturas",
        ["RF06", "RNF04"],
    )


def test_cp08_dashboard_responsive_and_performance(client, runtime, record):
    assert login(client, runtime, "operator").status_code == 200
    durations = []
    response = None
    for _ in range(25):
        started = time.perf_counter()
        response = client.get("/")
        durations.append((time.perf_counter() - started) * 1000)
    p95 = sorted(durations)[int(len(durations) * 0.95) - 1]
    assert response.status_code == 200
    assert b'name="viewport"' in response.data
    assert p95 < 3000
    record(
        "CP08",
        "Panel responsive y tiempo de respuesta",
        "25 solicitudes al panel y revisión de viewport",
        f"p95={p95:.2f} ms; meta viewport presente; HTTP 200",
        ["RF12", "RNF05", "RNF07", "RNF08"],
    )


def test_cp09_recovered_water_priority(client, database, runtime, record):
    response = client.post(
        "/api/v1/lecturas",
        json=measurement("cp09-recuperada", nivel_recuperada_pct=65, turbidez_ntu=2.1),
        headers=device_headers(runtime),
    )
    stored = database.lecturas_sensor.find_one({"idempotency_key": "cp09-recuperada"})
    assert response.status_code == 201
    assert response.json["fuente_autorizada"] == "recuperada"
    assert stored["calidad_lectura"] == "valida"
    record(
        "CP09",
        "Prioridad de agua recuperada apta",
        "Nivel 65%, turbidez 2.1 NTU y conductividad 760 µS/cm",
        "Lectura aceptada y fuente autorizada = recuperada",
        ["RF08", "RF11"],
    )


def test_cp10_bad_quality_blocks_reuse(client, database, runtime, record):
    response = client.post(
        "/api/v1/lecturas",
        json=measurement("cp10-calidad", turbidez_ntu=18),
        headers=device_headers(runtime),
    )
    alert = database.alertas.find_one({"tipo": "calidad_fuera_rango", "estado": "activa"})
    assert response.status_code == 201
    assert response.json["fuente_autorizada"] == "principal"
    assert alert
    record(
        "CP10",
        "Bloqueo por calidad",
        "Turbidez 18 NTU con máximo configurado de 5 NTU",
        "Medición conservada, reúso bloqueado, fuente principal y alerta activa",
        ["RF08", "RF09", "RF13"],
    )


def test_cp11_low_recovered_level_fallback(client, database, runtime, record):
    response = client.post(
        "/api/v1/lecturas",
        json=measurement("cp11-nivel", nivel_recuperada_pct=6),
        headers=device_headers(runtime),
    )
    alert = database.alertas.find_one({"tipo": "nivel_recuperada_bajo"})
    assert response.status_code == 201
    assert response.json["fuente_autorizada"] == "principal"
    assert alert
    record(
        "CP11",
        "Respaldo por nivel bajo",
        "Estanque recuperado al 6% con mínimo de 15%",
        "Fuente principal seleccionada y alerta de nivel registrada",
        ["RF08", "RF09", "RF13"],
    )


def test_cp12_authorized_manual_irrigation_and_audit(client, database, runtime, record):
    assert login(client, runtime, "operator").status_code == 200
    response = client.post(
        "/api/v1/riegos",
        json={
            "zona_id": str(IDS["zone_1"]),
            "accion": "iniciar",
            "fuente": "recuperada",
            "duracion_min": 6,
            "volumen_l": 14,
            "motivo": "Inspección de válvula sector norte",
        },
    )
    assert response.status_code == 201
    assert response.json["evento"]["estado"] == "activo"
    assert database.auditoria.find_one({"evento": "riego_manual", "resultado": "iniciado"})
    record(
        "CP12",
        "Riego manual autorizado",
        "Operador autorizado, fuente recuperada, 6 min y motivo informado",
        "HTTP 201, evento activo y auditoría vinculada",
        ["RF10", "RF15", "RNF03"],
    )


def test_cp13_unauthorized_and_conflicting_order(client, database, runtime, record):
    payload = {
        "zona_id": str(IDS["zone_1"]),
        "accion": "iniciar",
        "fuente": "principal",
        "duracion_min": 5,
        "volumen_l": 11,
        "motivo": "Control operativo de seguridad",
    }
    anonymous = client.post("/api/v1/riegos", json=payload)
    assert login(client, runtime, "operator").status_code == 200
    database.usuarios.update_one(
        {"_id": IDS["operator"]}, {"$set": {"control_manual_autorizado": False}}
    )
    unauthorized = client.post("/api/v1/riegos", json=payload)
    database.usuarios.update_one(
        {"_id": IDS["operator"]}, {"$set": {"control_manual_autorizado": True}}
    )
    accepted = client.post("/api/v1/riegos", json=payload)
    conflict = client.post("/api/v1/riegos", json=payload)
    assert anonymous.status_code == 401
    assert unauthorized.status_code == 403
    assert accepted.status_code == 201
    assert conflict.status_code == 409
    record(
        "CP13",
        "Orden no autorizada y conflicto",
        "Solicitud anónima, operador sin permiso y dos inicios consecutivos",
        "Estados 401, 403, 201 y 409 respectivamente",
        ["RF02", "RF09", "RF10", "RNF03"],
    )


def test_cp14_alert_confirmation_and_critical_close(client, app, database, runtime, record):
    alert_id = str(ObjectId("670000000000000000000003"))
    assert login(client, runtime, "operator").status_code == 200
    denied = client.patch(
        f"/api/v1/alertas/{alert_id}/confirmacion", json={"accion": "cerrar"}
    )
    confirmed = client.patch(
        f"/api/v1/alertas/{alert_id}/confirmacion", json={"accion": "confirmar"}
    )
    admin_client = app.test_client()
    assert login(admin_client, runtime, "admin").status_code == 200
    closed = admin_client.patch(
        f"/api/v1/alertas/{alert_id}/confirmacion", json={"accion": "cerrar"}
    )
    assert denied.status_code == 403
    assert confirmed.status_code == 200
    assert closed.status_code == 200
    assert database.alertas.find_one({"_id": ObjectId(alert_id)})["estado"] == "cerrada"
    record(
        "CP14",
        "Confirmación y cierre de alerta crítica",
        "Operador intenta cerrar, confirma; Administrador cierra",
        "Operador: 403 al cerrar y 200 al confirmar. Administrador: cierre 200",
        ["RF02", "RF13", "RF15"],
    )


def test_cp15_balance_history_and_export(client, database, runtime, record):
    assert login(client, runtime, "operator").status_code == 200
    response = client.get("/api/v1/reportes/balance")
    export = client.get("/reportes/balance.csv")
    balance = response.json["balance"]
    assert response.status_code == 200
    assert balance["consumo_total_l"] == 294.0
    assert balance["agua_reutilizada_l"] == 197.0
    assert balance["ciclos_reutilizacion"] == 10
    assert balance["sustitucion_pct"] == 67.01
    assert database.lecturas_sensor.count_documents({}) == 500
    assert export.status_code == 200
    assert len(export.data.splitlines()) >= 15
    record(
        "CP15",
        "Balance, historial y exportación",
        "500 lecturas y 14 ciclos cerrados, 10 con fuente recuperada",
        "294 L totales, 197 L reutilizados, 67.01% sustitución y CSV descargable",
        ["RF14", "RF15", "OE6"],
    )


def test_cp16_watchdog_safe_stop_and_disconnect(database, record):
    now = utcnow()
    event_id = database.eventos_riego.insert_one(
        {
            "zona_id": IDS["zone_1"],
            "usuario_id": IDS["operator"],
            "tipo": "manual",
            "fuente": "principal",
            "estado": "activo",
            "motivo": "Caso watchdog",
            "duracion_programada_min": 12,
            "volumen_l": 7.0,
            "iniciado_en": now - timedelta(minutes=20),
            "finalizado_en": None,
        }
    ).inserted_id
    database.dispositivos.update_one(
        {"_id": IDS["device_1"]},
        {"$set": {"ultima_conexion": now - timedelta(minutes=15), "estado": "conectado"}},
    )
    result = enforce_watchdog(database, now)
    event = database.eventos_riego.find_one({"_id": event_id})
    device = database.dispositivos.find_one({"_id": IDS["device_1"]})
    assert result == {"riegos_detenidos": 1, "dispositivos_desconectados": 1}
    assert event["estado"] == "detenido_seguridad"
    assert device["estado"] == "desconectado"
    assert database.alertas.find_one({"tipo": "dispositivo_desconectado"})
    record(
        "CP16",
        "Watchdog y pérdida de conexión",
        "Riego activo por 20 min y ESP32 sin telemetría por 15 min",
        "Riego detenido, dispositivo desconectado y alertas críticas creadas",
        ["RF09", "RF13", "RNF06"],
    )
