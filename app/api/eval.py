"""SP-EVAL-002 评测 API：评测看板数据源（SP-FE-003）。

- `GET /api/v1/eval/runs`：评测运行列表（指标卡 + 消融对比表），
  支持 `?run_type=` 过滤与 `?limit=`（默认 100，上限 500）
- `GET /api/v1/eval/runs/{id}`：单次运行详情；不存在 → 4040
"""
from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, Query

from app.core.config import get_settings
from app.core.responses import err, ok
from app.eval.runs import EvalRunRepo, PostgresEvalRunRepo

logger = logging.getLogger("app.api.eval")

router = APIRouter(prefix="/api/v1/eval", tags=["eval"])


@lru_cache(maxsize=1)
def _build_repo() -> PostgresEvalRunRepo:
    settings = get_settings()
    return PostgresEvalRunRepo(settings.postgres_dsn)


def get_eval_repo() -> EvalRunRepo:
    """评测仓储依赖（测试可 dependency_overrides 注入内存实现）。"""
    return _build_repo()


@router.get("/runs")
async def list_eval_runs(
    run_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    repo: EvalRunRepo = Depends(get_eval_repo),
) -> dict:
    runs = await repo.list_runs(run_type=run_type, limit=limit)
    return ok({"count": len(runs), "runs": [r.as_dict() for r in runs]})


@router.get("/runs/{run_id}")
async def get_eval_run(run_id: int, repo: EvalRunRepo = Depends(get_eval_repo)) -> dict:
    run = await repo.get_run(run_id)
    if run is None:
        return err(4040, 404, f"评测运行不存在: {run_id}")
    return ok({"run": run.as_dict()})
