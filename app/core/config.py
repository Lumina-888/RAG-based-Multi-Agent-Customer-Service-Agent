"""全局配置（SP-CFG-001）：pydantic-settings 从环境变量 / .env 加载。

- 必填项：`DEEPSEEK_API_KEY / MIMO_API_KEY`（仅云端 API，无本地模型分支）
- 缺失必填项启动即失败（fail fast），不静默使用假值
"""
from __future__ import annotations

from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: 必填的云端 API Key（缺失 → 启动失败）
REQUIRED_API_KEYS = ("DEEPSEEK_API_KEY", "MIMO_API_KEY")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- 应用 ----
    app_name: str = "RAG-based Multi-Agent Customer Service Agent"
    debug: bool = False

    # ---- LLM 云端 API（必填）----
    deepseek_api_key: str = ""
    mimo_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    mimo_base_url: str = "https://api.minimax.chat/v1"

    # ---- 模型路由（SP-CFG-004）----
    model_main: str = "deepseek-v4-flash"
    model_fallback: str = "mimo-v2.5"
    model_vision: str = "mimo-v2.5"

    # ---- LLM 调用参数 ----
    llm_timeout: float = 30.0
    #: 主模型连续失败次数上限，达到后自动降级备模型（SP-CFG-004）
    llm_max_retries: int = 2

    # ---- 外部依赖 ----
    postgres_dsn: str = "postgresql://postgres:postgres@localhost:5432/smart_agent"
    redis_url: str = "redis://localhost:6379/0"
    es_host: str = "http://localhost:9200"

    # ---- Embedding（硅基流动 bge-m3 云端 API；选填，M1 索引 / M2 检索时使用）----
    embedding_model: str = "bge-m3"
    embedding_dim: int = 1024
    embedding_api_key: str = ""
    embedding_base_url: str = "https://api.siliconflow.cn/v1"

    # ---- 重排（硅基流动 bge-reranker-v2-m3 云端 API；选填，SP-RET-004 使用）----
    reranker_model: str = "bge-reranker-v2-m3"
    reranker_api_key: str = ""
    reranker_base_url: str = "https://api.siliconflow.cn/v1"

    # ---- MinerU 云端文档解析（mineru.net 异步 API；选填，SP-ING-001 使用）----
    mineru_api_key: str = ""
    mineru_base_url: str = "https://mineru.net"

    # ---- 意图决策阈值（SP-INT-003）----
    intent_conf_high: float = 0.85
    intent_conf_mid: float = 0.6

    # ---- 检索拒答阈值（SP-INT-004 / SP-AGENT-002）----
    retrieval_reject_threshold: float = 0.45

    @model_validator(mode="after")
    def _validate_required_api_keys(self) -> "Settings":
        missing = [key for key in REQUIRED_API_KEYS if not getattr(self, key.lower())]
        if missing:
            raise ValueError(
                "缺少必填配置项: " + ", ".join(missing)
                + "（仅支持云端 API，请在 .env 或环境变量中配置）"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全局单例配置（启动时加载一次，缺失必填项在此 fail fast）。"""
    return Settings()
