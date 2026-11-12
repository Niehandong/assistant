"""过期上传文件清理：物理删除「已过期且未提交」的 upload_file 及其对象（原文件、预览解析缓存）。

* 已被文档消费的上传文件永不清理（文档仍引用其原文件与 ``parsed/`` 解析文本）。
* 额外保护：对象键若被任一文档（含已删除）引用，即使上传文件未消费也不删除对象。
* 行级 ``FOR UPDATE SKIP LOCKED``，与正在提交的事务互不干扰。
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import delete

from app.core.config import Settings, get_settings
from app.models import UploadFile
from app.repositories import document_repo
from app.storage.s3 import get_storage
from platform_common.db import get_session_factory
from platform_common.jobs import run_periodic

logger = logging.getLogger("kb.worker.upload_cleanup")

BATCH = 200


async def cleanup_expired_uploads(now: datetime | None = None) -> int:
    storage = get_storage()
    removed = 0
    while True:
        async with get_session_factory()() as s:
            rows = await document_repo.expired_upload_files(s, now or datetime.now(UTC), BATCH)
            if not rows:
                return removed
            keys = {k for r in rows for k in (r.storage_key, r.parsed_key) if k}
            protected = await document_repo.referenced_keys(s, keys)
            done_ids: list[int] = []
            for r in rows:
                try:
                    for key in (r.storage_key, r.parsed_key):
                        if key and key not in protected:
                            await storage.delete(key)
                except Exception:
                    logger.warning("清理上传文件对象失败，下轮重试", exc_info=True, extra={"upload_file_id": r.id})
                    continue
                done_ids.append(r.id)
            if done_ids:
                await s.execute(delete(UploadFile).where(UploadFile.id.in_(done_ids)))
            await s.commit()
            removed += len(done_ids)
            if len(done_ids) < len(rows):
                return removed  # 有失败项：留到下一轮，避免死循环


async def run_upload_cleanup(settings: Settings | None = None) -> None:
    s = settings or get_settings()

    async def _tick() -> None:
        n = await cleanup_expired_uploads()
        if n:
            logger.info("已清理过期上传文件", extra={"count": n})

    await run_periodic("kb_upload_cleanup", s.UPLOAD_CLEANUP_INTERVAL_SECONDS, _tick)
