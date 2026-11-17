"""Immutable artifacts, checked paths, atomic replacement and failure cleanup."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from uuid import uuid4

from dataforge.config import Settings
from dataforge.engines.values import Row, stable
from dataforge.errors import InputError


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Storage:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.root = settings.home / "artifacts"

    def path(self, relative: str) -> Path:
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root.resolve()) or path == self.root.resolve():
            raise InputError("Unsafe artifact path")
        return path

    def write(self, kind: str, data: bytes) -> dict:
        if kind not in {"source", "processed"}:
            raise InputError("Unknown artifact kind")
        relative = f"{kind}/{uuid4()}.{'bin' if kind == 'source' else 'jsonl'}"
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=target.parent, prefix=".tmp-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, target)
            return {
                "kind": kind,
                "path": relative,
                "checksum": checksum(data),
                "size_bytes": len(data),
            }
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def write_rows(self, rows: list[Row]) -> dict:
        data = "".join(stable(row) + "\n" for row in rows).encode("utf-8")
        if len(data) > self.settings.max_file_bytes * 4:
            raise InputError("Canonical artifact exceeds storage size limit")
        return self.write("processed", data)

    def read(self, artifact) -> bytes:
        try:
            data = self.path(artifact.path).read_bytes()
        except OSError as exc:
            raise InputError("Stored artifact is missing or unreadable") from exc
        if checksum(data) != artifact.checksum:
            raise InputError(
                "Artifact checksum mismatch; data may have been modified outside DataForge"
            )
        return data

    def rows(self, artifact) -> list[Row]:
        return [json.loads(line) for line in self.read(artifact).decode("utf-8").splitlines()]

    def discard(self, artifacts: list[dict]) -> None:
        for artifact in artifacts:
            self.path(artifact["path"]).unlink(missing_ok=True)
