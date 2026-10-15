"""The slips of a sent bill, for the backoffice to show."""

import mimetypes
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from app.billing.attachments import ATTACHMENT_DIR
from app.db.models import BillSend
from app.db.session import SessionLocal
from backoffice.api.auth import current_admin

router = APIRouter(prefix="/api/bill_sends")


async def _files(send_id: int) -> list[dict]:
    async with SessionLocal() as session:
        send = await session.get(BillSend, send_id)

    if send is None:
        raise HTTPException(404, "ไม่พบประวัติส่งบิลนี้")

    # Rows backfilled from the audit log only know the path.
    return [item if isinstance(item, dict) else {"path": item} for item in send.files or []]


def _safe_path(stored: str) -> Path | None:
    """The file, only if it really sits inside the slip folder (the DB value is editable)."""
    root = ATTACHMENT_DIR.resolve()
    path = Path(stored).resolve()
    return path if path.is_relative_to(root) and path.is_file() else None


@router.get("/{send_id}/files")
async def list_files(send_id: int, admin=Depends(current_admin)):
    files = []

    for index, item in enumerate(await _files(send_id)):
        path = Path(item["path"])
        files.append(
            {
                "index": index,
                "name": item.get("original_filename") or path.name,
                "mime_type": item.get("mime_type") or mimetypes.guess_type(path.name)[0] or "application/octet-stream",
                "file_size": item.get("file_size"),
                "available": _safe_path(item["path"]) is not None,
                "url": f"/api/bill_sends/{send_id}/files/{index}",
            }
        )

    return files


@router.get("/{send_id}/files/{index}")
async def get_file(send_id: int, index: int, admin=Depends(current_admin)):
    files = await _files(send_id)

    if not 0 <= index < len(files):
        raise HTTPException(404, "ไม่พบไฟล์")

    path = _safe_path(files[index]["path"])

    if path is None:
        raise HTTPException(404, "ไฟล์ไม่อยู่ในที่เก็บสลิปแล้ว")

    # inline: images/PDFs open in the browser rather than downloading
    return FileResponse(path, content_disposition_type="inline", filename=path.name)
