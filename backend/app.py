"""Aplicación y API de AgroVic AquaCircular."""
from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any

import bcrypt
from bson import ObjectId
from flask import (
    Flask,
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError
from werkzeug.middleware.proxy_fix import ProxyFix

LOGIN_ATTEMPTS: dict[str, list[float]] = {}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_oid(value: Any) -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    return ObjectId(str(value))


def serializable(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: serializable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [serializable(item) for item in value]
    return value


def db():
    return current_app.extensions["mongo_db"]


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    try:
        return db().usuarios.find_one({"_id": as_oid(user_id), "activo": True})
    except Exception:
        return None


def audit(evento: str, resultado: str, objetivo: str = "", detalle: dict | None = None, actor=None):
    user = actor or current_user()
    db().auditoria.insert_one(
        {
            "timestamp": utcnow(),
            "usuario_id": user.get("_id") if user else None,
            "rol": user.get("rol") if user else "anonimo",
            "evento": evento,
            "resultado": resultado,
            "objetivo": objetivo,
            "detalle": detalle or {},
            "ip": request.headers.get("X-Forwarded-For", request.remote_addr or "")[:80]
            if request
            else "",
        }
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            if request.path.startswith("/api/"):
                return jsonify(error="autenticacion_requerida"), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            user = current_user()
            if user["rol"] not in roles:
                audit("acceso_denegado", "bloqueado", request.path)
                if request.path.startswith("/api/"):
                    return jsonify(error="permiso_denegado"), 403
                abort(403)
            return view(*args, **kwargs)

        return wrapped

    return decorator


def parse_timestamp(value: Any) -> datetime:
    if not value:
        return utcnow()
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def validate_password(password: str) -> bool:
    return (
        len(password) >= 10
        and bool(re.search(r"[A-Z]", password))
        and bool(re.search(r"[a-z]", password))
        and bool(re.search(r"\d", password))
        and bool(re.search(r"[^A-Za-z0-9]", password))
    )


def check_login(email: str, password: str):
    key = f"{request.remote_addr}:{email.lower()}"
    now = time.time()
    attempts = [stamp for stamp in LOGIN_ATTEMPTS.get(key, []) if now - stamp < 600]
    if len(attempts) >= 5:
        return None, "bloqueado"
    user = db().usuarios.find_one({"email": email.lower(), "activo": True})
    valid = bool(user and bcrypt.checkpw(password.encode(), user["password_hash"].encode()))
    if not valid:
        attempts.append(now)
        LOGIN_ATTEMPTS[key] = attempts
        audit("inicio_sesion", "fallido", email.lower(), {"intentos": len(attempts)})
        return None, "invalido"
    LOGIN_ATTEMPTS.pop(key, None)
    return user, "ok"


def active_rule(zone_id: ObjectId):
    return db().reglas_riego.find_one(
        {"zona_id": zone_id, "activa": True}, sort=[("version", DESCENDING)]
    )


def latest_reading(zone_id: ObjectId):
    return db().lecturas_sensor.find_one(
        {"meta.zona_id": zone_id}, sort=[("timestamp", DESCENDING)]
    )


def source_decision(zone_id: ObjectId, reading: dict | None = None) -> dict:
    rule = active_rule(zone_id) or {}
    reading = reading or latest_reading(zone_id) or {}
    quality = reading.get("calidad", {})
    recovered_level = float(reading.get("nivel_recuperada_pct", 0))
    safe = (
        reading.get("calidad_lectura", "invalida") == "valida"
        and recovered_level >= float(rule.get("nivel_recuperada_min_pct", 15))
        and float(quality.get("turbidez_ntu", 9999))
        <= float(rule.get("turbidez_max_ntu", 5))
        and float(quality.get("conductividad_us_cm", 99999))
        <= float(rule.get("conductividad_max_us_cm", 1200))
    )
    preferred = rule.get("prioridad_fuente", "recuperada")
    selected = "recuperada" if safe and preferred == "recuperada" else "principal"
    reason = "calidad_y_nivel_aptos" if selected == "recuperada" else "respaldo_seguro"
    return {"fuente": selected, "recuperada_apta": safe, "motivo": reason, "regla": rule}


def water_balance():
    pipeline = [
        {"$match": {"estado": {"$in": ["completado", "detenido_seguridad"]}}},
        {
            "$group": {
                "_id": "$fuente",
                "litros": {"$sum": "$volumen_l"},
                "ciclos": {"$sum": 1},
            }
        },
    ]
    grouped = {item["_id"]: item for item in db().eventos_riego.aggregate(pipeline)}
    principal = round(float(grouped.get("principal", {}).get("litros", 0)), 2)
    reused = round(float(grouped.get("recuperada", {}).get("litros", 0)), 2)
    total = round(principal + reused, 2)
    capture = list(
        db().lecturas_sensor.aggregate(
            [{"$group": {"_id": None, "litros": {"$sum": "$volumen_recuperado_l"}}}]
        )
    )
    recovered = round(float(capture[0]["litros"]) if capture else 0, 2)
    substitution = round((reused / total * 100) if total else 0, 2)
    return {
        "consumo_total_l": total,
        "agua_principal_l": principal,
        "agua_reutilizada_l": reused,
        "agua_recuperada_l": recovered,
        "sustitucion_pct": substitution,
        "ciclos_reutilizacion": int(grouped.get("recuperada", {}).get("ciclos", 0)),
    }


def create_alert(zone_id, alert_type: str, severity: str, message: str):
    existing = db().alertas.find_one(
        {"zona_id": zone_id, "tipo": alert_type, "estado": {"$in": ["activa", "confirmada"]}}
    )
    if existing:
        return existing["_id"]
    result = db().alertas.insert_one(
        {
            "zona_id": zone_id,
            "tipo": alert_type,
            "severidad": severity,
            "mensaje": message,
            "estado": "activa",
            "creada_en": utcnow(),
            "confirmada_por": None,
            "cerrada_por": None,
        }
    )
    return result.inserted_id


def validate_measurement(payload: dict) -> tuple[dict | None, list[str]]:
    errors: list[str] = []
    numeric_ranges = {
        "humedad_suelo_pct": (0, 100),
        "nivel_principal_pct": (0, 100),
        "nivel_recuperada_pct": (0, 100),
        "caudal_l_min": (0, 200),
        "turbidez_ntu": (0, 100),
        "conductividad_us_cm": (0, 5000),
    }
    values: dict[str, float] = {}
    for field, bounds in numeric_ranges.items():
        try:
            value = float(payload[field])
            if not bounds[0] <= value <= bounds[1]:
                raise ValueError
            values[field] = value
        except (KeyError, TypeError, ValueError):
            errors.append(f"{field}: fuera de rango o ausente")
    try:
        timestamp = parse_timestamp(payload.get("timestamp"))
        if timestamp > utcnow() + timedelta(minutes=5) or timestamp < utcnow() - timedelta(days=2):
            errors.append("timestamp: fuera de ventana")
    except (TypeError, ValueError):
        timestamp = utcnow()
        errors.append("timestamp: formato invalido")
    if not str(payload.get("idempotency_key", "")).strip():
        errors.append("idempotency_key: requerido")
    if errors:
        return None, errors
    return {
        **values,
        "timestamp": timestamp,
        "lluvia": bool(payload.get("lluvia", False)),
        "idempotency_key": str(payload["idempotency_key"])[:100],
        "volumen_recuperado_l": max(0.0, float(payload.get("volumen_recuperado_l", 0))),
    }, []


def create_irrigation(payload: dict, actor: dict) -> tuple[dict | None, int, str | None]:
    try:
        zone_id = as_oid(payload.get("zona_id"))
    except Exception:
        return None, 400, "zona_invalida"
    zone = db().zonas_cultivo.find_one({"_id": zone_id, "activa": True})
    if not zone:
        return None, 404, "zona_no_encontrada"
    action = payload.get("accion", "iniciar")
    if action not in {"iniciar", "detener"}:
        return None, 400, "accion_invalida"
    active = db().eventos_riego.find_one({"zona_id": zone_id, "estado": "activo"})
    if action == "detener":
        if not active:
            return None, 409, "sin_riego_activo"
        db().eventos_riego.update_one(
            {"_id": active["_id"]},
            {"$set": {"estado": "completado", "finalizado_en": utcnow()}},
        )
        audit("riego_manual", "detenido", str(active["_id"]), actor=actor)
        return db().eventos_riego.find_one({"_id": active["_id"]}), 200, None
    if active:
        return None, 409, "riego_en_conflicto"
    if actor["rol"] == "operador" and not actor.get("control_manual_autorizado", False):
        return None, 403, "operador_no_autorizado"
    requested_source = payload.get("fuente", "automatica")
    decision = source_decision(zone_id)
    source = decision["fuente"] if requested_source == "automatica" else requested_source
    if source not in {"principal", "recuperada"}:
        return None, 400, "fuente_invalida"
    if source == "recuperada" and not decision["recuperada_apta"]:
        create_alert(zone_id, "reutilizacion_bloqueada", "alta", "Agua recuperada no apta; orden bloqueada")
        audit("riego_manual", "bloqueado", str(zone_id), {"motivo": decision["motivo"]}, actor)
        return None, 422, "fuente_recuperada_no_apta"
    try:
        duration = int(payload.get("duracion_min", 5))
        volume = float(payload.get("volumen_l", 0))
    except (TypeError, ValueError):
        return None, 400, "duracion_o_volumen_invalido"
    rule = decision["regla"]
    max_duration = int(rule.get("duracion_max_min", 12))
    if not 1 <= duration <= max_duration or not 0 <= volume <= 500:
        return None, 400, "limite_operacional_excedido"
    reason = str(payload.get("motivo", "")).strip()
    if len(reason) < 5:
        return None, 400, "motivo_requerido"
    event = {
        "zona_id": zone_id,
        "usuario_id": actor["_id"],
        "tipo": "manual",
        "fuente": source,
        "estado": "activo",
        "motivo": reason[:250],
        "duracion_programada_min": duration,
        "volumen_l": volume,
        "iniciado_en": utcnow(),
        "finalizado_en": None,
    }
    inserted = db().eventos_riego.insert_one(event)
    event["_id"] = inserted.inserted_id
    audit("riego_manual", "iniciado", str(inserted.inserted_id), {"fuente": source}, actor)
    return event, 201, None


def enforce_watchdog(database, now: datetime | None = None) -> dict:
    now = now or utcnow()
    stopped = 0
    disconnected = 0
    for event in database.eventos_riego.find({"estado": "activo"}):
        rule = database.reglas_riego.find_one(
            {"zona_id": event["zona_id"], "activa": True}, sort=[("version", DESCENDING)]
        ) or {}
        limit = int(rule.get("duracion_max_min", 12))
        if now - event["iniciado_en"] > timedelta(minutes=limit):
            database.eventos_riego.update_one(
                {"_id": event["_id"]},
                {"$set": {"estado": "detenido_seguridad", "finalizado_en": now}},
            )
            database.alertas.insert_one(
                {
                    "zona_id": event["zona_id"],
                    "tipo": "watchdog",
                    "severidad": "critica",
                    "mensaje": "Riego detenido por tiempo maximo de seguridad",
                    "estado": "activa",
                    "creada_en": now,
                }
            )
            stopped += 1
    for device in database.dispositivos.find({"activo": True}):
        last_seen = device.get("ultima_conexion")
        if last_seen and now - last_seen > timedelta(minutes=10) and device.get("estado") != "desconectado":
            database.dispositivos.update_one(
                {"_id": device["_id"]}, {"$set": {"estado": "desconectado"}}
            )
            database.alertas.insert_one(
                {
                    "zona_id": device["zona_id"],
                    "tipo": "dispositivo_desconectado",
                    "severidad": "critica",
                    "mensaje": "ESP32 sin telemetria por mas de 10 minutos",
                    "estado": "activa",
                    "creada_en": now,
                }
            )
            disconnected += 1
    return {"riegos_detenidos": stopped, "dispositivos_desconectados": disconnected}


def create_app(test_config: dict | None = None) -> Flask:
    LOGIN_ATTEMPTS.clear()
    app = Flask(
        __name__,
        template_folder="../frontend/templates",
        static_folder="../frontend/static",
        static_url_path="/static",
    )
    app.config.update(
        SECRET_KEY=os.getenv("SECRET_KEY") or secrets.token_hex(32),
        MONGO_URI=os.getenv("MONGO_URI", "mongodb://localhost:27017"),
        MONGO_DB_NAME=os.getenv("MONGO_DB_NAME", "agrovic_aquacircular"),
        PORT=int(os.getenv("PORT", "5000")),
        TESTING=False,
    )
    if test_config:
        app.config.update(test_config)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    client = MongoClient(app.config["MONGO_URI"], serverSelectionTimeoutMS=5000, tz_aware=True)
    app.extensions["mongo_client"] = client
    app.extensions["mongo_db"] = client[app.config["MONGO_DB_NAME"]]

    @app.before_request
    def protect_forms():
        session.setdefault("_csrf", secrets.token_urlsafe(24))
        if (
            request.method in {"POST", "PUT", "PATCH", "DELETE"}
            and not request.is_json
            and not app.config["TESTING"]
            and request.endpoint not in {"static"}
        ):
            if not secrets.compare_digest(session["_csrf"], request.form.get("_csrf", "")):
                abort(400, "Token CSRF invalido")

    @app.after_request
    def defensive_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:"
        )
        return response

    @app.context_processor
    def template_context():
        return {"usuario_actual": current_user(), "csrf_token": session.get("_csrf", "")}

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template("error.html", code=403, message="No tienes permisos para esta operacion."), 403

    @app.errorhandler(404)
    def not_found(_error):
        return render_template("error.html", code=404, message="La pagina solicitada no existe."), 404

    @app.route("/health")
    def health():
        try:
            app.extensions["mongo_db"].command("ping")
            return jsonify(status="ok", database="connected")
        except Exception:
            return jsonify(status="degraded", database="unavailable"), 503

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user():
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            user, status = check_login(request.form.get("email", ""), request.form.get("password", ""))
            if status == "bloqueado":
                flash("Acceso temporalmente bloqueado por intentos repetidos.", "error")
                return render_template("login.html"), 429
            if not user:
                flash("Credenciales no validas.", "error")
                return render_template("login.html"), 401
            session.clear()
            session["user_id"] = str(user["_id"])
            session["_csrf"] = secrets.token_urlsafe(24)
            audit("inicio_sesion", "exitoso", user["email"], actor=user)
            return redirect(url_for("dashboard"))
        return render_template("login.html")

    @app.post("/logout")
    @login_required
    def logout():
        audit("cierre_sesion", "exitoso")
        session.clear()
        return redirect(url_for("login"))

    @app.route("/recuperar", methods=["GET", "POST"])
    def recovery():
        token_for_demo = None
        if request.method == "POST":
            email = request.form.get("email", "").lower().strip()
            user = db().usuarios.find_one({"email": email, "activo": True})
            if user:
                raw = secrets.token_urlsafe(32)
                db().tokens_recuperacion.insert_one(
                    {
                        "usuario_id": user["_id"],
                        "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
                        "creado_en": utcnow(),
                        "expira_en": utcnow() + timedelta(minutes=20),
                        "usado_en": None,
                    }
                )
                if app.config["TESTING"]:
                    token_for_demo = raw
                audit("recuperacion_solicitada", "aceptada", email)
            flash("Si la cuenta existe, se genero una solicitud valida por 20 minutos.", "success")
        return render_template("recovery.html", token_demo=token_for_demo)

    @app.route("/restablecer/<token>", methods=["GET", "POST"])
    def reset_password(token):
        record = db().tokens_recuperacion.find_one(
            {"token_hash": hashlib.sha256(token.encode()).hexdigest()}
        )
        valid = bool(record and not record.get("usado_en") and record["expira_en"] > utcnow())
        if request.method == "POST":
            if not valid:
                flash("El enlace no es valido o ya expiro.", "error")
                return render_template("reset.html", valid=False), 410
            password = request.form.get("password", "")
            if not validate_password(password):
                flash("Usa 10 caracteres, mayuscula, minuscula, numero y simbolo.", "error")
                return render_template("reset.html", valid=True), 400
            db().usuarios.update_one(
                {"_id": record["usuario_id"]},
                {"$set": {"password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()}},
            )
            db().tokens_recuperacion.update_one({"_id": record["_id"]}, {"$set": {"usado_en": utcnow()}})
            audit("recuperacion_completada", "exitoso", str(record["usuario_id"]))
            flash("Contrasena actualizada. Ya puedes iniciar sesion.", "success")
            return redirect(url_for("login"))
        return render_template("reset.html", valid=valid)

    @app.get("/")
    @login_required
    def dashboard():
        zones = list(db().zonas_cultivo.find({"activa": True}).sort("nombre", ASCENDING))
        cards = []
        for zone in zones:
            reading = latest_reading(zone["_id"])
            cards.append({"zona": zone, "lectura": reading, "decision": source_decision(zone["_id"], reading)})
        alerts = list(
            db().alertas.find({"estado": {"$in": ["activa", "confirmada"]}})
            .sort("creada_en", DESCENDING)
            .limit(8)
        )
        events = list(db().eventos_riego.find().sort("iniciado_en", DESCENDING).limit(8))
        return render_template(
            "dashboard.html", cards=cards, alertas=alerts, eventos=events, balance=water_balance()
        )

    @app.get("/admin")
    @roles_required("administrador")
    def admin_panel():
        return render_template(
            "admin.html",
            usuarios=list(db().usuarios.find().sort("nombre", ASCENDING)),
            zonas=list(db().zonas_cultivo.find().sort("nombre", ASCENDING)),
            dispositivos=list(db().dispositivos.find().sort("nombre", ASCENDING)),
            reglas=list(db().reglas_riego.find({"activa": True})),
        )

    @app.post("/admin/usuarios")
    @roles_required("administrador")
    def add_user():
        email = request.form.get("email", "").lower().strip()
        password = request.form.get("password", "")
        role = request.form.get("rol")
        if not EMAIL_RE.match(email) or role not in {"administrador", "operador"} or not validate_password(password):
            flash("Datos de usuario invalidos.", "error")
            return redirect(url_for("admin_panel")), 400
        try:
            result = db().usuarios.insert_one(
                {
                    "nombre": request.form.get("nombre", "").strip()[:100],
                    "email": email,
                    "rol": role,
                    "activo": request.form.get("activo") == "on",
                    "control_manual_autorizado": request.form.get("control_manual") == "on",
                    "password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode(),
                    "creado_en": utcnow(),
                }
            )
        except DuplicateKeyError:
            flash("El correo ya existe.", "error")
            return redirect(url_for("admin_panel")), 409
        audit("usuario_creado", "exitoso", str(result.inserted_id))
        flash("Usuario creado correctamente.", "success")
        return redirect(url_for("admin_panel"))

    @app.post("/admin/zonas")
    @roles_required("administrador")
    def add_zone():
        name = request.form.get("nombre", "").strip()
        crop = request.form.get("cultivo", "").strip()
        location = request.form.get("ubicacion", "").strip()
        if len(name) < 3 or len(crop) < 3 or len(location) < 3:
            flash("Completa nombre, cultivo y ubicacion.", "error")
            return redirect(url_for("admin_panel")), 400
        zone = {
            "nombre": name[:80],
            "cultivo": crop[:80],
            "ubicacion": location[:120],
            "activa": True,
            "creada_en": utcnow(),
        }
        result = db().zonas_cultivo.insert_one(zone)
        audit("zona_creada", "exitoso", str(result.inserted_id))
        flash("Zona incorporada.", "success")
        return redirect(url_for("admin_panel"))

    @app.post("/admin/reglas")
    @roles_required("administrador")
    def add_rule():
        try:
            zone_id = as_oid(request.form.get("zona_id"))
            start = float(request.form.get("humedad_inicio_pct"))
            stop = float(request.form.get("humedad_detencion_pct"))
            minimum = float(request.form.get("nivel_recuperada_min_pct"))
            turbidity = float(request.form.get("turbidez_max_ntu"))
            conductivity = float(request.form.get("conductividad_max_us_cm"))
            duration = int(request.form.get("duracion_max_min"))
        except (TypeError, ValueError):
            flash("La regla contiene valores invalidos.", "error")
            return redirect(url_for("admin_panel")), 400
        if not (0 <= start < stop <= 100 and 0 <= minimum <= 100 and 1 <= duration <= 60):
            flash("Revisa la relacion entre umbrales y limites.", "error")
            return redirect(url_for("admin_panel")), 400
        previous = active_rule(zone_id)
        db().reglas_riego.update_many({"zona_id": zone_id, "activa": True}, {"$set": {"activa": False}})
        rule = {
            "zona_id": zone_id,
            "version": int(previous.get("version", 0) + 1) if previous else 1,
            "humedad_inicio_pct": start,
            "humedad_detencion_pct": stop,
            "nivel_recuperada_min_pct": minimum,
            "turbidez_max_ntu": turbidity,
            "conductividad_max_us_cm": conductivity,
            "duracion_max_min": duration,
            "prioridad_fuente": request.form.get("prioridad_fuente", "recuperada"),
            "horario_inicio": request.form.get("horario_inicio", "06:00"),
            "activa": True,
            "creada_en": utcnow(),
            "creada_por": current_user()["_id"],
        }
        result = db().reglas_riego.insert_one(rule)
        audit("regla_creada", "exitoso", str(result.inserted_id), {"version": rule["version"]})
        flash("Regla versionada y activada.", "success")
        return redirect(url_for("admin_panel"))

    @app.post("/riego/manual")
    @roles_required("administrador", "operador")
    def manual_irrigation():
        event, status, error = create_irrigation(request.form.to_dict(), current_user())
        if error:
            flash(f"Orden rechazada: {error.replace('_', ' ')}.", "error")
            return redirect(url_for("dashboard")), status
        flash("Orden registrada con trazabilidad.", "success")
        return redirect(url_for("dashboard"))

    @app.get("/alertas")
    @login_required
    def alerts_page():
        alerts = list(db().alertas.find().sort("creada_en", DESCENDING).limit(100))
        return render_template("alerts.html", alertas=alerts)

    @app.post("/alertas/<alert_id>")
    @roles_required("administrador", "operador")
    def update_alert_form(alert_id):
        action = request.form.get("accion", "confirmar")
        alert = db().alertas.find_one({"_id": as_oid(alert_id)})
        if not alert:
            abort(404)
        if action == "cerrar" and alert.get("severidad") == "critica" and current_user()["rol"] != "administrador":
            flash("Solo el administrador puede cerrar una alerta critica.", "error")
            return redirect(url_for("alerts_page")), 403
        state = "cerrada" if action == "cerrar" else "confirmada"
        field = "cerrada_por" if state == "cerrada" else "confirmada_por"
        db().alertas.update_one(
            {"_id": alert["_id"]},
            {"$set": {"estado": state, field: current_user()["_id"], f"{state}_en": utcnow()}},
        )
        audit("alerta_actualizada", "exitoso", alert_id, {"estado": state})
        flash(f"Alerta {state}.", "success")
        return redirect(url_for("alerts_page"))

    @app.get("/reportes")
    @login_required
    def reports_page():
        return render_template(
            "reports.html",
            balance=water_balance(),
            eventos=list(db().eventos_riego.find().sort("iniciado_en", DESCENDING).limit(50)),
        )

    @app.get("/reportes/balance.csv")
    @login_required
    def reports_csv():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["fecha", "zona_id", "fuente", "estado", "volumen_l", "motivo"])
        for item in db().eventos_riego.find().sort("iniciado_en", ASCENDING):
            writer.writerow(
                [
                    item["iniciado_en"].isoformat(),
                    str(item["zona_id"]),
                    item["fuente"],
                    item["estado"],
                    item.get("volumen_l", 0),
                    item.get("motivo", ""),
                ]
            )
        audit("reporte_exportado", "exitoso", "balance.csv")
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=balance_hidrico.csv"},
        )

    @app.post("/api/v1/auth/login")
    def api_login():
        payload = request.get_json(silent=True) or {}
        user, status = check_login(payload.get("email", ""), payload.get("password", ""))
        if status == "bloqueado":
            return jsonify(error="demasiados_intentos"), 429
        if not user:
            return jsonify(error="credenciales_invalidas"), 401
        session.clear()
        session["user_id"] = str(user["_id"])
        session["_csrf"] = secrets.token_urlsafe(24)
        audit("inicio_sesion_api", "exitoso", user["email"], actor=user)
        return jsonify(
            usuario={"id": str(user["_id"]), "nombre": user["nombre"], "rol": user["rol"]},
            csrf=session["_csrf"],
        )

    @app.post("/api/v1/auth/recuperaciones")
    def api_recovery():
        payload = request.get_json(silent=True) or {}
        email = str(payload.get("email", "")).lower().strip()
        user = db().usuarios.find_one({"email": email, "activo": True})
        response = {"mensaje": "Si la cuenta existe, se genero la solicitud."}
        if user:
            raw = secrets.token_urlsafe(32)
            db().tokens_recuperacion.insert_one(
                {
                    "usuario_id": user["_id"],
                    "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
                    "creado_en": utcnow(),
                    "expira_en": utcnow() + timedelta(minutes=20),
                    "usado_en": None,
                }
            )
            audit("recuperacion_solicitada_api", "aceptada", email)
            if app.config["TESTING"]:
                response["test_token"] = raw
        return jsonify(response), 202

    @app.post("/api/v1/auth/recuperaciones/<token>")
    def api_reset(token):
        payload = request.get_json(silent=True) or {}
        record = db().tokens_recuperacion.find_one(
            {"token_hash": hashlib.sha256(token.encode()).hexdigest()}
        )
        if not record or record.get("usado_en") or record["expira_en"] <= utcnow():
            return jsonify(error="token_invalido_o_expirado"), 410
        password = str(payload.get("password", ""))
        if not validate_password(password):
            return jsonify(error="password_debil"), 400
        db().usuarios.update_one(
            {"_id": record["usuario_id"]},
            {"$set": {"password_hash": bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()}},
        )
        db().tokens_recuperacion.update_one({"_id": record["_id"]}, {"$set": {"usado_en": utcnow()}})
        audit("recuperacion_completada_api", "exitoso", str(record["usuario_id"]))
        return jsonify(mensaje="password_actualizado")

    def device_from_request():
        token = request.headers.get("X-Device-Token", "")
        if not token and request.headers.get("Authorization", "").startswith("Bearer "):
            token = request.headers["Authorization"][7:]
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        return db().dispositivos.find_one({"token_hash": token_hash, "activo": True})

    @app.post("/api/v1/lecturas")
    def ingest_reading():
        device = device_from_request()
        if not device:
            return jsonify(error="dispositivo_no_autorizado"), 401
        payload = request.get_json(silent=True) or {}
        clean, errors = validate_measurement(payload)
        if errors:
            audit("lectura_rechazada", "bloqueado", str(device["_id"]), {"errores": errors})
            return jsonify(error="lectura_invalida", detalles=errors), 422
        duplicate = db().lecturas_sensor.find_one(
            {"meta.dispositivo_id": device["_id"], "idempotency_key": clean["idempotency_key"]}
        )
        if duplicate:
            return jsonify(duplicada=True, lectura_id=str(duplicate["_id"])), 200
        zone_id = device["zona_id"]
        rule = active_rule(zone_id) or {}
        valid_quality = (
            clean["turbidez_ntu"] <= float(rule.get("turbidez_max_ntu", 5))
            and clean["conductividad_us_cm"]
            <= float(rule.get("conductividad_max_us_cm", 1200))
        )
        reading = {
            "timestamp": clean["timestamp"],
            "meta": {"zona_id": zone_id, "dispositivo_id": device["_id"], "predio_id": "AGROVIC-PILOTO"},
            "humedad_suelo_pct": clean["humedad_suelo_pct"],
            "lluvia": clean["lluvia"],
            "nivel_principal_pct": clean["nivel_principal_pct"],
            "nivel_recuperada_pct": clean["nivel_recuperada_pct"],
            "caudal_l_min": clean["caudal_l_min"],
            "calidad": {
                "turbidez_ntu": clean["turbidez_ntu"],
                "conductividad_us_cm": clean["conductividad_us_cm"],
            },
            "calidad_lectura": "valida" if valid_quality else "invalida",
            "volumen_recuperado_l": clean["volumen_recuperado_l"],
            "idempotency_key": clean["idempotency_key"],
        }
        reading["fuente_autorizada"] = source_decision(zone_id, reading)["fuente"]
        try:
            result = db().lecturas_sensor.insert_one(reading)
        except DuplicateKeyError:
            duplicate = db().lecturas_sensor.find_one(
                {"meta.dispositivo_id": device["_id"], "idempotency_key": clean["idempotency_key"]}
            )
            return jsonify(duplicada=True, lectura_id=str(duplicate["_id"])), 200
        db().dispositivos.update_one(
            {"_id": device["_id"]},
            {"$set": {"ultima_conexion": utcnow(), "estado": "conectado"}},
        )
        if clean["humedad_suelo_pct"] < float(rule.get("humedad_inicio_pct", 35)):
            create_alert(zone_id, "humedad_baja", "media", "Humedad bajo umbral de inicio")
        if not valid_quality:
            create_alert(zone_id, "calidad_fuera_rango", "alta", "Reutilizacion bloqueada por calidad")
        if clean["nivel_recuperada_pct"] < float(rule.get("nivel_recuperada_min_pct", 15)):
            create_alert(zone_id, "nivel_recuperada_bajo", "media", "Tanque recuperado bajo minimo")
        return jsonify(lectura_id=str(result.inserted_id), fuente_autorizada=reading["fuente_autorizada"]), 201

    @app.get("/api/v1/zonas/<zone_id>/estado")
    @login_required
    def zone_state(zone_id):
        try:
            zone_oid = as_oid(zone_id)
        except Exception:
            return jsonify(error="zona_invalida"), 400
        zone = db().zonas_cultivo.find_one({"_id": zone_oid})
        if not zone:
            return jsonify(error="zona_no_encontrada"), 404
        return jsonify(
            zona=serializable(zone),
            lectura=serializable(latest_reading(zone_oid)),
            decision=serializable(source_decision(zone_oid)),
        )

    @app.route("/api/v1/riegos", methods=["GET", "POST"])
    @roles_required("administrador", "operador")
    def api_irrigations():
        if request.method == "GET":
            return jsonify(
                eventos=serializable(
                    list(db().eventos_riego.find().sort("iniciado_en", DESCENDING).limit(100))
                )
            )
        event, status, error = create_irrigation(request.get_json(silent=True) or {}, current_user())
        if error:
            return jsonify(error=error), status
        return jsonify(evento=serializable(event)), status

    @app.patch("/api/v1/alertas/<alert_id>/confirmacion")
    @roles_required("administrador", "operador")
    def api_alert(alert_id):
        try:
            alert = db().alertas.find_one({"_id": as_oid(alert_id)})
        except Exception:
            alert = None
        if not alert:
            return jsonify(error="alerta_no_encontrada"), 404
        payload = request.get_json(silent=True) or {}
        action = payload.get("accion", "confirmar")
        if action == "cerrar" and alert.get("severidad") == "critica" and current_user()["rol"] != "administrador":
            audit("alerta_actualizada", "bloqueado", alert_id, {"accion": action})
            return jsonify(error="cierre_critico_solo_administrador"), 403
        state = "cerrada" if action == "cerrar" else "confirmada"
        db().alertas.update_one(
            {"_id": alert["_id"]},
            {"$set": {"estado": state, f"{state}_por": current_user()["_id"], f"{state}_en": utcnow()}},
        )
        audit("alerta_actualizada", "exitoso", alert_id, {"estado": state})
        return jsonify(estado=state)

    @app.get("/api/v1/reportes/balance")
    @login_required
    def api_balance():
        return jsonify(balance=water_balance())

    @app.post("/api/v1/reglas")
    @roles_required("administrador")
    def api_rules():
        payload = request.get_json(silent=True) or {}
        required = [
            "zona_id",
            "humedad_inicio_pct",
            "humedad_detencion_pct",
            "nivel_recuperada_min_pct",
            "turbidez_max_ntu",
            "conductividad_max_us_cm",
            "duracion_max_min",
        ]
        if any(field not in payload for field in required):
            return jsonify(error="campos_requeridos"), 400
        try:
            zone_id = as_oid(payload["zona_id"])
            start = float(payload["humedad_inicio_pct"])
            stop = float(payload["humedad_detencion_pct"])
            duration = int(payload["duracion_max_min"])
        except (ValueError, TypeError):
            return jsonify(error="regla_invalida"), 400
        if not 0 <= start < stop <= 100 or not 1 <= duration <= 60:
            return jsonify(error="regla_invalida"), 400
        previous = active_rule(zone_id)
        db().reglas_riego.update_many({"zona_id": zone_id, "activa": True}, {"$set": {"activa": False}})
        document = {
            **payload,
            "zona_id": zone_id,
            "version": int(previous.get("version", 0) + 1) if previous else 1,
            "activa": True,
            "creada_en": utcnow(),
            "creada_por": current_user()["_id"],
        }
        result = db().reglas_riego.insert_one(document)
        audit("regla_creada_api", "exitoso", str(result.inserted_id))
        return jsonify(regla_id=str(result.inserted_id), version=document["version"]), 201

    @app.post("/api/v1/fuentes")
    @roles_required("administrador")
    def api_create_source():
        payload = request.get_json(silent=True) or {}
        try:
            zone_id = as_oid(payload.get("zona_id"))
        except Exception:
            return jsonify(error="zona_invalida"), 400
        source_type = payload.get("tipo")
        name = str(payload.get("nombre", "")).strip()
        if source_type not in {"principal", "recuperada"} or len(name) < 3:
            return jsonify(error="fuente_invalida"), 400
        if not db().zonas_cultivo.find_one({"_id": zone_id}):
            return jsonify(error="zona_no_encontrada"), 404
        result = db().fuentes_agua.insert_one(
            {
                "zona_id": zone_id,
                "tipo": source_type,
                "nombre": name[:100],
                "capacidad_l": float(payload.get("capacidad_l", 0)),
                "activa": True,
            }
        )
        audit("fuente_creada", "exitoso", str(result.inserted_id))
        return jsonify(fuente_id=str(result.inserted_id)), 201

    @app.post("/api/v1/dispositivos")
    @roles_required("administrador")
    def api_create_device():
        payload = request.get_json(silent=True) or {}
        try:
            zone_id = as_oid(payload.get("zona_id"))
        except Exception:
            return jsonify(error="zona_invalida"), 400
        name = str(payload.get("nombre", "")).strip()
        if len(name) < 3 or not db().zonas_cultivo.find_one({"_id": zone_id}):
            return jsonify(error="dispositivo_invalido"), 400
        provisioning_token = secrets.token_urlsafe(32)
        result = db().dispositivos.insert_one(
            {
                "nombre": name[:100],
                "modelo": str(payload.get("modelo", "ESP32"))[:80],
                "zona_id": zone_id,
                "token_hash": hashlib.sha256(provisioning_token.encode()).hexdigest(),
                "estado": "pendiente",
                "activo": True,
                "intervalo_segundos": int(payload.get("intervalo_segundos", 300)),
                "ultima_conexion": None,
            }
        )
        audit("dispositivo_creado", "exitoso", str(result.inserted_id))
        return jsonify(dispositivo_id=str(result.inserted_id), token_provisionamiento=provisioning_token), 201

    @app.patch("/api/v1/dispositivos/<device_id>")
    @roles_required("administrador")
    def api_device(device_id):
        payload = request.get_json(silent=True) or {}
        allowed = {key: payload[key] for key in ("nombre", "activo", "estado") if key in payload}
        if not allowed:
            return jsonify(error="sin_cambios_validos"), 400
        result = db().dispositivos.update_one({"_id": as_oid(device_id)}, {"$set": allowed})
        if not result.matched_count:
            return jsonify(error="dispositivo_no_encontrado"), 404
        audit("dispositivo_actualizado", "exitoso", device_id, allowed)
        return jsonify(actualizado=True)

    @app.post("/api/v1/seguridad/watchdog")
    @roles_required("administrador")
    def api_watchdog():
        result = enforce_watchdog(db())
        audit("watchdog_ejecutado", "exitoso", detalle=result)
        return jsonify(result)

    return app


app = create_app()
