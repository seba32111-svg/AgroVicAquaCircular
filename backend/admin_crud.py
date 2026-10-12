"""Administración de usuarios, zonas de cultivo y dispositivos ESP32."""
import hashlib
import secrets

import bcrypt
from bson.errors import InvalidId
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from pymongo.errors import DuplicateKeyError

from backend.app import (
    EMAIL_RE, as_oid, audit, current_user, db, roles_required, utcnow, validate_password
)

crud = Blueprint("crud", __name__, url_prefix="/admin")


def obj_id(value):
    try:
        return as_oid(value)
    except (ValueError, TypeError, InvalidId):
        abort(404)


def error(message, status=400):
    flash(message, "error")
    return redirect(url_for("admin_panel")), status


def text_value(field, low, high):
    value = request.form.get(field, "").strip()
    if not low <= len(value) <= high:
        raise ValueError(field)
    return value


def ensure_no_live_irrigation(zone_id):
    return db().eventos_riego.find_one({"zona_id": zone_id, "estado": "activo"}) is None


@crud.post("/usuarios/<user_id>/editar")
@roles_required("administrador")
def edit_user(user_id):
    oid = obj_id(user_id)
    previous = db().usuarios.find_one({"_id": oid})
    if not previous:
        abort(404)
    try:
        name = text_value("nombre", 3, 100)
        email = request.form.get("email", "").strip().lower()
        role = request.form.get("rol", "")
        if len(email) > 254 or not EMAIL_RE.fullmatch(email) or role not in {"operador", "administrador"}:
            raise ValueError("email")
    except ValueError:
        return error("Los datos del usuario no son validos.")
    active = request.form.get("activo") == "on"
    manual = request.form.get("control_manual") == "on"
    password = request.form.get("password", "")
    if password and not validate_password(password):
        return error("La nueva contrasena no cumple la politica de seguridad.")
    if oid == current_user()["_id"] and (not active or role != "administrador"):
        return error("No puedes desactivar tu cuenta ni quitarte el rol de administrador.", 409)
    if (previous["rol"] == "administrador" and previous["activo"]
            and (not active or role != "administrador")
            and db().usuarios.count_documents({"rol": "administrador", "activo": True}) <= 1):
        return error("Debe permanecer al menos un administrador activo.", 409)
    updates = {"nombre": name, "email": email, "rol": role, "activo": active,
               "control_manual_autorizado": manual, "actualizado_en": utcnow()}
    if password:
        updates["password_hash"] = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    try:
        db().usuarios.update_one({"_id": oid}, {"$set": updates})
    except DuplicateKeyError:
        return error("El correo ya esta registrado.", 409)
    audit("usuario_modificado", "exitoso", user_id, {"rol": role, "activo": active})
    flash("Usuario actualizado correctamente.", "success")
    return redirect(url_for("admin_panel"))


@crud.post("/usuarios/<user_id>/eliminar")
@roles_required("administrador")
def delete_user(user_id):
    oid = obj_id(user_id)
    previous = db().usuarios.find_one({"_id": oid})
    if not previous:
        abort(404)
    if oid == current_user()["_id"]:
        return error("No puedes desactivar tu propia cuenta.", 409)
    if (previous["rol"] == "administrador" and previous["activo"]
            and db().usuarios.count_documents({"rol": "administrador", "activo": True}) <= 1):
        return error("Debe permanecer al menos un administrador activo.", 409)
    db().usuarios.update_one({"_id": oid}, {"$set": {"activo": False, "actualizado_en": utcnow()}})
    audit("usuario_desactivado", "exitoso", user_id)
    flash("Usuario desactivado sin perder el historial.", "success")
    return redirect(url_for("admin_panel"))


@crud.post("/zonas/<zone_id>/editar")
@roles_required("administrador")
def edit_zone(zone_id):
    oid = obj_id(zone_id)
    if not db().zonas_cultivo.find_one({"_id": oid}):
        abort(404)
    try:
        name = text_value("nombre", 3, 80)
        crop = text_value("cultivo", 3, 80)
        location = text_value("ubicacion", 3, 120)
    except ValueError:
        return error("Nombre, cultivo o ubicacion invalidos.")
    active = request.form.get("activa") == "on"
    if not active and not ensure_no_live_irrigation(oid):
        return error("Primero debes detener el riego activo.", 409)
    db().zonas_cultivo.update_one({"_id": oid}, {"$set": {
        "nombre": name, "cultivo": crop, "ubicacion": location,
        "activa": active, "actualizada_en": utcnow(),
    }})
    if not active:
        db().dispositivos.update_many({"zona_id": oid, "activo": True}, {"$set": {
            "activo": False, "estado": "inactivo", "actualizado_en": utcnow(),
        }})
    audit("zona_modificada", "exitoso", zone_id, {"activa": active})
    flash("Zona actualizada. Reactiva los dispositivos por separado si corresponde.", "success")
    return redirect(url_for("admin_panel"))


@crud.post("/zonas/<zone_id>/eliminar")
@roles_required("administrador")
def delete_zone(zone_id):
    oid = obj_id(zone_id)
    if not db().zonas_cultivo.find_one({"_id": oid}):
        abort(404)
    if not ensure_no_live_irrigation(oid):
        return error("No puedes eliminar una zona con riego activo.", 409)
    db().zonas_cultivo.update_one({"_id": oid}, {"$set": {
        "activa": False, "actualizada_en": utcnow(),
    }})
    db().dispositivos.update_many({"zona_id": oid, "activo": True}, {"$set": {
        "activo": False, "estado": "inactivo", "actualizado_en": utcnow(),
    }})
    audit("zona_desactivada", "exitoso", zone_id)
    flash("Zona desactivada, conservando las lecturas historicas.", "success")
    return redirect(url_for("admin_panel"))


@crud.post("/dispositivos")
@roles_required("administrador")
def add_device():
    try:
        name = text_value("nombre", 3, 100)
        model = text_value("modelo", 2, 80)
        zone_id = obj_id(request.form.get("zona_id"))
        interval = int(request.form.get("intervalo_segundos", "300"))
        if not 60 <= interval <= 3600:
            raise ValueError("intervalo")
    except (ValueError, TypeError):
        return error("Los datos del dispositivo son invalidos.")
    if not db().zonas_cultivo.find_one({"_id": zone_id, "activa": True}):
        return error("Selecciona una zona activa.")
    token = secrets.token_urlsafe(32)
    device = db().dispositivos.insert_one({
        "nombre": name, "modelo": model, "zona_id": zone_id,
        "token_hash": hashlib.sha256(token.encode()).hexdigest(),
        "estado": "pendiente", "activo": True, "intervalo_segundos": interval,
        "ultima_conexion": None, "creado_en": utcnow(),
    })
    audit("dispositivo_creado_panel", "exitoso", str(device.inserted_id))
    return render_template("provision.html", token=token, nombre=name), 201, {"Cache-Control": "no-store"}


@crud.post("/dispositivos/<device_id>/editar")
@roles_required("administrador")
def edit_device(device_id):
    oid = obj_id(device_id)
    previous = db().dispositivos.find_one({"_id": oid})
    if not previous:
        abort(404)
    try:
        name = text_value("nombre", 3, 100)
        model = text_value("modelo", 2, 80)
        zone_id = obj_id(request.form.get("zona_id"))
        interval = int(request.form.get("intervalo_segundos", "300"))
        if not 60 <= interval <= 3600:
            raise ValueError("intervalo")
    except (ValueError, TypeError):
        return error("Los datos del dispositivo son invalidos.")
    active = request.form.get("activo") == "on"
    zone = db().zonas_cultivo.find_one({"_id": zone_id})
    if not zone or (active and not zone.get("activa", False)):
        return error("Un dispositivo activo requiere una zona activa.")
    state = previous.get("estado", "pendiente")
    if not active:
        state = "inactivo"
    elif not previous.get("activo"):
        state = "pendiente"
    db().dispositivos.update_one({"_id": oid}, {"$set": {
        "nombre": name, "modelo": model, "zona_id": zone_id,
        "intervalo_segundos": interval, "activo": active,
        "estado": state, "actualizado_en": utcnow(),
    }})
    audit("dispositivo_modificado_panel", "exitoso", device_id, {"activo": active})
    flash("Dispositivo actualizado.", "success")
    return redirect(url_for("admin_panel"))


@crud.post("/dispositivos/<device_id>/eliminar")
@roles_required("administrador")
def delete_device(device_id):
    oid = obj_id(device_id)
    if not db().dispositivos.find_one({"_id": oid}):
        abort(404)
    db().dispositivos.update_one({"_id": oid}, {"$set": {
        "activo": False, "estado": "inactivo", "actualizado_en": utcnow(),
    }})
    audit("dispositivo_desactivado", "exitoso", device_id)
    flash("Dispositivo desactivado sin perder sus lecturas historicas.", "success")
    return redirect(url_for("admin_panel"))
