"""PDF（pypdf，文字版）。"""

from __future__ import annotations

import logging
from pathlib import Path

from pypdf import PdfReader

from app.parsers.errors import ProcessError, broken

logging.getLogger("pypdf").setLevel(logging.ERROR)


def open_pdf(path: Path) -> PdfReader:
    """打开 PDF；加密且空密码无法解密 → ENCRYPTED；无法打开 → CORRUPT。均为 400504。"""
    try:
        reader = PdfReader(str(path))
        if reader.is_encrypted and not reader.decrypt(""):
            raise broken("文件已加密，无法解析", "ENCRYPTED")
        if len(reader.pages) == 0:
            raise broken()
    except ProcessError:
        raise
    except Exception as exc:  # pypdf 对坏文件抛出的异常类型很多
        raise broken() from exc
    return reader


def parse_pdf(path: Path) -> str:
    reader = open_pdf(path)
    texts: list[str] = []
    failed = 0
    try:
        pages = list(reader.pages)
    except Exception as exc:
        raise broken() from exc
    for page in pages:
        try:
            t = page.extract_text() or ""
        except Exception:
            failed += 1
            continue
        t = t.strip()
        if t:
            texts.append(t)
    if failed and failed == len(pages):
        raise broken()
    return "\n\n".join(texts)
