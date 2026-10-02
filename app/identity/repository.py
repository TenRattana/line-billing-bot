from sqlalchemy import delete, or_, select
from sqlalchemy.exc import IntegrityError

from app import audit
from app.audit import Action
from app.db.models.employee import Employee
from app.db.models.user_identity import UserIdentity
from app.db.session import SessionLocal

PROVIDER = "line"


async def get_employee_by_code(
    emp_code: str,
) -> Employee | None:
    async with SessionLocal() as session:
        return await session.get(Employee, emp_code.strip())


async def get_line_identity(
    line_user_id: str,
) -> tuple[Employee, UserIdentity] | None:
    """The active employee bound to this LINE user, with the binding row."""
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(Employee, UserIdentity)
                .join(
                    UserIdentity,
                    UserIdentity.emp_code == Employee.emp_code,
                )
                .where(
                    UserIdentity.provider == PROVIDER,
                    UserIdentity.external_id == line_user_id.strip(),
                    UserIdentity.active.is_(True),
                    Employee.active.is_(True),
                )
            )
        ).first()

        return tuple(row) if row else None


async def get_employee_by_line_user_id(
    line_user_id: str,
) -> Employee | None:
    identity = await get_line_identity(line_user_id)
    return identity[0] if identity else None


async def is_code_registered(emp_code: str) -> bool:
    """Whether this employee code is already bound to a LINE account."""
    async with SessionLocal() as session:
        return bool(
            await session.scalar(
                select(UserIdentity.id).where(
                    UserIdentity.provider == PROVIDER,
                    UserIdentity.emp_code == emp_code,
                    UserIdentity.active.is_(True),
                )
            )
        )


async def release_line_identity(emp_code: str, *, admin: str) -> str | None:
    """Admin unbinds an employee from their LINE account; returns that LINE user id.

    The employee must register again (code + name) from whichever LINE account.
    Sent-bill history is keyed by emp_code, so it stays.
    """
    async with SessionLocal() as session:
        identity = await session.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == PROVIDER,
                UserIdentity.emp_code == emp_code,
            )
        )

        if identity is None:
            return None

        await session.delete(identity)
        audit.add(
            session,
            Action.EMPLOYEE_RELEASED,
            actor=audit.admin(admin),
            emp_code=emp_code,
            line_user_id=identity.external_id,
            detail={"display_name": identity.display_name},
        )
        await session.commit()
        return identity.external_id


async def register_line_identity(
    *,
    line_user_id: str,
    emp_code: str,
    person: dict,
    display_name: str | None = None,
    picture_url: str | None = None,
) -> tuple[str, Employee | None]:
    """Save the verified employee (HR data wins over what's stored) and bind LINE to it."""
    line_user_id = line_user_id.strip()
    emp_code = emp_code.strip()

    async with SessionLocal() as session:
        employee = await session.get(Employee, emp_code)

        if employee is None:
            employee = Employee(emp_code=emp_code, active=True)
            session.add(employee)
        elif not employee.active:
            return "employee_inactive", employee

        employee.emp_fn = person["fn"]
        employee.emp_ln = person["ln"]
        employee.emp_full = person["name"]
        employee.emp_department = person["department"]

        # Bindings switched off by hand (active=false) count as released;
        # clear them so the unique (provider, code / LINE id) keys don't block this one.
        await session.execute(
            delete(UserIdentity).where(
                UserIdentity.provider == PROVIDER,
                UserIdentity.active.is_(False),
                or_(UserIdentity.emp_code == emp_code, UserIdentity.external_id == line_user_id),
            )
        )

        # LINE account นี้เคย register หรือยัง
        existing_line = await session.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == PROVIDER,
                UserIdentity.external_id == line_user_id,
            )
        )

        if existing_line:
            if existing_line.emp_code == emp_code:
                return "already_registered", employee
            return "line_already_registered", employee

        # Employee คนนี้ถูก LINE อื่น bind ไปหรือยัง
        existing_employee = await session.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == PROVIDER,
                UserIdentity.emp_code == emp_code,
            )
        )

        if existing_employee:
            return "employee_already_registered", employee

        session.add(
            UserIdentity(
                emp_code=emp_code,
                provider=PROVIDER,
                external_id=line_user_id,
                display_name=display_name,
                picture_url=picture_url,
                active=True,
            )
        )
        audit.add(
            session,
            Action.EMPLOYEE_REGISTERED,
            actor=audit.employee(emp_code),
            emp_code=emp_code,
            line_user_id=line_user_id,
            detail={
                "name": person["name"],
                "department": person["department"],
                "line_display_name": display_name,
            },
        )

        try:
            await session.commit()
        except IntegrityError:
            # Another LINE account bound this code at the same moment.
            return "employee_already_registered", None

        return "registered", employee


async def list_registered_line_user_ids() -> list[str]:
    async with SessionLocal() as session:
        result = await session.scalars(
            select(UserIdentity.external_id)
            .join(
                Employee,
                UserIdentity.emp_code == Employee.emp_code,
            )
            .where(
                UserIdentity.provider == PROVIDER,
                UserIdentity.active.is_(True),
                Employee.active.is_(True),
            )
        )
        return list(result)
