"""Cobertura de altas, consultas, modificaciones y bajas logicas del administrador."""
from datetime import datetime, timezone

from bson import ObjectId

from database.seed import IDS


def login(client, runtime, role="admin"):
    prefix = "admin" if role == "admin" else "operator"
    return client.post("/api/v1/auth/login", json={
        "email": runtime[f"{prefix}_email"],
        "password": runtime[f"{prefix}_password"],
    })


def test_crud_usuario(client, database, runtime):
    assert login(client, runtime).status_code == 200
    assert client.post("/admin/usuarios", data={
        "nombre": "Operador Temporal", "email": "temporal@agrovic.demo",
        "rol": "operador", "password": "TemporalSegura9!", "activo": "on",
    }).status_code == 302
    user = database.usuarios.find_one({"email": "temporal@agrovic.demo"})
    assert user and user["activo"]
    response = client.get("/admin")
    assert b"temporal@agrovic.demo" in response.data
    path = f"/admin/usuarios/{user['_id']}"
    assert client.post(path + "/editar", data={
        "nombre": "Operador Actualizado", "email": "nuevo@agrovic.demo",
        "rol": "operador", "activo": "on", "control_manual": "on",
    }).status_code == 302
    updated = database.usuarios.find_one({"_id": user["_id"]})
    assert updated["nombre"] == "Operador Actualizado"
    assert updated["email"] == "nuevo@agrovic.demo"
    assert updated["control_manual_autorizado"] is True
    assert client.post(path + "/eliminar").status_code == 302
    assert database.usuarios.find_one({"_id": user["_id"]})["activo"] is False
    assert client.post(path + "/editar", data={
        "nombre": "Operador Actualizado", "email": "nuevo@agrovic.demo",
        "rol": "operador", "activo": "on",
    }).status_code == 302
    assert database.usuarios.find_one({"_id": user["_id"]})["activo"] is True
    assert database.auditoria.find_one({"evento": "usuario_desactivado", "objetivo": str(user["_id"])})


def test_crud_zona(client, database, runtime):
    assert login(client, runtime).status_code == 200
    assert client.post("/admin/zonas", data={
        "nombre": "Nueva Parcela", "cultivo": "Tomates", "ubicacion": "Sector C",
    }).status_code == 302
    zone = database.zonas_cultivo.find_one({"nombre": "Nueva Parcela"})
    assert zone and zone["activa"]
    assert b"Nueva Parcela" in client.get("/admin").data
    path = f"/admin/zonas/{zone['_id']}"
    assert client.post(path + "/editar", data={
        "nombre": "Parcela Modificada", "cultivo": "Lechugas",
        "ubicacion": "Sector D", "activa": "on",
    }).status_code == 302
    assert database.zonas_cultivo.find_one({"_id": zone["_id"]})["cultivo"] == "Lechugas"
    assert client.post(path + "/eliminar").status_code == 302
    assert database.zonas_cultivo.find_one({"_id": zone["_id"]})["activa"] is False
    assert client.post(path + "/editar", data={
        "nombre": "Parcela Modificada", "cultivo": "Lechugas",
        "ubicacion": "Sector D", "activa": "on",
    }).status_code == 302
    assert database.zonas_cultivo.find_one({"_id": zone["_id"]})["activa"] is True
    assert database.auditoria.find_one({"evento": "zona_desactivada", "objetivo": str(zone["_id"])})


def test_crud_dispositivo(client, database, runtime):
    assert login(client, runtime).status_code == 200
    response = client.post("/admin/dispositivos", data={
        "nombre": "Nuevo ESP32", "modelo": "ESP32-WROOM",
        "zona_id": str(IDS["zone_1"]), "intervalo_segundos": "180",
    })
    assert response.status_code == 201
    assert b"Token de provisi" in response.data
    device = database.dispositivos.find_one({"nombre": "Nuevo ESP32"})
    assert device and device["activo"]
    assert len(device["token_hash"]) == 64
    assert b"Nuevo ESP32" in client.get("/admin").data
    path = f"/admin/dispositivos/{device['_id']}"
    assert client.post(path + "/editar", data={
        "nombre": "ESP32 Modificado", "modelo": "ESP32-S3",
        "zona_id": str(IDS["zone_2"]), "intervalo_segundos": "240", "activo": "on",
    }).status_code == 302
    updated = database.dispositivos.find_one({"_id": device["_id"]})
    assert updated["nombre"] == "ESP32 Modificado"
    assert updated["zona_id"] == IDS["zone_2"]
    assert client.post(path + "/eliminar").status_code == 302
    assert database.dispositivos.find_one({"_id": device["_id"]})["activo"] is False
    assert client.post(path + "/editar", data={
        "nombre": "ESP32 Modificado", "modelo": "ESP32-S3",
        "zona_id": str(IDS["zone_2"]), "intervalo_segundos": "240", "activo": "on",
    }).status_code == 302
    assert database.dispositivos.find_one({"_id": device["_id"]})["estado"] == "pendiente"


def test_crud_permisos_y_bajas_seguras(client, database, runtime):
    assert login(client, runtime, "operator").status_code == 200
    for path in (
        f"/admin/usuarios/{IDS['admin']}/eliminar",
        f"/admin/zonas/{IDS['zone_1']}/eliminar",
        f"/admin/dispositivos/{IDS['device_1']}/eliminar",
        "/admin/dispositivos",
    ):
        assert client.post(path, data={}).status_code == 403
    assert login(client, runtime).status_code == 200
    assert client.post(f"/admin/usuarios/{IDS['admin']}/eliminar").status_code == 409
    assert database.usuarios.find_one({"_id": IDS["admin"]})["activo"]
    database.eventos_riego.insert_one({
        "_id": ObjectId(), "zona_id": IDS["zone_1"],
        "usuario_id": IDS["operator"], "tipo": "manual",
        "fuente": "principal", "estado": "activo",
        "volumen_l": 2.0, "iniciado_en": datetime.now(timezone.utc),
    })
    assert client.post(f"/admin/zonas/{IDS['zone_1']}/eliminar").status_code == 409
    assert database.zonas_cultivo.find_one({"_id": IDS["zone_1"]})["activa"]


def test_crud_baja_zona_conserva_lecturas(client, database, runtime):
    assert login(client, runtime).status_code == 200
    before = database.lecturas_sensor.count_documents({"meta.zona_id": IDS["zone_1"]})
    assert client.post(f"/admin/zonas/{IDS['zone_1']}/eliminar").status_code == 302
    assert database.dispositivos.count_documents({"zona_id": IDS["zone_1"], "activo": True}) == 0
    assert database.lecturas_sensor.count_documents({"meta.zona_id": IDS["zone_1"]}) == before


def test_crud_validacion(client, database, runtime):
    assert login(client, runtime).status_code == 200
    assert client.post("/admin/dispositivos", data={
        "nombre": "X", "modelo": "X", "zona_id": str(IDS["zone_1"]), "intervalo_segundos": "10",
    }).status_code == 400
    assert client.post(f"/admin/zonas/{IDS['zone_1']}/editar", data={
        "nombre": "A", "cultivo": "B", "ubicacion": "C", "activa": "on",
    }).status_code == 400
    assert client.post("/admin/usuarios/id-invalido/eliminar").status_code == 404
    page = client.get("/admin")
    assert page.status_code == 200
    assert b"Gestionar usuarios" in page.data
    assert b"Gestionar zonas" in page.data
    assert b"Gestionar dispositivos" in page.data
