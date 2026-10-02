"""The real employee register, checked at registration (ported from line_oa).

    HR API --daily--> Redis hash {emp_code -> person}

A person is {"fn", "ln", "name", "aliases", "department"}. Registration checks
two things: the code exists, and the typed name matches it. What gets saved is
the HR data, not what the user typed.

Lookups always go through Redis, never HR per registration. If Redis is down,
HR is called directly (cached in memory briefly). Sync runs once per
EMPLOYEE_SYNC_INTERVAL_MINUTES, measured from the last sync time kept in Redis,
so restarts don't re-fetch; a wiped Redis re-syncs immediately.

Without EMPLOYEE_API_URL (dev), the employees table is the register instead.

HR response (GET, optional Authorization: Bearer <EMPLOYEE_API_TOKEN>):
    {"Success": true, "Message": "...", "Data": [
        {"EMPCODE": "12345", "F_NAME_TH": "...", "S_NAME_TH": "...",
         "F_NAME_EN": "...", "S_NAME_EN": "...", "Department_FULL": "...", ...}]}
"""

import asyncio
import json
import logging
import re
import time
import unicodedata
from enum import StrEnum

import httpx
import redis.asyncio as redis

from app.config import (
    EMPLOYEE_API_TOKEN,
    EMPLOYEE_API_URL,
    EMPLOYEE_SYNC_INTERVAL_MINUTES,
    REDIS_URL,
)
from app.identity import repository

logger = logging.getLogger(__name__)

_KEY = "billing:employee_directory:v1"
_TMP_KEY = f"{_KEY}:tmp"
_LOCK_KEY = f"{_KEY}:lock"
_SYNCED_AT_KEY = f"{_KEY}:synced_at"

_RETRY_SECONDS = 600  # a failed sync retries this soon, not a day later
_DIRECT_TTL_SECONDS = 300  # in-memory cache of a direct HR fetch while Redis is down

# Titles people commonly type (dots are stripped first, so "น.ส." is "นส").
# Longer ones first, or "นางสาว" would lose only "นาง".
_TITLES = re.compile(
    r"^(เด็กชาย|เด็กหญิง|นางสาว|นาง|นาย|นส|คุณ|ดร|ดช|ดญ|mrs|mr|ms|miss)\s*", re.IGNORECASE
)

_client: redis.Redis | None = None
_direct_cache: tuple[float, dict[str, dict]] | None = None


class Verdict(StrEnum):
    OK = "ok"
    NOT_FOUND = "not_found"  # no such code
    NAME_MISMATCH = "name_mismatch"  # code exists, name doesn't match
    UNAVAILABLE = "unavailable"  # can't check right now


def enabled() -> bool:
    return bool(EMPLOYEE_API_URL)


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(REDIS_URL, decode_responses=True)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def normalize_code(code: str) -> str:
    return code.strip().upper()


def normalize_name(name: str) -> str:
    """'นาย สมชาย  ใจดี' == 'น.ส.สมชาย-ใจดี' == 'สมชายใจดี'.

    Keeps letters, marks, digits and spaces (drops punctuation and invisible
    characters from mobile keyboards / copy-paste), strips a leading title,
    spaces and case. HR names and typed names go through the same rules.
    """
    name = "".join(ch for ch in name if unicodedata.category(ch)[0] in "LMN" or ch.isspace())
    name = _TITLES.sub("", name.strip())
    return re.sub(r"\s+", "", name).casefold()


def _full_name(first: object, last: object) -> str:
    return " ".join(str(part).strip() for part in (first, last) if part and str(part).strip())


# --------------------------------------------------------------------------
# Lookup
# --------------------------------------------------------------------------


async def lookup(code: str) -> tuple[Verdict, dict | None]:
    """(OK, person) / (NOT_FOUND, None) / (UNAVAILABLE, None)."""
    code = normalize_code(code)

    if not enabled():
        return await _lookup_db(code)

    try:
        r = _redis()

        if not await r.exists(_KEY):
            try:
                await sync()  # fresh boot or wiped Redis: fetch now
            except redis.RedisError:
                raise
            except Exception:  # HR down while Redis is fine
                logger.exception("First employee directory sync failed")

        raw = await r.hget(_KEY, code)
        has_data = bool(await r.exists(_KEY))
    except redis.RedisError as error:
        logger.warning("Redis unavailable (%s), calling HR directly", type(error).__name__)
        return await _lookup_direct(code)

    if raw is not None:
        return Verdict.OK, json.loads(raw)
    return (Verdict.NOT_FOUND if has_data else Verdict.UNAVAILABLE), None


async def _lookup_db(code: str) -> tuple[Verdict, dict | None]:
    employee = await repository.get_employee_by_code(code)

    if employee is None:
        return Verdict.NOT_FOUND, None

    return Verdict.OK, {
        "fn": employee.emp_fn,
        "ln": employee.emp_ln,
        "name": employee.emp_full,
        "aliases": [],
        "department": employee.emp_department,
    }


async def _lookup_direct(code: str) -> tuple[Verdict, dict | None]:
    global _direct_cache

    try:
        now = time.monotonic()
        if _direct_cache is None or now - _direct_cache[0] > _DIRECT_TTL_SECONDS:
            _direct_cache = (now, await _fetch())
        person = _direct_cache[1].get(code)
    except Exception:  # Redis and HR both down: refuse, never let it through
        logger.exception("Direct HR lookup failed")
        return Verdict.UNAVAILABLE, None

    return (Verdict.OK, person) if person else (Verdict.NOT_FOUND, None)


def name_matches(person: dict, typed: str) -> bool:
    """Thai or English name; last name first is fine too (reveals nothing extra)."""
    accepted = set()

    for name in (person["name"], *person.get("aliases", [])):
        accepted.add(normalize_name(name))
        parts = name.split(None, 1)
        if len(parts) == 2:
            accepted.add(normalize_name(f"{parts[1]} {parts[0]}"))

    return normalize_name(typed) in accepted


async def verify(code: str, full_name: str) -> tuple[Verdict, dict | None]:
    verdict, person = await lookup(code)

    if verdict is not Verdict.OK:
        return verdict, None

    if not name_matches(person, full_name):
        # Log lengths only, never names (personal data).
        logger.info(
            "Name mismatch for code=%s typed_len=%d official_len=%d",
            normalize_code(code),
            len(normalize_name(full_name)),
            len(normalize_name(person["name"])),
        )
        return Verdict.NAME_MISMATCH, None

    return Verdict.OK, person


# --------------------------------------------------------------------------
# Sync from HR
# --------------------------------------------------------------------------


async def _fetch() -> dict[str, dict]:
    headers = {"Authorization": f"Bearer {EMPLOYEE_API_TOKEN}"} if EMPLOYEE_API_TOKEN else {}

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(EMPLOYEE_API_URL, headers=headers)
    response.raise_for_status()

    body = response.json()
    if not body.get("Success"):
        raise RuntimeError(f"HR returned Success=false: {body.get('Message')}")

    people: dict[str, dict] = {}

    for row in body.get("Data") or []:
        code = normalize_code(str(row.get("EMPCODE") or ""))
        fn = str(row.get("F_NAME_TH") or "").strip()
        ln = str(row.get("S_NAME_TH") or "").strip()

        if not (code and fn):
            continue

        # English name only with both parts, or a last name alone would pass.
        aliases = []
        if row.get("F_NAME_EN") and row.get("S_NAME_EN"):
            aliases.append(_full_name(row["F_NAME_EN"], row["S_NAME_EN"]))

        department = row.get("Department_FULL") or row.get("Department_SEC") or row.get("Department")

        people[code] = {
            "fn": fn,
            "ln": ln,
            "name": _full_name(fn, ln),
            "aliases": aliases,
            "department": _full_name(department, "")[:150] or None,
        }

    return people


async def sync() -> int:
    """Replace the Redis register with HR's; return how many were loaded.

    An empty list is treated as an HR fault and never overwrites existing data.
    Writes a temp key then RENAMEs it, so the register is never half-written.
    """
    r = _redis()

    # Several workers booting together: only one fetches.
    if not await r.set(_LOCK_KEY, "1", nx=True, ex=60):
        return 0

    try:
        people = await _fetch()
        if not people:
            raise RuntimeError("HR returned no employees; keeping the existing register")

        pipe = r.pipeline()
        pipe.delete(_TMP_KEY)
        pipe.hset(_TMP_KEY, mapping={code: json.dumps(p, ensure_ascii=False) for code, p in people.items()})
        pipe.rename(_TMP_KEY, _KEY)
        pipe.set(_SYNCED_AT_KEY, str(time.time()))
        await pipe.execute()

        logger.info("Synced %d employees from HR", len(people))
        return len(people)
    finally:
        await r.delete(_LOCK_KEY)


async def _seconds_until_due() -> float:
    """<= 0 means sync now (never synced, or the data is gone)."""
    r = _redis()
    synced_at = await r.get(_SYNCED_AT_KEY)

    if synced_at is None or not await r.exists(_KEY):
        return 0

    return float(synced_at) + EMPLOYEE_SYNC_INTERVAL_MINUTES * 60 - time.time()


async def loop() -> None:
    """Background task: sync on schedule; a failure logs and retries in 10 minutes."""
    while True:
        try:
            wait = await _seconds_until_due()
            if wait <= 0:
                await sync()
                wait = await _seconds_until_due()
            wait = max(wait, 60)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Employee directory sync failed, retrying in %ds", _RETRY_SECONDS)
            wait = _RETRY_SECONDS

        await asyncio.sleep(wait)
