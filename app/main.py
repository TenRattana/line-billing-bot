import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.jobs.update_mock import update_data
from app.identity import directory, repository
from app.line import api as line_api
from app.line import richmenu
from app.routes.line import router as line_router

from app.jobs.scheduler import start_scheduler, scheduler
from app.jobs.update_mock import update_data

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await richmenu.setup(
            await repository.list_registered_line_user_ids()
        )
    except Exception:
        logger.exception("Rich menu setup failed")

    sync_task = (
        asyncio.create_task(directory.loop())
        if directory.enabled()
        else None
    )

    # สร้าง/โหลดข้อมูลทันทีตอนเปิดระบบ
    try:
        update_data()
        logger.info("Initial data update completed")
    except Exception:
        logger.exception("Initial data update failed")

    # จากนั้นตั้งให้อัปเดตทุกวัน 18:30
    start_scheduler()
    logger.info("Scheduler started")

    yield

    # -------------------------
    # Shutdown
    # -------------------------

    if scheduler.running:
        scheduler.shutdown(wait=False)

    if sync_task:
        sync_task.cancel()

    await directory.close()
    await line_api.close()


app = FastAPI(
    title="LINE Billing Bot",
    version="0.1.0",
    lifespan=lifespan,
)


app.mount(
    "/assets",
    StaticFiles(directory="/app/app/assets"),
    name="assets",
)


app.include_router(line_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "line-billing-bot",
    }


@app.post("/internal/update-mock", include_in_schema=False)
async def update_mock_now():
    update_data()
    return {"ok": True}
