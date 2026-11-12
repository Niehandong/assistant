"""tiktoken cl100k_base 离线加载与 token 计数。"""

from __future__ import annotations

from functools import lru_cache

import tiktoken
from tiktoken.load import load_tiktoken_bpe

from app.core.config import get_settings

CL100K_PAT = (
    r"""'(?i:[sdmt]|ll|ve|re)|[^\r\n\p{L}\p{N}]?+\p{L}+|\p{N}{1,3}| ?[^\s\p{L}\p{N}]++[\r\n]*|\s*[\r\n]|\s+(?!\S)|\s+"""
)
CL100K_SHA256 = "223921b76ee99bde995b7ff738513eef100fb51d18c93597a113bcffe865b2a7"
SPECIAL_TOKENS = {
    "<|endoftext|>": 100257,
    "<|fim_prefix|>": 100258,
    "<|fim_middle|>": 100259,
    "<|fim_suffix|>": 100260,
    "<|endofprompt|>": 100276,
}


@lru_cache(maxsize=1)
def get_encoding() -> tiktoken.Encoding:
    ranks = load_tiktoken_bpe(str(get_settings().tiktoken_file), expected_hash=CL100K_SHA256)
    return tiktoken.Encoding(
        name="cl100k_base", pat_str=CL100K_PAT, mergeable_ranks=ranks, special_tokens=SPECIAL_TOKENS
    )


def count_tokens(text: str) -> int:
    """token 数；文本中出现的特殊标记字面量按普通文本计。"""
    if not text:
        return 0
    return len(get_encoding().encode_ordinary(text))
