"""Google Drive / Shared Drive connector.
Proyecto funcional: Jazmin Lopez Zamora.

Las credenciales viven solo en el servidor. Soporta service account y, si se define
GOOGLE_IMPERSONATE_USER, Domain-Wide Delegation para actuar como un usuario de Workspace.
"""
from __future__ import annotations
import os

def upload_file_if_configured(path, filename, metadata=None):
    creds_path=os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE')
    folder_id=os.getenv('GOOGLE_DRIVE_FOLDER_ID')
    if not creds_path or not folder_id: return None
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    scopes=['https://www.googleapis.com/auth/drive.file']
    creds=service_account.Credentials.from_service_account_file(creds_path,scopes=scopes)
    subject=os.getenv('GOOGLE_IMPERSONATE_USER')
    if subject: creds=creds.with_subject(subject)
    service=build('drive','v3',credentials=creds,cache_discovery=False)
    body={'name':filename,'parents':[folder_id]}
    media=MediaFileUpload(str(path),mimetype='application/pdf',resumable=True)
    created=service.files().create(body=body,media_body=media,fields='id,name,webViewLink',supportsAllDrives=True).execute()
    return created
