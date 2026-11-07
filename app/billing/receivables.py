"""Receivables and sales groups, read from the daily JSON exports.

Loaded at import and reloaded daily after the 18:00 export (schedule), or at once
through refresh(). A load that fails keeps the data already loaded.
"""

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from functools import cache
from pathlib import Path

from app.config import BANGKOK

logger = logging.getLogger(__name__)

DATA_DIR = Path("/data/validated/output")
AR_FILE = DATA_DIR / "ar_outstanding_latest.json"
GROUP_FILE = DATA_DIR / "group_latest.json"
EXPORT_HOUR = 18


def _read_json(path: Path):
    if not path.exists():
        logger.warning("%s not found; no data loaded", path)
        return None

    return json.loads(path.read_text(encoding="utf-8-sig"))


def _str(value) -> str:
    return "" if value is None else str(value).strip()


def _float(value) -> float:
    return float(value) if value not in (None, "") else 0.0


def _int(value) -> int:
    return int(value) if value not in (None, "") else 0


def normalize_group(value: str) -> str:
    return value.strip().casefold()


def load_groups() -> dict[str, set[str]]:
    raw = _read_json(GROUP_FILE)
    items = raw if isinstance(raw, list) else (raw or {}).get("groups") or []

    groups_by_emp: dict[str, set[str]] = {}

    for item in items:
        emp_code = _str(item.get("EmpID") or item.get("empid"))
        ids = item.get("GroupID") or item.get("groupid") or []
        ids = ids if isinstance(ids, list) else re.split(r"[,;|]", str(ids))
        group_ids = {normalize_group(str(group_id)) for group_id in ids if _str(group_id)}

        if emp_code and group_ids:
            groups_by_emp.setdefault(emp_code, set()).update(group_ids)

    return groups_by_emp


def _invoice(customer: dict, invoice: dict) -> dict:
    return {
        "invoice_no": _str(invoice.get("invoice_no")),
        "voucher": _str(invoice.get("voucher")),
        "doc_type": _str(invoice.get("doc_type")),
        "invoice_date": _str(invoice.get("invoice_date")),
        "due_date": _str(invoice.get("due_date")),
        "currency": _str(invoice.get("currency")),
        "amount": _float(invoice.get("amount")),
        "province": _str(invoice.get("province")),
        "outstanding": _float(invoice.get("outstanding")),
        "outstanding_mst": _float(invoice.get("outstanding_mst")),
        "days_overdue": _int(invoice.get("days_overdue")),
        "aging": _str(invoice.get("aging")),
        "sales_group": _str(invoice.get("sales_group", customer.get("sales_group"))),
    }


def load_customers() -> list[dict]:
    raw = _read_json(AR_FILE)
    customers: dict[str, dict] = {}

    for customer in (raw or {}).get("customers", []):
        code = _str(customer.get("customer_code"))
        entry = customers.setdefault(
            code,
            {
                "customer_code": code,
                "customer_name": _str(customer.get("customer_name")),
                "tax_id": _str(customer.get("tax_id")),
                "cust_group": _str(customer.get("cust_group")),
                "invoices": [],
            },
        )
        entry["invoices"].extend(_invoice(customer, invoice) for invoice in customer.get("invoices", []))

    return [with_invoices(c, c["invoices"]) for c in customers.values() if c["invoices"]]


def with_invoices(customer: dict, invoices: list[dict]) -> dict:
    return {
        **customer,
        "invoices": invoices,
        "invoice_count": len(invoices),
        "total_outstanding": sum(invoice["outstanding"] for invoice in invoices),
        "overdue_amount": sum(invoice["outstanding"] for invoice in invoices if invoice["days_overdue"] > 0),
    }


GROUPS_BY_EMP_CODE: dict[str, set[str]] = {}
CUSTOMERS: list[dict] = []
# When AR_FILE was written. Only a bill sent since then is unknown to the export:
# anything sent earlier and still in the file is back to be sent (billing.repository).
EXPORTED_AT = datetime.fromtimestamp(0, timezone.utc)
_retry_needed = False


def _load(fresh_after: datetime | None = None) -> tuple[dict, list, datetime]:
    """Read the exports; raises instead of returning anything unusable."""
    # group_latest.json only changes when the groups do, so only the receivables file dates the export.
    # Read before the contents: a file replaced meanwhile then errs towards hiding a bill, not resending it.
    exported_at = datetime.fromtimestamp(AR_FILE.stat().st_mtime, timezone.utc)

    if fresh_after and exported_at < fresh_after:
        raise RuntimeError(f"{AR_FILE} is older than {fresh_after}")

    groups, customers = load_groups(), load_customers()

    if not groups or not customers:
        raise RuntimeError("the export has no groups or no customers")

    return groups, customers, exported_at


def _apply(loaded: tuple[dict, list, datetime]) -> None:
    global GROUPS_BY_EMP_CODE, CUSTOMERS, EXPORTED_AT

    GROUPS_BY_EMP_CODE, CUSTOMERS, EXPORTED_AT = loaded
    customers_for.cache_clear()
    logger.info("Loaded %d customers, %d employees with groups", len(CUSTOMERS), len(GROUPS_BY_EMP_CODE))


async def refresh(*, fresh_after: datetime | None = None) -> dict:
    """Load the exports now. Raises, keeping what is loaded, when they are unusable."""
    global _retry_needed

    # Applied here on the event loop, so customers_for never sees it half done.
    _apply(await asyncio.to_thread(_load, fresh_after))
    _retry_needed = False
    return {"customers": len(CUSTOMERS), "exported_at": EXPORTED_AT.isoformat()}


async def _daily_reload(*, retry: bool = False) -> None:
    global _retry_needed

    if retry and not _retry_needed:
        return

    try:
        await refresh(fresh_after=datetime.now(BANGKOK).replace(hour=EXPORT_HOUR, minute=0, second=0, microsecond=0))
    except Exception:
        _retry_needed = not retry
        logger.exception("Daily receivables load failed; %s", "keeping the data until tomorrow" if retry else "retry at 19:00")


@cache
def customers_for(emp_code: str) -> list[dict]:
    """The employee's customers, only with invoices of the employee's sales groups."""
    allowed_groups = GROUPS_BY_EMP_CODE.get(emp_code.strip(), set())

    if not allowed_groups:
        return []

    customers = []

    for customer in CUSTOMERS:
        invoices = sorted(
            (invoice for invoice in customer["invoices"] if normalize_group(invoice["sales_group"]) in allowed_groups),
            key=lambda invoice: -invoice["days_overdue"],
        )

        if invoices:
            customers.append(with_invoices(customer, invoices))

    return sorted(customers, key=lambda customer: -customer["total_outstanding"])


def schedule(scheduler) -> None:
    scheduler.add_job(_daily_reload, trigger="cron", hour=18, minute=30, id="reload_receivables")
    scheduler.add_job(
        _daily_reload, trigger="cron", hour=19, minute=0, id="retry_receivables", kwargs={"retry": True}
    )


try:
    _apply(_load())
except Exception:  # the bot still serves registration and history; refresh() fills this in
    logger.exception("No receivables loaded")
