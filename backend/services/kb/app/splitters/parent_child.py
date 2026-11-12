"""父子分段与文档级入口 ``split_document``。"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.parsers.errors import FULL_DOC_TOO_LONG, INVALID_RULE, NO_TEXT, ProcessError
from app.schemas.process_rule import FULL_DOC_MAX_TOKENS, ProcessRule, check_rule
from app.splitters.general import split_general
from app.splitters.preprocess import preprocess
from app.splitters.tokenizer import count_tokens


@dataclass(frozen=True)
class ChildDraft:
    position: int
    content: str
    char_count: int
    token_count: int


@dataclass(frozen=True)
class SegmentDraft:
    """通用分段 / 父块草稿；通用分段 ``children`` 为空。"""

    position: int
    content: str
    char_count: int
    token_count: int
    children: list[ChildDraft] = field(default_factory=list)


def split_parent_child(text: str, rule: ProcessRule) -> list[SegmentDraft]:
    """text 须已预处理。"""
    p, c = rule.parent, rule.child
    assert p is not None and c is not None
    if p.mode == "full_doc":
        whole = text.strip()
        if not whole:
            return []
        if count_tokens(whole) > FULL_DOC_MAX_TOKENS:
            raise ProcessError(FULL_DOC_TOO_LONG, "文档超过 10,000 tokens，请使用段落模式", "FULL_DOC_TOO_LONG")
        parents = [whole]
    else:
        parents = split_general(text, p.separator, p.max_tokens, 0)
    drafts: list[SegmentDraft] = []
    for i, parent in enumerate(parents, start=1):
        kids = [
            ChildDraft(j, s, len(s), count_tokens(s))
            for j, s in enumerate(split_general(parent, c.separator, c.max_tokens, 0), start=1)
        ]
        drafts.append(SegmentDraft(i, parent, len(parent), count_tokens(parent), kids))
    return drafts


def split_document(text: str, rule: ProcessRule, model_max_tokens: int | None = None) -> list[SegmentDraft]:
    """预处理 + 分段（预览与正式处理共用）。

    - 规则语义不合法 → ProcessError(400001, data={"errors": [{"field","message"}]})
    - 全文模式超 1 万 tokens → 400506；预处理后无内容 → 400505
    """
    errs = check_rule(rule, model_max_tokens)
    if errs:
        raise ProcessError(
            INVALID_RULE,
            "参数不合法",
            "INVALID_RULE",
            {"errors": [{"field": e.path, "message": e.message} for e in errs]},
        )
    pre = rule.pre_processing
    cleaned = preprocess(text, normalize_whitespace=pre.normalize_whitespace, remove_urls_emails=pre.remove_urls_emails)
    if rule.mode == "general":
        g = rule.general
        assert g is not None
        parts = split_general(cleaned, g.separator, g.max_tokens, g.chunk_overlap)
        drafts = [SegmentDraft(i, s, len(s), count_tokens(s)) for i, s in enumerate(parts, start=1)]
    else:
        drafts = split_parent_child(cleaned, rule)
    if not drafts:
        raise ProcessError(NO_TEXT, "未能从文件中提取到文本", "NO_TEXT")
    return drafts
