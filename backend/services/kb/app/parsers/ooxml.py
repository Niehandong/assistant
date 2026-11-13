"""DOCX / PPTX（python-docx / python-pptx）与 OOXML zip 校验。"""

from __future__ import annotations

import zipfile
from pathlib import Path

from app.parsers.errors import ProcessError, broken

MAIN_PARTS = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}
MAX_UNCOMPRESSED = 300 * 1024 * 1024  # 防 zip 炸弹


def check_ooxml(path: Path, ext: str) -> None:
    """必须是合法 zip 且含 ``[Content_Types].xml`` 与主部件（加密 OOXML 是 OLE 文件，会被判为不合法）。"""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "[Content_Types].xml" not in names or MAIN_PARTS[ext] not in names:
                raise broken()
            if sum(i.file_size for i in zf.infolist()) > MAX_UNCOMPRESSED:
                raise broken()
    except ProcessError:
        raise
    except Exception as exc:  # BadZipFile / OSError / NotImplementedError ...
        raise broken() from exc


def parse_docx(path: Path) -> str:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        doc = Document(str(path))
        blocks: list[str] = []
        for child in doc.element.body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                text = Paragraph(child, doc).text.strip()
                if text:
                    blocks.append(text)
            elif tag == "tbl":
                table_text = _table_text(Table(child, doc))
                if table_text:
                    blocks.append(table_text)
    except Exception as exc:
        raise broken() from exc
    return "\n\n".join(blocks)


def _table_text(table: object) -> str:
    rows: list[str] = []
    for row in table.rows:  # type: ignore[attr-defined]
        cells: list[str] = []
        seen: set[int] = set()
        for cell in row.cells:
            if id(cell._tc) in seen:  # 合并单元格只输出一次
                continue
            seen.add(id(cell._tc))
            cells.append(" ".join(cell.text.split()))
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def parse_pptx(path: Path) -> str:
    from pptx import Presentation

    try:
        prs = Presentation(str(path))
        slides: list[str] = []
        for slide in prs.slides:
            parts: list[str] = []
            _collect_shapes(slide.shapes, parts)
            if parts:
                slides.append("\n".join(parts))
    except Exception as exc:
        raise broken() from exc
    return "\n\n".join(slides)


def _collect_shapes(shapes: object, out: list[str]) -> None:
    for shape in shapes:  # type: ignore[attr-defined]
        if getattr(shape, "shape_type", None) == 6 and hasattr(shape, "shapes"):  # GROUP
            _collect_shapes(shape.shapes, out)
            continue
        if getattr(shape, "has_text_frame", False):
            text = shape.text_frame.text.strip()
            if text:
                out.append(text)
        elif getattr(shape, "has_table", False) and shape.has_table:
            t = _table_text(shape.table)
            if t:
                out.append(t)
