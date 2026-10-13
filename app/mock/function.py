import csv
from functools import cache
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

DATA_FILE = BASE_DIR / "data.txt"
GROUP_FILE = BASE_DIR / "group.txt"


def to_float(value):
    return float(value) if value else 0.0


def to_int(value):
    return int(value) if value else 0


def normalize_group(value: str) -> str:
    return value.strip().casefold()


def split_group_ids(value: str) -> set[str]:
    return {
        normalize_group(group_id)
        for group_id in value.split(",")
        if group_id.strip()
    }


def load_groups() -> dict[str, set[str]]:
    if not GROUP_FILE.exists():
        return {}

    groups_by_emp = {}

    with GROUP_FILE.open(
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            emp_code = row["emp_code"].strip()

            if not emp_code:
                continue

            groups_by_emp.setdefault(
                emp_code,
                set(),
            ).update(
                split_group_ids(row["group_id"])
            )

    return groups_by_emp


def load_customers() -> list[dict]:
    if not DATA_FILE.exists():
        return []

    customers = {}

    with DATA_FILE.open(
        encoding="utf-8-sig",
        newline="",
    ) as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            customer_code = row["customer_code"].strip()

            if customer_code not in customers:
                customers[customer_code] = {
                    "customer_code": customer_code,
                    "customer_name": row["customer_name"].strip(),
                    "tax_id": row["tax_id"].strip(),
                    "cust_group": row["cust_group"].strip(),
                    "total_outstanding": 0.0,
                    "overdue_amount": 0.0,
                    "invoice_count": 0,
                    "invoices": [],
                }

            customer = customers[customer_code]

            invoice = {
                "invoice_no": row["invoice_no"].strip(),
                "voucher": row["voucher"].strip(),
                "doc_type": row["doc_type"].strip(),
                "invoice_date": row["invoice_date"].strip(),
                "due_date": row["due_date"].strip(),
                "currency": row["currency"].strip(),
                "amount": to_float(row["amount"]),
                "province": row["province"].strip(),
                "outstanding": to_float(row["outstanding"]),
                "outstanding_mst": to_float(
                    row["outstanding_mst"]
                ),
                "days_overdue": to_int(
                    row["days_overdue"]
                ),
                "aging": row["aging"].strip(),
                "sales_group": row["sales_group"].strip(),
            }

            customer["invoices"].append(invoice)

            customer["total_outstanding"] += (
                invoice["outstanding"]
            )

            customer["invoice_count"] += 1

            if invoice["days_overdue"] > 0:
                customer["overdue_amount"] += (
                    invoice["outstanding"]
                )

    return list(customers.values())


GROUPS_BY_EMP_CODE = load_groups()
CUSTOMERS = load_customers()

def reload() -> None:
    global GROUPS_BY_EMP_CODE, CUSTOMERS

    GROUPS_BY_EMP_CODE = load_groups()
    CUSTOMERS = load_customers()

    customers_for.cache_clear()


def with_invoices(
    customer: dict,
    invoices: list[dict],
) -> dict:
    return {
        **customer,
        "invoices": invoices,
        "invoice_count": len(invoices),

        "total_outstanding": sum(
            invoice["outstanding"]
            for invoice in invoices
        ),

        "overdue_amount": sum(
            invoice["outstanding"]
            for invoice in invoices
            if invoice["days_overdue"] > 0
        ),
    }


@cache
def customers_for(emp_code: str) -> list[dict]:
    allowed_groups = GROUPS_BY_EMP_CODE.get(
        emp_code.strip(),
        set(),
    )

    if not allowed_groups:
        return []

    customers = []

    for customer in CUSTOMERS:
        invoices = sorted(
            (
                invoice
                for invoice in customer["invoices"]
                if normalize_group(
                    invoice["sales_group"]
                ) in allowed_groups
            ),
            key=lambda invoice: -invoice["days_overdue"],
        )

        if invoices:
            customers.append(
                with_invoices(
                    customer,
                    invoices,
                )
            )

    return sorted(
        customers,
        key=lambda customer: -customer["total_outstanding"],
    )
