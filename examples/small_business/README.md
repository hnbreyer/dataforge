# Juniper Supply: a fictional small-business workspace

An entirely fictional supply shop selling office goods, workshop tools, pantry
items, and packaging. The fixed period is **1 January–31 March 2026**, in **USD**.
All businesses, suppliers, vendors, orders, and contacts are invented. Email
addresses use the reserved `example.test` domain. No real personal information,
external APIs, downloads, randomness, or system-clock input is involved.

## Create the optional workspace

From the repository, with DataForge installed:

```bash
python scripts/import_business_examples.py --home /tmp/juniper-dataforge-demo
# Windows or another location: choose any NEW, nonexistent directory.
dataforge --home /tmp/juniper-dataforge-demo serve
```

The script requires `--home` and **refuses every existing path**, including an
empty directory, a file, an existing DataForge workspace, and a symlink. It
ignores `DATAFORGE_HOME`. Do not run `dataforge init` on the target first: the
importer creates and migrates the new workspace itself. Running the command
a second time fails without modifying the first workspace. To repeat the example,
choose another new directory.

The importer uses the existing shared services. It imports all five raw datasets,
saves validation/pipeline/report definitions, validates raw records, creates five
clean outputs, validates those outputs, produces paid-expense and inventory-balance
datasets, and generates seven reports. It creates **12 datasets, 10 validation
runs, 7 jobs, and 7 reports**. `business-example.json` inside the new workspace
maps every dataset, run, job, and report to its UUID and exact configuration.
If building fails partway, only the newly reserved directory may contain partial
example work; it is left for inspection, never automatically deleted or reused.

Original samples in `examples/sales.csv`, `people.json`, and their associated
rule/pipeline/report files are unchanged. Application startup and `dataforge init`
do not load any example data. The example scripts run offline after installation.

## Dataset relationships and contents

| File | Raw records | Clean records | Key and purpose |
|---|---:|---:|---|
| `customers.json` | 25 | 24 | `customer_id`; region, segment, joined date, optional contact |
| `products.json` | 13 | 12 | `product_id`; category, prices, costs, reorder level, supplier |
| `sales.csv` | 150 | 120 | `sale_id`; 72 valid orders / 144 valid lines before cancelled lines are excluded |
| `inventory_movements.csv` | 183 | 180 | `movement_id`; opening stock, receipts, sales, stock-count adjustments |
| `expenses.csv` | 52 | 48 | `expense_id`; categories, amounts, paid/unpaid status, receipts |
| **Total source records** | **423** | | Every source record is retained in the raw dataset |

Clean dataset names are `business_customers_clean`, `business_products_clean`,
`business_sales_clean`, `business_inventory_movements_clean`, and
`business_expenses_clean`. Source names replace `_clean` with `_raw`.

Sales reference customer/product IDs, with prices, costs, and category copied
from the product catalogue as transaction snapshots. Two sales lines form each
order; status is per line, so an order can contain a cancelled line. The 144
valid source lines include **120 completed** and **24 cancelled** lines. Only
completed lines contribute to revenue, COGS, and sales inventory movements.
Sales dates cover the first 24 days of each month. All clean foreign references
resolve to the clean customer/product masters.

Inventory movements reference products; `kind=sale` also references the exact
completed `sale_id`, with the same date and the negative of its quantity. There
is exactly one such movement for every completed sales line. All stock is in
warehouse `MAIN`. The ledger includes 12 opening balances of 100 units, 36
receipts of 20 units, 120 sales movements, and 12 physical-count adjustments
(alternating -1 / +2). Closing stock is after the 31 March adjustments.

Expenses are operating expenses, separate from product COGS. Every month has 16
valid expense entries. Six quarter-wide office-supply entries are unpaid, leaving
**42 paid entries** in the extra `business_paid_expenses` dataset. Categories
include rent, utilities, marketing, shipping, software, insurance, travel, and
office supplies. Vendors are independent fictional suppliers, not customers.

DataForge has no join engine. Related IDs are checked by explicit `allowed` rule
sets, using the master IDs. Transaction snapshots support analysis without joins;
tests independently reconcile the related source records and inventory quantities.

## Intentional quality issues

Record numbers are one-based data records, excluding CSV headers. Rules report
all applicable issues, so a duplicate produces a uniqueness error and a separate
duplicate-row warning. Rules skip missing values unless paired with `required`.

| Dataset | Record / identifier | Intentional issue | Cleaning policy |
|---|---|---|---|
| Customers | 7 / `C007` | Missing email (warning) | Preserve null; never invent a contact |
| Customers | 11 / `C011` | Region `east ` | Strip and uppercase to `EAST` |
| Customers | 25 / `C003` | Exact duplicate of record 3 | Keep first occurrence |
| Customers | 6 / `C006` | Email case and surrounding spaces (normalization example) | Strip and lowercase |
| Products | 1 / `P001` | Category ` Office ` outside allowed set | Strip to `Office` |
| Products | 13 / `P004` | Exact duplicate of record 4 | Keep first occurrence |
| Sales | 145 / `S0008` | Exact duplicate of record 8 | Keep first occurrence |
| Sales | 146 / `S0901` | Missing quantity | Exclude from clean sales |
| Sales | 147 / `S0902` | Invalid date `2026-02-30` | Explicit convert-to-null, then exclude |
| Sales | 148 / `S0903` | Unknown customer `C999` | Exclude explicitly |
| Sales | 149 / `S0904` | Negative quantity `-2` | Require quantity >= 1 |
| Sales | 150 / `S0905` | Missing customer ID | Exclude from clean sales |
| Inventory | 181 / `M0021` | Exact duplicate of record 21 | Keep first occurrence |
| Inventory | 182 / `M0901` | Unknown product `P999` | Exclude explicitly |
| Inventory | 183 / `M0902` | Missing units delta | Exclude from clean ledger |
| Expenses | 49 / `E0005` | Exact duplicate of record 5 | Keep first occurrence |
| Expenses | 50 / `E0901` | Missing amount | Exclude from clean expenses |
| Expenses | 51 / `E0902` | Invalid date `2026-13-01` | Explicit convert-to-null, then exclude |
| Expenses | 52 / `E0903` | Negative amount `-25.00` | Require amount >= 0 |

Cancelled sales are valid business records, not validation failures. Removing
cancelled lines is a deliberate reporting scope choice. Negative inventory
movements are valid stock-outs, not errors. The category/contact whitespace
examples demonstrate normalization without pretending every cosmetic inconsistency
has a validator rule.

Expected raw issue counts: **customers 4, products 3, sales 7, inventory 4,
expenses 5**. All raw runs fail. After cleaning, all five runs pass; customers
still have **one warning** for the intentionally absent contact. Other clean
runs have zero issues. Original bytes and raw records always remain available.

Row reconciliation: customers 25 - 1 duplicate = 24; products 13 - 1 duplicate =
12; sales 150 - 1 duplicate - 5 invalid lines - 24 cancelled lines = 120;
inventory 183 - 1 duplicate - 2 invalid movements = 180; expenses 52 - 1 duplicate
- 3 invalid entries = 48.

## Independently verifiable results

Amounts are exact decimal USD, excluding tax, delivery revenue, refunds,
depreciation, and finance charges. A `quantity` is an integer number of catalogue
units (one pack/tin/etc. is one unit). Per completed sales line:

```text
net_revenue = quantity × unit_price − discount_amount
cogs = quantity × unit_cost
gross_profit = net_revenue − cogs
operating_result = gross_profit − all valid operating expenses
closing_units = opening + receipts − completed sale quantities + count adjustments
```

The sales source has a 1.00 line discount when its zero-based sequence number is
divisible by seven; other discounts are zero. All snapshot prices/costs exactly
match the catalogue. No financial calculation uses binary floating-point amounts.

| Month | Completed lines | Units | Revenue | COGS | Gross profit | Expenses | Paid expenses | Operating result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-01 | 40 | 120 | 1,153.50 | 564.85 | 588.65 | 2,418.00 | 2,381.50 | -1,829.35 |
| 2026-02 | 40 | 120 | 1,152.50 | 560.50 | 592.00 | 2,450.00 | 2,409.50 | -1,858.00 |
| 2026-03 | 40 | 120 | 1,180.25 | 578.30 | 601.95 | 2,482.00 | 2,437.50 | -1,880.05 |
| **Quarter** | **120** | **360** | **3,486.25** | **1,703.65** | **1,782.60** | **7,350.00** | **7,228.50** | **-5,567.40** |

The fictional shop intentionally runs at an operating loss in this example.
Unpaid operating expenses are **121.50**. Gross profit uses all completed sales,
and operating result uses all valid expenses, including unpaid entries; it is
not a cash-flow statement. The paid-expense report supplies a separate cash-outlay
view and does not include purchasing stock.

Revenue by category: **Office 849.50; Packaging 999.00; Pantry 809.50;
Workshop 828.25**. Customer regions have **6 customers each**; product categories
have **3 products each**. One clean customer email is missing.

Closing units by product:

| Product | Units | Product | Units | Product | Units |
|---|---:|---|---:|---|---:|
| P001 | 134 | P005 | 126 | P009 | 133 |
| P002 | 132 | P006 | 138 | P010 | 125 |
| P003 | 128 | P007 | 124 | P011 | 131 |
| P004 | 135 | P008 | 132 | P012 | 128 |

Total closing units: **1,566 = 1,200 opening + 720 receipts - 360 sales + 6 net
adjustments**. The `business_inventory_balances` derived dataset computes these
balances using the standard aggregation transformation.

Machine-readable acceptance results are in [expected.json](expected.json).
The standard-library generator computes them without importing DataForge engines.
Tests separately read the committed CSV files with `csv.DictReader` and `Decimal`,
exclude the documented duplicate/invalid IDs, and verify monthly and quarterly
results. Fixed acceptance totals in tests protect against changing both generated
inputs and expected values accidentally.

## Explore and rerun workflows

The importer saves definitions under `business_customers`, `business_products`,
`business_sales`, `business_inventory_movements`, and `business_expenses` for each
of the validation, pipeline, and report kinds. The extra pipeline definitions are
`business_paid_expenses` and `business_inventory_balances`; the extra report
definitions are `business_paid_expenses` and `business_sales_by_category`.

```bash
# Prefix each CLI command with the same explicit --home.
dataforge --home /tmp/juniper-dataforge-demo dataset list --search business_
dataforge --home /tmp/juniper-dataforge-demo validate list
dataforge --home /tmp/juniper-dataforge-demo pipeline list
dataforge --home /tmp/juniper-dataforge-demo report list

# Intentionally fails with exit 2 and creates another raw validation run.
dataforge --home /tmp/juniper-dataforge-demo validate run business_sales_raw --definition business_sales

# Reuse the original source and saved cleaning configuration with a NEW output name.
dataforge --home /tmp/juniper-dataforge-demo pipeline run \
  --dataset business_sales_raw --output-name sales-recomputed --definition business_sales
dataforge --home /tmp/juniper-dataforge-demo report generate sales-recomputed --definition business_sales

# The exact same configuration is available as a committed JSON file.
dataforge --home /tmp/juniper-dataforge-demo report generate business_sales_clean \
  --config examples/small_business/reports/sales_by_category.json
dataforge --home /tmp/juniper-dataforge-demo dataset export business_inventory_balances --format csv
```

The dashboard can preview sources/outputs, show validation records and job
history, browse reports, and run each saved definition. The REST API uses the
same dataset names and saved definition names; no example-specific API or
business logic was added to the backend.

## Determinism and maintenance

```bash
python scripts/generate_business_examples.py --check  # Verify committed fixtures; no writes
python scripts/generate_business_examples.py --write  # Deliberately regenerate this bundle
pytest tests/test_business_examples.py -q
```

The generator uses fixed dates, catalogue values, sequence formulas, and Decimal
arithmetic. `--write` touches only this bundle's generated data/config/expected
files. Data bytes and analytical results are deterministic. Workspace UUIDs,
execution timestamps, and the absolute workspace path vary normally between
imports and do not influence analytical outputs. Importing never runs the
generator and never modifies any repository fixture.
