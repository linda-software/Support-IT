"""
Calendario laboral automático para México.
Autora funcional: Jazmin Lopez Zamora.

Fuente primaria: API pública Nager.Date.
Respaldo: reglas federales mexicanas conocidas para días de descanso obligatorio.
Los descansos corporativos pueden venir de Google Workspace en un calendario dedicado.
"""
from __future__ import annotations

from calendar import monthcalendar, MONDAY
from datetime import date, datetime, timedelta
import json
import os
import urllib.request

NAGER_URL = "https://nagerholidays.com/api/v4/Holidays/MX/{year}"
COUNTRY = "MX"


def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _nth_weekday(year, month, weekday, n):
    d = date(year, month, 1)
    count = 0
    while True:
        if d.weekday() == weekday:
            count += 1
            if count == n:
                return d
        d += timedelta(days=1)


def statutory_fallback(year: int):
    # Respaldo para mantener el dashboard operativo si el proveedor externo falla.
    days = [
        (date(year, 1, 1), "Año Nuevo"),
        (_nth_weekday(year, 2, MONDAY, 1), "Conmemoración de la Constitución"),
        (_nth_weekday(year, 3, MONDAY, 3), "Conmemoración del natalicio de Benito Juárez"),
        (date(year, 5, 1), "Día del Trabajo"),
        (date(year, 9, 16), "Día de la Independencia"),
        (_nth_weekday(year, 11, MONDAY, 3), "Conmemoración de la Revolución Mexicana"),
        (date(year, 12, 25), "Navidad"),
    ]
    if year >= 2024 and (year - 2024) % 6 == 0:
        days.append((date(year, 10, 1), "Transmisión del Poder Ejecutivo Federal"))
    return [
        {
            "date": d.isoformat(),
            "localName": name,
            "name": name,
            "countryCode": COUNTRY,
            "global": True,
            "types": ["Public"],
            "fallback": True,
        }
        for d, name in sorted(days)
    ]


def fetch_nager(year: int):
    req = urllib.request.Request(
        NAGER_URL.format(year=year),
        headers={"User-Agent": "Infraestructura-EmpresaDemo-v22/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = json.loads(response.read().decode("utf-8"))
    filtered = []
    for item in payload if isinstance(payload, list) else []:
        # Nager.Holidays v4 usa holidayTypes/nationalHoliday.
        # También aceptamos los nombres anteriores para mantener compatibilidad.
        types = item.get("holidayTypes") or item.get("types") or ["Public"]
        is_national = item.get("nationalHoliday")
        if is_national is None:
            is_national = item.get("global", True)
        if is_national is False:
            continue
        if "Public" not in types:
            continue
        if not item.get("date"):
            continue
        normalized = dict(item)
        normalized.setdefault("types", types)
        normalized.setdefault("global", bool(is_national))
        filtered.append(normalized)
    if not filtered:
        raise RuntimeError("La API no devolvió feriados públicos para México")
    return filtered


def sync_year(con, year: int):
    source = "nager.date"
    error = None
    try:
        holidays = fetch_nager(year)
    except Exception as exc:
        holidays = statutory_fallback(year)
        source = "fallback-lft"
        error = str(exc)
    stamp = now_iso()
    con.execute("DELETE FROM public_holidays WHERE year=?", (year,))
    for item in holidays:
        name = item.get("localName") or item.get("name") or "Día no laborable"
        con.execute(
            """INSERT INTO public_holidays(day,name,source,year,metadata_json,synced_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(day) DO UPDATE SET name=excluded.name,source=excluded.source,
               year=excluded.year,metadata_json=excluded.metadata_json,synced_at=excluded.synced_at""",
            (item["date"], name, source, year, json.dumps(item, ensure_ascii=False), stamp),
        )
    return {"year": year, "count": len(holidays), "source": source, "error": error, "synced_at": stamp}


def maybe_sync_year(con, year: int, max_age_hours=24):
    row = con.execute(
        "SELECT synced_at FROM public_holidays WHERE year=? ORDER BY synced_at DESC LIMIT 1", (year,)
    ).fetchone()
    if row:
        try:
            last = datetime.fromisoformat(row["synced_at"])
            age = datetime.now().astimezone() - last
            if age.total_seconds() < max_age_hours * 3600:
                return {"year": year, "cached": True, "synced_at": row["synced_at"]}
        except Exception:
            pass
    return sync_year(con, year)


def sync_relevant_years(con):
    y = datetime.now().year
    results = [maybe_sync_year(con, y), maybe_sync_year(con, y + 1)]
    try:
        from google_calendar_connector import sync_company_non_working_days
        google_result = sync_company_non_working_days(con, y, y + 1)
    except Exception as exc:
        google_result = {"configured": False, "error": str(exc)}
    return {"public_holidays": results, "google_workspace": google_result}
