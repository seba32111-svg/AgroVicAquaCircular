"""Siembra reproducible y exportación MongoDB de AgroVic AquaCircular."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import bcrypt
from bson import ObjectId, json_util
from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, MongoClient

IDS = {
    "admin": ObjectId("66a000000000000000000001"),
    "operator": ObjectId("66a000000000000000000002"),
    "zone_1": ObjectId("66b000000000000000000001"),
    "zone_2": ObjectId("66b000000000000000000002"),
    "device_1": ObjectId("66c000000000000000000001"),
    "device_2": ObjectId("66c000000000000000000002"),
    "source_main_1": ObjectId("66d000000000000000000001"),
    "source_recovered_1": ObjectId("66d000000000000000000002"),
    "source_main_2": ObjectId("66d000000000000000000003"),
    "source_recovered_2": ObjectId("66d000000000000000000004"),
    "rule_1": ObjectId("66e000000000000000000001"),
    "rule_2": ObjectId("66e000000000000000000002"),
}


def now_utc():
    return datetime.now(timezone.utc).replace(microsecond=0)


def generated_password(prefix: str) -> str:
    return f"{prefix}Aq9!{secrets.token_urlsafe(12)}"


def demo_credentials() -> dict:
    """Credenciales demo desde SEED_* (.env) o aleatorias si no están definidas."""
    from backend.app import validate_password

    credentials = {
        "admin_email": os.getenv("SEED_ADMIN_EMAIL") or "admin@agrovic.demo",
        "admin_password": os.getenv("SEED_ADMIN_PASSWORD") or generated_password("Admin"),
        "operator_email": os.getenv("SEED_OPERATOR_EMAIL") or "operador@agrovic.demo",
        "operator_password": os.getenv("SEED_OPERATOR_PASSWORD") or generated_password("Oper"),
    }
    for role, variable in (("admin", "SEED_ADMIN_PASSWORD"), ("operator", "SEED_OPERATOR_PASSWORD")):
        if not validate_password(credentials[f"{role}_password"]):
            raise SystemExit(
                f"{variable} no cumple la política: mínimo 10 caracteres, mayúscula, minúscula, número y símbolo."
            )
    return credentials


def create_collections(database):
    existing = set(database.list_collection_names())
    if "lecturas_sensor" not in existing:
        database.create_collection(
            "lecturas_sensor",
            timeseries={"timeField": "timestamp", "metaField": "meta", "granularity": "minutes"},
        )
    validators = {
        "usuarios": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["nombre", "email", "rol", "password_hash", "activo"],
                "properties": {
                    "email": {"bsonType": "string"},
                    "rol": {"enum": ["administrador", "operador"]},
                    "activo": {"bsonType": "bool"},
                },
            }
        },
        "zonas_cultivo": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["nombre", "cultivo", "ubicacion", "activa"],
            }
        },
        "dispositivos": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["nombre", "zona_id", "token_hash", "activo", "estado"],
            }
        },
        "fuentes_agua": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["zona_id", "tipo", "nombre", "activa"],
            }
        },
        "reglas_riego": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["zona_id", "version", "humedad_inicio_pct", "humedad_detencion_pct", "activa"],
            }
        },
        "eventos_riego": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["zona_id", "fuente", "estado", "volumen_l", "iniciado_en"],
            }
        },
        "alertas": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["zona_id", "tipo", "severidad", "estado", "creada_en"],
            }
        },
        "auditoria": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["timestamp", "evento", "resultado"],
            }
        },
        "tokens_recuperacion": {
            "$jsonSchema": {
                "bsonType": "object",
                "required": ["usuario_id", "token_hash", "expira_en"],
            }
        },
    }
    for name, validator in validators.items():
        if name not in existing:
            database.create_collection(name, validator=validator)


def create_indexes(database):
    database.usuarios.create_index("email", unique=True)
    database.lecturas_sensor.create_index(
        [("meta.zona_id", ASCENDING), ("timestamp", DESCENDING)]
    )
    database.lecturas_sensor.create_index(
        [("meta.dispositivo_id", ASCENDING), ("idempotency_key", ASCENDING)]
    )
    database.eventos_riego.create_index([("zona_id", ASCENDING), ("iniciado_en", DESCENDING)])
    database.alertas.create_index([("estado", ASCENDING), ("creada_en", DESCENDING)])
    database.auditoria.create_index([("timestamp", DESCENDING)])
    database.tokens_recuperacion.create_index("expira_en", expireAfterSeconds=0)


def export_collections(database, export_dir: Path):
    export_dir.mkdir(parents=True, exist_ok=True)
    for name in sorted(database.list_collection_names()):
        documents = list(database[name].find())
        (export_dir / f"{name}.json").write_text(
            json_util.dumps(documents, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


def seed_database(
    uri: str,
    database_name: str,
    *,
    if_empty: bool = False,
    export_dir: str | Path | None = None,
    artifact_dir: str | Path | None = None,
    credentials: dict | None = None,
    device_token: str | None = None,
):
    client = MongoClient(uri, serverSelectionTimeoutMS=8000, tz_aware=True)
    client.admin.command("ping")
    database = client[database_name]
    artifact_path = Path(artifact_dir or "artifacts")
    runtime_path = artifact_path / "runtime_credentials.json"
    if if_empty and "usuarios" in database.list_collection_names() and database.usuarios.count_documents({}):
        if runtime_path.exists():
            return json.loads(runtime_path.read_text(encoding="utf-8"))
        return {"database": database_name, "already_seeded": True}

    client.drop_database(database_name)
    database = client[database_name]
    create_collections(database)
    create_indexes(database)

    credentials = credentials or demo_credentials()
    device_token = device_token or secrets.token_urlsafe(32)
    current = now_utc()

    users = [
        {
            "_id": IDS["admin"],
            "nombre": "Administrador AgroVic",
            "email": credentials["admin_email"],
            "rol": "administrador",
            "activo": True,
            "control_manual_autorizado": True,
            "password_hash": bcrypt.hashpw(credentials["admin_password"].encode(), bcrypt.gensalt()).decode(),
            "creado_en": current - timedelta(days=30),
        },
        {
            "_id": IDS["operator"],
            "nombre": "Operador de Riego",
            "email": credentials["operator_email"],
            "rol": "operador",
            "activo": True,
            "control_manual_autorizado": True,
            "password_hash": bcrypt.hashpw(credentials["operator_password"].encode(), bcrypt.gensalt()).decode(),
            "creado_en": current - timedelta(days=30),
        },
    ]
    database.usuarios.insert_many(users)

    zones = [
        {
            "_id": IDS["zone_1"],
            "nombre": "Parcela Norte",
            "cultivo": "Vid de mesa",
            "ubicacion": "Sector A · Piloto",
            "superficie_m2": 480,
            "activa": True,
            "creada_en": current - timedelta(days=28),
        },
        {
            "_id": IDS["zone_2"],
            "nombre": "Parcela Sur",
            "cultivo": "Hortalizas",
            "ubicacion": "Sector B · Piloto",
            "superficie_m2": 320,
            "activa": True,
            "creada_en": current - timedelta(days=28),
        },
    ]
    database.zonas_cultivo.insert_many(zones)

    token_hash = hashlib.sha256(device_token.encode()).hexdigest()
    devices = [
        {
            "_id": IDS["device_1"],
            "nombre": "ESP32 Norte",
            "modelo": "ESP32-WROOM",
            "zona_id": IDS["zone_1"],
            "token_hash": token_hash,
            "estado": "conectado",
            "activo": True,
            "intervalo_segundos": 300,
            "ultima_conexion": current - timedelta(minutes=1),
        },
        {
            "_id": IDS["device_2"],
            "nombre": "ESP32 Sur",
            "modelo": "ESP32-WROOM",
            "zona_id": IDS["zone_2"],
            "token_hash": token_hash,
            "estado": "conectado",
            "activo": True,
            "intervalo_segundos": 300,
            "ultima_conexion": current - timedelta(minutes=2),
        },
    ]
    database.dispositivos.insert_many(devices)

    database.fuentes_agua.insert_many(
        [
            {
                "_id": IDS["source_main_1"],
                "zona_id": IDS["zone_1"],
                "tipo": "principal",
                "nombre": "Red principal Norte",
                "capacidad_l": 1000,
                "activa": True,
            },
            {
                "_id": IDS["source_recovered_1"],
                "zona_id": IDS["zone_1"],
                "tipo": "recuperada",
                "nombre": "Estanque circular Norte",
                "capacidad_l": 450,
                "activa": True,
            },
            {
                "_id": IDS["source_main_2"],
                "zona_id": IDS["zone_2"],
                "tipo": "principal",
                "nombre": "Red principal Sur",
                "capacidad_l": 800,
                "activa": True,
            },
            {
                "_id": IDS["source_recovered_2"],
                "zona_id": IDS["zone_2"],
                "tipo": "recuperada",
                "nombre": "Estanque circular Sur",
                "capacidad_l": 350,
                "activa": True,
            },
        ]
    )

    rules = []
    for index, zone_key in enumerate(("zone_1", "zone_2"), start=1):
        rules.append(
            {
                "_id": IDS[f"rule_{index}"],
                "zona_id": IDS[zone_key],
                "version": 1,
                "humedad_inicio_pct": 35.0,
                "humedad_detencion_pct": 45.0,
                "nivel_recuperada_min_pct": 15.0,
                "turbidez_max_ntu": 5.0,
                "conductividad_max_us_cm": 1200.0,
                "duracion_max_min": 12,
                "prioridad_fuente": "recuperada",
                "horario_inicio": "06:00",
                "activa": True,
                "creada_en": current - timedelta(days=21),
                "creada_por": IDS["admin"],
            }
        )
    database.reglas_riego.insert_many(rules)

    readings = []
    start = current - timedelta(minutes=5 * 249)
    for zone_index, (zone_key, device_key) in enumerate(
        (("zone_1", "device_1"), ("zone_2", "device_2"))
    ):
        for index in range(250):
            humidity = 39 + zone_index * 2 + 8 * math.sin(index / 18)
            level_recovered = 62 - zone_index * 5 + 10 * math.sin(index / 31)
            turbidity = 2.2 + zone_index * 0.35 + 0.45 * abs(math.sin(index / 13))
            conductivity = 710 + zone_index * 70 + 55 * math.sin(index / 19)
            readings.append(
                {
                    "timestamp": start + timedelta(minutes=5 * index),
                    "meta": {
                        "predio_id": "AGROVIC-PILOTO",
                        "zona_id": IDS[zone_key],
                        "dispositivo_id": IDS[device_key],
                    },
                    "humedad_suelo_pct": round(humidity, 2),
                    "lluvia": index % 67 in {0, 1, 2},
                    "nivel_principal_pct": round(78 - index * 0.025 + zone_index * 3, 2),
                    "nivel_recuperada_pct": round(level_recovered, 2),
                    "caudal_l_min": round(2.7 + 0.35 * math.sin(index / 9), 2),
                    "calidad": {
                        "turbidez_ntu": round(turbidity, 2),
                        "conductividad_us_cm": round(conductivity, 2),
                    },
                    "calidad_lectura": "valida",
                    "fuente_autorizada": "recuperada",
                    "volumen_recuperado_l": 0.48,
                    "idempotency_key": f"seed-{zone_index + 1}-{index:03d}",
                }
            )
    database.lecturas_sensor.insert_many(readings, ordered=False)

    recovered_volumes = [18, 20, 19, 22, 17, 21, 20, 18, 23, 19]
    main_volumes = [24, 22, 26, 25]
    events = []
    for index, volume in enumerate(recovered_volumes + main_volumes):
        source = "recuperada" if index < len(recovered_volumes) else "principal"
        started = current - timedelta(days=14 - index, hours=2)
        events.append(
            {
                "_id": ObjectId(f"66f000000000000000000{index + 1:03d}"),
                "zona_id": IDS["zone_1"] if index % 2 == 0 else IDS["zone_2"],
                "usuario_id": IDS["operator"],
                "tipo": "automatico" if index % 3 else "manual",
                "fuente": source,
                "estado": "completado",
                "motivo": "Umbral de humedad y ventana programada",
                "duracion_programada_min": 8,
                "volumen_l": float(volume),
                "iniciado_en": started,
                "finalizado_en": started + timedelta(minutes=8),
            }
        )
    database.eventos_riego.insert_many(events)

    database.alertas.insert_many(
        [
            {
                "_id": ObjectId("670000000000000000000001"),
                "zona_id": IDS["zone_1"],
                "tipo": "humedad_baja",
                "severidad": "media",
                "mensaje": "Humedad descendió bajo el umbral configurado",
                "estado": "activa",
                "creada_en": current - timedelta(minutes=32),
            },
            {
                "_id": ObjectId("670000000000000000000002"),
                "zona_id": IDS["zone_2"],
                "tipo": "nivel_recuperada_bajo",
                "severidad": "alta",
                "mensaje": "Nivel de reserva próximo al mínimo de seguridad",
                "estado": "confirmada",
                "creada_en": current - timedelta(hours=2),
                "confirmada_por": IDS["operator"],
            },
            {
                "_id": ObjectId("670000000000000000000003"),
                "zona_id": IDS["zone_1"],
                "tipo": "watchdog",
                "severidad": "critica",
                "mensaje": "Evento histórico de detención segura para demostración",
                "estado": "activa",
                "creada_en": current - timedelta(days=1),
            },
            {
                "_id": ObjectId("670000000000000000000004"),
                "zona_id": IDS["zone_2"],
                "tipo": "calidad_fuera_rango",
                "severidad": "alta",
                "mensaje": "Evento histórico de bloqueo por calidad",
                "estado": "cerrada",
                "creada_en": current - timedelta(days=2),
                "cerrada_por": IDS["admin"],
            },
        ]
    )

    database.auditoria.insert_many(
        [
            {
                "timestamp": current - timedelta(days=3),
                "usuario_id": IDS["admin"],
                "rol": "administrador",
                "evento": "base_inicializada",
                "resultado": "exitoso",
                "objetivo": database_name,
                "detalle": {"lecturas": 500, "eventos": 14},
                "ip": "local",
            },
            {
                "timestamp": current - timedelta(days=2),
                "usuario_id": IDS["operator"],
                "rol": "operador",
                "evento": "revision_panel",
                "resultado": "exitoso",
                "objetivo": "dashboard",
                "detalle": {},
                "ip": "local",
            },
        ]
    )

    if export_dir:
        export_collections(database, Path(export_dir))

    runtime = {
        **credentials,
        "device_token": device_token,
        "database": database_name,
        "generated_at": current.isoformat(),
    }
    artifact_path.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text(json.dumps(runtime, ensure_ascii=False, indent=2), encoding="utf-8")
    (artifact_path / "CREDENCIALES_DEMO.txt").write_text(
        "AGROVIC AQUACIRCULAR — ACCESO LOCAL DE PRUEBA\n"
        "Datos generados para esta instalación; no corresponden a cuentas reales.\n\n"
        f"Administrador: {credentials['admin_email']}\n"
        f"Contraseña: {credentials['admin_password']}\n\n"
        f"Operador: {credentials['operator_email']}\n"
        f"Contraseña: {credentials['operator_password']}\n\n"
        f"Token simulador ESP32: {device_token}\n",
        encoding="utf-8",
    )
    counts = {name: database[name].count_documents({}) for name in database.list_collection_names()}
    print(json.dumps({"database": database_name, "counts": counts}, ensure_ascii=False))
    return runtime


def main():
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument("--uri", default=os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--database", default=os.getenv("MONGO_DB_NAME", "agrovic_aquacircular"))
    parser.add_argument("--if-empty", action="store_true")
    parser.add_argument("--export-dir", default="database/exports")
    parser.add_argument("--artifact-dir", default="artifacts")
    args = parser.parse_args()
    seed_database(
        args.uri,
        args.database,
        if_empty=args.if_empty,
        export_dir=args.export_dir,
        artifact_dir=args.artifact_dir,
    )


if __name__ == "__main__":
    main()
