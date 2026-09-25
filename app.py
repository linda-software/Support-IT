"""
===============================================================================
AUTORA Y RESPONSABLE FUNCIONAL: Jazmin Lopez Zamora
PROYECTO: Plataforma de Infraestructura — Empresa Demo
VERSIÓN: v22 · 2026-09-08

Servidor web local de Infraestructura:
- URL compartida dentro de la red.
- Roles: Usuario estándar, Admin y Superadmin.
- Primera cuenta = Superadmin. Después solo Superadmin administra usuarios.
- PostgreSQL recomendado; SQLite funciona como modo de laboratorio/respaldo.
- Calendario laboral automático: L-J 09:00–18:00, V 09:00–14:00.
- Feriados públicos de México sincronizados por internet con caché local.
- Opción de combinar descansos corporativos desde Google Workspace Calendar.
- Puntos de integración con Odoo y Google Drive.
===============================================================================
"""
from __future__ import annotations

from http import cookies
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, unquote
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from datetime import datetime
import json
import mimetypes
import os
import secrets
import threading
import time
import uuid

from env_loader import load_env
load_env()

from database import db, init_db, backend_name
from auth import (
    COOKIE_NAME, ROLE_LABELS, audit, can, check_login, create_session, create_user,
    get_user_from_session, invalidate_session, public_user, users_count, iso as auth_iso,
    verify_password, set_password,
)
from holiday_service import sync_relevant_years

BASE = Path(__file__).resolve().parent
UPLOAD_DIR = Path(os.getenv("INFRA_UPLOAD_DIR", BASE / "uploads"))
STATIC_DIR = BASE / "static"
MAX_UPLOAD = 25 * 1024 * 1024
SETUP_CODE = secrets.token_hex(3).upper()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def row_to_payload(row):
    data = dict(row)
    if "payload_json" in data:
        payload = json.loads(data.pop("payload_json") or "{}")
        payload["id"] = data.get("id")
        return payload
    return data


def safe_filename(name: str) -> str:
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.() "
    clean = "".join(ch for ch in (name or "responsiva.pdf") if ch in allowed).strip()
    return clean[:180] or "responsiva.pdf"


class InfraHandler(BaseHTTPRequestHandler):
    server_version = "InfraestructuraEmpresaDemo/20"

    def log_message(self, fmt, *args):
        print(f"[{now_iso()}] {self.address_string()} - {fmt % args}")

    # --------------------------- response helpers ---------------------------
    def send_json(self, payload, status=200, extra_headers=None):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location, status=302, extra_headers=None):
        self.send_response(status)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()

    def send_static(self, filename):
        path = (STATIC_DIR / filename).resolve()
        if STATIC_DIR.resolve() not in path.parents or not path.is_file():
            return self.send_json({"error": "Archivo no encontrado"}, 404)
        content = path.read_bytes()
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8" if ctype.startswith("text/") or ctype in ("application/javascript",) else ctype)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.end_headers()
        self.wfile.write(content)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length > MAX_UPLOAD:
            raise ValueError("Archivo/solicitud demasiado grande")
        return self.rfile.read(length)

    def read_json(self):
        raw = self.read_body()
        return json.loads(raw.decode("utf-8") or "{}")

    def route_parts(self):
        parsed = urlparse(self.path)
        return parsed, [unquote(x) for x in parsed.path.strip("/").split("/") if x]

    # ------------------------------ auth ------------------------------------
    def raw_session_token(self):
        jar = cookies.SimpleCookie()
        try:
            jar.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = jar.get(COOKIE_NAME)
        return morsel.value if morsel else None

    def current_user(self):
        token = self.raw_session_token()
        if not token:
            return None
        try:
            with db() as con:
                return get_user_from_session(con, token)
        except Exception:
            return None

    def auth_required(self, permission=None):
        user = self.current_user()
        if not user:
            self.send_json({"error": "Sesión requerida"}, 401)
            return None
        path = urlparse(self.path).path
        password_routes = {"/api/me", "/api/auth/change-password", "/api/auth/logout"}
        if bool(dict(user).get("must_change_password", 0)) and path not in password_routes:
            self.send_json({
                "error": "Debes cambiar tu contraseña temporal antes de continuar",
                "code": "PASSWORD_CHANGE_REQUIRED"
            }, 403)
            return None
        if permission and not can(user["role"], permission):
            self.send_json({"error": "No tienes permiso para esta acción"}, 403)
            return None
        return user

    def page_auth(self, permission=None):
        user = self.current_user()
        if not user:
            self.redirect("/login")
            return None
        path = urlparse(self.path).path
        if bool(dict(user).get("must_change_password", 0)) and path not in ("/perfil", "/cambiar-contrasena"):
            self.redirect("/cambiar-contrasena")
            return None
        if permission and not can(user["role"], permission):
            self.redirect("/?forbidden=1")
            return None
        return user

    def session_cookie(self, raw, max_age):
        secure = os.getenv("COOKIE_SECURE", "false").lower() in ("1", "true", "yes")
        parts = [f"{COOKIE_NAME}={raw}", "Path=/", "HttpOnly", "SameSite=Strict", f"Max-Age={int(max_age)}"]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)

    def clear_cookie(self):
        return f"{COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"

    def audit_action(self, user, module, action, record_id=None, detail=None):
        try:
            with db() as con:
                audit(con, user["id"] if user else None, module, action, record_id, detail)
        except Exception as exc:
            print("Audit log error:", exc)

    # ------------------------------- GET ------------------------------------
    def do_GET(self):
        parsed, parts = self.route_parts()
        path = parsed.path

        # Public routes
        if path == "/api/health":
            with db() as con:
                setup_required = users_count(con) == 0
            return self.send_json({
                "ok": True, "service": "infraestructura",
                "version": "v22", "database": backend_name(), "setup_required": setup_required,
            })
        if path == "/api/auth/status":
            with db() as con:
                setup_required = users_count(con) == 0
            user = self.current_user()
            return self.send_json({"setup_required": setup_required, "authenticated": bool(user), "user": public_user(user) if user else None})
        if path == "/login":
            with db() as con:
                if users_count(con) == 0:
                    return self.redirect("/setup")
            if self.current_user():
                return self.redirect("/")
            return self.send_static("login.html")
        if path == "/setup":
            with db() as con:
                if users_count(con) > 0:
                    return self.redirect("/login")
            return self.send_static("setup.html")
        if path.startswith("/static/"):
            return self.send_static(path.removeprefix("/static/"))

        # Perfil propio y cambio obligatorio de contraseña.
        if path in ("/perfil", "/cambiar-contrasena"):
            user = self.current_user()
            if not user:
                return self.redirect("/login")
            return self.send_static("perfil.html")

        # Protected pages
        if path == "/":
            if not self.page_auth("dashboard.view"): return
            return self.send_static("index.html")
        if path == "/dashboard":
            if not self.page_auth("dashboard.view"): return
            return self.send_static("dashboard.html")
        if path == "/responsivas":
            if not self.page_auth("responsivas.view"): return
            return self.send_static("responsivas.html")
        if path == "/configuracion":
            if not self.page_auth(): return
            user = self.current_user()
            if user["role"] != "superadmin":
                return self.redirect("/?forbidden=1")
            return self.send_static("configuracion.html")
        if path == "/usuarios":
            if not self.page_auth(): return
            user = self.current_user()
            if user["role"] != "superadmin":
                return self.redirect("/?forbidden=1")
            return self.send_static("usuarios.html")
        if path == "/gobernanza":
            if not self.page_auth(): return
            user = self.current_user()
            if user["role"] != "superadmin":
                return self.redirect("/?forbidden=1")
            return self.send_static("gobernanza.html")

        # Protected APIs
        if path == "/api/me":
            user = self.auth_required()
            if not user: return
            return self.send_json({"user": public_user(user), "permissions": self.permission_summary(user["role"])})

        if path == "/api/calendar":
            user = self.auth_required("dashboard.view")
            if not user: return
            self.ensure_calendar_cache()
            with db() as con:
                schedule = con.execute("SELECT * FROM work_schedule ORDER BY weekday").fetchall()
                holiday_rows = con.execute("SELECT * FROM public_holidays ORDER BY day").fetchall()
                custom_rows = con.execute("SELECT * FROM non_working_days ORDER BY day").fetchall()
            union_days = sorted({r["day"] for r in holiday_rows} | {r["day"] for r in custom_rows})
            return self.send_json({
                "timezone": os.getenv("WORK_TIMEZONE", "America/Mexico_City"),
                "weekly_schedule": [dict(r) for r in schedule],
                "non_working_days": union_days,
                "public_holidays": [dict(r) for r in holiday_rows],
                "company_days": [dict(r) for r in custom_rows],
                "source": "Nager.Date + Google Workspace opcional + caché local",
            })

        if path == "/api/non-working-days":
            user = self.auth_required()
            if not user: return
            with db() as con:
                rows = con.execute("SELECT * FROM non_working_days ORDER BY day").fetchall()
            return self.send_json([dict(r) for r in rows])

        if path in ("/api/equipos", "/api/asignaciones"):
            user = self.auth_required("responsivas.view")
            if not user: return
            table = path.split("/")[-1]
            q = parse_qs(parsed.query)
            limit = min(max(int(q.get("limit", ["2000"])[0]), 1), 5000)
            with db() as con:
                rows = con.execute(f"SELECT id,payload_json FROM {table} ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
            return self.send_json([row_to_payload(r) for r in rows])

        if path == "/api/responsivas/documents":
            user = self.auth_required("documents.view")
            if not user: return
            with db() as con:
                rows = con.execute("SELECT * FROM responsiva_documents ORDER BY created_at DESC LIMIT 2000").fetchall()
            return self.send_json([dict(r) for r in rows])

        if path == "/api/users":
            user = self.auth_required()
            if not user: return
            if user["role"] != "superadmin":
                return self.send_json({"error": "Solo Superadmin puede administrar usuarios"}, 403)
            with db() as con:
                rows = con.execute("SELECT * FROM users ORDER BY created_at").fetchall()
            return self.send_json([public_user(r) for r in rows])

        if path == "/api/audit":
            user = self.auth_required()
            if not user: return
            if user["role"] != "superadmin":
                return self.send_json({"error": "Solo Superadmin"}, 403)
            with db() as con:
                rows = con.execute("SELECT * FROM audit_log ORDER BY created_at DESC LIMIT 500").fetchall()
            return self.send_json([dict(r) for r in rows])

        if path == "/api/governance":
            user = self.auth_required()
            if not user: return
            if user["role"] != "superadmin":
                return self.send_json({"error": "Solo Superadmin puede consultar Gobernanza"}, 403)
            with db() as con:
                current = con.execute(
                    "SELECT * FROM users WHERE role='superadmin' AND active=1 ORDER BY created_at LIMIT 1"
                ).fetchone()
                candidates = con.execute(
                    """SELECT * FROM users
                       WHERE id<>? AND active=1 AND role IN ('standard','admin')
                       ORDER BY display_name""",
                    (user["id"],),
                ).fetchall()
                rows = con.execute(
                    "SELECT * FROM project_history ORDER BY created_at DESC LIMIT 200"
                ).fetchall()
            history = []
            for row in rows:
                item = dict(row)
                try:
                    item["metadata"] = json.loads(item.get("metadata_json") or "{}")
                except Exception:
                    item["metadata"] = {}
                item.pop("metadata_json", None)
                history.append(item)
            return self.send_json({
                "current_superadmin": public_user(current) if current else None,
                "successor_candidates": [public_user(r) for r in candidates],
                "history": history,
                "policy": {
                    "single_active_superadmin": True,
                    "transfer_required_before_deactivation": True,
                    "project_history_read_only_from_ui": True,
                    "service_degrades_after_transfer": False,
                },
            })

        if len(parts) == 3 and parts[0] == "api" and parts[1] == "state":
            user = self.auth_required("dashboard.view")
            if not user: return
            key = parts[2]
            if key.startswith("developer_") and user["role"] != "superadmin":
                return self.send_json({"error": "Solo Superadmin puede consultar herramientas avanzadas"}, 403)
            with db() as con:
                row = con.execute("SELECT value_json,updated_at FROM app_state WHERE key=?", (key,)).fetchone()
            if not row:
                return self.send_json({"key": key, "exists": False, "value": None})
            return self.send_json({"key": key, "exists": True, "value": json.loads(row["value_json"]), "updated_at": row["updated_at"]})

        return self.send_json({"error": "Ruta no encontrada"}, 404)

    # ------------------------------- POST -----------------------------------
    def do_POST(self):
        parsed, parts = self.route_parts()
        try:
            if parsed.path == "/api/auth/setup":
                data = self.read_json()
                with db() as con:
                    if users_count(con) > 0:
                        return self.send_json({"error": "La configuración inicial ya fue completada"}, 409)
                    if str(data.get("setup_code") or "").strip().upper() != SETUP_CODE:
                        return self.send_json({"error": "Código de instalación incorrecto. Revisa la ventana del servidor."}, 403)
                    uid = create_user(
                        con,
                        data.get("username"),
                        data.get("display_name") or "Superadmin",
                        data.get("password"),
                        "superadmin",
                        actor_id=None,
                        must_change_password=False,
                    )
                    audit(con, uid, "auth", "setup_superadmin", uid, {"display_name": data.get("display_name")})
                    raw, expires = create_session(con, uid, self.client_address[0])
                    user = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                max_age = int((expires - datetime.now().astimezone()).total_seconds())
                return self.send_json({"ok": True, "user": public_user(user)}, 201, {"Set-Cookie": self.session_cookie(raw, max_age)})

            if parsed.path == "/api/auth/login":
                data = self.read_json()
                with db() as con:
                    user, error = check_login(con, data.get("username"), data.get("password"))
                    if not user:
                        return self.send_json({"error": error}, 401)
                    raw, expires = create_session(con, user["id"], self.client_address[0])
                    audit(con, user["id"], "auth", "login", user["id"], {"ip": self.client_address[0]})
                max_age = int((expires - datetime.now().astimezone()).total_seconds())
                return self.send_json({"ok": True, "user": public_user(user)}, 200, {"Set-Cookie": self.session_cookie(raw, max_age)})

            if parsed.path == "/api/auth/logout":
                token = self.raw_session_token()
                user = self.current_user()
                with db() as con:
                    invalidate_session(con, token)
                    if user:
                        audit(con, user["id"], "auth", "logout", user["id"], {})
                return self.send_json({"ok": True}, 200, {"Set-Cookie": self.clear_cookie()})

            if parsed.path == "/api/auth/change-password":
                user = self.auth_required()
                if not user: return
                data = self.read_json()
                current_password = str(data.get("current_password") or "")
                new_password = str(data.get("new_password") or "")
                if new_password == current_password:
                    return self.send_json({"error": "La nueva contraseña debe ser diferente a la actual"}, 400)
                with db() as con:
                    current = con.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
                    if not current or not verify_password(current_password, current["password_salt"], current["password_hash"]):
                        return self.send_json({"error": "La contraseña actual no es correcta"}, 400)
                    set_password(con, user["id"], new_password, must_change_password=False)
                    # Invalida todas las sesiones y crea una nueva para esta computadora.
                    con.execute("DELETE FROM sessions WHERE user_id=?", (user["id"],))
                    audit(con, user["id"], "auth", "password_change", user["id"], {
                        "forced_change_completed": bool(dict(user).get("must_change_password", 0))
                    })
                    raw, expires = create_session(con, user["id"], self.client_address[0])
                    updated = con.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
                max_age = int((expires - datetime.now().astimezone()).total_seconds())
                return self.send_json({"ok": True, "user": public_user(updated)}, 200, {"Set-Cookie": self.session_cookie(raw, max_age)})

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "users" and parts[3] == "reset-password":
                user = self.auth_required()
                if not user: return
                if user["role"] != "superadmin":
                    return self.send_json({"error": "Solo Superadmin puede restablecer contraseñas"}, 403)
                uid = parts[2]
                data = self.read_json()
                temporary_password = str(data.get("temporary_password") or "")
                with db() as con:
                    target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                    if not target:
                        return self.send_json({"error": "Usuario no encontrado"}, 404)
                    if uid == user["id"]:
                        return self.send_json({"error": "Para tu propia cuenta usa Mi perfil → Cambiar contraseña"}, 400)
                    set_password(con, uid, temporary_password, must_change_password=True)
                    con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                    audit(con, user["id"], "users", "password_reset", uid, {
                        "username": target["username"], "force_password_change": True, "sessions_revoked": True
                    })
                    updated = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                return self.send_json(public_user(updated))

            if len(parts) == 4 and parts[0] == "api" and parts[1] == "users" and parts[3] == "revoke-sessions":
                user = self.auth_required()
                if not user: return
                if user["role"] != "superadmin":
                    return self.send_json({"error": "Solo Superadmin puede cerrar sesiones de otros usuarios"}, 403)
                uid = parts[2]
                if uid == user["id"]:
                    return self.send_json({"error": "Para cerrar tu propia sesión usa el botón Salir"}, 400)
                with db() as con:
                    target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                    if not target:
                        return self.send_json({"error": "Usuario no encontrado"}, 404)
                    count_row = con.execute("SELECT COUNT(*) AS n FROM sessions WHERE user_id=?", (uid,)).fetchone()
                    count = int(count_row["n"] if count_row else 0)
                    con.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                    audit(con, user["id"], "users", "sessions_revoked", uid, {"count": count, "username": target["username"]})
                return self.send_json({"ok": True, "sessions_revoked": count})

            if parsed.path == "/api/users":
                user = self.auth_required()
                if not user: return
                if user["role"] != "superadmin":
                    return self.send_json({"error": "Solo Superadmin puede crear usuarios"}, 403)
                data = self.read_json()
                role = str(data.get("role") or "standard").lower()
                if role not in ("standard", "admin"):
                    return self.send_json({"error": "Solo existe una cuenta Superadmin. Puedes crear Standard o Admin."}, 400)
                force_change = bool(data.get("force_password_change", True))
                with db() as con:
                    uid = create_user(
                        con, data.get("username"), data.get("display_name"), data.get("password"),
                        role, user["id"], must_change_password=force_change
                    )
                    audit(con, user["id"], "users", "create", uid, {
                        "role": role, "username": data.get("username"),
                        "temporary_password": True, "force_password_change": force_change
                    })
                    created = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                return self.send_json(public_user(created), 201)

            if parsed.path == "/api/governance/transfer-superadmin":
                user = self.auth_required()
                if not user: return
                if user["role"] != "superadmin":
                    return self.send_json({"error": "Solo el Superadmin actual puede transferir la responsabilidad"}, 403)
                data = self.read_json()
                target_id = str(data.get("target_user_id") or "").strip()
                current_password = str(data.get("current_password") or "")
                reason = str(data.get("reason") or "").strip()
                authorized_by = str(data.get("authorized_by") or "").strip()
                confirmation = str(data.get("confirmation") or "").strip().upper()
                deactivate_current = bool(data.get("deactivate_current", False))
                if confirmation != "TRANSFERIR SUPERADMIN":
                    return self.send_json({"error": "Escribe exactamente TRANSFERIR SUPERADMIN para confirmar"}, 400)
                if len(reason) < 5:
                    return self.send_json({"error": "Captura el motivo de la transferencia"}, 400)
                if len(authorized_by) < 2:
                    return self.send_json({"error": "Captura quién autoriza o solicita la transferencia"}, 400)
                if not target_id or target_id == user["id"]:
                    return self.send_json({"error": "Selecciona otro usuario como sucesor"}, 400)
                with db() as con:
                    current = con.execute("SELECT * FROM users WHERE id=?", (user["id"],)).fetchone()
                    target = con.execute("SELECT * FROM users WHERE id=?", (target_id,)).fetchone()
                    if not current or current["role"] != "superadmin" or not bool(current["active"]):
                        return self.send_json({"error": "La cuenta actual ya no es el Superadmin activo"}, 409)
                    if not verify_password(current_password, current["password_salt"], current["password_hash"]):
                        return self.send_json({"error": "La contraseña actual de Superadmin no es correcta"}, 400)
                    if not target or not bool(target["active"]):
                        return self.send_json({"error": "El usuario sucesor no existe o está desactivado"}, 400)
                    if target["role"] == "superadmin":
                        return self.send_json({"error": "El usuario seleccionado ya es Superadmin"}, 400)
                    if bool(dict(target).get("must_change_password", 0)):
                        return self.send_json({"error": "El sucesor debe completar primero el cambio de su contraseña temporal"}, 400)
                    if not dict(target).get("last_login_at"):
                        return self.send_json({"error": "El sucesor debe iniciar sesión al menos una vez antes de recibir Superadmin"}, 400)

                    stamp = now_iso()
                    # Primero se retira el rol actual; después se promueve al sucesor.
                    # El índice único de BD impide dos Superadmin activos simultáneos.
                    con.execute(
                        "UPDATE users SET role='admin',active=?,updated_at=? WHERE id=?",
                        (0 if deactivate_current else 1, stamp, current["id"]),
                    )
                    con.execute(
                        "UPDATE users SET role='superadmin',active=1,updated_at=? WHERE id=?",
                        (stamp, target["id"]),
                    )
                    # La transferencia cambia permisos críticos: se cierran sesiones de ambas cuentas.
                    con.execute("DELETE FROM sessions WHERE user_id IN (?,?)", (current["id"], target["id"]))
                    detail = {
                        "from_username": current["username"],
                        "from_display_name": current["display_name"],
                        "to_username": target["username"],
                        "to_display_name": target["display_name"],
                        "reason": reason,
                        "authorized_by": authorized_by,
                        "previous_account_deactivated": deactivate_current,
                        "service_continuity": "sin degradacion funcional intencional",
                    }
                    audit(con, current["id"], "governance", "superadmin_transfer", target["id"], detail)
                    con.execute(
                        """INSERT INTO project_history(
                           id,event_key,event_type,title,description,actor_user_id,subject_user_id,metadata_json,created_at
                           ) VALUES(?,?,?,?,?,?,?,?,?)""",
                        (
                            uuid.uuid4().hex,
                            "superadmin_transfer_" + uuid.uuid4().hex,
                            "superadmin_transfer",
                            "Transferencia de responsabilidad Superadmin",
                            f"La administración principal fue transferida de {current['display_name']} a {target['display_name']}.",
                            current["id"], target["id"], json.dumps(detail, ensure_ascii=False), stamp,
                        ),
                    )
                return self.send_json({
                    "ok": True,
                    "message": "Transferencia completada. Ambos usuarios deben iniciar sesión nuevamente.",
                    "new_superadmin": {"id": target["id"], "username": target["username"], "display_name": target["display_name"]},
                    "previous_account_deactivated": deactivate_current,
                }, 200, {"Set-Cookie": self.clear_cookie()})

            if parsed.path == "/api/calendar/sync":
                user = self.auth_required()
                if not user: return
                if user["role"] not in ("admin", "superadmin"):
                    return self.send_json({"error": "Solo Admin o Superadmin pueden forzar sincronización"}, 403)
                with db() as con:
                    result = sync_relevant_years(con)
                    audit(con, user["id"], "calendar", "sync", None, result)
                return self.send_json(result)

            if parsed.path == "/api/non-working-days":
                user = self.auth_required()
                if not user: return
                if user["role"] != "superadmin":
                    return self.send_json({"error": "Solo Superadmin puede crear excepciones manuales"}, 403)
                data = self.read_json()
                day = str(data.get("day", "")).strip()
                name = str(data.get("name", "Descanso corporativo")).strip()
                if not day:
                    return self.send_json({"error": "day es obligatorio"}, 400)
                with db() as con:
                    con.execute(
                        """INSERT INTO non_working_days(day,name,created_at) VALUES(?,?,?)
                           ON CONFLICT(day) DO UPDATE SET name=excluded.name""",
                        (day, name, now_iso()),
                    )
                    audit(con, user["id"], "calendar", "custom_day_create", day, {"name": name})
                return self.send_json({"day": day, "name": name}, 201)

            if parsed.path in ("/api/equipos", "/api/asignaciones"):
                user = self.auth_required("responsivas.create")
                if not user: return
                table = parsed.path.split("/")[-1]
                data = self.read_json()
                rid = str(data.get("id") or uuid.uuid4().hex)
                payload = dict(data)
                payload.pop("id", None)
                stamp = now_iso()
                with db() as con:
                    con.execute(
                        f"INSERT INTO {table}(id,payload_json,created_at,updated_at) VALUES(?,?,?,?)",
                        (rid, json.dumps(payload, ensure_ascii=False), stamp, stamp),
                    )
                    audit(con, user["id"], table, "create", rid, {"summary": self.record_summary(payload)})
                return self.send_json({"id": rid}, 201)

            if parsed.path == "/api/responsivas/upload":
                user = self.auth_required("responsivas.create")
                if not user: return
                return self.handle_responsiva_upload(user)

            if parsed.path == "/api/sync/odoo/helpdesk":
                user = self.auth_required("odoo.sync")
                if not user: return
                try:
                    from odoo_connector import sync_helpdesk_tickets
                    result = sync_helpdesk_tickets(db, now_iso)
                    self.audit_action(user, "odoo", "helpdesk_sync", None, result)
                    return self.send_json(result)
                except Exception as exc:
                    return self.send_json({"error": str(exc)}, 503)

            return self.send_json({"error": "Ruta no encontrada"}, 404)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            return self.send_json({"error": f"Error del servidor: {exc}"}, 500)

    # ------------------------------- PUT ------------------------------------
    def do_PUT(self):
        parsed, parts = self.route_parts()
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "state":
            user = self.auth_required("responsivas.edit" if parts[2].startswith("resp") else "dashboard.view")
            if not user: return
            key = parts[2]
            if key.startswith("developer_") and user["role"] != "superadmin":
                return self.send_json({"error": "Solo Superadmin puede modificar herramientas avanzadas"}, 403)
            # app_state operativo puede ser actualizado por Admin/Superadmin; estándar solo consulta.
            if user["role"] == "standard":
                return self.send_json({"error": "El usuario estándar es de consulta"}, 403)
            try:
                data = self.read_json()
                value = data.get("value")
                with db() as con:
                    con.execute(
                        """INSERT INTO app_state(key,value_json,updated_at) VALUES(?,?,?)
                           ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json,updated_at=excluded.updated_at""",
                        (parts[2], json.dumps(value, ensure_ascii=False), now_iso()),
                    )
                    audit(con, user["id"], "app_state", "save", parts[2], {})
                return self.send_json({"key": parts[2], "saved": True})
            except Exception as exc:
                return self.send_json({"error": f"Error del servidor: {exc}"}, 500)
        return self.handle_collection_update(merge=False)

    def do_PATCH(self):
        parsed, parts = self.route_parts()
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "users":
            return self.handle_user_update(parts[2])
        return self.handle_collection_update(merge=True)

    def do_DELETE(self):
        parsed, parts = self.route_parts()
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "non-working-days":
            user = self.auth_required()
            if not user: return
            if user["role"] != "superadmin":
                return self.send_json({"error": "Solo Superadmin"}, 403)
            with db() as con:
                con.execute("DELETE FROM non_working_days WHERE day=?", (parts[2],))
                audit(con, user["id"], "calendar", "custom_day_delete", parts[2], {})
            return self.send_json({"deleted": True, "day": parts[2]})
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "users":
            return self.handle_user_delete(parts[2])
        return self.send_json({"error": "Ruta no encontrada"}, 404)

    # --------------------------- protected handlers -------------------------
    def handle_collection_update(self, merge):
        parsed, parts = self.route_parts()
        if len(parts) != 3 or parts[0] != "api" or parts[1] not in ("equipos", "asignaciones"):
            return self.send_json({"error": "Ruta no encontrada"}, 404)
        user = self.auth_required("responsivas.edit")
        if not user: return
        table, rid = parts[1], parts[2]
        try:
            incoming = self.read_json()
            stamp = now_iso()
            with db() as con:
                existing = con.execute(f"SELECT payload_json,created_at FROM {table} WHERE id=?", (rid,)).fetchone()
                current = json.loads(existing["payload_json"]) if existing else {}
                payload = {**current, **incoming} if merge else dict(incoming)
                payload.pop("id", None)
                created = existing["created_at"] if existing else stamp
                con.execute(
                    f"""INSERT INTO {table}(id,payload_json,created_at,updated_at) VALUES(?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET payload_json=excluded.payload_json,updated_at=excluded.updated_at""",
                    (rid, json.dumps(payload, ensure_ascii=False), created, stamp),
                )
                audit(con, user["id"], table, "update", rid, {"keys": list(incoming.keys())})
            return self.send_json({"id": rid, **payload})
        except Exception as exc:
            return self.send_json({"error": f"Error del servidor: {exc}"}, 500)

    def handle_user_update(self, uid):
        user = self.auth_required()
        if not user: return
        if user["role"] != "superadmin":
            return self.send_json({"error": "Solo Superadmin puede modificar usuarios"}, 403)
        try:
            data = self.read_json()
            with db() as con:
                target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                if not target:
                    return self.send_json({"error": "Usuario no encontrado"}, 404)
                display_name = str(data.get("display_name", target["display_name"])).strip()
                role = str(data.get("role", target["role"])).strip().lower()
                active = 1 if bool(data.get("active", bool(target["active"]))) else 0
                if role not in ROLE_LABELS:
                    return self.send_json({"error": "Rol no válido"}, 400)
                if role == "superadmin" and uid != user["id"]:
                    return self.send_json({"error": "Solo la cuenta principal puede ser Superadmin"}, 400)
                # No permitir que la sesión actual se quite a sí misma el control total.
                if uid == user["id"] and (role != "superadmin" or not active):
                    return self.send_json({"error": "No puedes quitarte a ti misma el rol Superadmin ni desactivar tu propia cuenta"}, 400)
                if "new_password" in data:
                    return self.send_json({"error": "Usa la acción Restablecer acceso para cambiar la contraseña de otro usuario"}, 400)
                con.execute("UPDATE users SET display_name=?,role=?,active=?,updated_at=? WHERE id=?", (display_name, role, active, now_iso(), uid))
                audit(con, user["id"], "users", "update", uid, {"role": role, "active": bool(active)})
                updated = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            return self.send_json(public_user(updated))
        except Exception as exc:
            return self.send_json({"error": f"Error del servidor: {exc}"}, 500)

    def handle_user_delete(self, uid):
        user = self.auth_required()
        if not user: return
        if user["role"] != "superadmin":
            return self.send_json({"error": "Solo Superadmin puede eliminar usuarios"}, 403)
        if uid == user["id"]:
            return self.send_json({"error": "No puedes eliminar tu propia cuenta Superadmin"}, 400)
        with db() as con:
            target = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if not target:
                return self.send_json({"error": "Usuario no encontrado"}, 404)
            con.execute("DELETE FROM users WHERE id=?", (uid,))
            audit(con, user["id"], "users", "delete", uid, {"username": target["username"], "role": target["role"]})
        return self.send_json({"deleted": True, "id": uid})

    def handle_responsiva_upload(self, user):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            return self.send_json({"error": "Se esperaba multipart/form-data"}, 400)
        body = self.read_body()
        prefix = f"Content-Type: {ctype}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        msg = BytesParser(policy=email_policy).parsebytes(prefix + body)
        file_bytes = None
        filename = None
        metadata = {}
        for part in msg.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if name == "file":
                file_bytes = part.get_payload(decode=True)
                filename = safe_filename(part.get_filename() or "responsiva.pdf")
            elif name == "metadata":
                try:
                    metadata = json.loads((part.get_payload(decode=True) or b"{}").decode("utf-8"))
                except Exception:
                    metadata = {}
        if not file_bytes:
            return self.send_json({"error": "PDF requerido"}, 400)

        temp_path = UPLOAD_DIR / f"{uuid.uuid4().hex}_{filename}"
        temp_path.write_bytes(file_bytes)
        storage = "local"
        drive_id = drive_url = None
        try:
            from google_drive_connector import upload_file_if_configured
            result = upload_file_if_configured(temp_path, filename, metadata)
            if result:
                storage = "google_drive"
                drive_id = result.get("id")
                drive_url = result.get("webViewLink")
                if os.getenv("KEEP_LOCAL_UPLOADS", "false").lower() not in ("1", "true", "yes"):
                    temp_path.unlink(missing_ok=True)
        except Exception as exc:
            print("Google Drive no disponible:", exc)

        rid = uuid.uuid4().hex
        with db() as con:
            con.execute(
                """INSERT INTO responsiva_documents(
                id,asignacion_id,serial,filename,storage,local_path,drive_file_id,drive_url,metadata_json,created_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (rid, metadata.get("asignacion_id"), metadata.get("serial"), filename, storage,
                 str(temp_path) if temp_path.exists() else None, drive_id, drive_url,
                 json.dumps(metadata, ensure_ascii=False), now_iso()),
            )
            audit(con, user["id"], "responsivas", "pdf_archive", rid, {"serial": metadata.get("serial"), "storage": storage})
        return self.send_json({"id": rid, "stored": True, "storage": storage, "drive_file_id": drive_id, "drive_url": drive_url}, 201)

    # ------------------------------ misc ------------------------------------
    def ensure_calendar_cache(self):
        try:
            with db() as con:
                sync_relevant_years(con)
        except Exception as exc:
            print("Calendario automático:", exc)

    @staticmethod
    def record_summary(payload):
        return {
            "serial": payload.get("serial"),
            "tipo": payload.get("tipo"),
            "capturadoPor": payload.get("capturadoPor"),
        }

    @staticmethod
    def permission_summary(role):
        return {
            "can_create_responsivas": can(role, "responsivas.create"),
            "can_edit_responsivas": can(role, "responsivas.edit"),
            "can_sync_odoo": can(role, "odoo.sync"),
            "can_manage_users": role == "superadmin",
            "can_configure_system": role == "superadmin",
            "can_manage_governance": role == "superadmin",
        }


def calendar_background_worker():
    # Una sincronización diaria basta: los feriados cambian muy poco y quedan en caché.
    while True:
        try:
            with db() as con:
                sync_relevant_years(con)
        except Exception as exc:
            print("[calendar-worker]", exc)
        time.sleep(24 * 60 * 60)


def run():
    init_db()
    try:
        with db() as con:
            sync_relevant_years(con)
    except Exception as exc:
        print("Calendario inicial no pudo sincronizarse; se usará caché/respaldo:", exc)

    worker = threading.Thread(target=calendar_background_worker, name="calendar-sync", daemon=True)
    worker.start()

    host = os.getenv("INFRA_HOST", "0.0.0.0")
    port = int(os.getenv("INFRA_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), InfraHandler)
    print("=" * 78)
    print("Plataforma de Infraestructura v22 · Empresa Demo")
    print(f"Base de datos: {backend_name()}")
    print("Horario: lunes-jueves 09:00–18:00 · viernes 09:00–14:00")
    print(f"Servidor activo en http://localhost:{port}")
    print(f"En la red local: http://IP_DEL_SERVIDOR:{port}")
    with db() as con:
        needs_setup = users_count(con) == 0
    if needs_setup:
        print("Primera ejecución: abre /setup para crear la cuenta Superadmin.")
        print(f"CÓDIGO DE INSTALACIÓN: {SETUP_CODE}")
    print("Ctrl+C para detener")
    print("=" * 78)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run()
