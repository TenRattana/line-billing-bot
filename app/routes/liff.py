import logging
import time

import httpx
from fastapi import APIRouter, Header, HTTPException
from linebot.v3.messaging import ApiException
from pydantic import BaseModel

from app.billing import receivables
from app.billing import repository as billing_repository
from app.config import LIFF_CHANNEL_ID
from app.flows import billing
from app.identity import repository
from app.line import api as line_api
from app.line.dispatcher import user_lock

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/liff", tags=["LIFF"])

_client: httpx.AsyncClient | None = None  # one pool: no new TLS handshake to LINE per request
# id token -> (sub, exp). LIFF reuses a token until it expires, so a page's
# GET and POST cost one LINE round trip.
_verified: dict[str, tuple[str, float]] = {}
_VERIFIED_MAX = 1000


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=5.0)
    return _client


async def close() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


async def verify_id_token(id_token: str) -> str:
    cached = _verified.get(id_token)
    if cached and cached[1] > time.time():
        return cached[0]

    try:
        response = await _http().post(
            "https://api.line.me/oauth2/v2.1/verify",
            data={"id_token": id_token, "client_id": LIFF_CHANNEL_ID},
        )
    except httpx.RequestError:
        raise HTTPException(status_code=503, detail="LINE authentication unavailable") from None

    if response.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid LINE ID token")

    try:
        claims = response.json()
    except ValueError:
        raise HTTPException(status_code=503, detail="LINE authentication unavailable") from None

    line_user_id = claims.get("sub")
    if not line_user_id:
        raise HTTPException(status_code=401, detail="Invalid LINE ID token")

    if claims.get("exp"):
        if len(_verified) >= _VERIFIED_MAX:
            # ponytail: drop all instead of LRU; only costs a re-verify per open page
            _verified.clear()
        _verified[id_token] = (line_user_id, float(claims["exp"]))

    return line_user_id


def _ms(since: float) -> float:
    return (time.perf_counter() - since) * 1000


async def _employee(authorization: str | None, timings: dict):
    scheme, _, id_token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not id_token:
        raise HTTPException(status_code=401, detail="Bearer token required")

    started = time.perf_counter()
    line_user_id = await verify_id_token(id_token)
    timings["verify_ms"] = _ms(started)

    started = time.perf_counter()
    employee = await repository.get_employee_by_line_user_id(line_user_id)
    timings["employee_ms"] = _ms(started)
    if employee is None:
        raise HTTPException(status_code=403, detail="LINE user is not registered")

    return line_user_id, employee


def _log_timings(endpoint: str, started: float, timings: dict) -> None:
    parts = " ".join(f"{name}={value:.0f}" for name, value in timings.items())
    logger.info("LIFF %s: %s total_ms=%.0f", endpoint, parts, _ms(started))


def _find_customer(customers: list[dict], customer_code: str) -> dict:
    code = customer_code.strip()
    selected = next((item for item in customers if item["customer_code"] == code), None)
    if selected is None:
        raise HTTPException(status_code=404, detail="Customer not found")

    return selected


async def _tell_expired(line_user_id: str) -> None:
    """The same answer a stale button gets, in the chat the LIFF closes back to."""
    try:
        await line_api.push_text(line_user_id, billing.EXPIRED_TEXT)
    except ApiException as error:
        logger.warning("Could not push the expired notice to %s: HTTP %s", line_user_id, error.status)


@router.get("/customer")
async def customer(
    customer_code: str,
    authorization: str | None = Header(default=None),
    flow_id: str = "",
    screen_step: str = "",
    screen_id: str = "",
):
    """The customer with the invoices still to send (none left: 200 with an empty list).

    404 only when the customer isn't in the employee's groups. 410 when the customer
    list the LIFF was opened from is no longer the screen on display (the chat is told).
    """
    started, timings = time.perf_counter(), {}
    try:
        line_user_id, employee = await _employee(authorization, timings)
        screen = {"flow_id": flow_id, "screen_step": screen_step, "screen_id": screen_id}
        if not billing.is_current_screen(line_user_id, screen):
            await _tell_expired(line_user_id)
            raise HTTPException(status_code=410, detail="Screen expired")

        selected = _find_customer(receivables.customers_for(employee.emp_code), customer_code)

        lookup = time.perf_counter()
        sent = await billing_repository.sent_invoice_ids([i["invoice_no"] for i in selected["invoices"]])
        timings["sent_ms"] = _ms(lookup)

        return receivables.with_invoices(selected, [i for i in selected["invoices"] if i["invoice_no"] not in sent])
    finally:
        _log_timings("customer", started, timings)


class Selection(BaseModel):
    customer_code: str
    invoice_nos: list[str]
    # The customer list the LIFF was opened from (from its URL).
    flow_id: str = ""
    screen_step: str = ""
    screen_id: str = ""


@router.post("/selection")
async def selection(
    body: Selection,
    authorization: str | None = Header(default=None),
):
    """Invoices confirmed in LIFF: the chat moves straight to the attachment step."""
    started, timings = time.perf_counter(), {}
    try:
        return await _select(body, authorization, timings)
    finally:
        _log_timings("selection", started, timings)


async def _select(body: Selection, authorization: str | None, timings: dict) -> dict:
    line_user_id, employee = await _employee(authorization, timings)

    invoice_nos = [number.strip() for number in body.invoice_nos]
    if not invoice_nos or len(set(invoice_nos)) != len(invoice_nos):
        raise HTTPException(status_code=400, detail="invoice_nos must be non-empty and unique")

    # All its invoices of the employee's groups, so a sent one is a 409, not a 404.
    selected = _find_customer(receivables.customers_for(employee.emp_code), body.customer_code)
    by_no = {invoice["invoice_no"]: invoice for invoice in selected["invoices"]}
    if any(number not in by_no for number in invoice_nos):
        raise HTTPException(status_code=404, detail="Invoice not found")

    sent = await billing_repository.sent_invoice_ids(invoice_nos)
    if sent:
        raise HTTPException(status_code=409, detail=f"Already sent: {', '.join(sorted(sent))}")

    pushed = time.perf_counter()
    try:
        async with user_lock(line_user_id):  # not alongside a chat event of the same user
            if not billing.is_current_screen(line_user_id, body.model_dump()):
                raise HTTPException(status_code=410, detail="Screen expired")
            await billing.start_selected(line_user_id, employee.emp_code, selected, [by_no[n] for n in invoice_nos])
    except ApiException:
        # The session is set; "เช็คงานค้าง" in the chat brings the screen back.
        raise HTTPException(status_code=502, detail="Could not send the screen to LINE chat") from None
    finally:
        timings["push_ms"] = _ms(pushed)

    return {"status": "ok"}
