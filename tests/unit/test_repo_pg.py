"""SP-CHAT-001 消息仓储（SQLite 内存替身跑 SQLAlchemy 代码路径，零外部服务）。

PostgresMessageRepo 与 MemoryMessageRepo 同接口行为对齐：
会话自动创建、消息持久化（历史不受短期上下文 TTL 影响）、时间升序查询、
归属查询、删除清空。
"""
from __future__ import annotations

import pytest

from app.memory.repo import MemoryMessageRepo, PostgresMessageRepo


@pytest.fixture
def pg_repo(tmp_path) -> PostgresMessageRepo:
    """临时文件 SQLite（aiosqlite）替代 PostgreSQL：SQL 兼容，行为等价。"""
    return PostgresMessageRepo(f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")


@pytest.mark.spec("SP-CHAT-001")
class TestPostgresMessageRepo:
    async def test_ensure_session_and_owner(self, pg_repo: PostgresMessageRepo) -> None:
        assert await pg_repo.get_session_owner("s1") is None
        await pg_repo.ensure_session("s1", "user-1")
        assert await pg_repo.get_session_owner("s1") == "user-1"
        await pg_repo.ensure_session("s1", "user-2")  # 幂等：不覆盖 owner
        assert await pg_repo.get_session_owner("s1") == "user-1"

    async def test_add_and_list_ordered(self, pg_repo: PostgresMessageRepo) -> None:
        await pg_repo.ensure_session("s1", "user-1")
        m1 = await pg_repo.add_message("s1", "user", "第一问", intent="pre_sales", conf=0.95)
        m2 = await pg_repo.add_message(
            "s1", "assistant", "回复内容", intent="pre_sales", conf=0.95, agent_route="qa_agent"
        )

        messages = await pg_repo.list_messages("s1")
        assert [m.content for m in messages] == ["第一问", "回复内容"]  # 时间升序
        assert messages[0].intent == "pre_sales" and messages[0].conf == 0.95
        assert messages[1].agent_route == "qa_agent"
        assert m1.id < m2.id
        assert "created_at" in messages[0].as_dict()

    async def test_history_survives_independent_of_ttl(self, pg_repo: PostgresMessageRepo) -> None:
        """历史在 PG 持久保留；短期上下文（Redis TTL）是另一条存储路径。"""
        await pg_repo.ensure_session("s1", "user-1")
        await pg_repo.add_message("s1", "user", "旧消息")
        # 无 Redis 侧操作，历史不受影响
        assert len(await pg_repo.list_messages("s1")) == 1

    async def test_delete_session(self, pg_repo: PostgresMessageRepo) -> None:
        await pg_repo.ensure_session("s1", "user-1")
        await pg_repo.add_message("s1", "user", "x")
        await pg_repo.delete_session("s1")
        assert await pg_repo.list_messages("s1") == []
        assert await pg_repo.get_session_owner("s1") is None

    async def test_memory_repo_parity(self) -> None:
        """内存实现与 PG 实现行为对齐（同协议）。"""
        mem = MemoryMessageRepo()
        assert await mem.get_session_owner("s1") is None
        await mem.ensure_session("s1", "user-1")
        await mem.add_message("s1", "user", "问", intent="refund", conf=0.9)
        await mem.add_message("s1", "assistant", "答", agent_route="qa_agent")
        msgs = await mem.list_messages("s1")
        assert [m.content for m in msgs] == ["问", "答"]
        assert msgs[0].intent == "refund" and msgs[1].agent_route == "qa_agent"
        await mem.delete_session("s1")
        assert await mem.list_messages("s1") == []
