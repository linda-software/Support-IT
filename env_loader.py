"""Carga simple de .env sin dependencias externas.
Contribución inicial documentada: Jazmin Lopez Zamora.
"""
from pathlib import Path
import os


def load_env(path=None):
    path = Path(path or Path(__file__).resolve().parent / '.env')
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
            value = value[1:-1]
        os.environ.setdefault(key, value)
