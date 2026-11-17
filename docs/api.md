# API reference and examples

The server provides `/api/v1`; live, offline schemas are at `/docs` and
`/openapi.json`. It is a local, unauthenticated, single-user API. Browser writes
must be same-origin; nonbrowser clients can use loopback directly. Headers include
content-type protection, a restrictive Content Security Policy, and same-origin
referrer policy. No cross-origin permissions are enabled.

| Method | Path (after `/api/v1`) | Purpose |
|---|---|---|
| GET | `/health` | Database-backed status and overview counts |
| GET | `/datasets` | Search with `search`, `offset`, `limit` |
| POST | `/imports` | Multipart `name` and `file`, returns dataset |
| GET | `/imports` | Import history, including failures |
| GET | `/datasets/{dataset}` | Metadata and ordered columns |
| GET | `/datasets/{dataset}/preview` | Paginated records, default 20, max 200 |
| GET | `/datasets/{dataset}/source` | Byte-identical original import |
| GET | `/datasets/{dataset}/export` | `format=csv\|json`, `spreadsheet_safe=false` |
| DELETE | `/datasets/{dataset}?confirm=true` | Confirmed, dependency-protected deletion |
| POST | `/datasets/{dataset}/validations` | Body: `config` or saved `definition` |
| GET | `/validations` | Paginated run history |
| GET | `/validations/{run}` | Run summary and paginated issues |
| POST | `/pipelines/run` | Body: dataset, output_name, config or definition |
| GET | `/jobs` | Paginated pipeline history |
| GET | `/jobs/{job}` | Full job and immutable configuration snapshot |
| POST | `/jobs/{job}/recover?confirm=true` | Explicitly mark interrupted work failed |
| POST | `/datasets/{dataset}/reports` | Optional body: config or definition |
| GET | `/reports` | Paginated generated reports |
| GET | `/reports/{report}` | Full stored profile and results |
| GET | `/reports/{report}/export` | `format=json\|csv`, `spreadsheet_safe=false` |
| POST | `/definitions/{kind}` | Body: name and config; immutable save |
| GET | `/definitions/{kind}` | Paginated reusable configurations |
| GET | `/definitions/{kind}/{reference}` | Definition by name or UUID |
| DELETE | `/history/{kind}/{id}?confirm=true` | Delete validation/job/report/import history |

Definition kinds: `validation`, `pipeline`, `report`. Dataset references are
exact names or UUIDs; UUID takes precedence. List responses use:

```json
{"items": [], "total": 0, "offset": 0, "limit": 50}
```

Offset is nonnegative; limits are 1–200. Pages sort newest-first with a stable
UUID tiebreaker. Validation issues sort in insertion order: rule, then record.
Each issue has `run_id`, and its run has `dataset_id`. Dates/times are UTC ISO
strings. Monetary and other decimal values are represented as JSON strings.

## Saved rule set

```bash
curl -H 'Content-Type: application/json' \
  -d '{"name":"required-amount","config":{"rules":[{"kind":"required","column":"amount"}]}}' \
  http://127.0.0.1:8000/api/v1/definitions/validation
curl -H 'Content-Type: application/json' \
  -d '{"definition":"required-amount"}' \
  http://127.0.0.1:8000/api/v1/datasets/sales/validations
```

The resulting run has `passed`, `issue_count`, dataset/definition UUIDs,
timestamps, and a configuration snapshot. Get issues by run UUID:

```bash
curl 'http://127.0.0.1:8000/api/v1/validations/RUN_UUID?offset=0&limit=50'
```

A failed data check still creates a run with HTTP 201 and `passed: false`.
Invalid rules, unknown columns, or exceeding the issue limit return 422 without
creating a partial validation run.

## Pipeline and report

```bash
curl -H 'Content-Type: application/json' \
  -d '{"dataset":"sales","output_name":"clean","config":{"steps":[{"op":"deduplicate"}]}}' \
  http://127.0.0.1:8000/api/v1/pipelines/run
curl -H 'Content-Type: application/json' \
  -d '{"config":{"group_by":["category"],"metrics":[{"op":"sum","column":"amount","name":"total"}]}}' \
  http://127.0.0.1:8000/api/v1/datasets/clean/reports
```

Job execution is synchronous. Its `status` is running, succeeded, or failed; a
successful result includes `output_id`. Runtime failures return an error with
the job UUID and remain visible in `/jobs`. A failed job has no output reference.
Configurations rejected before a job can be created have no job UUID.

Use a new dataset name to rerun; reusing a name conflicts instead of replacing
stored data. Recovery is explicit and revokes an old worker's ability to commit;
it does not kill a process. Successful/failed jobs cannot be recovered again.

## Exports and deletion

```bash
curl 'http://127.0.0.1:8000/api/v1/datasets/clean/export?format=csv&spreadsheet_safe=true'
curl 'http://127.0.0.1:8000/api/v1/reports/REPORT_UUID/export?format=json'
curl -X DELETE 'http://127.0.0.1:8000/api/v1/history/report/REPORT_UUID?confirm=true'
curl -X DELETE 'http://127.0.0.1:8000/api/v1/datasets/clean?confirm=true'
```

A source download preserves exact original bytes; transformed datasets point to
their parent and have no separate original-source download. Dependency errors
are HTTP 409; delete dependent history and derived data deliberately first.
Deletion never cascades into derived datasets or erases history implicitly.

Errors use `{"detail": "message"}` for business rules, or FastAPI's structured
`detail` list for request schema violations. File errors include record/column
context where available. Oversized HTTP bodies return 413 before decoding.
Invalid imports that reach the import service create failed import records;
HTTP transport/schema rejections do not, since no complete import is available.
