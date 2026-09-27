from __future__ import annotations

import json
import os
import secrets
from pathlib import Path

import pytest
from pymongo import MongoClient

from backend.app import create_app
from database.seed import seed_database

RESULTS_DIR = Path("artifacts")
NDJSON = RESULTS_DIR / "test_results.ndjson"
SUMMARY = RESULTS_DIR / "test_results.json"


def pytest_sessionstart(session):
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    NDJSON.unlink(missing_ok=True)
    SUMMARY.unlink(missing_ok=True)


def pytest_sessionfinish(session, exitstatus):
    rows = []
    if NDJSON.exists():
        rows = [json.loads(line) for line in NDJSON.read_text(encoding="utf-8").splitlines() if line]
    ordered = sorted(rows, key=lambda row: row["case"])
    summary = {
        "suite": "AgroVic AquaCircular CP01-CP16",
        "exit_status": exitstatus,
        "total": 16,
        "executed": len(ordered),
        "passed": sum(row["status"] == "APROBADO" for row in ordered),
        "pass_rate": round(sum(row["status"] == "APROBADO" for row in ordered) / 16 * 100, 2),
        "results": ordered,
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture()
def app(tmp_path):
    uri = os.getenv("MONGO_URI", "mongodb://localhost:27017")
    database_name = "agrovic_aquacircular_test"
    runtime = seed_database(uri, database_name, artifact_dir=tmp_path)
    application = create_app(
        {
            "TESTING": True,
            "MONGO_URI": uri,
            "MONGO_DB_NAME": database_name,
            "SECRET_KEY": secrets.token_hex(32),
        }
    )
    application.config["TEST_RUNTIME"] = runtime
    yield application
    application.extensions["mongo_client"].drop_database(database_name)
    application.extensions["mongo_client"].close()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def database(app):
    return app.extensions["mongo_db"]


@pytest.fixture()
def runtime(app):
    return app.config["TEST_RUNTIME"]


@pytest.fixture()
def record():
    def save(case, title, inputs, observed, requirements):
        row = {
            "case": case,
            "evidence": case.replace("CP", "EV"),
            "title": title,
            "status": "APROBADO",
            "inputs": inputs,
            "observed": observed,
            "requirements": requirements,
        }
        with NDJSON.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return save
