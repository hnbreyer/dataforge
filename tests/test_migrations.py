from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text

from dataforge.config import Settings
from dataforge.db import Database
from dataforge.models import Base
from dataforge.workspace import Workspace


def test_fresh_migration_matches_models_and_preserves_data_on_repeat(tmp_path):
    workspace = Workspace(Settings(home=tmp_path / "migrated"))
    workspace.initialize()
    dataset = workspace.datasets.import_bytes(b"a\n1\n", "x.csv", "x")
    workspace.initialize()
    assert workspace.datasets.get("x")["id"] == dataset["id"]
    with workspace.db.engine.connect() as connection:
        assert compare_metadata(MigrationContext.configure(connection), Base.metadata) == []
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001"
        assert set(Base.metadata.tables).issubset(inspect(connection).get_table_names())
    workspace.close()


def test_downgrade_and_upgrade_empty_database(tmp_path):
    settings = Settings(home=tmp_path / "roundtrip")
    database = Database(settings)
    database.migrate()
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[1] / "src/dataforge/migrations")
    )
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.downgrade(config, "base")
    assert inspect(database.engine).get_table_names() == ["alembic_version"]
    command.upgrade(config, "head")
    assert "datasets" in inspect(database.engine).get_table_names()
    database.close()
