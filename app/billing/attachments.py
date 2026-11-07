import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from app.config import BANGKOK

logger = logging.getLogger(__name__)

# Another system collects from here and moves the files away within days. It relies on
# these names and metadata: only confirmed slips land here, exactly as they are named below.
ATTACHMENT_DIR = Path(os.getenv("ATTACHMENT_DIR", "/data/validated/slips"))
TEMP_DIR = ATTACHMENT_DIR.with_name("slips_temp")  # uploaded, not confirmed yet
HISTORY_DIR = ATTACHMENT_DIR.with_name("slips_history")  # kept for the backoffice
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


def _metadata(file_path: Path) -> Path:
    return file_path.with_suffix(file_path.suffix + ".json")


def save(
    *,
    content: bytes,
    mime_type: str,
    filename: str | None,
    invoice_id: str,
    invoice_date: str,
    customer_id:str,
    province:str,
    line_message_id: str,
    user_id: str,
) -> dict:

    mime_type = normalize_mime(mime_type)
    received_at = datetime.now(BANGKOK)

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

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
    # The message id keeps two people's uploads for one invoice apart until they confirm.
    temp_path = TEMP_DIR / f"{_safe_name(line_message_id)}_{stored_filename}"
    temp_path.write_bytes(content)

    try:
        _metadata(temp_path).write_text(
            json.dumps(
                {
                    "invoice_id": invoice_id,
                    "invoice_date": invoice_date,
                    "customer_id": customer_id,
                    "province": province,
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
    except Exception:
        temp_path.unlink(missing_ok=True)  # no slip without its metadata
        raise

    return {
        "invoice_no": invoice_id,
        "temp_path": str(temp_path),
        "file_path": str(file_path),
        "history_path": str(HISTORY_DIR / stored_filename),
        "mime_type": mime_type,
        "original_filename": filename,
        "file_size": len(content),
    }


def save_copies(*, invoices: list[dict], customer_id: str, **upload) -> list[dict]:
    """One upload covering several invoices: a copy per invoice, all or none."""
    saved = []
    try:
        for invoice in invoices:
            saved.append(
                save(
                    invoice_id=invoice["invoice_no"],
                    invoice_date=invoice["invoice_date"],
                    province=invoice["province"],
                    customer_id=customer_id,
                    **upload,
                )
            )
    except Exception:
        for attachment in saved:
            delete(attachment)
        raise

    return saved


def _from_temp(attachment: dict, folder: Path) -> list[tuple[Path, Path]]:
    """(temp file, its place in folder) for the slip and its metadata."""
    temp, target = Path(attachment["temp_path"]), folder / Path(attachment["file_path"]).name
    return [(temp, target), (_metadata(temp), _metadata(target))]


def archive(saved: list[dict]) -> None:
    """Copy confirmed slips to the history. Raises before anything is recorded."""
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)

    for attachment in saved:
        for source, target in _from_temp(attachment, HISTORY_DIR):
            shutil.copy2(source, target)


def publish(saved: list[dict]) -> None:
    """Hand recorded slips over. The send is already saved, so a failure is logged, not raised."""
    ATTACHMENT_DIR.mkdir(parents=True, exist_ok=True)

    for attachment in saved:
        try:
            for source, target in _from_temp(attachment, ATTACHMENT_DIR):
                os.replace(source, target)  # same volume: appears whole, never half written
        except OSError:
            logger.exception("Slip not delivered to %s; copy is in %s", ATTACHMENT_DIR, attachment["history_path"])


def delete(attachment: dict) -> None:
    """Remove an upload that will never be sent."""
    temp = Path(attachment["temp_path"])
    for path in (temp, _metadata(temp)):
        path.unlink(missing_ok=True)


def clear_temp() -> None:
    """At startup: sessions live in memory, so nothing in here belongs to anyone any more."""
    shutil.rmtree(TEMP_DIR, ignore_errors=True)


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
