"""SP-CFG-001 配置加载：T-CFG-101 / T-CFG-102。

- T-CFG-101 缺必填 API Key 抛错（fail fast）且报错信息指明缺失项
- T-CFG-102 双 Key 齐备时默认值生效
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.fixture(autouse=True)
def _clean_llm_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """清空可能干扰的 LLM 环境变量，保证用例 hermetic。"""
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_MAIN", raising=False)


@pytest.mark.spec("SP-CFG-001")
class TestConfigRequired:
    def test_cfg_101_missing_deepseek_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MIMO_API_KEY", "mimo-test")
        with pytest.raises(ValidationError) as exc:
            Settings(_env_file=None)
        assert "DEEPSEEK_API_KEY" in str(exc.value)

    def test_cfg_101_missing_mimo_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")
        with pytest.raises(ValidationError) as exc:
            Settings(_env_file=None)
        assert "MIMO_API_KEY" in str(exc.value)

    def test_cfg_101_missing_both_keys_raises(self) -> None:
        with pytest.raises(ValidationError) as exc:
            Settings(_env_file=None)
        msg = str(exc.value)
        assert "DEEPSEEK_API_KEY" in msg
        assert "MIMO_API_KEY" in msg

    def test_cfg_102_defaults_take_effect(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")
        monkeypatch.setenv("MIMO_API_KEY", "mimo-test")
        s = Settings(_env_file=None)
        # 模型路由默认值
        assert s.model_main == "deepseek-v4-flash"
        assert s.model_fallback == "mimo-v2.5"
        assert s.model_vision == "mimo-v2.5"
        # 外部依赖默认值
        assert s.postgres_dsn == "postgresql://postgres:postgres@localhost:5432/smart_agent"
        assert s.redis_url == "redis://localhost:6379/0"
        assert s.es_host == "http://localhost:9200"
        assert s.embedding_model == "bge-m3"
        assert s.embedding_base_url == "https://api.siliconflow.cn/v1"
        # 重排模型默认值（硅基流动 bge-reranker-v2-m3）
        assert s.reranker_model == "bge-reranker-v2-m3"
        assert s.reranker_base_url == "https://api.siliconflow.cn/v1"
        # MinerU 云端解析默认值（mineru.net）
        assert s.mineru_api_key == ""
        assert s.mineru_base_url == "https://mineru.net"
        # 业务阈值默认值
        assert s.intent_conf_high == 0.85
        assert s.intent_conf_mid == 0.6
        assert s.retrieval_reject_threshold == 0.45

    def test_cfg_102_env_override_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """环境变量可覆盖默认值。"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-test")
        monkeypatch.setenv("MIMO_API_KEY", "mimo-test")
        monkeypatch.setenv("MODEL_MAIN", "deepseek-custom")
        s = Settings(_env_file=None)
        assert s.model_main == "deepseek-custom"
