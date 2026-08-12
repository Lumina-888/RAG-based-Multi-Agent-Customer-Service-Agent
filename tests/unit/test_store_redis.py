"""SP-CHAT-001 / SP-SSE-001 存储层（fakeredis 替身，零外部服务）。

- RedisSessionStore：短期上下文 TTL（30 分钟，过期即记忆失效）+ 事件序列
  序号化（RPUSH 位置 = SSE id / Last-Event-ID 重放依据）
"""
from __future__ import annotations

import pytest
import fakeredis.aioredis

from app.memory.store import CONTEXT_TTL_SECONDS, RedisSessionStore


@pytest.fixture
def store() -> RedisSessionStore:
    return RedisSessionStore("redis://localhost:6379/0", ttl=CONTEXT_TTL_SECONDS,
                             client=fakeredis.aioredis.FakeRedis(decode_responses=True))


@pytest.mark.spec("SP-CHAT-001")
class TestRedisSessionStore:
    async def test_context_roundtrip(self, store: RedisSessionStore) -> None:
        assert await store.get_context("s1") == []
        await store.set_context("s1", [{"role": "user", "content": "你好"}])
        assert await store.get_context("s1") == [{"role": "user", "content": "你好"}]

    async def test_context_ttl_expiry(self) -> None:
        """TTL 只影响上下文注入：过期后 get_context 为空（记忆失效）。"""
        import time

        store = RedisSessionStore("redis://x", ttl=1,
                                  client=fakeredis.aioredis.FakeRedis(decode_responses=True))
        await store.set_context("s1", [{"role": "user", "content": "旧上下文"}])
        time.sleep(1.1)  # TTL=1s 过期
        assert await store.get_context("s1") == []

    async def test_events_seq_and_replay(self, store: RedisSessionStore) -> None:
        """事件序号从 1 递增；Last-Event-ID 重放（id > after_id 的事件）。"""
        sid = "s1"
        assert await store.append_event(sid, {"event": "intent", "data": {"intent": "refund"}}) == 1
        assert await store.append_event(sid, {"event": "done", "data": {}}) == 2

        all_events = await store.get_events(sid)
        assert [e["id"] for e in all_events] == [1, 2]
        assert all_events[0]["event"] == "intent"

        after_1 = await store.get_events(sid, after_id=1)
        assert [e["id"] for e in after_1] == [2]  # 只重放 id > 1 的事件

    async def test_clear(self, store: RedisSessionStore) -> None:
        await store.set_context("s1", [{"role": "user", "content": "x"}])
        await store.append_event("s1", {"event": "intent", "data": {}})
        await store.clear("s1")
        assert await store.get_context("s1") == []
        assert await store.get_events("s1") == []
