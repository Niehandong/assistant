"""分段规则（process_rule）模型与校验。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

Separator = Annotated[str, Field(min_length=1, max_length=10)]

FULL_DOC_MAX_TOKENS = 10000


class PreProcessing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    normalize_whitespace: bool = True
    remove_urls_emails: bool = False


class GeneralRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    separator: Separator = "\\n\\n"
    max_tokens: int = Field(1024, ge=50, le=4000)
    chunk_overlap: int = Field(50, ge=0)

    @field_validator("chunk_overlap")
    @classmethod
    def _overlap(cls, v: int, info: ValidationInfo) -> int:
        max_tokens = info.data.get("max_tokens")
        if isinstance(max_tokens, int) and v > max_tokens // 2:
            raise ValueError(f"分段重叠长度不能超过最大长度的 50%（{max_tokens // 2}）")
        return v


class ParentRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["paragraph", "full_doc"] = "paragraph"
    separator: Separator = "\\n\\n"  # full_doc 模式忽略
    max_tokens: int = Field(1024, ge=50, le=4000)  # full_doc 模式忽略


class ChildRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    separator: Separator = "\\n"
    max_tokens: int = Field(512, ge=20, le=4000)


class ProcessRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["general", "parent_child"]
    pre_processing: PreProcessing = Field(default_factory=PreProcessing)
    general: GeneralRule | None = None
    parent: ParentRule | None = None
    child: ChildRule | None = None

    def model_post_init(self, __context: object) -> None:
        # 当前模式的子规则缺省取默认值
        if self.mode == "general" and self.general is None:
            self.general = GeneralRule()
        if self.mode == "parent_child":
            if self.parent is None:
                self.parent = ParentRule()
            if self.child is None:
                self.child = ChildRule()


@dataclass(frozen=True)
class RuleFieldError:
    path: str  # 如 process_rule.general.chunk_overlap
    message: str


def check_rule(rule: ProcessRule, model_max_tokens: int | None = None) -> list[RuleFieldError]:
    """语义校验（需要模型信息或跨字段）；通过 pydantic 无法表达的约束。返回空列表表示合法。"""
    errs: list[RuleFieldError] = []
    if rule.mode == "general":
        g = rule.general
        assert g is not None
        if model_max_tokens is not None and g.max_tokens > model_max_tokens:
            errs.append(
                RuleFieldError(
                    "process_rule.general.max_tokens", f"不能超过向量模型的单次最大输入（{model_max_tokens}）"
                )
            )
    else:
        p, c = rule.parent, rule.child
        assert p is not None and c is not None
        upper = p.max_tokens if p.mode == "paragraph" else 4000
        if c.max_tokens > upper:
            errs.append(
                RuleFieldError(
                    "process_rule.child.max_tokens",
                    f"不能超过{'父块最大长度' if p.mode == 'paragraph' else ''}（{upper}）",
                )
            )
        if model_max_tokens is not None and c.max_tokens > model_max_tokens:
            errs.append(
                RuleFieldError("process_rule.child.max_tokens", f"不能超过向量模型的单次最大输入（{model_max_tokens}）")
            )
    return errs
