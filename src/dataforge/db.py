from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from dataforge.config import Settings


class Database:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.engine = create_engine(
            settings.database_url, connect_args={"check_same_thread": False, "timeout": 30}
        )

        @event.listens_for(self.engine, "connect")
        def sqlite_config(connection, _):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()

        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def migrate(self, revision: str = "head") -> None:
        self.settings.home.mkdir(parents=True, exist_ok=True)
        config = Config()
        config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
        config.set_main_option("sqlalchemy.url", self.settings.database_url.replace("%", "%%"))
        command.upgrade(config, revision)

    @contextmanager
    def session(self) -> Iterator[Session]:
        with self.sessions.begin() as session:
            yield session

    def close(self) -> None:
        self.engine.dispose()
