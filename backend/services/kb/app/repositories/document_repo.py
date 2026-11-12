"""文档与上传文件的查询/创建（BE-17 创建部分；列表/管理查询由 BE-19 追加）。

文档、上传文件均不受数据权限控制，访问边界由知识库 ACL 保证（调用方先 ``require_dataset``）。
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChildChunk, Dataset, Document, Segment, UploadFile, UserRef


async def count_documents(session: AsyncSession, dataset_id: int) -> int:
    stmt = (
        select(func.count())
        .select_from(Document)
        .where(Document.dataset_id == dataset_id, Document.is_deleted.is_(False))
    )
    return int((await session.execute(stmt)).scalar_one())


async def existing_names_by_hash(session: AsyncSession, dataset_id: int, hashes: Collection[str]) -> dict[str, str]:
    """本库未删除文档中内容哈希已存在的 ``{hash: 文档名}``。"""
    if not hashes:
        return {}
    stmt = (
        select(Document.file_hash, Document.name)
        .where(Document.dataset_id == dataset_id, Document.is_deleted.is_(False), Document.file_hash.in_(hashes))
        .order_by(Document.id)
    )
    result: dict[str, str] = {}
    for h, name in (await session.execute(stmt)).all():
        result.setdefault(h, name)
    return result


async def get_valid_upload_file(
    session: AsyncSession, dataset_id: int, upload_file_id: int, now: datetime
) -> UploadFile | None:
    """属于本库、未删除、未过期、未提交的上传文件。"""
    stmt = select(UploadFile).where(
        UploadFile.id == upload_file_id,
        UploadFile.dataset_id == dataset_id,
        UploadFile.is_deleted.is_(False),
        UploadFile.consumed_document_id.is_(None),
        UploadFile.expires_at > now,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def lock_valid_upload_files(
    session: AsyncSession, dataset_id: int, ids: Sequence[int], now: datetime
) -> dict[int, UploadFile]:
    """加锁读取有效的上传文件（提交用）；不存在/失效的 id 不在结果中。"""
    stmt = (
        select(UploadFile)
        .where(
            UploadFile.id.in_(ids),
            UploadFile.dataset_id == dataset_id,
            UploadFile.is_deleted.is_(False),
            UploadFile.consumed_document_id.is_(None),
            UploadFile.expires_at > now,
        )
        .order_by(UploadFile.id)
        .with_for_update()
    )
    return {u.id: u for u in (await session.execute(stmt)).scalars().all()}


# ---------------------------------------------------------------- 处理流水线（BE-18）
# 所有状态写入都带 ``process_attempt`` 栅栏：attempt 不一致/已删除/已离开处理态 → 返回 False，调用方静默结束。

PROCESSING_STATUSES = ("queued", "parsing", "splitting", "indexing")
STAGE_OF_STATUS = {"parsing": "parse", "splitting": "split", "indexing": "index"}


async def get_alive(session: AsyncSession, document_id: int, *, for_update: bool = False) -> Document | None:
    stmt = select(Document).where(Document.id == document_id, Document.is_deleted.is_(False))
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_dataset_alive(session: AsyncSession, dataset_id: int) -> Dataset | None:
    stmt = select(Dataset).where(Dataset.id == dataset_id, Dataset.is_deleted.is_(False))
    return (await session.execute(stmt)).scalar_one_or_none()


def _fence(document_id: int, attempt: int) -> list[ColumnElement[bool]]:
    return [
        Document.id == document_id,
        Document.process_attempt == attempt,
        Document.is_deleted.is_(False),
        Document.status.in_(PROCESSING_STATUSES),
    ]


async def cas_status(session: AsyncSession, document_id: int, attempt: int, status: str) -> bool:
    """进入新阶段：刷新进度时间并清除上次失败信息。"""
    stmt = (
        update(Document)
        .where(*_fence(document_id, attempt))
        .values(
            status=status,
            progress_updated_at=func.now(),
            failed_stage=None,
            error_code=None,
            error_message=None,
        )
        .returning(Document.id)
    )
    return (await session.execute(stmt)).first() is not None


async def cas_parsed_key(session: AsyncSession, document_id: int, attempt: int, parsed_key: str) -> bool:
    stmt = (
        update(Document)
        .where(*_fence(document_id, attempt))
        .values(parsed_key=parsed_key, progress_updated_at=func.now())
        .returning(Document.id)
    )
    return (await session.execute(stmt)).first() is not None


async def cas_progress(
    session: AsyncSession, document_id: int, attempt: int, *, done: int, total: int | None = None
) -> bool:
    values: dict[str, object] = {"progress_done": done, "progress_updated_at": func.now()}
    if total is not None:
        values["progress_total"] = total
    stmt = update(Document).where(*_fence(document_id, attempt)).values(**values).returning(Document.id)
    return (await session.execute(stmt)).first() is not None


async def mark_failed(
    session: AsyncSession, document_id: int, attempt: int, *, stage: str, code: str, message: str
) -> bool:
    stmt = (
        update(Document)
        .where(*_fence(document_id, attempt))
        .values(
            status="failed",
            failed_stage=stage,
            error_code=code,
            error_message=message[:500],
            progress_updated_at=func.now(),
        )
        .returning(Document.id)
    )
    return (await session.execute(stmt)).first() is not None


async def mark_available(session: AsyncSession, document_id: int, attempt: int) -> bool:
    stmt = (
        update(Document)
        .where(*_fence(document_id, attempt))
        .values(
            status="available",
            failed_stage=None,
            error_code=None,
            error_message=None,
            progress_updated_at=func.now(),
        )
        .returning(Document.id)
    )
    return (await session.execute(stmt)).first() is not None


async def lock_dataset_row(session: AsyncSession, dataset_id: int) -> bool:
    """锁知识库行（串行化 recalc_dataset，避免并发完成时统计互相覆盖）；知识库已删除返回 False。"""
    stmt = select(Dataset.id).where(Dataset.id == dataset_id, Dataset.is_deleted.is_(False)).with_for_update()
    return (await session.execute(stmt)).first() is not None


async def timed_out_dataset_ids(session: AsyncSession, cutoff: datetime) -> list[int]:
    stmt = (
        select(Document.dataset_id)
        .where(
            Document.is_deleted.is_(False),
            Document.status.in_(("parsing", "splitting", "indexing")),
            Document.progress_updated_at < cutoff,
        )
        .distinct()
    )
    return [int(x) for x in (await session.execute(stmt)).scalars().all()]


async def fail_timed_out(session: AsyncSession, dataset_id: int, cutoff: datetime) -> list[int]:
    """把某知识库内超时的处理中文档置为失败（TIMEOUT）并 attempt+1，使在途旧任务失效。"""
    stage = case(
        (Document.status == "parsing", "parse"),
        (Document.status == "splitting", "split"),
        else_="index",
    )
    stmt = (
        update(Document)
        .where(
            Document.dataset_id == dataset_id,
            Document.is_deleted.is_(False),
            Document.status.in_(("parsing", "splitting", "indexing")),
            Document.progress_updated_at < cutoff,
        )
        .values(
            failed_stage=stage,
            status="failed",
            error_code="TIMEOUT",
            error_message="处理超时",
            process_attempt=Document.process_attempt + 1,
            progress_updated_at=func.now(),
        )
        .returning(Document.id)
        .execution_options(synchronize_session=False)
    )
    return [int(x) for x in (await session.execute(stmt)).scalars().all()]


async def stale_queued(session: AsyncSession, cutoff: datetime, limit: int) -> list[Document]:
    stmt = (
        select(Document)
        .where(Document.is_deleted.is_(False), Document.status == "queued", Document.progress_updated_at < cutoff)
        .order_by(Document.progress_updated_at)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars().all())


async def touch_queued(session: AsyncSession, document_id: int, attempt: int) -> bool:
    """重新投递后刷新排队时间，避免每轮巡检都重投。"""
    stmt = (
        update(Document)
        .where(
            Document.id == document_id,
            Document.process_attempt == attempt,
            Document.status == "queued",
            Document.is_deleted.is_(False),
        )
        .values(progress_updated_at=func.now())
        .returning(Document.id)
    )
    return (await session.execute(stmt)).first() is not None


async def expired_upload_files(session: AsyncSession, now: datetime, limit: int) -> list[UploadFile]:
    """过期且未被文档消费的上传文件（加锁跳过正被提交的行）。"""
    stmt = (
        select(UploadFile)
        .where(UploadFile.expires_at < now, UploadFile.consumed_document_id.is_(None))
        .order_by(UploadFile.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list((await session.execute(stmt)).scalars().all())


async def referenced_keys(session: AsyncSession, keys: Collection[str]) -> set[str]:
    """被任意文档（含已删除）引用的对象键，清理上传文件时不得删除。"""
    if not keys:
        return set()
    found: set[str] = set()
    for column in (Document.storage_key, Document.parsed_key):
        for key in (await session.execute(select(column).where(column.in_(keys)))).scalars().all():
            if key is not None:
                found.add(key)
    return found


# ---------------------------------------------------------------- 文档管理（BE-19）


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@dataclass(frozen=True)
class DocumentFilter:
    keyword: str | None = None
    status: str | None = None  # 具体状态或 processing
    enabled: bool | None = None
    sort_by: str = "created_at"
    sort_desc: bool = True


_SORT_COLUMNS = {"created_at": Document.created_at, "char_count": Document.char_count, "hit_count": Document.hit_count}


async def list_documents(
    session: AsyncSession, dataset_id: int, f: DocumentFilter, offset: int, limit: int
) -> tuple[list[tuple[Document, str | None]], int]:
    """分页查询本库未删除文档，同时带出上传人姓名（user_ref 左连接，无 N+1）。"""
    conds: list[ColumnElement[bool]] = [Document.dataset_id == dataset_id, Document.is_deleted.is_(False)]
    if f.keyword:
        conds.append(Document.name.like(_like(f.keyword), escape="\\"))
    if f.status == "processing":
        conds.append(Document.status.in_(PROCESSING_STATUSES))
    elif f.status:
        conds.append(Document.status == f.status)
    if f.enabled is not None:
        conds.append(Document.enabled.is_(f.enabled))
    total = int((await session.execute(select(func.count()).select_from(Document).where(*conds))).scalar_one())
    col = _SORT_COLUMNS.get(f.sort_by, Document.created_at)
    order = col.desc() if f.sort_desc else col.asc()
    stmt = (
        select(Document, UserRef.name)
        .outerjoin(UserRef, UserRef.id == Document.created_by)
        .where(*conds)
        .order_by(order, Document.id.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(r[0], r[1]) for r in rows], total


async def get_in_dataset(
    session: AsyncSession, dataset_id: int, document_id: int, *, for_update: bool = False
) -> Document | None:
    stmt = select(Document).where(
        Document.id == document_id, Document.dataset_id == dataset_id, Document.is_deleted.is_(False)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return (await session.execute(stmt)).scalar_one_or_none()


async def uploader_name(session: AsyncSession, user_id: int | None) -> str | None:
    if user_id is None:
        return None
    return (await session.execute(select(UserRef.name).where(UserRef.id == user_id))).scalar_one_or_none()


async def list_by_ids(
    session: AsyncSession, dataset_id: int, ids: Sequence[int], *, for_update: bool = False
) -> list[Document]:
    """本库未删除的文档（按 id 升序加锁，避免并发批量操作死锁）；不存在的 id 不在结果中。"""
    if not ids:
        return []
    stmt = (
        select(Document)
        .where(Document.id.in_(ids), Document.dataset_id == dataset_id, Document.is_deleted.is_(False))
        .order_by(Document.id)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await session.execute(stmt)).scalars().all())


async def uploader_names(session: AsyncSession, user_ids: Collection[int | None]) -> dict[int, str]:
    ids = {i for i in user_ids if i is not None}
    if not ids:
        return {}
    rows = (await session.execute(select(UserRef.id, UserRef.name).where(UserRef.id.in_(ids)))).all()
    return {int(r[0]): r[1] for r in rows}


async def soft_delete_content(session: AsyncSession, document_ids: Sequence[int], operator_id: int) -> None:
    """软删文档下全部分段与子块，并关闭检索可见标志。"""
    if not document_ids:
        return
    await session.execute(
        update(ChildChunk)
        .where(ChildChunk.document_id.in_(document_ids), ChildChunk.is_deleted.is_(False))
        .values(is_deleted=True, search_enabled=False, updated_by=operator_id)
        .execution_options(synchronize_session=False)
    )
    await session.execute(
        update(Segment)
        .where(Segment.document_id.in_(document_ids), Segment.is_deleted.is_(False))
        .values(is_deleted=True, search_enabled=False, updated_by=operator_id)
        .execution_options(synchronize_session=False)
    )


async def has_alive_documents(session: AsyncSession, dataset_id: int) -> bool:
    return await count_documents(session, dataset_id) > 0
