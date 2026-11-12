"""通用分段 ``split_general``。确定性纯函数。"""

from __future__ import annotations

from app.splitters.tokenizer import count_tokens

FALLBACK_SEPARATORS = ["\n", "。", "！", "？", "；", ".", "!", "?", ";", "，", ",", " ", ""]
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\"}


def unescape_separator(sep: str) -> str:
    """把用户输入的转义写法还原：``\\n`` → 换行，``\\t`` → 制表符，``\\\\`` → 反斜杠；其他原样保留。"""
    out: list[str] = []
    i = 0
    while i < len(sep):
        ch = sep[i]
        if ch == "\\" and i + 1 < len(sep) and sep[i + 1] in _ESCAPES:
            out.append(_ESCAPES[sep[i + 1]])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _units(text: str, sep: str, group: int) -> list[str]:
    """按分隔符切分，分隔符附着在前一单元末尾；``sep == ""`` 为每 ``group`` 个字符一组。

    单个字符最多 4 个 token（UTF-8 字节数），``group`` 由调用方保证 group*4 不超过上限。
    """
    if sep == "":
        return [text[i : i + group] for i in range(0, len(text), group)]
    parts = text.split(sep)
    units = [p + sep for p in parts[:-1]] + [parts[-1]]
    return [u for u in units if u]


def _atomize(text: str, max_tokens: int, level: int, group: int) -> list[str]:
    """把文本递归切成每个 ≤ max_tokens 的原子单元（从 FALLBACK_SEPARATORS[level] 起）。"""
    if count_tokens(text) <= max_tokens:
        return [text]
    for idx in range(level, len(FALLBACK_SEPARATORS)):
        sep = FALLBACK_SEPARATORS[idx]
        if sep != "" and sep not in text:
            continue
        units = _units(text, sep, group)
        if len(units) <= 1 and sep != "":
            continue
        result: list[str] = []
        for u in units:
            result.extend(_atomize(u, max_tokens, idx + 1, group) if count_tokens(u) > max_tokens else [u])
        return result
    return [text]  # 理论上不可达：逐字符层必然成功


def _merge(units: list[str], max_tokens: int, overlap: int) -> list[str]:
    counts = [count_tokens(u) for u in units]
    chunks: list[str] = []
    cur: list[int] = []  # 当前块的单元下标
    cur_sum = 0
    i = 0
    n = len(units)
    while i < n:
        if cur and cur_sum + counts[i] > max_tokens:
            chunks.append("".join(units[j] for j in cur))
            cur, cur_sum = _carry(cur, counts, overlap, max_tokens, counts[i])
            continue
        cur.append(i)
        cur_sum += counts[i]
        i += 1
        # 估算按单元求和；拼接后 BPE 边界可能略有出入，这里以真实计数兜底
        if cur_sum > max_tokens * 0.9 and len(cur) > 1:
            while len(cur) > 1 and count_tokens("".join(units[j] for j in cur)) > max_tokens:
                i -= 1
                cur_sum -= counts[cur.pop()]
    if cur:
        chunks.append("".join(units[j] for j in cur))
    return chunks


def _carry(cur: list[int], counts: list[int], overlap: int, max_tokens: int, nxt: int) -> tuple[list[int], int]:
    """取上一块末尾累计 ≤ overlap 的单元作为新块开头，同时保证加上下一个单元不超限。"""
    carried: list[int] = []
    total = 0
    if overlap > 0:
        for j in reversed(cur):
            if total + counts[j] > overlap or total + counts[j] + nxt > max_tokens:
                break
            carried.append(j)
            total += counts[j]
        carried.reverse()
    return carried, total


def split_general(text: str, separator: str, max_tokens: int, overlap: int) -> list[str]:
    """通用分段。``separator`` 为用户输入的转义写法（如 ``\\n\\n``）。

    1. 按分隔符切分，strip，丢弃空段；2. 超长段递归按后备分隔符切分、贪心合并并带重叠；
    3. 相邻短段不合并。返回内容列表（position 由调用方从 1 编号）。
    """
    sep = unescape_separator(separator)
    pieces = text.split(sep) if sep else [text]
    # 逐字符层的分组大小：保证单组 ≤ max_tokens，且（有重叠时）≤ 重叠长度，使重叠可以被携带
    group = max(1, (min(max_tokens, overlap) if overlap > 0 else max_tokens) // 4)
    result: list[str] = []
    for piece in pieces:
        seg = piece.strip()
        if not seg:
            continue
        if count_tokens(seg) <= max_tokens:
            result.append(seg)
            continue
        units = _atomize(seg, max_tokens, 0, group)
        for chunk in _merge(units, max_tokens, overlap):
            c = chunk.strip()
            if c:
                result.append(c)
    return result
