import os
from datetime import timedelta, timezone

from dotenv import load_dotenv

# This checkout is the isolated test stack.
load_dotenv(".env", override=True)

# ponytail: fixed UTC+7, Thailand has no DST
BANGKOK = timezone(timedelta(hours=7))

def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is not set")

    return value


LINE_CHANNEL_ID = require_env("LINE_CHANNEL_ID")
LINE_CHANNEL_SECRET = require_env("LINE_CHANNEL_SECRET")  # in .env
LINE_RICH_MENU_SETUP_ENABLED = os.getenv("LINE_RICH_MENU_SETUP_ENABLED", "false").lower() == "true"
TEST_TEXT_COMMANDS_ENABLED = os.getenv("TEST_TEXT_COMMANDS_ENABLED", "false").lower() == "false"
BILLING_LIFF_URL = os.getenv("BILLING_LIFF_URL", "https://liff.line.me/2012025842-Hn7vjID5")
LIFF_CHANNEL_ID = os.getenv("LIFF_CHANNEL_ID", "2012025842")
LIFF_ALLOWED_ORIGIN = os.getenv("LIFF_ALLOWED_ORIGIN", "").rstrip("/")
PUBLIC_BASE_URL = require_env("PUBLIC_BASE_URL").rstrip("/")
