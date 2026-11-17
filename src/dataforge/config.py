import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    home: Path = field(default_factory=lambda: Path(os.getenv("DATAFORGE_HOME", ".dataforge")))
    max_file_bytes: int = field(
        default_factory=lambda: int(os.getenv("DATAFORGE_MAX_FILE_BYTES", 26214400))
    )
    max_rows: int = field(default_factory=lambda: int(os.getenv("DATAFORGE_MAX_ROWS", 100000)))
    max_cells: int = field(default_factory=lambda: int(os.getenv("DATAFORGE_MAX_CELLS", 2000000)))

    def __post_init__(self):
        object.__setattr__(self, "home", self.home.expanduser().resolve())
        if min(self.max_file_bytes, self.max_rows, self.max_cells) < 1:
            raise ValueError("Resource limits must be positive")

    @property
    def database_url(self) -> str:
        return f"sqlite:///{self.home / 'dataforge.db'}"
