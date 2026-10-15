import time
import uuid
from typing import Any

from app.billing import attachments

UI_RESEND_COOLDOWN_SECONDS = 5.0

# Steps: customer -> (invoices picked in LIFF) -> attachment -> confirm
_sessions: dict[str, dict[str, Any]] = {}


def _discard_files(user_id: str) -> None:
    """Uploaded files are saved at once; delete them when the bill they were for is dropped."""
    session = _sessions.get(user_id)
    for attachment in session["attachments"] if session else []:
        attachments.delete(attachment)


def new_session(user_id: str, emp_code: str) -> dict[str, Any]:
    _discard_files(user_id)  # the bill in progress is replaced
    session = {
        "emp_code": emp_code,  # whose sales group to show, and who the audit log names
        "flow_id": uuid.uuid4().hex,
        "screen_id": None,
        "step": "customer",
        "customer": None,
        "invoices": [],  # one, or several covered by the same upload
        "attachments": [],
        # The customer list on display: typed search text and page number.
        "query": "",
        "page": 0,
        "last_ui_sent_at": 0.0,
    }
    _sessions[user_id] = session
    return session


def get_session(user_id: str) -> dict[str, Any] | None:
    return _sessions.get(user_id)


def update(user_id: str, **fields: Any) -> None:
    """Change the session. Any change invalidates the screen on display."""
    session = _sessions.get(user_id)
    if session:
        session.update(fields, screen_id=None)


def reset_customer(user_id: str) -> None:
    _discard_files(user_id)
    update(user_id, customer=None, invoices=[], attachments=[], query="", page=0, step="customer")


def set_selection(user_id: str, customer: dict, invoices: list[dict]) -> None:
    _discard_files(user_id)
    update(user_id, customer=customer, invoices=invoices, attachments=[], step="attachment")


def add_attachments(user_id: str, saved: list[dict]) -> None:
    """One upload: its copy for each invoice of the bill."""
    session = _sessions.get(user_id)
    if session:
        update(user_id, attachments=[*session["attachments"], *saved], step="confirm")


def mark_screen_sent(user_id: str, screen_id: str) -> None:
    session = _sessions.get(user_id)
    if session:
        session["screen_id"] = screen_id
        session["last_ui_sent_at"] = time.monotonic()


def can_resend_ui(user_id: str) -> bool:
    session = _sessions.get(user_id)
    if not session:
        return False
    return time.monotonic() - session["last_ui_sent_at"] >= UI_RESEND_COOLDOWN_SECONDS


def clear_session(user_id: str, *, keep_files: bool = False) -> None:
    """keep_files: the files belong to a recorded send (don't delete a sent slip)."""
    if not keep_files:
        _discard_files(user_id)
    _sessions.pop(user_id, None)
