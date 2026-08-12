"""SP-CFG-003 项目骨架：T-CFG-301 / T-CFG-302。

- T-CFG-301 pytest 可直接运行，collect 用例数 > 0
- T-CFG-302 import app 及其子模块无异常
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.spec("SP-CFG-003")
def test_cfg_301_pytest_collect_count() -> None:
    """`pytest --collect-only` 收集用例数 > 0（规格 §0.4/§5 约定 pytest 开箱可用）。"""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", str(PROJECT_ROOT / "tests")],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    match = re.search(r"(\d+) tests? collected", result.stdout)
    assert match, f"未解析到收集数量: {result.stdout}"
    assert int(match.group(1)) > 0


@pytest.mark.spec("SP-CFG-003")
def test_cfg_302_import_app_ok() -> None:
    """`import app` 及核心子模块无异常。"""
    import app  # noqa: F401
    import app.core  # noqa: F401
    import app.services  # noqa: F401
