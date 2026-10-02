"""Backoffice API (runs in its own container, next to the bot).

    uvicorn backoffice_api.main:app --port 8600

The React app talks to it through nginx at /api; it shares the bot's database
and models but none of its runtime, so either can restart without the other.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import Body, Depends, FastAPI, Response

from app.line import api as line_api
from backoffice_api import auth, bill_files, dashboard, line_routes, tables

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await line_api.close()


app = FastAPI(title="LINE Billing Backoffice", lifespan=lifespan, docs_url=None, redoc_url=None)

app.include_router(tables.router)
app.include_router(dashboard.router)
app.include_router(line_routes.router)
app.include_router(bill_files.router)


def _me(admin) -> dict:
    return {"username": admin.username, "role": admin.role}


@app.post("/api/login")
async def login(response: Response, username: str = Body(...), password: str = Body(...)):
    return _me(await auth.login(username, password, response))


@app.post("/api/logout", status_code=204)
async def logout(response: Response):
    auth.logout(response)


@app.get("/api/me")
async def me(admin=Depends(auth.current_admin)):
    return _me(admin)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "backoffice-api"}
