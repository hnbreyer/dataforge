# DataForge

A local-first data processing and analytics workspace for small businesses and
analysts. Import CSV/JSON, validate records, run structured transformation
pipelines, and generate reproducible reports through a **CLI**, **REST API**, or
**server-rendered dashboard**. All three call the same Python services. There are
no cloud dependencies, database servers, frontend builds, or runtime network
requirements.

## Quick start

Requires Python **3.12+**. The baseline is verified on Python 3.14. Installation
requires package-index access; all operations then work offline.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
dataforge init
dataforge dataset import examples/sales.csv --name sales
dataforge dataset preview sales
dataforge serve
```

On Windows, activate with `.venv\Scripts\Activate.ps1`; run commands directly
instead of the optional Unix Makefile. Open **http://127.0.0.1:8000** for the
dashboard, **/docs** for an offline API reference, or **/openapi.json** for the
FastAPI-generated OpenAPI schema. The service binds to loopback by default.

`dataforge init` applies Alembic migrations without starting a server. `serve`
also applies pending migrations before accepting requests. Other CLI commands
require an initialized workspace. No example data is imported automatically.

## Architecture

```text
CLI (Typer) ─────────┐
REST (FastAPI) ──────┼─> shared services ─> pure engines
Web (Jinja2) ────────┘         │                 │
                              ├─ SQLite metadata / SQLAlchemy
                              └─ immutable source and JSONL artifacts
```

- `src/dataforge/models.py`, `db.py`, `migrations/`: normalized SQLAlchemy 2.x
  metadata and a frozen initial Alembic revision. Foreign keys are enforced on
  every database connection. Names, artifact kinds, and definition names have
  uniqueness constraints; references and listing fields are indexed.
- `engines/parsing.py`, `values.py`: strict parsing, column discovery, missing
  value policy, type inference, canonical JSON scalars, and Decimal handling.
- `engines/validation.py`: deterministic rules and structured record issues.
- `engines/transformation.py`, `expressions.py`: validated pipelines and a small
  arithmetic interpreter; no `eval`, Python execution, calls, or attribute access.
- `engines/analytics.py`: actual-data profiling, frequencies, and grouped metrics.
- `services/`: dataset lifecycle, immutable reusable definitions, validation,
  pipeline jobs, persisted reports, and exports. Transaction boundaries and
  dependency checks live here, not in interface handlers.
- `workspace.py`: composition root; one workspace directory owns its database
  and storage. Every interface can use the same directory.
- `cli.py`, `api.py`, `web/`: thin interface adapters, typed HTTP schemas, offline
  templates and CSS, and bounded HTTP bodies. No JavaScript is required.
- `tests/`: isolated engine, SQLite, migration, CLI, HTTPX API, dashboard,
  rollback, integrity, and export tests.

Each dataset has an immutable canonical artifact and ordered column metadata.
Imports additionally preserve the exact uploaded file and SHA-256 checksum.
Transformed datasets have a parent reference. Import records survive dataset
deletion; validation runs and issues, pipeline jobs, saved definitions, reports,
and report outputs retain provenance. Reports and jobs snapshot the configuration
used, even when launched through a saved definition.

## Configuration and data policy

By default, data lives in `.dataforge/` under the current directory:

```text
.dataforge/
  dataforge.db
  artifacts/
    source/<uuid>.bin       # exact original bytes
    processed/<uuid>.jsonl  # canonical immutable records
```

Use a global option before the command or set environment variables:

```bash
dataforge --home /path/to/workspace init
export DATAFORGE_HOME=/path/to/workspace
dataforge --json dataset list --limit 10 --offset 0
```

`.env.example` documents variables. Environment files are **not loaded
automatically**; export values in your shell. Defaults are 25 MiB per input file,
100,000 rows, and 2,000,000 cells. Column count is capped at 1,000, column names
at 200 characters, and configurations at 100 rules or steps. Validation rejects
runs exceeding 50,000 issues, without persisting a truncated result. HTTP JSON
and configuration bodies are capped at 1 MB; multipart uploads allow the file
limit plus 64 KiB of envelope overhead. Limits reject work explicitly.

Imports accept UTF-8 (including BOM), CSV headers, and JSON arrays of flat
objects. JSON column order is first appearance across all records. CSV headers
must be nonblank and unique. Header-only CSV is supported; empty JSON arrays
are rejected because they provide no column schema. Nested JSON, duplicate JSON
keys, non-finite numbers, invalid encodings, ragged CSV, and malformed quotations
reject the entire import. Python's standard CSV field limit (typically 128 KiB)
also applies. No rows are silently skipped.

Blank/whitespace-only strings, absent JSON properties, and JSON null become
`null`. Literal strings such as `NA`, `null`, and `N/A` remain data. Present text
is preserved until explicitly normalized. Duplicate records remain in the
source and canonical import; `deduplicate` is an explicit transformation.

CSV values remain strings; JSON numeric tokens become exact decimal strings,
including their decimal scale. JSON booleans remain booleans. Type inference
labels columns without coercing values. Supported numbers have at most 38
significant digits and adjusted exponent within ±38. Totals use Decimal with
160-digit working precision (sufficient for bounded datasets); averages and
expression division use an explicit **28-significant-digit** rounding policy
(half-even). Other arithmetic is exact within supported bounds or fails. Exported
decimals are strings in JSON to avoid downstream binary float conversion.

Validation record numbers are one-based **data records**, excluding the CSV
header; a quoted multiline cell still occupies one record. Every issue identifies
the rule index/type, column, record, severity, and description; the run identifies
the dataset. Missing values are checked by `required`; other field rules skip
missing values. Warnings are recorded but do not make a run fail. Equality,
uniqueness, grouping, and allowed sets are scalar-type sensitive. Cross-column
comparisons use Decimal when both operands are numeric, otherwise textual order.

## CLI workflows

Every group has `--help`. Results are pretty JSON by default; global `--json`
emits compact JSON. Errors go to stderr. Exit codes: **0** success, **1** business
or I/O error, **2** a failed validation run (also Typer's argument-error code).
Commands never prompt, including deletion. Dataset references accept a UUID or
an exact case-sensitive name; UUID matches take precedence.

```bash
dataforge dataset list --search sales --limit 20 --offset 0
dataforge dataset show sales
dataforge dataset preview sales --limit 5
dataforge history imports

# This sample intentionally fails validation: expect exit 2.
dataforge validate run sales --rules examples/sales-rules.json
dataforge validate list
dataforge validate show RUN_UUID --limit 20

# Source is unchanged; create a separately named output.
dataforge pipeline run --dataset sales --output-name clean-sales \
  --config examples/clean-sales.json
dataforge pipeline list
dataforge pipeline show JOB_UUID

dataforge report generate clean-sales --config examples/sales-report.json
dataforge report generate sales --group-by category --sum amount
dataforge report list
dataforge report show REPORT_UUID

dataforge dataset export clean-sales --format csv --output exports/clean-sales.csv
dataforge dataset export clean-sales --format json
dataforge report export REPORT_UUID --format json --output exports/report.json
dataforge report export REPORT_UUID --format csv
dataforge dataset source sales exports/original-sales.csv
```

The example import contains five records. Validation reports three errors and one
warning. Cleaning removes the duplicate and the missing-amount row, leaving three
records. The report of `line_total` produces **food = 9.90** and **office = 40.40**.
See [fixture expectations](tests/fixtures/README.md).

Saved definitions are immutable and versioned by new names:

```bash
dataforge definition save validation sales-v1 examples/sales-rules.json
dataforge definition save pipeline clean-v1 examples/clean-sales.json
dataforge definition save report totals-v1 examples/sales-report.json
dataforge definition list pipeline
dataforge definition show pipeline clean-v1
dataforge validate run sales --definition sales-v1
dataforge pipeline run --dataset sales --output-name clean-v2 --definition clean-v1
dataforge report generate clean-v2 --definition totals-v1
```

Exports to files are atomic and **never overwrite existing files**, including
original inputs. Default CSV preserves values literally. For spreadsheets,
`--spreadsheet-safe` prefixes formula-like strings with an apostrophe; this is an
explicit opt-in because it changes exported values. JSON report exports include
the full profile and provenance; CSV report exports contain the grouped summary.

Dataset deletion requires `--yes`, and fails while derived datasets, validation
runs, jobs, or reports reference it. Remove history deliberately, then derived
datasets, then the source. This also removes the corresponding audit evidence.

```bash
dataforge history delete validation RUN_UUID --yes
dataforge history delete report REPORT_UUID --yes
dataforge history delete job JOB_UUID --yes
dataforge dataset delete clean-sales --yes
dataforge dataset delete sales --yes
```

## REST API

Run `dataforge serve`. No server is needed for CLI workflows. The versioned API
uses multipart imports, JSON configurations, explicit response schemas, bounded
pagination (`offset >= 0`, `1 <= limit <= 200`), and standard HTTP status codes:
201 creation, 404 missing references, 409 conflicts/dependencies, 413 oversized
requests, and 422 invalid configurations/data. Error bodies contain `detail`.

```bash
curl -F 'name=sales' -F 'file=@examples/sales.csv' http://127.0.0.1:8000/api/v1/imports
curl 'http://127.0.0.1:8000/api/v1/datasets?search=sales&limit=20'
curl http://127.0.0.1:8000/api/v1/datasets/sales/preview
curl -H 'Content-Type: application/json' \
  -d '{"config":{"rules":[{"kind":"required","column":"amount"}]}}' \
  http://127.0.0.1:8000/api/v1/datasets/sales/validations
curl -H 'Content-Type: application/json' \
  -d '{"dataset":"sales","output_name":"clean","config":{"steps":[{"op":"deduplicate"}]}}' \
  http://127.0.0.1:8000/api/v1/pipelines/run
curl -X POST http://127.0.0.1:8000/api/v1/datasets/clean/reports
curl 'http://127.0.0.1:8000/api/v1/datasets/clean/export?format=csv'
```

A failed validation is a successfully created run (`201`, `passed: false`), not
an HTTP failure. A failed pipeline returns `422` with its job UUID in `detail`;
`GET /api/v1/jobs` retains its configuration, error, and timestamps. Pipeline and
report requests execute synchronously; no external worker service is needed.

All endpoint families and request examples are in [docs/api.md](docs/api.md),
with live schemas at `/docs`. Dashboard pages support import, search, preview,
validation, pipeline execution, reports, exports, definition creation/reuse,
import failures, and confirmed dataset deletion. Dataset inputs accept any exact
name or UUID; suggestions show the most recent 200 datasets/definitions.

## Migrations, development, and tests

```bash
make install
make check                         # Ruff lint and format verification
make test                          # Complete isolated pytest suite
# Equivalent commands:
ruff check src tests scripts
ruff format --check src tests scripts
pytest
python scripts/verify_examples.py     # Real CLI commands in a temporary workspace

dataforge init                     # Idempotent upgrade for configured workspace
# Developer workflow for default .dataforge path (create it with init first):
alembic current
alembic revision --autogenerate -m 'Describe schema change'
alembic upgrade head
# Custom path; remember to supply the same URL to Alembic through Config or edit ini.
```

`dataforge init` respects `--home` / `DATAFORGE_HOME`; direct `alembic` commands
use `alembic.ini`, whose default URL is `.dataforge/dataforge.db`. Inspect generated
migrations, preserve existing data, and test upgrades. Never use downgrade on a
valuable workspace without a backup; the initial downgrade deletes all tables.
The frozen initial revision does not call ORM `create_all` and is included in
installed wheels. `requirements-dev.lock` records the verified environment; use
`pip install -r requirements-dev.lock` followed by `pip install -e . --no-deps`
when reproducing it on a compatible Python/platform.

Every test uses a pytest temporary directory or temporary `--home`. Tests do not
modify developer data. HTTPX tests run the real ASGI lifespan, migration, request
validation, service operations, and templates. Tests inject failures after flush
and artifact writes to verify rollback and cleanup; migration tests compare the
resulting schema to model metadata. See [docs/verification.md](docs/verification.md)
for the final baseline checks and source-line count.

## Reliability and limitations

This is a bounded, local, single-user application. It intentionally does not
include authentication, background queues, multi-user coordination, cloud storage,
or distributed processing. Bind to loopback; do not expose it directly to a public
network. Host validation permits localhost/loopback, and browser writes reject
foreign origins. Dashboard/API docs use only local CSS, no CDN or scripts.

Files are flushed and atomically renamed before metadata commit. An ordinary
failure cleans staged artifacts and rolls back metadata. A failed pipeline leaves
no partially committed output dataset. A process/power failure between filesystem
and database operations can leave unreferenced files; it cannot be made fully
atomic across SQLite and a filesystem. Back up the entire workspace with all
DataForge processes stopped, and avoid manually changing stored artifacts.
Checksums detect later artifact changes.

Processing loads a bounded dataset into memory, and metadata inference/profiling
makes additional passes. This is not an out-of-core engine; increase limits only
with sufficient memory. Preview reads/checks the canonical artifact before
slicing. HTTP bodies are bounded before multipart parsing but also occupy memory.
No silent sampling occurs. Large runs block the calling request/CLI; the server
uses worker threads for synchronous routes.

Job `running` is committed before execution. A killed process may leave a running
record; it is never automatically rerun (to avoid duplicate results). Re-run the
saved configuration under a fresh output name after confirming the old process
has stopped. Use `dataforge pipeline recover JOB_UUID --yes` (or
`POST /api/v1/jobs/JOB_UUID/recover?confirm=true`) to explicitly mark interrupted
work failed. Recovery revokes the old execution's permission to commit, so even
a still-active worker cannot publish a partial output afterward. It does not
terminate a worker process or restart work automatically.
Concurrent writes use SQLite's 30-second busy timeout and database constraints;
this is not a multi-writer scheduling system.

Normal errors clean temporary files, but abrupt termination may leave `.tmp-*`
artifacts; do not delete files until all processes stop and their database
references have been checked. Dataset deletion commits metadata first; an OS
cleanup failure may leave an unreferenced artifact rather than break live data.
A complete workspace backup preserves audit history and source data.

Dates require explicit formats for validation/conversion. Financial currencies,
timezones, spreadsheet workbook formats, nested JSON, joins, and arbitrary SQL or
Python transformations are outside this baseline. Decimal type conversion may
normalize formatting; source bytes remain available for exact reproduction.
