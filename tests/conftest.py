from pathlib import Path

import pytest

from dataforge.config import Settings
from dataforge.workspace import Workspace


@pytest.fixture
def workspace(tmp_path):
    instance = Workspace(Settings(home=tmp_path / "isolated"))
    instance.initialize()
    yield instance
    instance.close()


@pytest.fixture
def sales(workspace):
    return workspace.datasets.import_file(Path(__file__).parent / "fixtures" / "sales.csv", "sales")


@pytest.fixture
def anyio_backend():
    # AnyIO supplies pytest integration; no trio dependency is required.
    return "asyncio"
