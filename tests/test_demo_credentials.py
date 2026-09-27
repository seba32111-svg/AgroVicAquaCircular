import bcrypt
import pytest
from pymongo import MongoClient

from database.seed import demo_credentials, seed_database

ENV_KEYS = ("SEED_ADMIN_EMAIL", "SEED_ADMIN_PASSWORD", "SEED_OPERATOR_EMAIL", "SEED_OPERATOR_PASSWORD")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_demo_credentials_are_random_without_env():
    first, second = demo_credentials(), demo_credentials()
    assert first["admin_email"] == "admin@agrovic.demo"
    assert first["admin_password"] != second["admin_password"]


def test_demo_credentials_use_env_values(monkeypatch):
    monkeypatch.setenv("SEED_ADMIN_EMAIL", "profe@agrovic.demo")
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "Defensa2026!")
    credentials = demo_credentials()
    assert credentials["admin_email"] == "profe@agrovic.demo"
    assert credentials["admin_password"] == "Defensa2026!"
    assert credentials["operator_email"] == "operador@agrovic.demo"


def test_demo_credentials_reject_weak_password(monkeypatch):
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "admin123")
    with pytest.raises(SystemExit, match="SEED_ADMIN_PASSWORD"):
        demo_credentials()


def test_seed_creates_admin_with_env_password(monkeypatch, tmp_path):
    monkeypatch.setenv("SEED_ADMIN_PASSWORD", "Defensa2026!")
    uri, name = "mongodb://localhost:27017", "agrovic_aquacircular_test_credentials"
    seed_database(uri, name, artifact_dir=tmp_path)
    client = MongoClient(uri)
    try:
        admin = client[name].usuarios.find_one({"email": "admin@agrovic.demo"})
        assert bcrypt.checkpw(b"Defensa2026!", admin["password_hash"].encode())
        assert "Defensa2026!" in (tmp_path / "CREDENCIALES_DEMO.txt").read_text(encoding="utf-8")
    finally:
        client.drop_database(name)
        client.close()
