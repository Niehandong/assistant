"""解析器注册表：``validate`` / ``parse`` / ``parse_with_timeout``。"""

from __future__ import annotations

import asyncio
import multiprocessing
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from app.parsers.errors import (
    FILE_EMPTY,
    FILE_TOO_LARGE,
    NO_TEXT,
    UNSUPPORTED_TYPE,
    ProcessError,
    broken,
)
from app.parsers.excel import open_xls, parse_xls, parse_xlsx
from app.parsers.html import parse_html
from app.parsers.ooxml import check_ooxml, parse_docx, parse_pptx
from app.parsers.orphan_guard import init_worker_process
from app.parsers.pdf import open_pdf, parse_pdf
from app.parsers.text import parse_csv, parse_plain, read_text

ALLOWED_EXTS = frozenset({"txt", "md", "markdown", "pdf", "docx", "xlsx", "xls", "csv", "html", "htm", "pptx"})
MAX_FILE_SIZE = 15 * 1024 * 1024
PARSE_TIMEOUT_SECONDS = 60

_PARSERS: dict[str, Callable[[Path], str]] = {
    "txt": parse_plain,
    "md": parse_plain,
    "markdown": parse_plain,
    "csv": parse_csv,
    "pdf": parse_pdf,
    "docx": parse_docx,
    "xlsx": parse_xlsx,
    "xls": parse_xls,
    "html": parse_html,
    "htm": parse_html,
    "pptx": parse_pptx,
}


def normalize_ext(ext: str) -> str:
    return ext.strip().lstrip(".").lower()


def validate(path: Path | str, ext: str) -> None:
    """上传时的轻量校验；不通过抛 :class:`ProcessError`（400501/400502/400503/400504）。"""
    p = Path(path)
    e = normalize_ext(ext)
    if e not in ALLOWED_EXTS:
        raise ProcessError(UNSUPPORTED_TYPE, "不支持的文件类型", "UNSUPPORTED_TYPE")
    size = p.stat().st_size
    if size == 0:
        raise ProcessError(FILE_EMPTY, "文件为空", "EMPTY")
    if size > MAX_FILE_SIZE:
        raise ProcessError(FILE_TOO_LARGE, "文件超过 15 MB", "TOO_LARGE")
    if e == "pdf":
        open_pdf(p)
    elif e in ("docx", "xlsx", "pptx"):
        check_ooxml(p, e)
    elif e == "xls":
        wb = open_xls(p)
        wb.release_resources()
    else:  # 文本类：可解码即可
        read_text(p)


def parse(path: Path | str, ext: str) -> str:
    """解析为纯文本。无法解析 → 400504；全文去空白后为空 → 400505（NO_TEXT）。

    不做大小/类型之外的上传校验；调用前应已 ``validate``，这里仍保留类型与大小的兜底。
    """
    p = Path(path)
    e = normalize_ext(ext)
    parser = _PARSERS.get(e)
    if parser is None:
        raise ProcessError(UNSUPPORTED_TYPE, "不支持的文件类型", "UNSUPPORTED_TYPE")
    if e in ("docx", "xlsx", "pptx"):
        check_ooxml(p, e)
    try:
        text = parser(p)
    except ProcessError:
        raise
    except Exception as exc:
        raise broken() from exc
    text = text.replace("\x00", "")
    if not "".join(text.split()):
        raise ProcessError(NO_TEXT, "未能从文件中提取到文本", "NO_TEXT")
    return text


_pool: ProcessPoolExecutor | None = None


def get_pool(max_workers: int = 2) -> ProcessPoolExecutor:
    global _pool
    if _pool is None:
        _pool = ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=multiprocessing.get_context("spawn"),
            initializer=init_worker_process,
            initargs=(os.getpid(),),  # 父进程被强杀时子进程自行退出，见 orphan_guard
        )
    return _pool


def shutdown_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


async def parse_with_timeout(
    path: Path | str, ext: str, timeout_seconds: float = PARSE_TIMEOUT_SECONDS, pool: ProcessPoolExecutor | None = None
) -> str:
    """进程池解析；超时抛 400504（reason=TIMEOUT，message“文件解析超时”）。

    超时后该任务仍可能占用一个池进程直至自然结束，所以池大小需限制并发。
    """
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(pool or get_pool(), parse, str(path), ext)
    try:
        return await asyncio.wait_for(fut, timeout_seconds)
    except TimeoutError as exc:
        raise broken("文件解析超时", "TIMEOUT") from exc
