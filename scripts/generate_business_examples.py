"""Generate or check the deterministic, fictional Juniper Supply example bundle.

Uses only the standard library. Expected values are calculated independently of
DataForge's parsing, transformation, validation, and reporting engines.
"""

import argparse
import csv
import io
import json
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1] / "examples" / "small_business"


def money(value) -> str:
    return format(Decimal(value).quantize(Decimal("0.01")), "f")


def json_bytes(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def csv_bytes(rows: list[dict]) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8")


def rule(kind: str, column: str | None = None, **parameters) -> dict:
    return {"kind": kind, **({"column": column} if column else {}), **parameters}


def metric(op: str, column: str | None, name: str) -> dict:
    return {"op": op, **({"column": column} if column else {}), "name": name}


def generated_files() -> dict[str, bytes]:
    """Pure fixture construction: no random state, network, clock, or database."""
    files: dict[str, bytes] = {}
    names = [
        "Alder",
        "Birch",
        "Cedar",
        "Dahlia",
        "Elm",
        "Fern",
        "Grove",
        "Hazel",
        "Iris",
        "Juniper",
        "Kestrel",
        "Laurel",
        "Maple",
        "Nettle",
        "Olive",
        "Pine",
        "Quince",
        "Rowan",
        "Sorrel",
        "Thistle",
        "Umber",
        "Violet",
        "Willow",
        "Yarrow",
    ]
    customers = [
        {
            "customer_id": f"C{i + 1:03}",
            "business_name": f"{name} Studio (Fictional)",
            "email": f"orders{i + 1:02}@example.test",
            "region": ["NORTH", "SOUTH", "EAST", "WEST"][i % 4],
            "segment": ["retail", "trade", "office"][i % 3],
            "joined_date": (date(2025, 1, 1) + timedelta(days=i * 11)).isoformat(),
        }
        for i, name in enumerate(names)
    ]
    customers[6]["email"] = None
    customers[10]["region"] = "east "
    customers[5]["email"] = " Orders06@EXAMPLE.TEST "
    customers_raw = customers + [dict(customers[2])]
    files["customers.json"] = json_bytes(customers_raw)

    catalogue = [
        ("Recycled notebook", "Office", "4.50", "2.10"),
        ("Gel pen pack", "Office", "6.00", "2.80"),
        ("Desk organiser", "Office", "18.00", "9.00"),
        ("Work gloves", "Workshop", "12.50", "6.25"),
        ("Measuring tape", "Workshop", "9.75", "4.50"),
        ("Utility brush", "Workshop", "7.25", "3.20"),
        ("Coffee beans 250g", "Pantry", "11.00", "6.00"),
        ("Tea box", "Pantry", "8.50", "4.00"),
        ("Oat biscuit tin", "Pantry", "6.75", "3.10"),
        ("Small mailer pack", "Packaging", "14.00", "7.00"),
        ("Paper tape roll", "Packaging", "5.25", "2.25"),
        ("Kraft bag pack", "Packaging", "10.00", "4.75"),
    ]
    products = [
        {
            "product_id": f"P{i + 1:03}",
            "product_name": name,
            "category": category,
            "unit_price": price,
            "unit_cost": cost,
            "reorder_level": 25,
            "supplier": f"Fictional Supplier {i // 3 + 1}",
        }
        for i, (name, category, price, cost) in enumerate(catalogue)
    ]
    products_raw = [dict(p) for p in products]
    products_raw[0]["category"] = " Office "
    products_raw.append(dict(products_raw[3]))
    files["products.json"] = json_bytes(products_raw)

    sales = []
    for i in range(144):
        # Two lines per order on the first 24 days of each month.
        month, within_month = divmod(i, 48)
        product = products[(i * 5 + i // 12) % 12]
        quantity = i % 5 + 1
        discount = Decimal("1.00") if i % 7 == 0 else Decimal("0.00")
        sales.append(
            {
                "sale_id": f"S{i + 1:04}",
                "order_id": f"O{i // 2 + 1:04}",
                "date": date(2026, month + 1, within_month // 2 + 1).isoformat(),
                "month": f"2026-{month + 1:02}",
                "customer_id": customers[(i * 7) % 24]["customer_id"],
                "product_id": product["product_id"],
                "category": product["category"],
                "channel": ["shop", "web", "trade"][i % 3],
                "status": "cancelled" if i % 6 == 5 else "completed",
                "quantity": str(quantity),
                "unit_price": product["unit_price"],
                "unit_cost": product["unit_cost"],
                "discount_amount": money(discount),
            }
        )
    sales_raw = sales + [dict(sales[7])]
    for identifier, changes in [
        ("S0901", {"quantity": ""}),
        ("S0902", {"date": "2026-02-30"}),
        ("S0903", {"customer_id": "C999"}),
        ("S0904", {"quantity": "-2"}),
        ("S0905", {"customer_id": ""}),
    ]:
        sales_raw.append(
            {**sales[0], "sale_id": identifier, "order_id": identifier.replace("S", "O"), **changes}
        )
    files["sales.csv"] = csv_bytes(sales_raw)
    completed = [s for s in sales if s["status"] == "completed"]

    movements = []

    def movement(day, product, kind, units, reference):
        movements.append(
            {
                "movement_id": f"M{len(movements) + 1:04}",
                "date": day,
                "product_id": product,
                "kind": kind,
                "units_delta": str(units),
                "reference": reference,
                "warehouse": "MAIN",
            }
        )

    for product in products:
        movement("2026-01-01", product["product_id"], "opening", 100, "OPEN-2026")
    for month in range(1, 4):
        for product in products:
            movement(
                f"2026-{month:02}-01",
                product["product_id"],
                "receipt",
                20,
                f"PO-{month:02}-{product['product_id']}",
            )
    for sale in completed:
        movement(sale["date"], sale["product_id"], "sale", -int(sale["quantity"]), sale["sale_id"])
    for i, product in enumerate(products):
        movement(
            "2026-03-31", product["product_id"], "adjustment", -1 if i % 2 == 0 else 2, "COUNT-Q1"
        )
    movements_raw = movements + [dict(movements[20])]
    movements_raw.extend(
        [
            {**movements[0], "movement_id": "M0901", "product_id": "P999", "units_delta": "20"},
            {**movements[0], "movement_id": "M0902", "units_delta": ""},
        ]
    )
    files["inventory_movements.csv"] = csv_bytes(movements_raw)

    expense_categories = [
        "Rent",
        "Utilities",
        "Marketing",
        "Shipping",
        "Software",
        "Insurance",
        "Travel",
        "Office supplies",
    ]
    amounts = ["800.00", "95.50", "120.00", "28.75", "39.00", "65.00", "42.50", "18.25"]
    expenses = []
    for i in range(48):
        month, offset = divmod(i, 16)
        expenses.append(
            {
                "expense_id": f"E{i + 1:04}",
                "date": date(2026, month + 1, offset + 1).isoformat(),
                "month": f"2026-{month + 1:02}",
                "category": expense_categories[i % 8],
                "vendor": f"Fictional Vendor {i % 8 + 1}",
                "amount": money(Decimal(amounts[i % 8]) + Decimal(month * 2)),
                "payment_status": "unpaid" if i % 8 == 7 else "paid",
                "currency": "USD",
                "receipt_reference": f"R{i + 1:04}",
            }
        )
    expenses_raw = expenses + [dict(expenses[4])]
    expenses_raw.extend(
        [
            {**expenses[0], "expense_id": "E0901", "amount": ""},
            {**expenses[0], "expense_id": "E0902", "date": "2026-13-01"},
            {**expenses[0], "expense_id": "E0903", "amount": "-25.00"},
        ]
    )
    files["expenses.csv"] = csv_bytes(expenses_raw)

    customer_ids = [c["customer_id"] for c in customers]
    product_ids = [p["product_id"] for p in products]
    rules = {
        "customers": [
            rule("required", "customer_id"),
            rule("unique", "customer_id"),
            rule("required", "email", severity="warning"),
            rule("allowed", "region", values=["NORTH", "SOUTH", "EAST", "WEST"]),
            rule("duplicate_rows", severity="warning"),
        ],
        "products": [
            rule("unique", "product_id"),
            rule("range", "unit_price", minimum="0"),
            rule("range", "unit_cost", minimum="0"),
            rule("compare", "unit_cost", other_column="unit_price", operator="le"),
            rule("allowed", "category", values=["Office", "Workshop", "Pantry", "Packaging"]),
            rule("duplicate_rows", severity="warning"),
        ],
        "sales": [
            rule("unique", "sale_id"),
            rule("required", "quantity"),
            rule("range", "quantity", minimum="1"),
            rule("date", "date"),
            rule("required", "customer_id"),
            rule("allowed", "customer_id", values=customer_ids),
            rule("allowed", "product_id", values=product_ids),
            rule("allowed", "status", values=["completed", "cancelled"]),
            rule("duplicate_rows", severity="warning"),
        ],
        "inventory_movements": [
            rule("unique", "movement_id"),
            rule("required", "units_delta"),
            rule("numeric", "units_delta"),
            rule("allowed", "product_id", values=product_ids),
            rule("date", "date"),
            rule("duplicate_rows", severity="warning"),
        ],
        "expenses": [
            rule("unique", "expense_id"),
            rule("required", "amount"),
            rule("range", "amount", minimum="0"),
            rule("date", "date"),
            rule("allowed", "currency", values=["USD"]),
            rule("duplicate_rows", severity="warning"),
        ],
    }
    pipelines = {
        "customers": [
            {"op": "deduplicate"},
            {"op": "normalize", "columns": ["region", "email"], "mode": "strip"},
            {"op": "normalize", "columns": ["region"], "mode": "upper"},
            {"op": "normalize", "columns": ["email"], "mode": "lower"},
        ],
        "products": [
            {"op": "deduplicate"},
            {"op": "normalize", "columns": ["category"], "mode": "strip"},
        ],
        "sales": [
            {"op": "deduplicate"},
            {"op": "convert", "column": "date", "type": "date", "on_error": "null"},
            {"op": "missing", "columns": ["quantity", "date", "customer_id"], "strategy": "drop"},
            {"op": "filter", "column": "quantity", "operator": "ge", "value": "1", "numeric": True},
            {"op": "filter", "column": "customer_id", "operator": "ne", "value": "C999"},
            {"op": "filter", "column": "status", "operator": "eq", "value": "completed"},
            {"op": "convert", "column": "quantity", "type": "integer"},
            {
                "op": "calculate",
                "column": "net_revenue",
                "expression": "quantity * unit_price - discount_amount",
            },
            {"op": "calculate", "column": "cogs", "expression": "quantity * unit_cost"},
            {"op": "calculate", "column": "gross_profit", "expression": "net_revenue - cogs"},
        ],
        "inventory_movements": [
            {"op": "deduplicate"},
            {"op": "missing", "columns": ["units_delta"], "strategy": "drop"},
            {"op": "filter", "column": "product_id", "operator": "ne", "value": "P999"},
            {"op": "convert", "column": "units_delta", "type": "integer"},
            {"op": "sort", "columns": ["date", "movement_id"]},
        ],
        "expenses": [
            {"op": "deduplicate"},
            {"op": "convert", "column": "date", "type": "date", "on_error": "null"},
            {"op": "missing", "columns": ["amount", "date"], "strategy": "drop"},
            {"op": "filter", "column": "amount", "operator": "ge", "value": "0", "numeric": True},
            {"op": "convert", "column": "amount", "type": "decimal"},
        ],
    }
    reports = {
        "customers": {"group_by": ["region"], "metrics": [metric("count", None, "customers")]},
        "products": {
            "group_by": ["category"],
            "metrics": [
                metric("count", None, "products"),
                metric("avg", "unit_price", "average_price"),
            ],
        },
        "sales": {
            "group_by": ["month"],
            "metrics": [
                metric("count", None, "lines"),
                metric("sum", "quantity", "units"),
                metric("sum", "net_revenue", "revenue"),
                metric("sum", "cogs", "cogs"),
                metric("sum", "gross_profit", "gross_profit"),
            ],
        },
        "inventory_movements": {
            "group_by": ["product_id"],
            "metrics": [metric("sum", "units_delta", "closing_units")],
        },
        "expenses": {
            "group_by": ["month"],
            "metrics": [metric("count", None, "entries"), metric("sum", "amount", "expenses")],
        },
    }
    for name in rules:
        files[f"rules/{name}.json"] = json_bytes({"rules": rules[name]})
        files[f"pipelines/{name}.json"] = json_bytes({"steps": pipelines[name]})
        files[f"reports/{name}.json"] = json_bytes(reports[name])
    files["reports/sales_by_category.json"] = json_bytes(
        {**reports["sales"], "group_by": ["category"]}
    )
    files["pipelines/paid_expenses.json"] = json_bytes(
        {"steps": [{"op": "filter", "column": "payment_status", "operator": "eq", "value": "paid"}]}
    )
    files["reports/paid_expenses.json"] = json_bytes(
        {"group_by": ["month"], "metrics": [metric("sum", "amount", "paid_expenses")]}
    )
    files["pipelines/inventory_balances.json"] = json_bytes(
        {"steps": [{"op": "aggregate", **reports["inventory_movements"]}]}
    )

    # Independent, standard-library arithmetic from the valid source records.
    monthly = defaultdict(
        lambda: {
            "lines": 0,
            "units": 0,
            "revenue": Decimal(0),
            "cogs": Decimal(0),
            "expenses": Decimal(0),
            "paid_expenses": Decimal(0),
        }
    )
    category_revenue = defaultdict(Decimal)
    for sale in completed:
        row = monthly[sale["month"]]
        quantity = int(sale["quantity"])
        net = quantity * Decimal(sale["unit_price"]) - Decimal(sale["discount_amount"])
        row["lines"] += 1
        row["units"] += quantity
        row["revenue"] += net
        row["cogs"] += quantity * Decimal(sale["unit_cost"])
        category_revenue[sale["category"]] += net
    for expense in expenses:
        row = monthly[expense["month"]]
        row["expenses"] += Decimal(expense["amount"])
        if expense["payment_status"] == "paid":
            row["paid_expenses"] += Decimal(expense["amount"])
    expected_months = []
    for month, row in sorted(monthly.items()):
        row["gross_profit"] = row["revenue"] - row["cogs"]
        row["operating_result"] = row["gross_profit"] - row["expenses"]
        expected_months.append(
            {
                "month": month,
                **{k: money(v) if isinstance(v, Decimal) else v for k, v in row.items()},
            }
        )
    balances = defaultdict(int)
    for entry in movements:
        balances[entry["product_id"]] += int(entry["units_delta"])
    raw_counts = {
        "customers": len(customers_raw),
        "products": len(products_raw),
        "sales": len(sales_raw),
        "inventory_movements": len(movements_raw),
        "expenses": len(expenses_raw),
    }
    clean_counts = {
        "customers": len(customers),
        "products": len(products),
        "sales": len(completed),
        "inventory_movements": len(movements),
        "expenses": len(expenses),
    }
    expected = {
        "raw_rows": raw_counts,
        "clean_rows": clean_counts,
        "validation_issues": {
            "customers": 4,
            "products": 3,
            "sales": 7,
            "inventory_movements": 4,
            "expenses": 5,
        },
        "monthly": expected_months,
        "category_revenue": {k: money(v) for k, v in sorted(category_revenue.items())},
        "closing_inventory": dict(sorted(balances.items())),
        "totals": {
            k: money(sum(Decimal(row[k]) for row in expected_months))
            for k in [
                "revenue",
                "cogs",
                "gross_profit",
                "expenses",
                "paid_expenses",
                "operating_result",
            ]
        },
    }
    files["expected.json"] = json_bytes(expected)
    files["manifest.json"] = json_bytes(
        {
            "business": "Juniper Supply (entirely fictional)",
            "period": "2026-01-01 through 2026-03-31",
            "currency": "USD",
            "datasets": [
                {
                    "name": name,
                    "file": f"{name}.{'json' if name in {'customers', 'products'} else 'csv'}",
                }
                for name in rules
            ],
        }
    )
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--check", action="store_true", help="Check committed files without modifying them."
    )
    mode.add_argument(
        "--write",
        action="store_true",
        help="Regenerate only the business bundle's known fixture files.",
    )
    args = parser.parse_args()
    for relative, data in generated_files().items():
        path = BUNDLE / relative
        if args.write:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        elif not path.is_file() or path.read_bytes() != data:
            parser.exit(
                1, f"Example is missing or differs from deterministic generator: {relative}\n"
            )
    print(
        f"{'Generated' if args.write else 'Verified'} {len(generated_files())} deterministic example files."
    )


if __name__ == "__main__":
    main()
