"""SP-EVAL-001 测试集加载：`data/test_cases/` 三种格式，非法行跳过并计数报告。

- `load_intent_cases(path)`：intent.csv（列：label,text）
- `load_retrieval_cases(path)`：retrieval.jsonl（`{"query", "gold_docs": [doc_id...]}`）
- `load_chat_cases(path)`：chat_e2e.jsonl（`{"id", "path", "turns": [{role, content}]}`）

返回值统一 `(cases, skipped_count)`：非法行（缺字段 / 坏 JSON / 空列表 / 非法角色）
跳过但**计数报告**，不抛错、不静默吞掉；文件不存在直接抛 FileNotFoundError。
"""
from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("app.eval.case_loader")

VALID_ROLES = ("user", "assistant")


@dataclass
class IntentCase:
    """意图测试样本：`label,text`。"""

    label: str
    text: str


@dataclass
class RetrievalCase:
    """检索标注样本：查询 → 期望命中的文档（doc 级 gold）。"""

    query: str
    gold_docs: list[str]


@dataclass
class ChatCase:
    """E2E 对话样本：`{id, path, turns}`，turns 为 user/assistant 轮次对。"""

    case_id: str
    path: str
    turns: list[dict]


def load_intent_cases(path: str | Path) -> tuple[list[IntentCase], int]:
    """加载 intent.csv；空 label / 空 text 的行跳过并计数。"""
    cases: list[IntentCase] = []
    skipped = 0
    with Path(path).open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row and row[0].strip() == "label" and len(row) > 1 and row[1].strip() == "text":
                continue  # 表头
            if not row or all(not cell.strip() for cell in row):
                continue  # 空行不计入跳过
            if len(row) < 2 or not row[0].strip() or not row[1].strip():
                skipped += 1
                continue
            cases.append(IntentCase(label=row[0].strip(), text=row[1].strip()))
    logger.info("intent 用例加载 path=%s 有效=%d 跳过=%d", path, len(cases), skipped)
    return cases, skipped


def load_retrieval_cases(path: str | Path) -> tuple[list[RetrievalCase], int]:
    """加载 retrieval.jsonl；坏 JSON / 缺 query / gold_docs 非法 → 跳过并计数。"""
    cases: list[RetrievalCase] = []
    skipped = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(obj, dict):
            skipped += 1
            continue
        query = str(obj.get("query", "")).strip()
        gold = obj.get("gold_docs")
        if not query or not isinstance(gold, list) or not gold:
            skipped += 1
            continue
        if not all(isinstance(g, str) and g.strip() for g in gold):
            skipped += 1
            continue
        cases.append(RetrievalCase(query=query, gold_docs=[g.strip() for g in gold]))
    logger.info("retrieval 用例加载 path=%s 有效=%d 跳过=%d", path, len(cases), skipped)
    return cases, skipped


def load_chat_cases(path: str | Path) -> tuple[list[ChatCase], int]:
    """加载 chat_e2e.jsonl；坏 JSON / 缺 id / turns 非法（空、角色非法、空内容）→ 跳过。"""
    cases: list[ChatCase] = []
    skipped = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if not isinstance(obj, dict) or not str(obj.get("id", "")).strip():
            skipped += 1
            continue
        turns = obj.get("turns")
        if not isinstance(turns, list) or not turns:
            skipped += 1
            continue
        if not all(
            isinstance(t, dict) and t.get("role") in VALID_ROLES and str(t.get("content", "")).strip()
            for t in turns
        ):
            skipped += 1
            continue
        cases.append(
            ChatCase(
                case_id=str(obj["id"]).strip(),
                path=str(obj.get("path", "")).strip() or "normal",
                turns=[{"role": t["role"], "content": str(t["content"]).strip()} for t in turns],
            )
        )
    logger.info("chat_e2e 用例加载 path=%s 有效=%d 跳过=%d", path, len(cases), skipped)
    return cases, skipped
