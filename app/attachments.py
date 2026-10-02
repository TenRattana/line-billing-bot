import json
import os
import re
from datetime import datetime
from pathlib import Path

from app.config import BANGKOK

ATTACHMENT_DIR = Path(os.getenv("ATTACHMENT_DIR", "/data/validated/slips"))
MAX_FILE_SIZE = 10 * 1024 * 1024
TOO_LARGE_ERROR = "ไฟล์มีขนาดเกิน 10 MB"

# mime type -> (allowed extensions, default extension, label)
ATTACHMENT_TYPES = {
    "image/jpeg": ({".jpg", ".jpeg"}, ".jpg", "JPEG"),
    "image/png": ({".png"}, ".png", "PNG"),
    "image/webp": ({".webp"}, ".webp", "WebP"),
    "image/heic": ({".heic"}, ".heic", "HEIC"),
    "image/heif": ({".heif"}, ".heif", "HEIF"),
    "image/tiff": ({".tif", ".tiff"}, ".tiff", "TIFF"),
    "application/pdf": ({".pdf"}, ".pdf", "PDF"),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ({".xlsx"}, ".xlsx", "XLSX"),
    "application/vnd.ms-excel": ({".xls"}, ".xls", "XLS"),
}


def normalize_mime(mime_type: str) -> str:
    return mime_type.split(";", 1)[0].strip().lower()


def validate(
    *,
    message_type: str,
    filename: str | None,
    mime_type: str,
    file_size: int,
) -> str | None:
    """Return an error message, or None when the attachment is allowed."""
    mime_type = normalize_mime(mime_type)

    if file_size > MAX_FILE_SIZE:
        return TOO_LARGE_ERROR

    attachment_type = ATTACHMENT_TYPES.get(mime_type)

    if not attachment_type:
        return f"ไม่รองรับไฟล์ประเภท {mime_type}"

    extensions, _, label = attachment_type

    if message_type == "image":
        if not mime_type.startswith("image/"):
            return "ไฟล์ที่ส่งมาไม่ใช่รูปภาพ"
        return None

    if message_type == "file":
        if not filename:
            return "ไม่พบชื่อไฟล์"

        extension = Path(filename).suffix.lower()

        if extension not in extensions:
            return f"นามสกุลไฟล์ {extension} ไม่ตรงกับประเภท {label}"
        return None

    return "ไม่รองรับ message type นี้"


def _safe_name(name: str) -> str:
    """One path component: ASCII letters, digits, . _ - only; never "." / ".."."""
    return re.sub(r"[^A-Za-z0-9._-]", "_", name).strip(".") or "_"


def save(
    *,
    content: bytes,
    mime_type: str,
    filename: str | None,
    invoice_id: str,
    customer_id:str,
    line_message_id: str,
    user_id: str,
) -> dict:

    mime_type = normalize_mime(mime_type)
    received_at = datetime.now(BANGKOK)

    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)

    if filename:
        extension = Path(filename).suffix.lower()
    else:
        extension = ATTACHMENT_TYPES[mime_type][1]

    stored_filename = (
        f"{received_at:%Y%m%d}_"
        f"{_safe_name(invoice_id)}_"
        f"{_safe_name(customer_id)}"
        f"{extension}"
    )

    file_path = ATTACHMENT_DIR / stored_filename
    file_path.write_bytes(content)

    metadata_path = file_path.with_suffix(
        file_path.suffix + ".json"
    )

    metadata_path.write_text(
        json.dumps(
            {
                "invoice_id": invoice_id,
                "customer_id": customer_id,
                "line_message_id": line_message_id,
                "user_id": user_id,
                "original_filename": filename,
                "stored_filename": file_path.name,
                "stored_path": str(file_path),
                "mime_type": mime_type,
                "file_size": len(content),
                "received_at": received_at.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return {
        "file_path": str(file_path),
        "metadata_path": str(metadata_path),
        "mime_type": mime_type,
        "original_filename": filename,
        "file_size": len(content),
    }


def delete(attachment: dict) -> None:
    """Remove a saved file (and its metadata) that will never be sent."""
    for path in (attachment["file_path"], attachment["metadata_path"]):
        Path(path).unlink(missing_ok=True)


def format_file_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def type_label(mime_type: str) -> str:
    mime_type = normalize_mime(mime_type)
    attachment_type = ATTACHMENT_TYPES.get(mime_type)
    return attachment_type[2] if attachment_type else mime_type
