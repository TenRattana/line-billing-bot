"""Read-only access to the central employee directory database."""

import os

from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _database_url() -> URL:
    env_file = os.getenv("EMPLOYEE_DB_ENV_FILE", "../db/.env")
    password = dotenv_values(env_file).get("POSTGRES_PASSWORD")

    if not password:
        raise RuntimeError(f"POSTGRES_PASSWORD is not set in {env_file}")

    return URL.create(
        "postgresql+asyncpg",
        username="central",
        password=password,
        host="central-db",
        port=5432,
        database="central",
    )


engine = create_async_engine(_database_url(), pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_active_by_code(emp_code: str) -> dict | None:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                text(
                    """
                    SELECT first_name_th, last_name_th,
                           first_name_en, last_name_en,
                           department, email, tel_inner
                    FROM public.employees
                    WHERE emp_code = :emp_code AND active IS TRUE
                    """
                ),
                {"emp_code": emp_code},
            )
        ).mappings().one_or_none()

    if row is None:
        return None

    return _person_from_row(row)


def _person_from_row(row: dict) -> dict:
    first_name = str(row["first_name_th"] or "").strip()
    last_name = str(row["last_name_th"] or "").strip()
    first_name_en = str(row["first_name_en"] or "").strip()
    last_name_en = str(row["last_name_en"] or "").strip()
    english_name = f"{first_name_en} {last_name_en}" if first_name_en and last_name_en else ""

    return {
        "fn": first_name,
        "ln": last_name,
        "name": f"{first_name} {last_name}".strip(),
        "aliases": [english_name] if english_name else [],
        "department": row["department"],
        "email": row["email"],
        "phone": row["tel_inner"],
    }


async def close() -> None:
    await engine.dispose()
