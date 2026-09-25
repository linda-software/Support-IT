"""Conector Odoo.

Autora funcional del proyecto: Jazmin Lopez Zamora.

La integración real requiere conocer la versión de Odoo, el plan con acceso API y
los nombres TÉCNICOS de los campos personalizados usados por la instancia.
El export Excel usa etiquetas visibles, que no siempre coinciden con esos nombres.

Modos soportados:
- xmlrpc: compatible con varias versiones históricas de Odoo.
- json2: API recomendada para Odoo 19+.
"""
from __future__ import annotations
import os
import json
import xmlrpc.client
import urllib.request


def _required(name):
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta configurar {name} en el entorno")
    return value


def _mode():
    return os.getenv("ODOO_API_MODE", "xmlrpc").strip().lower()


def _xmlrpc_client():
    url = _required("ODOO_URL").rstrip("/")
    db = _required("ODOO_DB")
    user = _required("ODOO_USER")
    key = _required("ODOO_API_KEY")
    common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
    uid = common.authenticate(db, user, key, {})
    if not uid:
        raise RuntimeError("Odoo rechazó las credenciales")
    models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")
    return models, db, uid, key


def _json2_call(model, method, payload):
    url = _required("ODOO_URL").rstrip("/")
    key = _required("ODOO_API_KEY")
    headers = {
        "Authorization": f"bearer {key}",
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "application/json",
    }
    db_name = os.getenv("ODOO_DB")
    if db_name:
        headers["X-Odoo-Database"] = db_name
    req = urllib.request.Request(
        f"{url}/json/2/{model}/{method}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Error JSON-2 de Odoo: {exc}") from exc


def get_helpdesk_fields():
    model = os.getenv("ODOO_HELPDESK_MODEL", "helpdesk.ticket")
    if _mode() == "json2":
        return _json2_call(model, "fields_get", {"attributes": ["string", "type", "required"]})
    models, db, uid, key = _xmlrpc_client()
    return models.execute_kw(db, uid, key, model, "fields_get", [], {"attributes": ["string", "type", "required"]})


def fetch_helpdesk_records():
    """Lee tickets con campos configurados, sin inventar nombres técnicos."""
    fields = json.loads(os.getenv("ODOO_HELPDESK_FIELDS_JSON", '["id","name","create_date","write_date"]'))
    model = os.getenv("ODOO_HELPDESK_MODEL", "helpdesk.ticket")
    limit = int(os.getenv("ODOO_SYNC_LIMIT", "5000"))
    if _mode() == "json2":
        records = _json2_call(model, "search_read", {
            "domain": [],
            "fields": fields,
            "limit": limit,
            "order": "id asc",
        })
    else:
        models, db_name, uid, key = _xmlrpc_client()
        records = models.execute_kw(
            db_name, uid, key, model, "search_read", [[]],
            {"fields": fields, "limit": limit, "order": "id asc"},
        )
    return model, fields, records


def sync_helpdesk_tickets(db_factory, now_iso):
    """Sincroniza Odoo -> SQLite para histórico y futuras pantallas sin Excel."""
    model, fields, records = fetch_helpdesk_records()
    stamp = now_iso()
    with db_factory() as con:
        for record in records:
            con.execute(
                """INSERT INTO odoo_tickets(odoo_id,payload_json,synced_at) VALUES(?,?,?)
                ON CONFLICT(odoo_id) DO UPDATE SET payload_json=excluded.payload_json,synced_at=excluded.synced_at""",
                (int(record["id"]), json.dumps(record, ensure_ascii=False, default=str), stamp),
            )
    return {"ok": True, "mode": _mode(), "model": model, "records": len(records), "fields": fields, "synced_at": stamp}
