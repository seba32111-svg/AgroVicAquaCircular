"""Diagnostica la conexión a MongoDB y prepara la estructura inicial.

Uso:
    python -m database.doctor           # solo diagnostica
    python -m database.doctor --init    # crea colecciones e índices faltantes (sin datos)
    python -m database.doctor --seed    # carga datos demo si la base está vacía
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.errors import ConfigurationError, OperationFailure, PyMongoError, ServerSelectionTimeoutError

from database.seed import create_collections, create_indexes, seed_database

EXPECTED_COLLECTIONS = (
    "usuarios",
    "zonas_cultivo",
    "dispositivos",
    "lecturas_sensor",
    "fuentes_agua",
    "reglas_riego",
    "eventos_riego",
    "alertas",
    "auditoria",
    "tokens_recuperacion",
)

OK, FAIL, WARN = "[OK]  ", "[FALLA]", "[AVISO]"


def mask_uri(uri: str) -> str:
    return re.sub(r"^(mongodb(?:\+srv)?://[^:/@]+):[^@]*@", r"\1:****@", uri)


def find_uri_problem(uri: str) -> str | None:
    if not uri:
        return "MONGO_URI está vacía. Defínela en .env o como variable de entorno."
    if not uri.startswith(("mongodb://", "mongodb+srv://")):
        return "MONGO_URI debe comenzar con mongodb:// o mongodb+srv://."
    placeholder = re.search(r"<[^>]+>", uri)
    if placeholder:
        return (
            f"MONGO_URI contiene el texto de ejemplo {placeholder.group(0)}. "
            "Reemplázalo por la contraseña real del usuario de base de datos."
        )
    return None


def explain_error(error: Exception) -> str:
    if isinstance(error, OperationFailure) and error.code in (18, 8000):
        return (
            "Falló la autenticación: usuario o contraseña incorrectos. Revisa Database Access en Atlas; "
            "si la contraseña tiene caracteres como @ : / ? # debe ir codificada (urllib.parse.quote_plus)."
        )
    if isinstance(error, ConfigurationError):
        return f"No se pudo resolver el DNS del cluster (revisa el host de la URI): {error}"
    if isinstance(error, ServerSelectionTimeoutError):
        return (
            "No se alcanzó el servidor. En local: ¿está corriendo mongod? (systemctl --user status mongod). "
            "En Atlas: agrega tu IP (o 0.0.0.0/0) en Network Access."
        )
    return f"{type(error).__name__}: {error}"


def inspect_database(database) -> dict:
    infos = {info["name"]: info for info in database.list_collections()}
    present = [name for name in EXPECTED_COLLECTIONS if name in infos]
    return {
        "missing": [name for name in EXPECTED_COLLECTIONS if name not in infos],
        "timeseries_ok": infos.get("lecturas_sensor", {}).get("type") == "timeseries",
        "counts": {name: database[name].estimated_document_count() for name in present},
    }


def print_report(report: dict) -> None:
    for name in EXPECTED_COLLECTIONS:
        if name in report["counts"]:
            print(f"  {OK} {name:<22} {report['counts'][name]} documentos")
        else:
            print(f"  {FAIL} {name:<22} no existe")
    if "lecturas_sensor" in report["counts"] and not report["timeseries_ok"]:
        print(f"  {WARN} lecturas_sensor existe pero no es time-series; ejecuta database/seed.py para recrearla")


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Diagnóstico de conexión MongoDB")
    parser.add_argument("--uri", default=os.getenv("MONGO_URI", "mongodb://localhost:27017"))
    parser.add_argument("--database", default=os.getenv("MONGO_DB_NAME", "agrovic_aquacircular"))
    parser.add_argument("--init", action="store_true", help="crea colecciones e índices faltantes, sin datos")
    parser.add_argument("--seed", action="store_true", help="carga datos demo solo si la base está vacía")
    args = parser.parse_args()

    print(f"URI:   {mask_uri(args.uri)}")
    print(f"Base:  {args.database}\n")

    problem = find_uri_problem(args.uri)
    if problem:
        print(f"{FAIL} {problem}")
        return 1

    client = MongoClient(args.uri, serverSelectionTimeoutMS=8000, tz_aware=True)
    try:
        started = time.perf_counter()
        client.admin.command("ping")
        latency = (time.perf_counter() - started) * 1000
        version = client.server_info()["version"]
        print(f"{OK} Conexión establecida ({latency:.0f} ms) - MongoDB {version}")

        database = client[args.database]
        if args.seed:
            seed_database(args.uri, args.database, if_empty=True)
            print(f"{OK} Datos demo verificados; credenciales en artifacts/CREDENCIALES_DEMO.txt")
        elif args.init:
            create_collections(database)
            create_indexes(database)
            print(f"{OK} Colecciones e índices creados donde faltaban")

        print("\nColecciones:")
        report = inspect_database(database)
        print_report(report)
    except PyMongoError as error:
        print(f"{FAIL} {explain_error(error)}")
        return 1
    finally:
        client.close()

    if report["missing"]:
        print("\nFaltan colecciones. Usa --init (estructura vacía) o --seed (datos demo).")
        return 1
    if not report["counts"].get("usuarios"):
        print(f"\n{WARN} No hay usuarios: no podrás iniciar sesión. Usa --seed para cargar los datos demo.")
    print("\nTodo en orden.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
