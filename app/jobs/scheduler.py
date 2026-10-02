from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.jobs.update_mock import update_data


scheduler = AsyncIOScheduler(
    timezone="Asia/Bangkok",
)


def start_scheduler() -> None:
    scheduler.add_job(
        update_data,
        trigger="cron",
        hour=18,
        minute=30,
        id="update_mock_data",
        replace_existing=True,
    )

    scheduler.start()
