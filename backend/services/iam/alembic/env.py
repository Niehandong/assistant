"""iam 迁移环境：异步引擎，版本表与业务表均在 iam schema，只处理 iam 的对象。"""

from __future__ import annotations

import asyncio
from typing import Any

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  导入全部模型
from app.core.config import get_settings
from platform_common.db import Base

SCHEMA = "iam"
config = context.config
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    if type_ == "schema":
        return name == SCHEMA
    return True


def _configure(connection: Connection | None = None, url: str | None = None) -> None:
    context.configure(
        connection=connection,
        url=url,
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_name=include_name,
        compare_type=True,
        literal_binds=connection is None,
        dialect_opts={"paramstyle": "named"} if connection is None else None,
    )


def run_migrations_offline() -> None:
    _configure(url=get_settings().DATABASE_URL)
    with context.begin_transaction():
        context.run_migrations()


def _do_run(connection: Connection) -> None:
    # 版本表在 iam schema 中，必须先于迁移建好 schema
    connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(get_settings().DATABASE_URL)
    async with engine.connect() as connection:
        await connection.run_sync(_do_run)
        await connection.commit()
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
