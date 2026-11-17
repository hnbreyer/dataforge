"""Optional business fixtures: safety, independent accounting, and actual services."""

import csv
import io
import json
import runpy
import socket
import subprocess
import sys
from collections import defaultdict
from decimal import Decimal
from pathlib import Path

import pytest

from dataforge.config import Settings
from dataforge.errors import Conflict
from dataforge.workspace import Workspace

ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "examples" / "small_business"
SCRIPT = ROOT / "scripts" / "import_business_examples.py"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def csv_rows(name):
    with (BUNDLE / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@pytest.fixture(scope="module")
def build():
    return runpy.run_path(str(SCRIPT))["build_workspace"]


@pytest.fixture(scope="module")
def business(tmp_path_factory, build):
    home = tmp_path_factory.mktemp("business-parent") / "workspace"
    result = build(home)
    workspace = Workspace(Settings(home=home))
    yield workspace, result
    workspace.close()


def stored_rows(workspace, name):
    # Exercise public export without a preview page's 200-record cap.
    return json.loads(workspace.datasets.export(name, "json"))


def test_business_imports_and_saved_workflows(business):
    workspace, result = business
    expected = read_json(BUNDLE / "expected.json")
    assert {k: d["row_count"] for k, d in result["raw"].items()} == expected["raw_rows"]
    assert {k: d["row_count"] for k, d in result["clean"].items()} == expected["clean_rows"]
    assert sum(expected["raw_rows"].values()) == 423
    assert workspace.datasets.list()["total"] == 12
    assert workspace.pipelines.list()["total"] == 7
    assert workspace.reports.list()["total"] == 7
    assert workspace.validation.list()["total"] == 10
    assert workspace.definitions.list("pipeline")["total"] == 7
    assert workspace.definitions.list("validation")["total"] == 5
    assert workspace.definitions.list("report")["total"] == 7
    assert all(j["status"] == "succeeded" for j in result["jobs"].values())
    assert result["derived"]["paid_expenses"]["row_count"] == 42
    assert result["derived"]["inventory_balances"]["row_count"] == 12
    assert (
        read_json(workspace.settings.home / "business-example.json")["reports"] == result["reports"]
    )


@pytest.mark.parametrize(
    "name", ["customers", "products", "sales", "inventory_movements", "expenses"]
)
def test_raw_source_preservation_and_quality_issues(business, name):
    workspace, result = business
    manifest = read_json(BUNDLE / "manifest.json")
    source = next(d["file"] for d in manifest["datasets"] if d["name"] == name)
    assert workspace.datasets.source(result["raw"][name]["id"]) == (BUNDLE / source).read_bytes()
    raw_run, clean_run = result["validations"][name].values()
    assert raw_run["issue_count"] == read_json(BUNDLE / "expected.json")["validation_issues"][name]
    assert not raw_run["passed"]
    assert clean_run["passed"]
    assert clean_run["issue_count"] == (1 if name == "customers" else 0)
    assert result["clean"][name]["parent_id"] == result["raw"][name]["id"]


def test_intentional_sales_issues_match_documented_records(business):
    workspace, result = business
    run = result["validations"]["sales"]["raw"]
    issues = workspace.validation.get(run["id"])["issues"]["items"]
    assert {(i["row"], i["rule"].split(":")[1]) for i in issues} == {
        (145, "unique"),
        (146, "required"),
        (147, "date"),
        (148, "allowed"),
        (149, "range"),
        (150, "required"),
        (145, "duplicate_rows"),
    }


def test_related_clean_data_and_inventory_reconciliation(business):
    workspace, _ = business
    customers = stored_rows(workspace, "business_customers_clean")
    products = stored_rows(workspace, "business_products_clean")
    sales = stored_rows(workspace, "business_sales_clean")
    inventory = stored_rows(workspace, "business_inventory_movements_clean")
    product_lookup = {p["product_id"]: p for p in products}
    customer_ids = {c["customer_id"] for c in customers}
    sale_lookup = {s["sale_id"]: s for s in sales}
    assert len(sale_lookup) == len(sales) == 120
    for sale in sales:
        assert sale["customer_id"] in customer_ids
        product = product_lookup[sale["product_id"]]
        assert sale["unit_price"] == product["unit_price"]
        assert sale["unit_cost"] == product["unit_cost"]
        assert sale["category"] == product["category"]
    stock_out = defaultdict(int)
    for movement in inventory:
        assert movement["product_id"] in product_lookup
        if movement["kind"] == "sale":
            sale = sale_lookup[movement["reference"]]
            assert movement["product_id"] == sale["product_id"]
            assert movement["date"] == sale["date"]
            assert movement["units_delta"] == -sale["quantity"]
            stock_out[movement["reference"]] += 1
    assert dict(stock_out) == dict.fromkeys(sale_lookup, 1)
    assert sum(s["quantity"] for s in sales) == 360
    assert sum(int(m["units_delta"]) for m in inventory) == 1566


def test_monthly_results_match_independent_decimal_accounting(business):
    workspace, result = business
    expected = read_json(BUNDLE / "expected.json")
    monthly = defaultdict(lambda: defaultdict(Decimal))
    seen = set()
    for sale in csv_rows("sales.csv"):
        identifier = sale["sale_id"]
        if identifier in seen or identifier.startswith("S09"):
            continue
        seen.add(identifier)
        if sale["status"] != "completed":
            continue
        units = Decimal(sale["quantity"])
        group = monthly[sale["date"][:7]]
        group["lines"] += 1
        group["units"] += units
        group["revenue"] += units * Decimal(sale["unit_price"]) - Decimal(sale["discount_amount"])
        group["cogs"] += units * Decimal(sale["unit_cost"])
    seen = set()
    for expense in csv_rows("expenses.csv"):
        identifier = expense["expense_id"]
        if identifier in seen or identifier.startswith("E09"):
            continue
        seen.add(identifier)
        group = monthly[expense["date"][:7]]
        group["expenses"] += Decimal(expense["amount"])
        if expense["payment_status"] == "paid":
            group["paid_expenses"] += Decimal(expense["amount"])
    for row in expected["monthly"]:
        month = row["month"]
        group = monthly[month]
        group["gross_profit"] = group["revenue"] - group["cogs"]
        group["operating_result"] = group["gross_profit"] - group["expenses"]
        assert {k: Decimal(str(v)) for k, v in row.items() if k != "month"} == dict(group)
        sales_report = next(
            g for g in result["reports"]["sales"]["result"]["groups"] if g["month"] == month
        )
        for key in ["lines", "units", "revenue", "cogs", "gross_profit"]:
            assert Decimal(str(sales_report[key])) == group[key]
        expenses_report = next(
            g for g in result["reports"]["expenses"]["result"]["groups"] if g["month"] == month
        )
        assert Decimal(expenses_report["expenses"]) == group["expenses"]
        paid_report = next(
            g for g in result["reports"]["paid_expenses"]["result"]["groups"] if g["month"] == month
        )
        assert Decimal(paid_report["paid_expenses"]) == group["paid_expenses"]
    # Independently fixed acceptance totals, so changing fixtures/expectations
    # together cannot silently change the documented business scenario.
    totals = expected["totals"]
    assert totals == {
        "revenue": "3486.25",
        "cogs": "1703.65",
        "gross_profit": "1782.60",
        "expenses": "7350.00",
        "paid_expenses": "7228.50",
        "operating_result": "-5567.40",
    }
    for key in totals:
        assert sum(group[key] for group in monthly.values()) == Decimal(totals[key])
    assert workspace.datasets.get("business_sales_raw")["row_count"] == 150


def test_category_inventory_and_customer_reports(business):
    workspace, result = business
    expected = read_json(BUNDLE / "expected.json")
    revenue = {
        r["category"]: r["revenue"]
        for r in result["reports"]["sales_by_category"]["result"]["groups"]
    }
    assert revenue == expected["category_revenue"]
    balances = {
        r["product_id"]: int(r["closing_units"])
        for r in stored_rows(workspace, "business_inventory_balances")
    }
    assert balances == expected["closing_inventory"]
    raw_balance = defaultdict(int)
    for movement in csv_rows("inventory_movements.csv")[:180]:
        raw_balance[movement["product_id"]] += int(movement["units_delta"])
    assert balances == dict(raw_balance)
    customers = {
        r["region"]: r["customers"] for r in result["reports"]["customers"]["result"]["groups"]
    }
    assert customers == {"EAST": 6, "NORTH": 6, "SOUTH": 6, "WEST": 6}
    products = result["reports"]["products"]["result"]["groups"]
    assert all(r["products"] == 3 for r in products)


def test_business_report_csv_and_json_exports(business):
    workspace, result = business
    report_id = result["reports"]["sales"]["id"]
    payload = json.loads(workspace.reports.export(report_id, "json"))
    csv_payload = workspace.reports.export(report_id, "csv").decode()
    rows = list(csv.DictReader(io.StringIO(csv_payload)))
    assert len(rows) == 3
    assert sum(Decimal(r["revenue"]) for r in rows) == Decimal("3486.25")
    assert payload["result"]["row_count"] == 120
    assert payload["dataset_id"] == result["clean"]["sales"]["id"]


@pytest.mark.parametrize("kind", ["directory", "file", "workspace", "symlink", "broken_symlink"])
def test_existing_targets_are_never_modified(tmp_path, build, kind):
    target = tmp_path / "existing"
    actual = tmp_path / "actual"
    if kind == "file":
        target.write_bytes(b"user data")
    elif kind in {"symlink", "broken_symlink"}:
        if kind == "symlink":
            actual.mkdir()
            (actual / "notes.txt").write_text("user data", encoding="utf-8")
        target.symlink_to(actual, target_is_directory=True)
    else:
        target.mkdir()
        if kind == "workspace":
            instance = Workspace(Settings(home=target))
            try:
                instance.initialize()
                instance.datasets.import_bytes(b"a\noriginal", "user.csv", "user")
            finally:
                instance.close()

    def snapshot():
        return {
            str(p.relative_to(tmp_path)): p.read_bytes()
            for p in tmp_path.rglob("*")
            if p.is_file() and not p.is_symlink()
        }

    before = snapshot()
    with pytest.raises(Conflict, match="existing path"):
        build(target)
    assert snapshot() == before
    assert target.exists() or target.is_symlink()


def test_default_environment_is_ignored_and_offline_build_is_repeatable(
    tmp_path, monkeypatch, build, business
):
    normal_home = tmp_path / "normal-user-home"
    normal_home.mkdir()
    marker = normal_home / "important.txt"
    marker.write_bytes(b"keep")
    monkeypatch.setenv("DATAFORGE_HOME", str(normal_home))

    def no_network(*args, **kwargs):
        raise AssertionError("Example workflow must run offline")

    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.chdir(tmp_path)
    second_result = build(Path("second-demo"))
    workspace, first_result = business
    assert marker.read_bytes() == b"keep"
    assert list(normal_home.iterdir()) == [marker]
    for name in first_result["reports"]:
        assert second_result["reports"][name]["result"] == first_result["reports"][name]["result"]
    for name in first_result["raw"]:
        assert second_result["raw"][name]["checksum"] == first_result["raw"][name]["checksum"]
        assert second_result["clean"][name]["checksum"] == first_result["clean"][name]["checksum"]
    assert workspace.datasets.get("business_sales_raw")["row_count"] == 150


def test_import_script_requires_explicit_home_and_refuses_rerun(tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT)], cwd=tmp_path, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 2 and "--home" in result.stderr
    home = tmp_path / "demo"
    command = [sys.executable, str(SCRIPT), "--home", str(home)]
    first = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=60)
    assert first.returncode == 0, first.stderr
    assert json.loads(first.stdout)["clean_rows"]["sales"] == 120
    before = (home / "dataforge.db").read_bytes()
    second = subprocess.run(command, cwd=tmp_path, capture_output=True, text=True, timeout=20)
    assert second.returncode == 1 and "Refusing existing path" in second.stderr
    assert (home / "dataforge.db").read_bytes() == before


def test_committed_examples_match_deterministic_standard_library_generator():
    generator = runpy.run_path(str(ROOT / "scripts" / "generate_business_examples.py"))[
        "generated_files"
    ]
    first, second = generator(), generator()
    assert first == second
    for relative, data in first.items():
        assert (BUNDLE / relative).read_bytes() == data, relative
