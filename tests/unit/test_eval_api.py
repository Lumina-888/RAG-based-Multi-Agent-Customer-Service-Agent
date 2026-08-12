"""SP-EVAL-002 API 层（离线，内存 repo 注入）：评测看板数据源（SP-FE-003）。

- `GET /api/v1/eval/runs`：评测运行列表（指标卡 + 消融对比表数据源），
  支持 `?run_type=` 过滤与 `?limit=`
- `GET /api/v1/eval/runs/{id}`：单次运行详情；不存在 → 4040
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import eval as eval_api
from app.eval.runs import MemoryEvalRunRepo


@pytest.fixture
def client() -> tuple[TestClient, MemoryEvalRunRepo]:
    app = FastAPI()
    app.include_router(eval_api.router)
    repo = MemoryEvalRunRepo()
    app.dependency_overrides[eval_api.get_eval_repo] = lambda: repo
    return TestClient(app), repo


@pytest.mark.spec("SP-EVAL-002")
class TestEvalRunsApi:
    def test_list_empty_and_after_record(self, client: tuple[TestClient, MemoryEvalRunRepo]) -> None:
        client, repo = client
        resp = client.get("/api/v1/eval/runs")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0 and resp.json()["data"]["count"] == 0

        import asyncio

        asyncio.run(
            repo.record_run(
                run_type="ablation", name="E1_bm25", metrics={"recall@5": 0.8, "mrr": 0.6}
            )
        )
        asyncio.run(repo.record_run(run_type="intent", name="i1", metrics={"acc": 0.9}))
        data = client.get("/api/v1/eval/runs").json()["data"]
        assert data["count"] == 2
        assert data["runs"][0]["name"] == "i1"  # 新→旧
        assert data["runs"][0]["metrics"]["acc"] == 0.9

    def test_filter_and_detail(self, client: tuple[TestClient, MemoryEvalRunRepo]) -> None:
        client, repo = client
        import asyncio

        run = asyncio.run(
            repo.record_run(run_type="ablation", name="E3_rrf", metrics={"recall@5": 0.66})
        )
        filtered = client.get("/api/v1/eval/runs", params={"run_type": "ablation"}).json()["data"]
        assert filtered["count"] == 1 and filtered["runs"][0]["name"] == "E3_rrf"

        detail = client.get(f"/api/v1/eval/runs/{run.id}").json()
        assert detail["code"] == 0 and detail["data"]["run"]["run_type"] == "ablation"

        missing = client.get("/api/v1/eval/runs/404")
        assert missing.status_code == 404 and missing.json()["code"] == 4040
