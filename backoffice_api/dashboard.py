"""Numbers for the dashboard, over the last N days (Bangkok calendar days)."""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select

from app.audit import Action
from app.config import BANGKOK
from app.db.models import AuditLog, BillSend, Employee, UserIdentity, WebhookEvent
from app.db.session import SessionLocal
from backoffice_api.auth import current_admin

router = APIRouter(prefix="/api/dashboard")


def _days(since_day, days: int) -> list[str]:
    return [(since_day + timedelta(days=i)).isoformat() for i in range(days)]


@router.get("")
async def dashboard(days: int = 30, admin=Depends(current_admin)):
    days = min(max(days, 1), 365)
    first_day = datetime.now(BANGKOK).date() - timedelta(days=days - 1)
    since = datetime.combine(first_day, datetime.min.time(), BANGKOK).astimezone(timezone.utc)
    day_keys = _days(first_day, days)

    def day(value: datetime) -> str:
        if value.tzinfo is None:  # stored as UTC; some drivers hand it back naive
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(BANGKOK).date().isoformat()

    async with SessionLocal() as session:
        employees = await session.scalar(select(func.count()).select_from(Employee))
        bound = await session.scalar(
            select(func.count()).select_from(UserIdentity).where(UserIdentity.active.is_(True))
        )

        # ponytail: rows in range grouped in Python (portable across Postgres/SQLite);
        # move the grouping into SQL if a range ever holds more than ~100k events.
        events = (
            await session.execute(
                select(WebhookEvent.received_at, WebhookEvent.status).where(WebhookEvent.received_at >= since)
            )
        ).all()
        sends = (
            await session.execute(select(BillSend.sent_at, BillSend.amount).where(BillSend.sent_at >= since))
        ).all()
        top = (
            await session.execute(
                select(BillSend.emp_code, Employee.emp_full, func.count(), func.sum(BillSend.amount))
                .join(Employee, Employee.emp_code == BillSend.emp_code, isouter=True)
                .where(BillSend.sent_at >= since)
                .group_by(BillSend.emp_code, Employee.emp_full)
                .order_by(func.count().desc())
                .limit(10)
            )
        ).all()
        rejections = await session.scalars(
            select(AuditLog.detail).where(AuditLog.action == Action.EMPLOYEE_REJECTED.value, AuditLog.at >= since)
        )
        rejected_by_reason = Counter((detail or {}).get("reason", "unknown") for detail in rejections)
        failures = await session.scalars(
            select(WebhookEvent)
            .where(WebhookEvent.status == "failed")
            .order_by(WebhookEvent.received_at.desc())
            .limit(10)
        )
        recent_failures = [
            {
                "id": event.id,
                "received_at": event.received_at.isoformat(),
                "event_type": event.event_type,
                "line_user_id": event.line_user_id,
                "error": (event.error or "").strip().splitlines()[-1:] or [""],
            }
            for event in failures
        ]

    events_by_day = {key: {"processed": 0, "skipped": 0, "failed": 0} for key in day_keys}
    for received_at, status in events:
        bucket = events_by_day.get(day(received_at))
        if bucket is not None and status in bucket:
            bucket[status] += 1

    sends_by_day = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for sent_at, amount in sends:
        sends_by_day[day(sent_at)]["count"] += 1
        sends_by_day[day(sent_at)]["amount"] += float(amount)

    return {
        "days": days,
        "totals": {
            "employees": employees,
            "bound_line_accounts": bound,
            "sends": len(sends),
            "sent_amount": sum(float(amount) for _, amount in sends),
            "events": len(events),
            "failed_events": sum(1 for _, status in events if status == "failed"),
            "rejected_registrations": sum(rejected_by_reason.values()),
        },
        "events_by_day": [{"day": key, **events_by_day[key]} for key in day_keys],
        "sends_by_day": [{"day": key, **sends_by_day[key]} for key in day_keys],
        "top_employees": [
            {"emp_code": code, "name": name, "sends": count, "amount": float(amount or 0)}
            for code, name, count, amount in top
        ],
        "rejected_by_reason": dict(rejected_by_reason.most_common()),
        "recent_failures": [{**f, "error": f["error"][0]} for f in recent_failures],
    }
