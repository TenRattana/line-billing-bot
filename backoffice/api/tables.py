"""Browse / create / edit / delete rows of any table, driven by the SQLAlchemy models.

Logs are read-only: an editable audit trail can't be trusted. admin_users is
read-only here too (accounts are managed with the create_admin command) and its
password_hash never leaves the server. Every write is audited with the admin's name.
"""

from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import String, Text, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.sql.sqltypes import JSON, Boolean, DateTime, Integer, Numeric

from app import audit
from app.audit import Action
from app.db.models import (
    AdminUser,
    AuditLog,
    BillSend,
    Employee,
    UserIdentity,
    WebhookEvent,
)
from app.db.session import SessionLocal
from backoffice.api.auth import current_admin, require_admin

router = APIRouter(prefix="/api/tables")

# name -> (model, editable, label)
TABLES = {
    "employees": (Employee, True, "พนักงาน"),
    "user_identities": (UserIdentity, True, "การผูกบัญชี LINE"),
    "bill_sends": (BillSend, True, "ประวัติส่งบิล"),
    "audit_logs": (AuditLog, False, "Audit log"),
    "webhook_events": (WebhookEvent, False, "Webhook events"),
    "admin_users": (AdminUser, False, "ผู้ใช้หลังบ้าน"),
}
HIDDEN = {"admin_users": {"password_hash"}}
MAX_LIMIT = 200


def _table(name: str):
    if name not in TABLES:
        raise HTTPException(404, f"ไม่มีตาราง {name}")
    return TABLES[name]


def _columns(name: str) -> list:
    model = TABLES[name][0]
    return [c for c in model.__table__.columns if c.name not in HIDDEN.get(name, set())]


def _kind(column) -> str:
    kind = column.type
    if isinstance(kind, Boolean):
        return "boolean"
    if isinstance(kind, DateTime):
        return "datetime"
    if isinstance(kind, Integer):
        return "integer"
    if isinstance(kind, Numeric):
        return "number"
    if isinstance(kind, JSON):
        return "json"
    if isinstance(kind, Text):
        return "text"
    return "string"


def _pk(name: str):
    return TABLES[name][0].__table__.primary_key.columns.values()[0]


def _serialize(name: str, row) -> dict:
    out = {}
    for column in _columns(name):
        value = getattr(row, column.key)
        if isinstance(value, (datetime, date)):
            value = value.isoformat()
        elif isinstance(value, Decimal):
            value = str(value)
        out[column.name] = value
    return out


def _coerce(column, value):
    """JSON value from the browser -> the column's Python type (400 on nonsense)."""
    if value is None or value == "":
        if not column.nullable and column.server_default is None and column.default is None:
            raise HTTPException(400, f"{column.name} ต้องมีค่า")
        return None

    kind = _kind(column)
    try:
        if kind == "boolean":
            return value if isinstance(value, bool) else str(value).lower() in ("true", "1", "yes")
        if kind == "integer":
            return int(value)
        if kind == "number":
            return Decimal(str(value))
        if kind == "datetime":
            return datetime.fromisoformat(str(value))
        if kind == "json":
            return value
    except (ValueError, InvalidOperation):
        raise HTTPException(400, f"ค่าของ {column.name} ไม่ถูกต้อง: {value}") from None

    text = str(value)
    if isinstance(column.type, String) and column.type.length and len(text) > column.type.length:
        raise HTTPException(400, f"{column.name} ยาวเกิน {column.type.length} ตัวอักษร")
    return text


def _values(name: str, body: dict, *, creating: bool) -> dict:
    columns = {c.name: c for c in _columns(name)}
    unknown = set(body) - set(columns)
    if unknown:
        raise HTTPException(400, f"ไม่มีคอลัมน์ {', '.join(sorted(unknown))}")

    if creating:
        missing = [
            name
            for name, c in columns.items()
            if not c.nullable
            and c.server_default is None
            and c.default is None
            and not (c.primary_key and c.autoincrement is True)
            and body.get(name) in (None, "")
        ]
        if missing:
            raise HTTPException(400, f"ต้องกรอก {', '.join(missing)}")

    values = {}
    for key, value in body.items():
        column = columns[key]
        if column.primary_key and not creating:
            continue  # the key identifies the row; changing it would orphan references
        if column.primary_key and column.autoincrement is True and value in (None, ""):
            continue
        values[column.key] = _coerce(column, value)
    return values


async def _get_row(session, name: str, pk: str):
    column = _pk(name)
    row = await session.get(TABLES[name][0], _coerce(column, pk))
    if row is None:
        raise HTTPException(404, "ไม่พบข้อมูลแถวนี้")
    return row


@asynccontextmanager
async def _writing():
    """A session for one change; a constraint violation (duplicate key, row still
    referenced, ...) becomes a 409 whether it surfaces at flush or at commit."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except IntegrityError as error:
            await session.rollback()
            detail = str(error.orig).splitlines()[0][:300]
            raise HTTPException(409, f"บันทึกไม่ได้เพราะขัดกับข้อมูลอื่น: {detail}") from None


def _time_column(name: str) -> str | None:
    """The column the time-range picker filters on: the table's first timestamp."""
    return next((c.name for c in _columns(name) if _kind(c) == "datetime"), None)


# filter.<column>__<op>=value; a bare filter.<column>=value means "eq"
OPERATORS = {
    "eq": lambda c, v: c == v,
    "ne": lambda c, v: c != v,
    "contains": lambda c, v: cast(c, String).ilike(f"%{v}%"),  # also searches inside JSON
    "gt": lambda c, v: c > v,
    "gte": lambda c, v: c >= v,
    "lt": lambda c, v: c < v,
    "lte": lambda c, v: c <= v,
    "isnull": lambda c, v: c.is_(None) if v else c.is_not(None),
}


def _condition(columns: dict, field: str, value: str):
    name, _, op = field.partition("__")
    op = op or "eq"
    column = columns.get(name)

    if column is None or op not in OPERATORS:
        raise HTTPException(400, f"filter ไม่ถูกต้อง: {field}")

    if op == "isnull":
        typed = value.lower() in ("true", "1", "yes")
    elif op == "contains":
        typed = value
    else:
        typed = _coerce(column, value)

    return OPERATORS[op](column, typed)


# --------------------------------------------------------------------------
# Routes
# --------------------------------------------------------------------------


@router.get("")
async def list_tables(admin=Depends(current_admin)):
    async with SessionLocal() as session:
        counts = {
            name: await session.scalar(select(func.count()).select_from(model))
            for name, (model, _, _) in TABLES.items()
        }

    return [
        {
            "name": name,
            "label": label,
            "editable": editable and admin.role == "admin",
            "rows": counts[name],
            "primary_key": _pk(name).name,
            "time_column": _time_column(name),
            "columns": [
                {
                    "name": c.name,
                    "kind": _kind(c),
                    "nullable": bool(c.nullable),
                    "primary_key": c.primary_key,
                    "generated": c.server_default is not None or (c.primary_key and c.autoincrement is True),
                }
                for c in _columns(name)
            ],
        }
        for name, (model, editable, label) in TABLES.items()
    ]


@router.get("/{name}/rows")
async def list_rows(
    name: str,
    request: Request,
    limit: int = 50,
    offset: int = 0,
    q: str = "",
    sort: str = "",
    order: str = "desc",
    admin=Depends(current_admin),
):
    model = _table(name)[0]
    columns = {c.name: c for c in _columns(name)}
    query = select(model)

    for key, value in request.query_params.multi_items():
        if key.startswith("filter."):
            query = query.where(_condition(columns, key.removeprefix("filter."), value))

    if q.strip():
        needle = f"%{q.strip()}%"
        text_columns = [c for c in columns.values() if _kind(c) in ("string", "text")]
        query = query.where(or_(*(c.ilike(needle) for c in text_columns)))

    sort_column = columns[sort] if sort in columns else _pk(name)
    query = query.order_by(sort_column.asc() if order == "asc" else sort_column.desc())

    async with SessionLocal() as session:
        total = await session.scalar(select(func.count()).select_from(query.subquery()))
        rows = await session.scalars(query.limit(min(max(limit, 1), MAX_LIMIT)).offset(max(offset, 0)))
        return {"total": total, "rows": [_serialize(name, row) for row in rows]}


@router.get("/{name}/values/{column}")
async def column_values(name: str, column: str, q: str = "", admin=Depends(current_admin)):
    """The most common values of a column (for the filter's value suggestions)."""
    _table(name)
    target = {c.name: c for c in _columns(name)}.get(column)

    if target is None:
        raise HTTPException(404, f"ไม่มีคอลัมน์ {column}")
    if _kind(target) in ("json", "datetime"):
        return []

    count = func.count().label("n")
    query = select(target, count).where(target.is_not(None)).group_by(target).order_by(count.desc()).limit(20)
    if q.strip():
        query = query.where(cast(target, String).ilike(f"%{q.strip()}%"))

    async with SessionLocal() as session:
        rows = (await session.execute(query)).all()

    return [{"value": str(value) if not isinstance(value, bool) else value, "count": n} for value, n in rows]


@router.get("/{name}/rows/{pk}")
async def get_row(name: str, pk: str, admin=Depends(current_admin)):
    _table(name)
    async with SessionLocal() as session:
        return _serialize(name, await _get_row(session, name, pk))


def _writable(name: str) -> type:
    model, editable, _ = _table(name)
    if not editable:
        raise HTTPException(403, f"ตาราง {name} แก้ไขไม่ได้")
    return model


@router.post("/{name}/rows", status_code=201)
async def create_row(name: str, body: dict = Body(...), admin=Depends(require_admin)):
    model = _writable(name)

    async with _writing() as session:
        row = model(**_values(name, body, creating=True))
        session.add(row)
        await session.flush()
        await session.refresh(row)  # server defaults (create_at, ...) come back from the DB
        created = _serialize(name, row)
        audit.add(
            session,
            Action.RECORD_CREATED,
            actor=audit.admin(admin.username),
            detail={"table": name, "pk": str(created[_pk(name).name]), "row": created},
        )
        await session.refresh(row)
        return _serialize(name, row)


@router.patch("/{name}/rows/{pk}")
async def update_row(name: str, pk: str, body: dict = Body(...), admin=Depends(require_admin)):
    _writable(name)

    async with _writing() as session:
        row = await _get_row(session, name, pk)
        before = _serialize(name, row)

        for key, value in _values(name, body, creating=False).items():
            setattr(row, key, value)

        await session.flush()
        await session.refresh(row)  # onupdate columns (update_at) come back from the DB
        after = _serialize(name, row)
        changes = {k: [before[k], after[k]] for k in after if before[k] != after[k]}

        audit.add(
            session,
            Action.RECORD_UPDATED,
            actor=audit.admin(admin.username),
            detail={"table": name, "pk": pk, "changes": changes},
        )
        await session.refresh(row)
        return _serialize(name, row)


@router.delete("/{name}/rows/{pk}", status_code=204)
async def delete_row(name: str, pk: str, admin=Depends(require_admin)):
    _writable(name)

    async with _writing() as session:
        row = await _get_row(session, name, pk)
        audit.add(
            session,
            Action.RECORD_DELETED,
            actor=audit.admin(admin.username),
            detail={"table": name, "pk": pk, "row": _serialize(name, row)},
        )
        await session.delete(row)
