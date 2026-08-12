"""SP-EVAL-002 eval_runs 读写（内存 repo + SQLite 替身跑 SQLAlchemy 代码路径）。

- MemoryEvalRunRepo：内存实现（CI / 演示）
- PostgresEvalRunRepo：eval_runs 表（SQLite 临时文件替身，SQL 兼容行为等价，
  同 test_repo_pg.py 的 PG 守卫模式）；真实 PG 在 M9 起服务后由集成层覆盖
- 覆盖：record → list（新→旧）、run_type 过滤、detail、metrics JSON 往返
"""
from __future__ import annotations

import pytest

from app.eval.runs import EvalRun, MemoryEvalRunRepo, PostgresEvalRunRepo


@pytest.fixture
def pg_repo(tmp_path) -> PostgresEvalRunRepo:
    return PostgresEvalRunRepo(f"sqlite+aiosqlite:///{tmp_path / 'eval.db'}")


@pytest.mark.spec("SP-EVAL-002")
class TestEvalRunRepo:
    async def test_memory_record_and_list_newest_first(self) -> None:
        repo = MemoryEvalRunRepo()
        r1 = await repo.record_run(run_type="ablation", name="E1_bm25", metrics={"recall@5": 0.8})
        r2 = await repo.record_run(run_type="intent", name="intent-baseline", metrics={"acc": 0.9})
        assert isinstance(r1, EvalRun) and r1.id < r2.id
        runs = await repo.list_runs()
        assert [r.name for r in runs] == ["intent-baseline", "E1_bm25"]  # 新→旧
        assert runs[0].metrics == {"acc": 0.9}
        # run_type 过滤 + detail
        assert [r.name for r in await repo.list_runs(run_type="ablation")] == ["E1_bm25"]
        assert (await repo.get_run(r1.id)).name == "E1_bm25"  # type: ignore[union-attr]
        assert await repo.get_run(999) is None
        assert "created_at" in r1.as_dict()

    async def test_postgres_record_and_list_roundtrip(self, pg_repo: PostgresEvalRunRepo) -> None:
        await pg_repo.record_run(
            run_type="ablation", name="E3_rrf",
            metrics={"recall@5": 0.66, "mrr": 0.5, "ndcg@5": 0.72},
        )
        await pg_repo.record_run(run_type="ragas", name="faithfulness", metrics={"f": 0.83})
        runs = await pg_repo.list_runs()
        assert len(runs) == 2
        assert runs[0].name == "faithfulness"  # 新→旧
        assert runs[1].metrics["recall@5"] == pytest.approx(0.66)  # JSON 往返
        assert (await pg_repo.get_run(runs[1].id)).run_type == "ablation"  # type: ignore[union-attr]
        assert await pg_repo.get_run(404) is None

    async def test_postgres_list_filter_and_empty(self, pg_repo: PostgresEvalRunRepo) -> None:
        await pg_repo.record_run(run_type="intent", name="i1", metrics={"acc": 1.0})
        assert len(await pg_repo.list_runs(run_type="ablation")) == 0
        assert len(await pg_repo.list_runs(run_type="intent")) == 1
        empty = PostgresEvalRunRepo("sqlite+aiosqlite:///:memory:")
        assert await empty.list_runs() == []
