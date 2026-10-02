import os
from datetime import timedelta, timezone

from dotenv import load_dotenv

load_dotenv()

# ponytail: fixed UTC+7, Thailand has no DST
BANGKOK = timezone(timedelta(hours=7))

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set")

    return value


LINE_CHANNEL_ID = require_env("LINE_CHANNEL_ID")
LINE_CHANNEL_SECRET = require_env("LINE_CHANNEL_SECRET")  # in .env

# HR employee directory, cached in Redis for registration checks (app/identity/directory.py).
# Leave EMPLOYEE_API_URL empty to check against the employees table instead (dev).
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
EMPLOYEE_API_URL = os.getenv("EMPLOYEE_API_URL", "")
EMPLOYEE_API_TOKEN = os.getenv("EMPLOYEE_API_TOKEN", "")
EMPLOYEE_SYNC_INTERVAL_MINUTES = int(os.getenv("EMPLOYEE_SYNC_INTERVAL_MINUTES", "1440"))
