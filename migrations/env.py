from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.config import AppSettings
from app.database import Base
import app.models  # noqa: F401 - imports all ORM models into Base.metadata


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata


def get_database_url() -> str:
    """Resolve a URL without putting a deploy-time secret in alembic.ini."""
    command_line_url = context.get_x_argument(as_dictionary=True).get("database_url")
    return command_line_url or AppSettings.from_env().database_url


def configure_database_url() -> str:
    database_url = get_database_url()
    config.set_main_option("sqlalchemy.url", database_url)
    return database_url


def run_migrations_offline() -> None:
    """Run migrations without creating an Engine."""
    context.configure(
        url=configure_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations with a live database connection."""
    configure_database_url()
    configuration = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            render_as_batch=connection.dialect.name == "sqlite",
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
