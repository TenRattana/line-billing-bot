import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.billing import receivables
from app.config import LIFF_ALLOWED_ORIGIN, LINE_RICH_MENU_SETUP_ENABLED
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
    # Off until a new LINE channel is verified: setup replaces menus and relinks every user.
    if LINE_RICH_MENU_SETUP_ENABLED:
        try:
            await richmenu.setup(await repository.list_registered_line_user_ids())
        except Exception:
            logger.exception("Rich menu setup failed")

    receivables.start_daily_reload()  # the first load happens at import

    yield

    receivables.stop_daily_reload()

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
