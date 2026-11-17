"""Regression coverage for eager annotations on Python 3.12 and 3.13."""

import subprocess
import sys
from typing import get_type_hints

from dataforge.services.datasets import DatasetService


def test_dataset_service_annotation_resolves_builtin_list():
    # The public list() method must not shadow the container in load()'s hint.
    assert get_type_hints(DatasetService.load)["return"] == tuple[list[str], list[dict]]


def test_public_interfaces_import_and_cli_help_without_workspace(tmp_path):
    source = "from dataforge.api import create_app; from dataforge.cli import app; from dataforge.workspace import Workspace"
    result = subprocess.run(
        [sys.executable, "-c", source], cwd=tmp_path, capture_output=True, text=True, timeout=20
    )
    assert result.returncode == 0, result.stderr
    result = subprocess.run(
        [sys.executable, "-m", "dataforge.cli", "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert "dataset" in result.stdout
    assert not (tmp_path / ".dataforge").exists()
