"""Google Workspace Calendar connector.
Autora funcional: Jazmin Lopez Zamora.

Uso recomendado: crear un calendario compartido exclusivo llamado, por ejemplo,
"Infraestructura - Días no laborables". El sistema toma sus eventos de día completo
como descansos corporativos y los combina con los feriados públicos automáticos.
"""
from __future__ import annotations
from datetime import datetime, timezone
import os


def sync_company_non_working_days(con, start_year, end_year):
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    calendar_id = os.getenv("GOOGLE_NON_WORKING_CALENDAR_ID")
    if not creds_path or not calendar_id:
        return {"configured": False, "reason": "GOOGLE_NON_WORKING_CALENDAR_ID no configurado"}

    from google.oauth2 import service_account
    from googleapiclient.discovery import build

    scopes = ["https://www.googleapis.com/auth/calendar.readonly"]
    creds = service_account.Credentials.from_service_account_file(creds_path, scopes=scopes)
    subject = os.getenv("GOOGLE_IMPERSONATE_USER")
    if subject:
        creds = creds.with_subject(subject)
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    time_min = f"{start_year}-01-01T00:00:00Z"
    time_max = f"{end_year + 1}-01-01T00:00:00Z"
    # Refrescar la copia de Google para que eventos eliminados del calendario
    # también desaparezcan del cálculo en la siguiente sincronización.
    con.execute(
        "DELETE FROM non_working_days WHERE name LIKE ? AND day>=? AND day<?",
        ("Google Workspace · %", f"{start_year}-01-01", f"{end_year + 1}-01-01"),
    )
    page = None
    imported = 0
    while True:
        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
            pageToken=page,
            maxResults=2500,
        ).execute()
        for event in result.get("items", []):
            start = (event.get("start") or {}).get("date")
            if not start:  # Solo eventos de día completo para evitar falsos positivos.
                continue
            name = event.get("summary") or "Descanso corporativo"
            con.execute(
                """INSERT INTO non_working_days(day,name,created_at) VALUES(?,?,?)
                   ON CONFLICT(day) DO UPDATE SET name=excluded.name""",
                (start, f"Google Workspace · {name}", datetime.now().astimezone().isoformat(timespec="seconds")),
            )
            imported += 1
        page = result.get("nextPageToken")
        if not page:
            break
    return {"configured": True, "imported": imported, "calendar_id": calendar_id}
