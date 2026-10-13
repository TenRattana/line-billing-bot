import csv
import json
import re
from pathlib import Path


DATA_FIELDS = [
    "customer_code",
    "customer_name",
    "tax_id",
    "cust_group",
    "sales_group",
    "invoice_no",
    "province",
    "voucher",
    "doc_type",
    "invoice_date",
    "due_date",
    "currency",
    "amount",
    "outstanding",
    "outstanding_mst",
    "days_overdue",
    "aging",
]


def _write_tsv(
    output_file: str | Path,
    fieldnames: list[str],
    rows: list[dict],
) -> None:
    output_file = Path(output_file)

    with output_file.open("w", encoding="utf-8", newline="",) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            delimiter="\t",
            lineterminator="\n",
        )

        writer.writeheader()
        writer.writerows(rows)


def _split_group_ids(value) -> list[str]:
    if value is None:
        return []

    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[,;|]", str(value))

    return [
        str(item).strip()
        for item in values
        if str(item).strip()
    ]


def export_data_txt(input_file: str | Path, output_file: str | Path,) -> None:
    with Path(input_file).open("r", encoding="utf-8-sig",) as f:
        raw = json.load(f)

    customers = raw["customers"]

    rows = []

    for customer in customers:
        for invoice in customer.get("invoices", []):
            rows.append(
                {
                    "customer_code": customer.get("customer_code", ""),
                    "customer_name": customer.get("customer_name", ""),
                    "tax_id": customer.get("tax_id", ""),
                    "cust_group": customer.get("cust_group", ""),

                    "sales_group": invoice.get(
                        "sales_group",
                        customer.get("sales_group", ""),
                    ),

                    "invoice_no": invoice.get("invoice_no", ""),
                    "voucher": invoice.get("voucher", ""),
                    "province": invoice.get("province", ""),
                    "doc_type": invoice.get("doc_type", ""),
                    "invoice_date": invoice.get("invoice_date", ""),
                    "due_date": invoice.get("due_date", ""),
                    "currency": invoice.get("currency", ""),
                    "amount": invoice.get("amount", 0),
                    "outstanding": invoice.get("outstanding", 0),
                    "outstanding_mst": invoice.get("outstanding_mst", 0),
                    "days_overdue": invoice.get("days_overdue", 0),
                    "aging": invoice.get("aging", ""),
                }
            )

    _write_tsv(output_file, DATA_FIELDS, rows,)

    print(f"สร้าง {output_file} เรียบร้อย")
    print(f"Customers : {len(customers)}")
    print(f"Invoices  : {len(rows)}")


def export_group_txt(input_file: str | Path, output_file: str | Path,) -> None:
    with Path(input_file).open("r", encoding="utf-8-sig",) as f:
        raw = json.load(f)

    if isinstance(raw, list):
        items = raw
    else:
        items = (
            raw.get("groups")
            or []
        )

    groups_by_emp: dict[str, set[str]] = {}

    for item in items:
        emp_code = str(
            item.get("EmpID")
            or item.get("empid")
            or ""
        ).strip()

        if not emp_code:
            continue

        group_ids = _split_group_ids(
            item.get("GroupID")
            or item.get("groupid")
        )

        if not group_ids:
            continue

        groups_by_emp.setdefault(emp_code, set()).update(group_ids)

    rows = [
        {
            "emp_code": emp_code,
            "group_id": ",".join(sorted(group_ids)),
        }
        for emp_code, group_ids in sorted(groups_by_emp.items())
    ]

    _write_tsv(
        output_file,
        ["emp_code", "group_id"],
        rows,
    )

    print(f"สร้าง {output_file} เรียบร้อย")
    print(f"Employees : {len(rows)}")
