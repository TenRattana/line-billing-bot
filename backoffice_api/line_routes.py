"""LINE data for the backoffice: friend / block counts, user profiles, releasing a binding."""

import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from linebot.v3 import insight

from app.identity import repository
from app.line import api as line_api
from app.line import richmenu
from backoffice_api.auth import current_admin, require_admin

router = APIRouter(prefix="/api/line")

# LINE Insight dates are UTC+9 days; a finished ("ready") day never changes, so it's cached.
JST = timezone(timedelta(hours=9))
_followers_cache: dict[str, dict] = {}


async def _followers_on(client: insight.AsyncApiClient, day: str) -> dict:
    if day in _followers_cache:
        return _followers_cache[day]

    try:
        result = await insight.AsyncInsight(client).get_number_of_followers(var_date=day)
    except insight.ApiException as error:
        return {"date": day, "status": f"error {error.status}"}

    row = {
        "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
        "status": result.status,  # ready / unready (not computed yet) / out_of_service
        "followers": result.followers,
        "targeted_reaches": result.targeted_reaches,
        "blocks": result.blocks,
    }
    if result.status == "ready":
        _followers_cache[day] = row
    return row


@router.get("/followers")
async def followers(days: int = 14, admin=Depends(current_admin)):
    """Daily friends / blocks. LINE computes a day after it ends, so the series stops at yesterday."""
    days = min(max(days, 1), 60)
    today = datetime.now(JST).date()
    dates = [(today - timedelta(days=offset)).strftime("%Y%m%d") for offset in range(days, 0, -1)]

    configuration = insight.Configuration(access_token=await line_api.access_token())
    async with insight.AsyncApiClient(configuration) as client:
        return await asyncio.gather(*(_followers_on(client, day) for day in dates))


@router.get("/profile/{line_user_id}")
async def profile(line_user_id: str, admin=Depends(current_admin)):
    result = await line_api.get_profile(line_user_id)

    if result is None:  # blocked the bot, or not a friend
        raise HTTPException(404, "LINE ไม่ให้ข้อมูลโปรไฟล์ (ผู้ใช้อาจบล็อกบอท)")

    return {
        "display_name": result.display_name,
        "picture_url": result.picture_url,
        "status_message": result.status_message,
        "language": result.language,
    }


@router.post("/release/{emp_code}")
async def release(emp_code: str, admin=Depends(require_admin)):
    """Unbind an employee from LINE (same as the release command); they must register again."""
    line_user_id = await repository.release_line_identity(emp_code, admin=admin.username)

    if line_user_id is None:
        raise HTTPException(404, f"ไม่พบการผูก LINE ของรหัส {emp_code}")

    await richmenu.unlink(line_user_id)
    return {"emp_code": emp_code, "line_user_id": line_user_id}
