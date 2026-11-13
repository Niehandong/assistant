"""文本预处理。"""

from __future__ import annotations

import re

_WS = re.compile(r"[ \t\f\v　]+")
_MANY_NL = re.compile(r"\n{3,}")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL = re.compile(r"https?://\S+|www\.\S+")


def preprocess(text: str, *, normalize_whitespace: bool = True, remove_urls_emails: bool = False) -> str:
    text = text.replace("\x00", "")
    if remove_urls_emails:
        text = _URL.sub("", text)
        text = _EMAIL.sub("", text)
    if normalize_whitespace:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _WS.sub(" ", text)
        text = "\n".join(line.strip() for line in text.split("\n"))
        text = _MANY_NL.sub("\n\n", text)
    return text
