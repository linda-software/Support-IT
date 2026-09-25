"""
Autenticación y perfiles de usuario.
Autora funcional: Jazmin Lopez Zamora.
Versión: v22 · 2026-09-08

Roles:
- standard: consulta / visualización.
- admin: operación diaria, captura, edición operativa y sincronizaciones.
- superadmin: control total de usuarios, configuración y acciones destructivas.

Principios de seguridad vigentes en v22:
- Las contraseñas nunca se guardan ni se muestran en texto plano.
- Superadmin puede restablecer acceso, pero no conocer la contraseña elegida por otro usuario.
- Los usuarios creados con contraseña temporal deben cambiarla en su primer acceso.
- Los usuarios pueden cambiar su propia contraseña desde Mi perfil.
- Un restablecimiento administrativo invalida las sesiones activas del usuario.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import base64
import hashlib
import hmac
import json
import os
import secrets
import uuid

PBKDF2_ITERATIONS = int(os.getenv("PASSWORD_ITERATIONS", "390000"))
SESSION_HOURS = int(os.getenv("SESSION_HOURS", "12"))
COOKIE_NAME = "infra_session"

ROLE_LABELS = {
    "standard": "Usuario estándar",
    "admin": "Admin",
    "superadmin": "Superadmin",
}


def now_dt():
    return datetime.now().astimezone()


def iso(dt=None):
    return (dt or now_dt()).isoformat(timespec="seconds")


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def normalize_username(value):
    return str(value or "").strip().lower()


def hash_password(password: str, salt_b64: str | None = None):
    if salt_b64:
        salt = base64.b64decode(salt_b64.encode("ascii"))
    else:
        salt = secrets.token_bytes(18)
        salt_b64 = base64.b64encode(salt).decode("ascii")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return salt_b64, base64.b64encode(digest).decode("ascii")


def verify_password(password: str, salt_b64: str, expected_hash_b64: str):
    _, actual = hash_password(password, salt_b64)
    return hmac.compare_digest(actual, expected_hash_b64)


def validate_password(password: str):
    password = str(password or "")
    if len(password) < 10:
        raise ValueError("La contraseña debe tener al menos 10 caracteres")
    if password.isspace():
        raise ValueError("La contraseña no puede estar vacía")
    return password


def users_count(con):
    row = con.execute("SELECT COUNT(*) AS n FROM users").fetchone()
    return int(row["n"] if row else 0)


def public_user(row):
    data = dict(row)
    return {
        "id": data["id"],
        "username": data["username"],
        "display_name": data["display_name"],
        "role": data["role"],
        "role_label": ROLE_LABELS.get(data["role"], data["role"]),
        "active": bool(data["active"]),
        "must_change_password": bool(data.get("must_change_password", 0)),
        "password_changed_at": data.get("password_changed_at"),
        "last_login_at": data.get("last_login_at"),
        "created_at": data["created_at"],
    }


def create_user(con, username, display_name, password, role, actor_id=None, must_change_password=False):
    username = normalize_username(username)
    display_name = str(display_name or "").strip()
    role = str(role or "standard").strip().lower()
    if role not in ROLE_LABELS:
        raise ValueError("Rol no válido")
    if len(username) < 3:
        raise ValueError("El usuario debe tener al menos 3 caracteres")
    if len(display_name) < 2:
        raise ValueError("Captura el nombre del usuario")
    password = validate_password(password)
    exists = con.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()
    if exists:
        raise ValueError("Ese usuario ya existe")
    salt, phash = hash_password(password)
    uid = uuid.uuid4().hex
    stamp = iso()
    changed_at = None if must_change_password else stamp
    con.execute(
        """INSERT INTO users(id,username,display_name,role,password_salt,password_hash,active,
           failed_attempts,locked_until,last_login_at,created_by,created_at,updated_at,
           must_change_password,password_changed_at)
           VALUES(?,?,?,?,?,?,1,0,NULL,NULL,?,?,?,?,?)""",
        (
            uid, username, display_name, role, salt, phash, actor_id, stamp, stamp,
            1 if must_change_password else 0, changed_at,
        ),
    )
    return uid


def set_password(con, user_id, new_password, must_change_password=False):
    """Cambia/restablece contraseña. Nunca devuelve el valor de la contraseña."""
    new_password = validate_password(new_password)
    salt, phash = hash_password(new_password)
    stamp = iso()
    changed_at = None if must_change_password else stamp
    con.execute(
        """UPDATE users
           SET password_salt=?,password_hash=?,failed_attempts=0,locked_until=NULL,
               must_change_password=?,password_changed_at=?,updated_at=?
           WHERE id=?""",
        (salt, phash, 1 if must_change_password else 0, changed_at, stamp, user_id),
    )


def audit(con, actor, module, action, record_id=None, detail=None):
    con.execute(
        "INSERT INTO audit_log(actor,module,action,record_id,detail_json,created_at) VALUES(?,?,?,?,?,?)",
        (actor, module, action, record_id, json.dumps(detail or {}, ensure_ascii=False), iso()),
    )


def create_session(con, user_id, ip_address=None):
    raw = secrets.token_urlsafe(36)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    created = now_dt()
    expires = created + timedelta(hours=SESSION_HOURS)
    con.execute(
        "INSERT INTO sessions(token_hash,user_id,expires_at,created_at,last_seen_at,ip_address) VALUES(?,?,?,?,?,?)",
        (token_hash, user_id, iso(expires), iso(created), iso(created), ip_address),
    )
    return raw, expires


def session_hash(raw):
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


def get_user_from_session(con, raw_token):
    if not raw_token:
        return None
    token_hash = session_hash(raw_token)
    row = con.execute(
        """SELECT u.* , s.expires_at AS session_expires_at
           FROM sessions s JOIN users u ON u.id=s.user_id
           WHERE s.token_hash=?""",
        (token_hash,),
    ).fetchone()
    if not row or not bool(row["active"]):
        return None
    exp = parse_iso(row["session_expires_at"])
    if not exp or exp <= now_dt():
        con.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        return None
    con.execute("UPDATE sessions SET last_seen_at=? WHERE token_hash=?", (iso(), token_hash))
    return row


def invalidate_session(con, raw_token):
    if raw_token:
        con.execute("DELETE FROM sessions WHERE token_hash=?", (session_hash(raw_token),))


def check_login(con, username, password):
    username = normalize_username(username)
    row = con.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
    if not row or not bool(row["active"]):
        return None, "Usuario o contraseña incorrectos"
    locked = parse_iso(row["locked_until"])
    if locked and locked > now_dt():
        minutes = max(1, int((locked - now_dt()).total_seconds() // 60) + 1)
        return None, f"Cuenta bloqueada temporalmente. Intenta en {minutes} min."
    if not verify_password(password or "", row["password_salt"], row["password_hash"]):
        attempts = int(row["failed_attempts"] or 0) + 1
        locked_until = None
        if attempts >= 5:
            locked_until = iso(now_dt() + timedelta(minutes=15))
            attempts = 0
        con.execute(
            "UPDATE users SET failed_attempts=?,locked_until=?,updated_at=? WHERE id=?",
            (attempts, locked_until, iso(), row["id"]),
        )
        return None, "Usuario o contraseña incorrectos"
    con.execute(
        "UPDATE users SET failed_attempts=0,locked_until=NULL,last_login_at=?,updated_at=? WHERE id=?",
        (iso(), iso(), row["id"]),
    )
    return con.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone(), None


def can(role, permission):
    permissions = {
        "standard": {
            "dashboard.view", "responsivas.view", "inventory.view", "documents.view",
        },
        "admin": {
            "dashboard.view", "responsivas.view", "responsivas.create", "responsivas.edit",
            "inventory.view", "inventory.edit", "documents.view", "odoo.sync", "calendar.view",
        },
        "superadmin": {"*"},
    }
    p = permissions.get(role, set())
    return "*" in p or permission in p
