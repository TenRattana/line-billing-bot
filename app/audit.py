"""Record who did what, to what, when (ported from line_oa's audit service).

Meant to be a one-liner from anywhere: a timeline with gaps is worse than none,
because it suggests nothing happened.

    await audit.record(Action.INVOICE_OPENED, actor=audit.employee(emp_code), invoice_no="...")

Use `add(session, ...)` instead when the log must commit together with the
change it describes (register, release, submit).
"""

from enum import StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.audit_log import AuditLog
from app.db.session import SessionLocal


class Action(StrEnum):
    """Only events this bot actually has."""

    EMPLOYEE_REGISTERED = "employee.registered"
    EMPLOYEE_REJECTED = "employee.rejected"  # wrong code / name at registration or re-verify
    EMPLOYEE_REVERIFIED = "employee.reverified"  # typed their code again after unblock
    EMPLOYEE_RELEASED = "employee.released"  # admin unbound their LINE account

    INVOICE_OPENED = "invoice.opened"  # picked a bill to send
    INVOICE_SUBMITTED = "invoice.submitted"
    INVOICE_CANCELLED = "invoice.cancelled"

    FILE_UPLOADED = "file.uploaded"  # passed checks, saved, attached
    FILE_REJECTED = "file.rejected"  # failed checks, not saved

    # Backoffice
    ADMIN_LOGIN = "admin.login"
    ADMIN_LOGIN_FAILED = "admin.login_failed"
    RECORD_CREATED = "record.created"  # a row added from the backoffice
    RECORD_UPDATED = "record.updated"
    RECORD_DELETED = "record.deleted"


def employee(emp_code: str) -> tuple[str, str]:
    return "employee", emp_code


def line_user(line_user_id: str) -> tuple[str, str]:
    """Someone not registered (yet)."""
    return "line_user", line_user_id


def admin(name: str) -> tuple[str, str]:
    return "admin", name


def add(
    session: AsyncSession,
    action: Action,
    *,
    actor: tuple[str, str],
    emp_code: str | None = None,
    line_user_id: str | None = None,
    invoice_no: str | None = None,
    detail: dict | None = None,
) -> None:
    """Stage a log row in the caller's transaction."""
    actor_type, actor_label = actor
    session.add(
        AuditLog(
            action=action.value,
            actor_type=actor_type,
            actor_label=actor_label[:64],
            emp_code=emp_code,
            line_user_id=line_user_id,
            invoice_no=invoice_no,
            detail=detail or {},
        )
    )


async def record(action: Action, **fields) -> None:
    """Write a log row in its own transaction."""
    async with SessionLocal() as session:
        add(session, action, **fields)
        await session.commit()
