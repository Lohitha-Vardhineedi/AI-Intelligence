"""Migrations run with the sync driver for whatever DATABASE_URL points at."""

from logging.config import fileConfig

from alembic import context
from app.core.config import get_settings
from app.core.database import make_sync_engine
from app.models import Base

if context.config.config_file_name is not None:
    fileConfig(context.config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    from app.core.database import database_url

    context.configure(
        url=database_url(get_settings().database_url, use_async=False),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = make_sync_engine(get_settings().database_url)
    with engine.connect() as connection:
        # Batch mode lets ALTER TABLE migrations work on SQLite too.
        context.configure(connection=connection, target_metadata=target_metadata,
                          render_as_batch=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
