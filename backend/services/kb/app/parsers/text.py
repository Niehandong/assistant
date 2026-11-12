"""TXT / Markdown / CSV 的解码与文本行格式化。"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from pathlib import Path

from charset_normalizer import from_bytes

from app.parsers.errors import broken

csv.field_size_limit(10 * 1024 * 1024)


def decode_bytes(data: bytes) -> str:
    """先 UTF-8（含 BOM），失败用 charset-normalizer 识别；无法识别 → 400504。"""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        pass
    best = from_bytes(data).best()
    if best is None:
        raise broken("文本编码无法识别，文件可能已损坏")
    return str(best)


def read_text(path: Path) -> str:
    return decode_bytes(path.read_bytes())


def row_to_line(headers: list[str], values: Iterable[str]) -> str:
    """``表头1: 值1; 表头2: 值2``；空值跳过。"""
    parts = [f"{h}: {v}" for h, v in zip(headers, values, strict=False) if v != ""]
    return "; ".join(parts)


def normalize_headers(row: Iterable[str]) -> list[str]:
    return [(h.strip() or f"列{i}") for i, h in enumerate(row, start=1)]


def parse_csv(path: Path) -> str:
    text = read_text(path)
    try:
        rows = list(csv.reader(io.StringIO(text, newline="")))
    except csv.Error as exc:
        raise broken("CSV 文件格式错误") from exc
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    headers = normalize_headers(rows[0])
    lines = [row_to_line(headers, [c.strip() for c in r]) for r in rows[1:]]
    return "\n\n".join(line for line in lines if line)


def parse_plain(path: Path) -> str:
    return read_text(path)


__all__ = ["decode_bytes", "parse_csv", "parse_plain", "read_text"]
