"""Migrations run against the app's own engine (DATABASE_URL / DATABASE_HOST)."""

import asyncio
from logging.config import fileConfig

from alembic import context

from app.db import models  # noqa: F401  registers every table on Base.metadata
from app.db.base import Base
from app.db.session import engine

if context.config.config_file_name:
    fileConfig(context.config.config_file_name)


def _migrate(connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run() -> None:
    async with engine.connect() as connection:
        await connection.run_sync(_migrate)
    await engine.dispose()


# ponytail: online mode only; add offline (--sql) when SQL scripts are needed for a DBA
if context.is_offline_mode():
    raise SystemExit("offline migrations are not supported; run against the database")

asyncio.run(_run())
