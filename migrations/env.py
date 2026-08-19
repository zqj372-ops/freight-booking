"""Alembic env - 走 sync engine (和 async runtime 分开)"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from app.config import settings
from app.database import Base
from app import models  # noqa: F401  - 触发模型注册

config = context.config

# Alembic 用 sync URL (运行时用 async URL,这里转换一下)
_sync_url = settings.database_url
if _sync_url.startswith("sqlite+aiosqlite"):
    _sync_url = _sync_url.replace("sqlite+aiosqlite", "sqlite", 1)
elif _sync_url.startswith("postgresql+asyncpg"):
    _sync_url = _sync_url.replace("postgresql+asyncpg", "postgresql+psycopg2", 1)

config.set_main_option("sqlalchemy.url", _sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Sync engine - alembic 推荐方式"""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
