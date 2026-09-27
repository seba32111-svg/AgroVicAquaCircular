"""Genera accesos locales después de importar exportaciones MongoDB.

Usa SEED_ADMIN_* / SEED_OPERATOR_* del .env si están definidas; si no, contraseñas aleatorias.
"""
from __future__ import annotations

import os
from pathlib import Path

import bcrypt
from dotenv import load_dotenv
from pymongo import MongoClient

from database.seed import IDS, demo_credentials


def main():
    load_dotenv()
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    name = os.getenv("MONGO_DB_NAME", "agrovic_aquacircular")
    database = MongoClient(uri)[name]
    access = demo_credentials()
    updates = [
        (IDS["admin"], access["admin_email"], access["admin_password"]),
        (IDS["operator"], access["operator_email"], access["operator_password"]),
    ]
    for user_id, email, password in updates:
        result = database.usuarios.update_one(
            {"_id": user_id},
            {
                "$set": {
                    "email": email,
                    "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
                    "activo": True,
                }
            },
        )
        if result.matched_count != 1:
            raise SystemExit(f"No se encontró la cuenta demostrativa {email}. Ejecuta primero database/seed.py.")
    output = Path("artifacts/CREDENCIALES_DEMO.txt")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "ACCESOS LOCALES GENERADOS\n"
        "No publicar este archivo.\n\n"
        f"Administrador: {access['admin_email']}\n"
        f"Contraseña: {access['admin_password']}\n\n"
        f"Operador: {access['operator_email']}\n"
        f"Contraseña: {access['operator_password']}\n",
        encoding="utf-8",
    )
    print(f"Accesos actualizados en la base {name}. Revisa {output}.")


if __name__ == "__main__":
    main()
