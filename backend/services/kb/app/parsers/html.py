"""HTML（bs4 + lxml）。"""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString

from app.parsers.errors import broken
from app.parsers.text import read_text

BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "body", "dd", "details", "div", "dl", "dt", "fieldset",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6", "header", "hr", "li",
    "main", "nav", "ol", "p", "pre", "section", "summary", "table", "tbody", "td", "tfoot", "th", "thead",
    "title", "tr", "ul",
}  # fmt: skip
REMOVE_TAGS = ["script", "style", "noscript", "template"]


def parse_html(path: Path) -> str:
    raw = read_text(path)
    try:
        soup = BeautifulSoup(raw, "lxml")
        for tag in soup(REMOVE_TAGS):
            tag.decompose()
        for node in soup.find_all(string=True):
            if isinstance(node, Comment) or not isinstance(node, NavigableString):
                continue
            if node.find_parent("pre") is None:
                node.replace_with(NavigableString(re.sub(r"\s+", " ", str(node))))
        for br in soup.find_all("br"):
            br.replace_with(NavigableString("\n"))
        for tag in soup.find_all(list(BLOCK_TAGS)):
            tag.insert_before(NavigableString("\n"))
            tag.insert_after(NavigableString("\n"))
        text = soup.get_text()
    except Exception as exc:  # RecursionError 等
        raise broken() from exc
    lines = [ln.strip() for ln in text.split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
