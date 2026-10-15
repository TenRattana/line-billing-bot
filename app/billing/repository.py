from datetime import datetime

from sqlalchemy import select

from app import audit
from app.audit import Action
from app.db.models.bill_send import BillSend
from app.db.session import SessionLocal


async def record_send(
    *,
    emp_code: str,
    customer: dict,
    invoices: list[dict],
    attachments: list[dict],
) -> None:
    """Save one send per invoice, each with its own copy of the files, and their audit rows in one transaction."""
    async with SessionLocal() as session:
        for invoice in invoices:
            files = [a for a in attachments if a["invoice_no"] == invoice["invoice_no"]]
            session.add(
                BillSend(
                    emp_code=emp_code,
                    invoice_id=invoice["invoice_no"],
                    customer_id=customer["customer_code"],
                    customer_name=customer["customer_name"],
                    customer_email=customer.get("email"),  # not in the receivables data yet
                    amount=invoice["outstanding"],  # the amount being billed
                    attachment_count=len(files),
                    files=[
                        {
                            "path": attachment["file_path"],
                            "mime_type": attachment["mime_type"],
                            "original_filename": attachment["original_filename"],
                            "file_size": attachment["file_size"],
                        }
                        for attachment in files
                    ],
                )
            )
            audit.add(
                session,
                Action.INVOICE_SUBMITTED,
                actor=audit.employee(emp_code),
                emp_code=emp_code,
                invoice_no=invoice["invoice_no"],
                detail={
                    "customer_code": customer["customer_code"],
                    "customer_name": customer["customer_name"],
                    "amount": float(invoice["outstanding"]),
                    "files": [attachment["file_path"] for attachment in files],
                    "sent_with": [i["invoice_no"] for i in invoices],
                },
            )
        await session.commit()


async def sent_invoice_ids(invoice_nos: list[str]) -> set[str]:
    """Which of these invoices were already sent (by anyone)."""
    if not invoice_nos:
        return set()

    async with SessionLocal() as session:
        result = await session.scalars(
            select(BillSend.invoice_id).where(BillSend.invoice_id.in_(invoice_nos)).distinct()
        )
        return set(result)


async def list_sends(*, emp_code: str, since: datetime) -> list[BillSend]:
    """The employee's sends since `since`, newest first."""
    async with SessionLocal() as session:
        result = await session.scalars(
            select(BillSend)
            .where(
                BillSend.emp_code == emp_code,
                BillSend.sent_at >= since,
            )
            .order_by(BillSend.sent_at.desc())
        )
        return list(result)
