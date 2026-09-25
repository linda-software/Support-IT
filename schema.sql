-- ============================================================================
-- AUTORA: Jazmin Lopez Zamora
-- Plataforma de Infraestructura v22 · Esquema SQLite
-- ============================================================================
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS equipos (
  id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS asignaciones (
  id TEXT PRIMARY KEY,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS responsiva_documents (
  id TEXT PRIMARY KEY,
  asignacion_id TEXT,
  serial TEXT,
  filename TEXT NOT NULL,
  storage TEXT NOT NULL,
  local_path TEXT,
  drive_file_id TEXT,
  drive_url TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS non_working_days (
  day TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS public_holidays (
  day TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  source TEXT NOT NULL,
  year INTEGER NOT NULL,
  metadata_json TEXT,
  synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS work_schedule (
  weekday INTEGER PRIMARY KEY,
  is_working INTEGER NOT NULL DEFAULT 0,
  start_time TEXT,
  end_time TEXT,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS odoo_tickets (
  odoo_id INTEGER PRIMARY KEY,
  payload_json TEXT NOT NULL,
  synced_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_state (
  key TEXT PRIMARY KEY,
  value_json TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('standard','admin','superadmin')),
  password_salt TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1,
  failed_attempts INTEGER NOT NULL DEFAULT 0,
  locked_until TEXT,
  last_login_at TEXT,
  created_by TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  must_change_password INTEGER NOT NULL DEFAULT 0,
  password_changed_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  ip_address TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  actor TEXT,
  module TEXT NOT NULL,
  action TEXT NOT NULL,
  record_id TEXT,
  detail_json TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_history (
  id TEXT PRIMARY KEY,
  event_key TEXT UNIQUE,
  event_type TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT,
  actor_user_id TEXT,
  subject_user_id TEXT,
  metadata_json TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_resp_serial ON responsiva_documents(serial);
CREATE INDEX IF NOT EXISTS idx_resp_asig ON responsiva_documents(asignacion_id);
CREATE INDEX IF NOT EXISTS idx_holiday_year ON public_holidays(year);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_single_active_superadmin ON users(role) WHERE role='superadmin' AND active=1;
CREATE INDEX IF NOT EXISTS idx_project_history_created ON project_history(created_at);
