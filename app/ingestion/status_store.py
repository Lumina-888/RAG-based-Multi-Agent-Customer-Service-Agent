"""KB 文档索引状态存储（SP-ING-004 补充）：上传者可查的处理进度。

- `RedisDocStatusStore`：`kb:doc:{doc_id}` → JSON 记录（TTL 7 天）
- `MemoryDocStatusStore`：进程内实现（单测 / 无 Redis 场景）

记录字段：`doc_id / filename / status(processing|done|failed) /
chunks / error / updated_at`。状态写入为尽力而为：存储不可用时只记
日志，不阻断上传与索引主流程。
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Protocol

import redis.asyncio as aioredis

#: 状态记录保留时长（秒）：7 天，足够上传者事后查询，过期视为不存在
DOC_STATUS_TTL_SECONDS = 7 * 24 * 3600


class DocStatusStore(Protocol):
    """文档状态存储协议（Fake 可注入）。"""

    async def mark(
        self,
        doc_id: str,
        status: str,
        *,
        filename: str = "",
        chunks: int | None = None,
        error: str | None = None,
    ) -> None: ...

    async def get(self, doc_id: str) -> dict | None: ...


def _record(
    doc_id: str,
    status: str,
    filename: str,
    chunks: int | None,
    error: str | None,
) -> dict:
    return {
        "doc_id": doc_id,
        "filename": filename,
        "status": status,
        "chunks": chunks,
        "error": error,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


class RedisDocStatusStore:
    """Redis 实现：`kb:doc:{doc_id}` → JSON 状态记录。"""

    def __init__(self, redis_url: str, client=None) -> None:
        self._redis = client if client is not None else aioredis.from_url(
            redis_url, decode_responses=True
        )

    @staticmethod
    def _key(doc_id: str) -> str:
        return f"kb:doc:{doc_id}"

    async def mark(
        self,
        doc_id: str,
        status: str,
        *,
        filename: str = "",
        chunks: int | None = None,
        error: str | None = None,
    ) -> None:
        record = _record(doc_id, status, filename, chunks, error)
        await self._redis.set(
            self._key(doc_id), json.dumps(record), ex=DOC_STATUS_TTL_SECONDS
        )

    async def get(self, doc_id: str) -> dict | None:
        raw = await self._redis.get(self._key(doc_id))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def aclose(self) -> None:
        await self._redis.aclose()


class MemoryDocStatusStore:
    """进程内实现：带 TTL 语义，供单测与无 Redis 场景注入。"""

    def __init__(self, ttl: int = DOC_STATUS_TTL_SECONDS) -> None:
        self._records: dict[str, tuple[dict, float]] = {}
        self._ttl = ttl

    async def mark(
        self,
        doc_id: str,
        status: str,
        *,
        filename: str = "",
        chunks: int | None = None,
        error: str | None = None,
    ) -> None:
        record = _record(doc_id, status, filename, chunks, error)
        self._records[doc_id] = (record, time.monotonic() + self._ttl)

    async def get(self, doc_id: str) -> dict | None:
        item = self._records.get(doc_id)
        if item is None:
            return None
        record, expires_at = item
        if time.monotonic() > expires_at:
            del self._records[doc_id]
            return None
        return record
