import hmac
import logging
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.billing import attachments, receivables
from app.billing import session as billing_session
from app.config import LIFF_ALLOWED_ORIGIN, LINE_RICH_MENU_SETUP_ENABLED, RELOAD_TOKEN
from app.identity import directory, repository
from app.line import api as line_api
from app.line import richmenu
from app.routes.line import router as line_router
from app.routes import liff

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    attachments.clear_temp()

    # Off until a new LINE channel is verified: setup replaces menus and relinks every user.
    if LINE_RICH_MENU_SETUP_ENABLED:
        try:
            await richmenu.setup(await repository.list_registered_line_user_ids())
        except Exception:
            logger.exception("Rich menu setup failed")

    scheduler = AsyncIOScheduler(timezone="Asia/Bangkok")
    receivables.schedule(scheduler)  # the first load happens at import
    scheduler.add_job(billing_session.expire_idle, trigger="interval", hours=1, id="expire_idle_sessions")
    scheduler.start()

    yield

    scheduler.shutdown(wait=False)

    await directory.close()
    await line_api.close()
    await liff.close()


app = FastAPI(
    title="LINE Billing Bot",
    version="0.1.0",
    lifespan=lifespan,
)

if LIFF_ALLOWED_ORIGIN:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[LIFF_ALLOWED_ORIGIN],
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )


app.mount(
    "/assets",
    StaticFiles(directory="/app/app/assets"),
    name="assets",
)


app.include_router(line_router)
app.include_router(liff.router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "line-billing-bot",
    }


@app.post("/internal/reload")
async def reload_receivables(x_reload_token: str = Header(default="")):
    """Load the exports now, after a correction; the daily load still runs. nginx exposes this, hence the token."""
    if not RELOAD_TOKEN or not hmac.compare_digest(x_reload_token.encode(), RELOAD_TOKEN.encode()):
        raise HTTPException(status_code=403, detail="Forbidden")

    try:
        return await receivables.refresh()
    except Exception:
        logger.exception("Receivables reload failed; keeping the current data")
        raise HTTPException(status_code=503, detail="Export not usable; keeping the current data") from None
