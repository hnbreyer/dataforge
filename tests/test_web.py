from urllib.parse import urlparse

import httpx
import pytest

from dataforge.api import create_app
from dataforge.config import Settings

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client(tmp_path):
    app = create_app(Settings(home=tmp_path / "web"))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            yield client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/datasets",
        "/import",
        "/pipelines",
        "/reports",
        "/validations",
        "/definitions",
        "/definitions?kind=pipeline",
        "/imports",
        "/static/app.css",
    ],
)
async def test_empty_routes(client, path):
    response = await client.get(path)
    assert response.status_code == 200, response.text
    if path != "/static/app.css":
        assert "DataForge" in response.text
        assert "viewport" in response.text


async def test_dashboard_forms_complete_workflow(client):
    response = await client.post(
        "/import",
        data={"name": "sales"},
        files={"file": ("sales.csv", b"category,amount\nOffice,0.10\nOffice,0.20\n")},
    )
    assert response.status_code == 303
    detail = await client.get(response.headers["location"])
    assert detail.status_code == 200 and "0.10" in detail.text
    dataset_id = response.headers["location"].split("/")[-1]
    response = await client.post(
        f"/datasets/{dataset_id}/validate",
        data={"config": '{"rules":[{"kind":"required","column":"amount"}]}'},
    )
    assert response.status_code == 303
    assert "Passed" in (await client.get(response.headers["location"])).text
    response = await client.post(
        "/pipelines",
        data={
            "dataset": dataset_id,
            "output_name": "clean",
            "config": '{"steps":[{"op":"deduplicate"}]}',
        },
    )
    assert response.status_code == 303
    assert "succeeded" in (await client.get(response.headers["location"])).text
    response = await client.post(
        "/reports",
        data={
            "dataset": "clean",
            "config": '{"group_by":["category"],"metrics":[{"op":"sum","column":"amount","name":"total"}]}',
        },
    )
    assert response.status_code == 303
    report_page = await client.get(response.headers["location"])
    assert report_page.status_code == 200 and "0.30" in report_page.text
    for path in ["/", "/datasets", "/pipelines", "/reports", "/validations", "/imports"]:
        assert (await client.get(path)).status_code == 200


async def test_web_definitions_reuse_and_escaping(client):
    await client.post(
        "/import", data={"name": "<script>alert(1)</script>"}, files={"file": ("x.csv", b"a\n1")}
    )
    page = await client.get("/datasets")
    assert "&lt;script&gt;" in page.text and "<script>alert(1)</script>" not in page.text
    response = await client.post(
        "/definitions",
        data={
            "name": "ids",
            "kind": "validation",
            "config": '{"rules":[{"kind":"required","column":"a"}]}',
        },
    )
    assert response.status_code == 303
    assert "ids" in (await client.get(response.headers["location"])).text
    dataset_id = (await client.get("/api/v1/datasets")).json()["items"][0]["id"]
    response = await client.post(
        f"/datasets/{dataset_id}/validate", data={"definition": "ids", "config": ""}
    )
    assert response.status_code == 303


async def test_web_error_states_and_pagination(client):
    response = await client.get("/datasets/missing")
    assert response.status_code == 404 and "Unable to complete" in response.text
    response = await client.post("/reports", data={"dataset": "missing", "config": "{bad"})
    assert response.status_code == 422 and "valid JSON" in response.text
    for index in range(3):
        await client.post(
            "/import", data={"name": f"sales-{index}"}, files={"file": ("x.csv", b"a\n1")}
        )
    first = await client.get("/datasets?search=sales&limit=1")
    assert "Next →" in first.text and "search=sales" in first.text
    assert "offset=1" in first.text
    second = await client.get("/datasets?search=sales&limit=1&offset=1")
    assert "Previous" in second.text and "offset=2" in second.text


async def test_web_delete_requires_checked_confirmation(client):
    response = await client.post("/import", data={"name": "x"}, files={"file": ("x.csv", b"a\n1")})
    path = urlparse(response.headers["location"]).path
    assert (await client.post(path + "/delete")).status_code == 409
    assert (await client.post(path + "/delete", data={"confirm": "true"})).status_code == 303
