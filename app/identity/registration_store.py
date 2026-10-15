from typing import Any

# line_user_id -> registration in progress. Steps: employee_code -> full_name -> confirm,
# or "reverify" for an already-bound user.
_registrations: dict[str, dict[str, Any]] = {}


def start_registration(
    line_user_id: str,
    *,
    display_name: str | None,
    picture_url: str | None,
) -> dict[str, Any]:
    registration = _registrations[line_user_id] = {
        "step": "employee_code",
        "emp_code": None,
        "person": None,  # directory data from the code step; the name is checked against it, saved on confirm
        "name_attempts": 0,
        "display_name": display_name,
        "picture_url": picture_url,
    }
    return registration


def start_reverify(line_user_id: str, *, emp_code: str) -> None:
    """A bound user re-confirming their code (after block -> unblock)."""
    _registrations[line_user_id] = {"step": "reverify", "emp_code": emp_code}


def get_registration(line_user_id: str) -> dict[str, Any] | None:
    return _registrations.get(line_user_id)


def update(line_user_id: str, **fields: Any) -> None:
    registration = _registrations.get(line_user_id)

    if registration:
        registration.update(fields)


def clear_registration(line_user_id: str) -> None:
    _registrations.pop(line_user_id, None)
