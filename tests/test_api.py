"""Real ASGI lifecycle, HTTPX requests, and isolated SQLite/filesystem state."""

from pathlib import Path

import httpx
import pytest

from dataforge.api import create_app
from dataforge.config import Settings

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client(tmp_path):
    app = create_app(Settings(home=tmp_path / "http-workspace"))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client


async def upload(client, name="sales"):
    response = await client.post(
        "/api/v1/imports",
        data={"name": name},
        files={
            "file": (
                "sales.csv",
                (Path(__file__).parent / "fixtures" / "sales.csv").read_bytes(),
                "text/csv",
            )
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_api_complete_workflow(client):
    dataset = await upload(client)
    assert (await client.get("/api/v1/datasets")).json()["total"] == 1
    assert (await client.get(f"/api/v1/datasets/{dataset['id']}")).json()["name"] == "sales"
    preview = await client.get("/api/v1/datasets/sales/preview?offset=1&limit=2")
    assert preview.json()["items"][0]["id"] == "2"
    definition = await client.post(
        "/api/v1/definitions/validation",
        json={"name": "ids", "config": {"rules": [{"kind": "unique", "column": "id"}]}},
    )
    assert definition.status_code == 201
    run = await client.post("/api/v1/datasets/sales/validations", json={"definition": "ids"})
    assert run.status_code == 201 and run.json()["issue_count"] == 1
    issues = await client.get(f"/api/v1/validations/{run.json()['id']}")
    assert issues.json()["issues"]["items"][0]["row"] == 4
    job = await client.post(
        "/api/v1/pipelines/run",
        json={
            "dataset": "sales",
            "output_name": "clean",
            "config": {"steps": [{"op": "deduplicate"}]},
        },
    )
    assert job.status_code == 201 and job.json()["status"] == "succeeded"
    assert (await client.get(f"/api/v1/jobs/{job.json()['id']}")).json()["output_id"]
    report = await client.post(
        "/api/v1/datasets/clean/reports",
        json={
            "config": {
                "group_by": ["category"],
                "metrics": [{"op": "sum", "column": "amount", "name": "total"}],
            }
        },
    )
    assert report.status_code == 201
    assert report.json()["result"]["columns"]["amount"]["numeric"]["sum"] == "33.60"
    report_id = report.json()["id"]
    assert (await client.get(f"/api/v1/reports/{report_id}/export?format=csv")).text.startswith(
        "category,total\n"
    )
    assert (await client.get(f"/api/v1/reports/{report_id}/export")).json()["result"][
        "row_count"
    ] == 4
    exported = await client.get("/api/v1/datasets/clean/export?format=json")
    assert len(exported.json()) == 4
    assert "attachment" in exported.headers["content-disposition"]
    original = await client.get("/api/v1/datasets/sales/source")
    assert original.content == (Path(__file__).parent / "fixtures" / "sales.csv").read_bytes()
    assert (await client.get("/api/v1/health")).json()["summary"]["datasets"] == 2


@pytest.mark.parametrize(
    ("method", "path", "body", "status"),
    [
        ("get", "/api/v1/datasets/missing", None, 404),
        ("get", "/api/v1/datasets?limit=201", None, 422),
        ("get", "/api/v1/datasets?offset=-1", None, 422),
        ("get", "/api/v1/definitions/invalid", None, 422),
        ("post", "/api/v1/datasets/missing/validations", {"config": {"rules": []}}, 422),
        ("post", "/api/v1/datasets/missing/validations", {}, 422),
        (
            "post",
            "/api/v1/pipelines/run",
            {
                "dataset": "x",
                "output_name": "y",
                "config": {"steps": [{"op": "python", "code": "unsafe"}]},
            },
            422,
        ),
        ("post", "/api/v1/definitions/report", {"name": "x", "config": {"typo": 1}}, 422),
    ],
)
async def test_api_errors(client, method, path, body, status):
    response = await client.request(method, path, json=body)
    assert response.status_code == status
    assert "detail" in response.json()


async def test_failed_pipeline_history_and_no_partial_output(client):
    await upload(client)
    response = await client.post(
        "/api/v1/pipelines/run",
        json={
            "dataset": "sales",
            "output_name": "bad",
            "config": {
                "steps": [{"op": "calculate", "column": "invalid", "expression": "amount / 0"}]
            },
        },
    )
    assert response.status_code == 422
    jobs = (await client.get("/api/v1/jobs")).json()
    assert jobs["items"][0]["status"] == "failed"
    assert (await client.get("/api/v1/datasets")).json()["total"] == 1


async def test_api_duplicate_import_bad_import_and_deletion(client):
    dataset = await upload(client)
    duplicate = await client.post(
        "/api/v1/imports", data={"name": "sales"}, files={"file": ("x.csv", b"a\n1")}
    )
    assert duplicate.status_code == 409
    bad = await client.post(
        "/api/v1/imports", data={"name": "bad"}, files={"file": ("x.csv", b"a,b\n1")}
    )
    assert bad.status_code == 422
    assert (await client.get("/api/v1/imports")).json()["total"] == 3
    assert (await client.delete(f"/api/v1/datasets/{dataset['id']}")).status_code == 409
    assert (
        await client.delete(f"/api/v1/datasets/{dataset['id']}?confirm=true")
    ).status_code == 200


async def test_api_history_dependency_protection(client):
    await upload(client)
    report = (await client.post("/api/v1/datasets/sales/reports")).json()
    assert (await client.delete("/api/v1/datasets/sales?confirm=true")).status_code == 409
    assert (await client.delete(f"/api/v1/history/report/{report['id']}")).status_code == 409
    assert (
        await client.delete(f"/api/v1/history/report/{report['id']}?confirm=true")
    ).status_code == 200
    assert (await client.delete("/api/v1/datasets/sales?confirm=true")).status_code == 200


async def test_security_headers_host_and_cross_origin(client):
    assert (await client.get("/")).headers["x-content-type-options"] == "nosniff"
    assert (await client.get("/", headers={"host": "evil.example"})).status_code == 400
    assert (
        await client.post(
            "/api/v1/pipelines/run", headers={"origin": "https://evil.example"}, json={}
        )
    ).status_code == 403
    assert (
        await client.post("/reports", headers={"sec-fetch-site": "cross-site"}, data={})
    ).status_code == 403


async def test_body_limits_for_json_and_chunked_upload(tmp_path):
    app = create_app(Settings(home=tmp_path / "limits", max_file_bytes=10))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/imports",
                data={"name": "big"},
                files={"file": ("x.csv", b"a\n" + b"x" * 20)},
            )
            assert response.status_code == 422
            response = await client.post("/api/v1/definitions/report", content=b"x" * 1_000_001)
            assert response.status_code == 413

            async def chunks():
                yield b"x" * 40000
                yield b"x" * 40000

            response = await client.post("/api/v1/imports", content=chunks())
            assert response.status_code == 413


async def test_openapi_documents_request_and_response_schemas(client):
    response = await client.get("/openapi.json")
    spec = response.json()
    assert response.status_code == 200
    assert "/api/v1/pipelines/run" in spec["paths"]
    assert "DatasetResponse" in spec["components"]["schemas"]
    assert "PipelineConfig" in spec["components"]["schemas"]
    assert (await client.get("/docs")).status_code == 200


async def test_recover_completed_job_is_rejected(client):
    await upload(client)
    result = await client.post(
        "/api/v1/pipelines/run",
        json={
            "dataset": "sales",
            "output_name": "clean",
            "config": {"steps": [{"op": "deduplicate"}]},
        },
    )
    job_id = result.json()["id"]
    assert (await client.post(f"/api/v1/jobs/{job_id}/recover")).status_code == 409
    assert (await client.post(f"/api/v1/jobs/{job_id}/recover?confirm=true")).status_code == 409
    assert (await client.post("/api/v1/jobs/missing/recover?confirm=true")).status_code == 404


async def test_docs_work_without_external_assets(client):
    response = await client.get("/docs")
    assert "Schema definitions" in response.text
    assert "/api/v1/imports" in response.text
    assert "<script" not in response.text
    assert 'src="https://' not in response.text
