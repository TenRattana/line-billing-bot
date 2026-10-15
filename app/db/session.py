import os

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

database_url = make_url(os.environ["DATABASE_URL"])
DATABASE_URL = database_url.set(host=os.getenv("DATABASE_HOST", database_url.host))


engine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
)


SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
