"""vector_index_support：segment/child_chunk 增加 embedding_model_id，embedding 列存储策略调整（BE-21b）

HNSW 索引依赖模型 ID 与维度，由 kb-worker 在运行时创建（tech-design-m2 3.10.2），本迁移不建索引。

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12 10:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("segment", "child_chunk")
BATCH = 5000
STORAGE_NAMES = {"p": "PLAIN", "e": "EXTERNAL", "m": "MAIN", "x": "EXTENDED"}


def _backfill(table: str) -> None:
    """按 id 区间分批回填，每批一个事务；``embedding = t.embedding`` 让存量行按新存储策略重写。"""
    bind = op.get_bind()
    lo, hi = bind.execute(sa.text(f"SELECT min(id), max(id) FROM kb.{table}")).one()
    if lo is None:
        return
    start = int(lo)
    while start <= int(hi):
        end = start + BATCH - 1
        bind.execute(
            sa.text(
                f"UPDATE kb.{table} t SET embedding_model_id = d.embedding_model_id, embedding = t.embedding "
                "FROM kb.dataset d WHERE t.dataset_id = d.id AND t.embedding IS NOT NULL "
                "AND t.embedding_model_id IS NULL AND t.id BETWEEN :a AND :b"
            ),
            {"a": start, "b": end},
        )
        start = end + 1


def upgrade() -> None:
    for t in TABLES:
        op.execute(f"ALTER TABLE kb.{t} ADD COLUMN embedding_model_id BIGINT NULL")
        op.execute(f"ALTER TABLE kb.{t} ALTER COLUMN embedding SET STORAGE MAIN")
        op.execute(f"ALTER TABLE kb.{t} SET (toast_tuple_target = 8160)")
    with op.get_context().autocommit_block():
        for t in TABLES:
            _backfill(t)


def downgrade() -> None:
    bind = op.get_bind()
    with op.get_context().autocommit_block():
        names = (
            bind.execute(
                sa.text(
                    "SELECT indexname FROM pg_indexes WHERE schemaname = 'kb' "
                    "AND (indexname LIKE 'ix\\_seg\\_hnsw\\_m%' OR indexname LIKE 'ix\\_child\\_hnsw\\_m%')"
                )
            )
            .scalars()
            .all()
        )
        for name in names:
            bind.execute(sa.text(f'DROP INDEX CONCURRENTLY IF EXISTS kb."{name}"'))
    typstorage = bind.execute(sa.text("SELECT typstorage::text FROM pg_type WHERE typname = 'halfvec'")).scalar_one()
    default_storage = STORAGE_NAMES[str(typstorage)]
    for t in TABLES:
        op.execute(f"ALTER TABLE kb.{t} RESET (toast_tuple_target)")
        op.execute(f"ALTER TABLE kb.{t} ALTER COLUMN embedding SET STORAGE {default_storage}")
        op.execute(f"ALTER TABLE kb.{t} DROP COLUMN embedding_model_id")
