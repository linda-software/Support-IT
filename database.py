"""
===============================================================================
AUTORA Y RESPONSABLE FUNCIONAL: Jazmin Lopez Zamora
PROYECTO: Plataforma de Infraestructura — Empresa Demo
VERSIÓN: v22 · 2026-09-08

Capa de base de datos con dos modos:
- PostgreSQL (recomendado para uso compartido y crecimiento).
- SQLite (respaldo inmediato / modo laboratorio sin dependencias).

Si DATABASE_URL existe, se usa PostgreSQL. Si no, se usa SQLite.
===============================================================================
"""
from __future__ import annotations

from pathlib import Path
from datetime import datetime
import os
import sqlite3

BASE = Path(__file__).resolve().parent
SQLITE_PATH = Path(os.getenv("INFRA_DB_PATH", BASE / "data" / "infraestructura.db"))
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
PGDATABASE = os.getenv("PGDATABASE", "").strip()
FORCE_BACKEND = os.getenv("INFRA_DB_BACKEND", "").strip().lower()
BACKEND = "postgresql" if (DATABASE_URL or PGDATABASE or FORCE_BACKEND == "postgresql") else "sqlite"


class CursorProxy:
    def __init__(self, cursor):
        self.cursor = cursor

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class ConnectionProxy:
    def __init__(self, conn, backend: str):
        self.conn = conn
        self.backend = backend

    def _sql(self, sql: str) -> str:
        if self.backend == "postgresql":
            # El proyecto no usa '?' dentro de literales SQL, por lo que esta traducción
            # mantiene una sola sintaxis de consultas entre SQLite y PostgreSQL.
            return sql.replace("?", "%s")
        return sql

    def execute(self, sql: str, params=()):
        cur = self.conn.execute(self._sql(sql), params)
        return CursorProxy(cur)

    def executescript(self, script: str):
        if self.backend == "sqlite":
            self.conn.executescript(script)
            return
        # psycopg puede ejecutar múltiples sentencias simples en modo texto, pero
        # dividir aquí hace el arranque más predecible.
        for statement in script.split(";"):
            statement = statement.strip()
            if statement:
                self.conn.execute(statement)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def __enter__(self):
        self.conn.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self.conn.__exit__(exc_type, exc, tb)


def db() -> ConnectionProxy:
    if BACKEND == "postgresql":
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:
            raise RuntimeError(
                "DATABASE_URL está configurado, pero falta psycopg. "
                "Ejecuta: pip install -r requirements-postgresql.txt"
            ) from exc
        if DATABASE_URL:
            conn = psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
        else:
            conn = psycopg.connect(
                host=os.getenv("PGHOST", "localhost"),
                port=int(os.getenv("PGPORT", "5432")),
                dbname=os.getenv("PGDATABASE", "infraestructura"),
                user=os.getenv("PGUSER", "infra_app"),
                password=os.getenv("PGPASSWORD", ""),
                row_factory=dict_row,
                autocommit=False,
            )
        return ConnectionProxy(conn, "postgresql")

    SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return ConnectionProxy(conn, "sqlite")


def init_db():
    schema_name = "schema_postgresql.sql" if BACKEND == "postgresql" else "schema.sql"
    schema = (BASE / schema_name).read_text(encoding="utf-8")
    with db() as con:
        con.executescript(schema)
        migrate_auth_schema(con)
        seed_work_schedule(con)
        seed_project_history(con)



def migrate_auth_schema(con):
    """Añade campos de seguridad sin destruir una BD existente."""
    if con.backend == "postgresql":
        con.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS must_change_password INTEGER NOT NULL DEFAULT 0")
        con.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_changed_at TEXT")
        return

    cols = {row["name"] for row in con.execute("PRAGMA table_info(users)").fetchall()}
    if "must_change_password" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0")
    if "password_changed_at" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN password_changed_at TEXT")

def seed_work_schedule(con):
    # 0=domingo, 1=lunes ... 6=sábado. Viernes termina a las 14:00.
    schedule = [
        (0, 0, None, None),
        (1, 1, "09:00", "18:00"),
        (2, 1, "09:00", "18:00"),
        (3, 1, "09:00", "18:00"),
        (4, 1, "09:00", "18:00"),
        (5, 1, "09:00", "14:00"),
        (6, 0, None, None),
    ]
    for weekday, is_working, start_time, end_time in schedule:
        con.execute(
            """INSERT INTO work_schedule(weekday,is_working,start_time,end_time,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(weekday) DO NOTHING""",
            (weekday, is_working, start_time, end_time, datetime.now().astimezone().isoformat(timespec="seconds")),
        )


def backend_name():
    return BACKEND


def seed_project_history(con):
    """
    Registra la procedencia técnica del proyecto una sola vez.

    Este registro es histórico y no implica propiedad patrimonial del software.
    No existe endpoint de edición o eliminación para project_history.
    """
    stamp = datetime.now().astimezone().isoformat(timespec="seconds")
    metadata = (
        '{"contributor":"Jazmin Lopez Zamora",'
        '"scope":["concepcion inicial","diseno funcional","prototipo",'
        '"arquitectura de plataforma","documentacion tecnica"],'
        '"note":"Registro historico de contribucion; no es una marca de propiedad."}'
    )
    con.execute(
        """INSERT INTO project_history(
             id,event_key,event_type,title,description,actor_user_id,subject_user_id,metadata_json,created_at
           ) VALUES(?,?,?,?,?,?,?,?,?)
           ON CONFLICT(event_key) DO NOTHING""",
        (
            "history-initial-contribution-jlz",
            "initial_contribution_jlz",
            "initial_contribution",
            "Contribución inicial documentada",
            "Concepción inicial, diseño funcional, desarrollo del prototipo y documentación técnica del proyecto.",
            None, None, metadata, stamp,
        ),
    )
