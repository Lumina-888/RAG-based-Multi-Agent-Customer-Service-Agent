"""SP-ING-002 结构感知分块：按标题层级切块，块不跨 H1，相邻块重叠 50 token。

规则（与规格对齐）：
- 块只属于单一 H1（按小节分块，小节已含祖先路径，绝不跨标题）
- 默认块长 300~500 token（size=400，段落级贪心打包 + 超预算段落按 token 硬切）
- 相邻块重叠 `overlap` token（同一 H1 内；跨 H1 不携带重叠）
- FAQ（Q:/A: 或 问：/答：）与表格整体原子成块，不被拆进两个块
- 每块带 `heading_path` 元数据（如 "产品介绍 / 退款政策"）
"""
from __future__ import annotations

import re

from app.ingestion.models import Chunk, Document, Section

#: token 近似：CJK 每字 1 token，ASCII 词（字母/数字串）每词 1 token
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9]+")
#: FAQ 起始标记：Q: / 问：/ Q1: / 问1：
_FAQ_START_RE = re.compile(r"^(?:Q|问)\s*[:：]")

#: 原子块类型（不可硬切）：table / faq
_ATOMIC_KINDS = {"table", "faq"}


def tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text)


def count_tokens(text: str) -> int:
    return len(_TOKEN_RE.findall(text))


def _split_text_at_tokens(text: str, n: int) -> tuple[str, str]:
    """按 token 边界硬切段落（仅普通段落允许）：返回 (head, rest)。"""
    if n <= 0:
        return "", text
    spans = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    if len(spans) <= n:
        return text, ""
    end = spans[n - 1][1]
    return text[:end], text[end:]


def _tail_text(text: str, n: int) -> str:
    """取文本最后 n 个 token（n ≤ 0 → 空串；不足则整段）。"""
    if n <= 0:
        return ""
    spans = [(m.start(), m.end()) for m in _TOKEN_RE.finditer(text)]
    if len(spans) <= n:
        return text
    return text[spans[-n][0] :]


def _split_blocks(content: str) -> list[tuple[str, str]]:
    """小节正文 → [(kind, text)]，kind ∈ {para, table, faq}。

    - 表格：连续 `|` 行成块（含表头分隔行），原子
    - FAQ：`Q:`/`问：` 起始行连同其后内容（含 `A:`/`答：` 行与空行）成块，
      直到下一个 Q 标记，原子
    - 引用块（`>`）同样按原子块处理
    """
    blocks: list[tuple[str, str]] = []
    cur_kind = "para"
    cur: list[str] = []

    def flush() -> None:
        nonlocal cur
        if cur:
            blocks.append((cur_kind, "\n".join(cur)))
            cur = []

    for line in content.splitlines():
        s = line.strip()
        if s.startswith("|"):
            if cur_kind != "table":
                flush()
                cur_kind = "table"
            cur.append(line)
        elif _FAQ_START_RE.match(s):
            flush()  # 新 Q 行总在新块开头（结束上一个 FAQ 块）
            cur_kind = "faq"
            cur.append(line)
        elif s.startswith(">"):  # 引用块原子处理
            if cur_kind != "faq":
                flush()
                cur_kind = "faq"
            cur.append(line)
        elif s == "":
            if cur_kind == "faq":  # FAQ 内空行不打断 Q/A 关联
                cur.append(line)
            else:
                flush()
                cur_kind = "para"
        else:
            if cur_kind == "table":
                flush()
                cur_kind = "para"
            cur.append(line)
    flush()
    return blocks


def _overlap_tail(
    window: list[tuple[str, str]], overlap: int
) -> tuple[list[tuple[str, str]], int]:
    """取窗口尾部 ≈ overlap token 作为下一块的起始（重叠窗口）。

    从尾部收集整块直到达到 overlap：边界为普通段落时做 token 级切片；
    边界为表格/FAQ 原子块时放弃重叠（原子块不可复制进下一窗口，宁缺勿重）。
    """
    if overlap <= 0:
        return [], 0
    tail: list[tuple[str, str]] = []
    acc = 0
    for kind, text in reversed(window):
        t = count_tokens(text)
        if kind == "para":
            take = _tail_text(text, overlap - acc)
            if take:
                tail.append(("para", take))
                acc += count_tokens(take)
            break
        if acc + t <= overlap:
            tail.append((kind, text))
            acc += t
        else:
            break  # 原子块越过重叠边界 → 不携带重叠
    tail.reverse()
    return tail, acc


def chunk(doc: Document, size: int = 400, overlap: int = 50, doc_id: str = "") -> list[Chunk]:
    """结构感知分块：`chunk(doc, size=400, overlap=50)` → `list[Chunk]`。"""
    chunks: list[Chunk] = []
    seq = 0

    def emit(window: list[tuple[str, str]], section: Section) -> Chunk:
        nonlocal seq
        content = "\n\n".join(t for _, t in window)
        chunk_ = Chunk(
            doc_id=doc_id,
            seq=seq,
            title=doc.title,
            source=doc.source,
            heading_path=section.heading_path,
            content=content,
            tokens=count_tokens(content),
        )
        seq += 1
        return chunk_

    for section in doc.sections:
        blocks = _split_blocks(section.content)
        window: list[tuple[str, str]] = []
        window_tokens = 0
        window_is_tail = False  # 窗口仅含上一块的重叠尾（未追加新内容）
        i = 0
        while i < len(blocks):
            kind, text = blocks[i]
            t = count_tokens(text)
            if window_tokens + t <= size:
                window.append((kind, text))
                window_tokens += t
                window_is_tail = False
                i += 1
                continue
            if window and not window_is_tail:
                chunks.append(emit(window, section))
                window, window_tokens = _overlap_tail(window, overlap)
                window_is_tail = True
                continue
            # 窗口为空 / 仅重叠尾：当前块放不下 → 普通段落硬切，原子块整体成块
            if kind == "para":
                head, rest = _split_text_at_tokens(text, size - window_tokens)
                window.append(("para", head))
                window_tokens += count_tokens(head)
                chunks.append(emit(window, section))
                window, window_tokens = _overlap_tail(window, overlap)
                window_is_tail = True
                if rest:
                    blocks[i] = ("para", rest)
                else:
                    i += 1
            else:
                window.append((kind, text))
                window_tokens += t
                chunks.append(emit(window, section))
                window, window_tokens = _overlap_tail(window, overlap)
                window_is_tail = bool(window)
                i += 1
        if window and not window_is_tail:  # 纯重叠尾不单独成块（避免重复内容）
            chunks.append(emit(window, section))
    return chunks
