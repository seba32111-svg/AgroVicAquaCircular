"""Simulador reproducible del protocolo ESP32 de AgroVic AquaCircular."""
from __future__ import annotations

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def runtime_token():
    token = os.getenv("DEVICE_TOKEN")
    if token:
        return token
    path = Path("artifacts/runtime_credentials.json")
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["device_token"]
    raise SystemExit("No se encontró un token local. Ejecuta database/seed.py primero.")


def payload(index: int, scenario: str):
    values = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "idempotency_key": f"sim-{int(time.time())}-{index}",
        "humedad_suelo_pct": round(36 + 7 * math.sin(index / 4), 2),
        "lluvia": index % 20 == 0,
        "nivel_principal_pct": round(78 - index * 0.05, 2),
        "nivel_recuperada_pct": round(58 + 4 * math.sin(index / 7), 2),
        "caudal_l_min": 2.8,
        "turbidez_ntu": 2.5,
        "conductividad_us_cm": 760,
        "volumen_recuperado_l": 0.4 if index % 3 == 0 else 0,
    }
    if scenario == "calidad":
        values["turbidez_ntu"] = 18
    elif scenario == "nivel":
        values["nivel_recuperada_pct"] = 6
    return values


def send(url: str, token: str, document: dict):
    request = urllib.request.Request(
        url,
        data=json.dumps(document).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "X-Device-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://localhost:5000/api/v1/lecturas")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--scenario", choices=["normal", "calidad", "nivel", "desconexion"], default="normal")
    args = parser.parse_args()
    if args.scenario == "desconexion":
        print("Escenario desconexión: no se envían datos; ejecutar el watchdog tras 10 minutos simulados.")
        return
    token = runtime_token()
    for index in range(args.count):
        status, response = send(args.url, token, payload(index, args.scenario))
        print(json.dumps({"envio": index + 1, "status": status, "respuesta": response}, ensure_ascii=False))
        if index + 1 < args.count:
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
