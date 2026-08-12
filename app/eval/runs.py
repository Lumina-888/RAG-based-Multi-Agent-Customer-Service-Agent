"""SP-EVAL-002 评测运行存储：`eval_runs` 落 PG（内存实现供 CI/演示）。

- `record_run(run_type, name, metrics)`：写入一条评测运行（指标卡 / 消融表）
- `list_runs(run_type=None, limit=100)`：按时间新→旧列出；`get_run(id)` 详情
- MemoryEvalRunRepo：进程内实现；PostgresEvalRunRepo：eval_runs 表
  （复用 app.models.db，init_db 自动 create_all）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app.models.db import make_sessionmaker


@dataclass
class EvalRun:
    """一次评测运行：{id, run_type, name, metrics, created_at}。"""

    id: int
    run_type: str
    name: str
    metrics: dict
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "run_type": self.run_type,
            "name": self.name,
            "metrics": self.metrics,
            "created_at": self.created_at.isoformat(),
        }


class EvalRunRepo(Protocol):
    """评测运行仓储协议：内存与 PG 实现同一接口。"""

    async def record_run(self, *, run_type: str, name: str, metrics: dict) -> EvalRun: ...

    async def list_runs(self, run_type: str | None = None, limit: int = 100) -> list[EvalRun]: ...

    async def get_run(self, run_id: int) -> EvalRun | None: ...

    async def aclose(self) -> None: ...


class MemoryEvalRunRepo:
    """内存实现：自增 id，list 新→旧。"""

    def __init__(self) -> None:
        self.runs: list[EvalRun] = []
        self._seq = 0

    async def record_run(self, *, run_type: str, name: str, metrics: dict) -> EvalRun:
        self._seq += 1
        run = EvalRun(
            id=self._seq, run_type=run_type, name=name,
            metrics=dict(metrics), created_at=datetime.now(timezone.utc),
        )
        self.runs.append(run)
        return run

    async def list_runs(self, run_type: str | None = None, limit: int = 100) -> list[EvalRun]:
        items = self.runs if run_type is None else [r for r in self.runs if r.run_type == run_type]
        return list(reversed(items))[:limit]  # 新→旧

    async def get_run(self, run_id: int) -> EvalRun | None:
        return next((r for r in self.runs if r.id == run_id), None)

    async def aclose(self) -> None:
        pass


class PostgresEvalRunRepo:
    """PostgreSQL 实现（eval_runs 表）：惰性建引擎（同 PostgresTicketRepo 模式）。"""

    def __init__(self, dsn: str) -> None:
        self._engine = None
        self._dsn = dsn

    async def _sessionmaker(self):
        from app.models.db import init_db

        if self._engine is None:
            self._engine = await init_db(self._dsn)
        return make_sessionmaker(self._engine)

    async def record_run(self, *, run_type: str, name: str, metrics: dict) -> EvalRun:
        from app.models.db import EvalRunRow

        sm = await self._sessionmaker()
        async with sm() as session:
            row = EvalRunRow(run_type=run_type, name=name, metrics=dict(metrics))
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return EvalRun(
                id=row.id, run_type=row.run_type, name=row.name,
                metrics=row.metrics, created_at=row.created_at,
            )

    async def list_runs(self, run_type: str | None = None, limit: int = 100) -> list[EvalRun]:
        from sqlalchemy import select

        from app.models.db import EvalRunRow

        sm = await self._sessionmaker()
        async with sm() as session:
            stmt = select(EvalRunRow).order_by(EvalRunRow.id.desc()).limit(limit)  # 新→旧
            if run_type:
                stmt = stmt.where(EvalRunRow.run_type == run_type)
            rows = (await session.execute(stmt)).scalars().all()
            return [_row_to_run(r) for r in rows]

    async def get_run(self, run_id: int) -> EvalRun | None:
        from app.models.db import EvalRunRow

        sm = await self._sessionmaker()
        async with sm() as session:
            return _row_to_run(await session.get(EvalRunRow, run_id))

    async def aclose(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()


def _row_to_run(row: Any) -> EvalRun | None:
    if row is None:
        return None
    return EvalRun(
        id=row.id, run_type=row.run_type, name=row.name,
        metrics=row.metrics, created_at=row.created_at,
    )
