"""XLSX（openpyxl read_only）/ XLS（xlrd）。"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from app.parsers.errors import broken
from app.parsers.text import normalize_headers, row_to_line


def cell_to_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        if value == int(value) and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    if isinstance(value, dt.datetime):
        if value.time() == dt.time(0):
            return value.date().isoformat()
        return value.isoformat(sep=" ")
    if isinstance(value, dt.date | dt.time):
        return value.isoformat()
    return " ".join(str(value).split())


def _sheet_text(name: str, rows: Iterable[list[str]]) -> str:
    headers: list[str] | None = None
    lines: list[str] = []
    for row in rows:
        if not any(row):
            continue
        if headers is None:
            headers = normalize_headers(row)
            continue
        line = row_to_line(headers, row)
        if line:
            lines.append(line)
    if not lines:
        return ""
    return "\n\n".join([f"# {name}", *lines])


def parse_xlsx(path: Path) -> str:
    from openpyxl import load_workbook  # type: ignore[import-untyped]

    try:
        wb = load_workbook(str(path), read_only=True, data_only=True)
        try:
            sheets: list[str] = []
            for ws in wb.worksheets:
                ws.reset_dimensions()  # 部分文件 dimension 记录错误，read_only 下重置后按真实数据读取
                rows = ([cell_to_str(c) for c in r] for r in ws.iter_rows(values_only=True))
                t = _sheet_text(ws.title, rows)
                if t:
                    sheets.append(t)
        finally:
            wb.close()
    except Exception as exc:
        raise broken() from exc
    return "\n\n".join(sheets)


def open_xls(path: Path) -> Any:
    import xlrd  # type: ignore[import-untyped]

    try:
        return xlrd.open_workbook(str(path), on_demand=True)
    except Exception as exc:
        raise broken() from exc


def parse_xls(path: Path) -> str:
    import xlrd

    wb = open_xls(path)
    try:
        sheets: list[str] = []
        for sh in wb.sheets():
            rows: list[list[str]] = []
            for r in range(sh.nrows):
                row: list[str] = []
                for c in range(sh.ncols):
                    cell = sh.cell(r, c)
                    if cell.ctype == xlrd.XL_CELL_DATE:
                        try:
                            row.append(cell_to_str(xlrd.xldate.xldate_as_datetime(cell.value, wb.datemode)))
                        except Exception:
                            row.append(cell_to_str(cell.value))
                    elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                        row.append("")
                    elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                        row.append(cell_to_str(bool(cell.value)))
                    elif cell.ctype == xlrd.XL_CELL_ERROR:
                        row.append("")
                    else:
                        row.append(cell_to_str(cell.value))
                rows.append(row)
            t = _sheet_text(sh.name, rows)
            if t:
                sheets.append(t)
    except Exception as exc:
        raise broken() from exc
    finally:
        wb.release_resources()
    return "\n\n".join(sheets)
