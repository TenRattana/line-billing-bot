"""Employee registration checks against the central employees table.

One query per registration: the code step looks the person up, and the name
step is checked against that same result (kept in the registration).
"""

import logging
import re
import unicodedata
from enum import StrEnum

from app.identity import directory_repository

logger = logging.getLogger(__name__)

# Titles people commonly type (dots are stripped first, so "น.ส." is "นส").
# Longer ones first, or "นางสาว" would lose only "นาง".
_TITLES = re.compile(
    r"^(เด็กชาย|เด็กหญิง|นางสาว|นาง|นาย|นส|คุณ|ดร|ดช|ดญ|mrs|mr|ms|miss)\s*", re.IGNORECASE
)


class Verdict(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"
    NAME_MISMATCH = "name_mismatch"
    UNAVAILABLE = "unavailable"


def normalize_code(code: str) -> str:
    return code.strip().upper()


def normalize_name(name: str) -> str:
    """Treat titles, punctuation, whitespace and case as insignificant."""
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] in "LMN" or ch.isspace())
    name = _TITLES.sub("", name.strip())
    return re.sub(r"\s+", "", name).casefold()


async def lookup(code: str) -> tuple[Verdict, dict | None]:
    try:
        person = await directory_repository.get_active_by_code(normalize_code(code))
    except Exception:
        logger.exception("Central employee database lookup failed")
        return Verdict.UNAVAILABLE, None

    return (Verdict.OK, person) if person else (Verdict.NOT_FOUND, None)


def name_matches(person: dict, typed: str) -> bool:
    accepted = set()

    for name in (person["name"], *person.get("aliases", [])):
        accepted.add(normalize_name(name))
        parts = name.split(None, 1)
        if len(parts) == 2:
            accepted.add(normalize_name(f"{parts[1]} {parts[0]}"))

    return normalize_name(typed) in accepted


async def close() -> None:
    await directory_repository.close()
