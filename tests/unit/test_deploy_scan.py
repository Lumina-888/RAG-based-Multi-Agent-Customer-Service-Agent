"""SP-DEP-002 配置外置（T-DEP-201，CI 密钥扫描）：仓库无密钥硬编码。

扫描范围（规格口径："占位符不在 docker-compose/代码中"）：
- docker-compose.yml / Dockerfile / deploy/ / app/ / scripts/ / frontend/src/
- 规则：`your_*_key_here` 占位符 与 疑似真实密钥（sk-* / AIza*）均不得出现
- `.env.example` 允许占位符（规格：不含真实值即可）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

#: 扫描范围（相对仓库根）
SCAN_PATHS = ("docker-compose.yml", "Dockerfile", "deploy", "app", "scripts", "frontend/src")
#: 允许含占位符的文件（模板，不含真实值）
PLACEHOLDER_ALLOWED = (".env.example",)

_PLACEHOLDER_RE = re.compile(r"your_[a-z_]+_key_here")
#: 疑似真实密钥形态（示例密钥不在仓库中，命中即视为泄漏）
_REAL_KEY_RE = re.compile(r"(sk-[A-Za-z0-9]{20,}|AIza[0-9A-Za-z_-]{20,})")


def _scan_files() -> list[Path]:
    files: list[Path] = []
    for entry in SCAN_PATHS:
        path = REPO / entry
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files += [p for p in path.rglob("*") if p.is_file()]
    return files


@pytest.mark.spec("SP-DEP-002")
class TestSecretScan:
    def test_dep_201_no_placeholder_in_code_or_compose(self) -> None:
        """占位符不得出现在代码 / compose / 部署配置中。"""
        for path in _scan_files():
            if path.name in PLACEHOLDER_ALLOWED:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not _PLACEHOLDER_RE.search(text), f"占位符泄漏: {path}"

    def test_dep_201_no_real_api_keys(self) -> None:
        """仓库扫描范围不得出现疑似真实密钥。"""
        for path in _scan_files():
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert not _REAL_KEY_RE.search(text), f"疑似真实密钥: {path}"

    def test_dep_201_example_has_placeholders_only(self) -> None:
        """.env.example 仅含占位符（无真实值）。"""
        example = (REPO / ".env.example").read_text(encoding="utf-8")
        assert "your_deepseek_api_key_here" in example
        assert not _REAL_KEY_RE.search(example)

    def test_dep_201_compose_has_no_secrets_env(self) -> None:
        """docker-compose.yml 不得出现密钥类环境变量名。"""
        compose = (REPO / "docker-compose.yml")
        if not compose.exists():
            pytest.skip("docker-compose.yml 未创建")
        text = compose.read_text(encoding="utf-8")
        for secret_key in ("DEEPSEEK_API_KEY", "MIMO_API_KEY", "EMBEDDING_API_KEY"):
            assert secret_key not in text, f"compose 中出现密钥变量 {secret_key}（密钥仅来自 .env）"
