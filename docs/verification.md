# Baseline verification

Verified on 2026-11-17 with Python 3.14.2. The dependency versions are recorded in
`requirements-dev.lock`. All tests and manual workflows used temporary data;
there is no normal `.dataforge` directory in the project after verification.

| Check | Result |
|---|---|
| Editable project and development dependencies installed | Passed |
| `python -m pip check` | No broken requirements |
| Fresh Alembic upgrade, repeat upgrade, and downgrade/upgrade test | Passed |
| Migrated SQLite schema compared with SQLAlchemy metadata | No differences |
| `ruff check src tests scripts` | Passed |
| `ruff format --check src tests scripts` | 38 files already formatted |
| `pytest -q` | **156 passed in 8.92 seconds**, zero failures |
| `python -m compileall -q src` | Passed |
| `python scripts/verify_examples.py` | Passed |
| Noneditable wheel installation into a temporary target | Passed |
| Installed-package migration, import, report, templates, CSS checks | Passed |
| Actual Uvicorn startup on loopback | Passed |
| Live HTTP dashboard/API checks and full processing workflow | Passed |
| `git diff --check` | Passed |

## What the checks cover

Engine tests exercise strict CSV/JSON parsing, BOM, quoted/multiline fields,
duplicate keys/headers, flat-record restrictions, exact decimals, extreme-scale
numeric totals, inference, missing-value policy, every validation rule and
transformation operation, all aggregation metrics, deterministic ordering, numeric
conversion failure/null behavior, safe arithmetic, and malicious expression
rejection. Schema tests reject unknown operations, fields, columns, invalid
bounds, and incompatible configurations.

SQLite/service tests cover metadata, source checksums, byte preservation,
artifact integrity checks, literal search, pagination, saved-definition snapshots,
failed import history, pipeline success/failure, retries, grouped reporting,
CSV/JSON export, explicit deletion, foreign keys, dependency protection, and
transaction rollback. Injected failures after artifact writes and database flush
verify that partially inserted outputs and staged files are removed. Interrupted
job recovery revokes an active execution's ability to commit.

Typer tests exercise CLI initialization, import, list/show/preview, saved
pipeline execution, validation exit status and issue pages, reports, source and
result export, overwrite refusal, deletion confirmation, stderr errors, JSON
output, help, and custom workspace paths. All test workspaces are isolated by
pytest's `tmp_path`.

HTTPX tests exercise the actual ASGI lifespan, SQLite migrations, multipart
uploads, schema/error responses, full validation/pipeline/report/export workflows,
request size bounds including chunked bodies, dependency protection, jobs,
definitions, pagination, origin/host protection, and offline OpenAPI docs. Web
tests submit forms, follow redirects, verify populated/empty/error pages, escaping,
search pagination, and deletion. Browser layout was not visually inspected.

The live server check returned HTTP 200 for `/`, `/datasets`, `/import`,
`/validations`, `/pipelines`, `/reports`, `/definitions`, `/imports`, `/docs`,
`/openapi.json`, and `/api/v1/health`. It imported a real fixture, validated it,
created a deduplicated output, generated an exact-total report, downloaded CSV,
and rendered populated dataset/report pages. The verification server was stopped.

The separate CLI example script verified five source records, four validation
issues (three errors and one warning), three cleaned records, grouped line totals
of food **9.90** and office **40.40**, CSV export, and an unchanged source file.
It creates and removes its own temporary workspace.

## Reproduce

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts
.venv/bin/pytest -q
.venv/bin/python scripts/verify_examples.py
.venv/bin/python scripts/count_source.py
```

In the execution environment, the sandbox blocked network package installation,
loopback socket binding/requests, and asyncio worker-thread notifications. Those
checks were rerun with approved execution outside the sandbox and passed. Engine,
service, CLI, migration, formatting, and example checks also ran inside the
sandbox. These restrictions do not require application changes.

## Source size

`python scripts/count_source.py` reports:

| Area | Physical lines | Nonblank lines | Files |
|---|---:|---:|---:|
| Application Python, Jinja2, and CSS | 4,409 | 3,854 | 44 |
| Python tests | 1,210 | 1,015 | 7 |
| Verification/count scripts | 98 | 84 | 2 |
| **Total** | **5,717** | **4,953** | **53** |

This counts source and tests only. Dependencies, virtual environments, caches,
build artifacts, generated migration revisions, documentation, configuration,
lockfiles, and data fixtures are excluded. The frozen generated migration is
included in the application package but excluded from this count. The baseline
is smaller than the suggested 10,000–15,000-line range; functionality and tests
were implemented without expanding code to meet a size target.

## Remaining limits

There are no known test failures. This is a bounded, synchronous, single-user
baseline, rather than an out-of-core or distributed engine. Sources and output
artifacts are immutable through the services; external filesystem changes are
checked with hashes. SQLite and file writes cannot share a distributed atomic
commit, so hard termination can leave orphaned files for administrative cleanup.
Recovery of interrupted job status is explicit; processing is never automatically
retried. The supported domain is flat scalar datasets; joins, Excel workbooks,
currency units, timezone normalization, remote hosting, and multi-user operation
are outside this baseline. See the README for numerical and resource policies.
