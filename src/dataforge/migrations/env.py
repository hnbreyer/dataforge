from alembic import context
from sqlalchemy import engine_from_config, pool

from dataforge.models import Base

config = context.config


def run():
    if context.is_offline_mode():
        context.configure(
            url=config.get_main_option("sqlalchemy.url"),
            target_metadata=Base.metadata,
            literal_binds=True,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    else:
        engine = engine_from_config(
            config.get_section(config.config_ini_section) or {},
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            connection.commit()
            context.configure(
                connection=connection, target_metadata=Base.metadata, render_as_batch=True
            )
            with context.begin_transaction():
                context.run_migrations()
        engine.dispose()


run()
