# RAG-based Multi-Agent Customer Service Agent

> 基于 RAG 的多 Agent 智能客服系统 — Hybrid Retrieval + Intent Recognition + Multi-Agent Orchestration

企业级智能客服系统：以 **BM25 + 向量混合检索** 为核心，结合 **意图识别双路兜底** 与 **多智能体协作**（LangGraph 状态机），实现订单查询、退款工单、转人工等完整业务闭环；全过程**可解释、可评测、可部署**。

> 定位：毕业设计（核心系统）+ 秋招项目 · LLM 全部走云端 API（DeepSeek-V4-flash 主 / mimo-v2.5 备 + 多模态）

---

## 核心亮点

| 亮点 | 说明 |
|---|---|
| 混合检索 | BM25 + 向量检索 + RRF 融合 + 重排（bge-reranker-v2-m3），多组消融实验证明效果 |
| 意图识别双路兜底 | fastText 轻量分类器（主）+ LLM 兜底（辅），置信度分级决策 + 拒答策略 |
| 多 Agent 协作 | LangGraph 状态机驱动：路由 / 问答 / 工具 / 工单 / 转人工 Agent |
| 全链路可观测 | SSE 过程事件（intent → route → retrieval → tool_call → message → done），前端追踪面板可视化 |
| 可评测 | RAGAS 指标 + 自建测试集 + E1~E5 消融对比实验 |
| 可部署 | Docker Compose 一键起，Nginx 反代 + 限流，SSE 流式输出 |
| 企业规范 | 退款工单状态机 + 部分唯一索引幂等防重 + 审计留痕 + AI 不直接触达资金 |

## 架构总览

```
┌─────────────── 前端 (Vue3 + Element Plus) ───────────────┐
│  客服对话页 · Agent 追踪面板 · 评测看板 · 工单管理          │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTPS / SSE 流式
┌───────────────────────▼──────────────────────────────────┐
│ 接入层  Nginx（反代 / 静态资源 / 限流）                     │
┌───────────────────────▼──────────────────────────────────┐
│ 服务层  FastAPI (Python 3.11)                              │
│  意图识别 · 路由 Agent · 问答 Agent · 工具 Agent · 工单 Agent │
│  编排：LangGraph 状态机 / 会话记忆(Redis) / SSE 流式引擎     │
│  检索：BM25(ES) + 向量(ES dense_vector) + RRF + reranker   │
└──────────┬──────────────────────────────┬─────────────────┘
           │                              │
┌──────────▼──────────────┐  ┌────────────▼───────────────┐
│ 数据层                   │  │ 外部依赖（全部云端 API）      │
│ PostgreSQL: 会话/工单/评测 │  │ DeepSeek-V4-flash（主模型）  │
│ Redis: 会话上下文/限流计数  │  │ mimo-v2.5（备 + 图片理解）   │
│ ES 8.x: 知识库索引         │  │ 硅基流动 bge-m3 / bge-reranker-v2-m3
│                          │  │ MinerU 云端文档解析（mineru.net）
└──────────────────────────┘  └────────────────────────────┘
```

## 技术栈

| 层次 | 选型 | 说明 |
|---|---|---|
| 语言 / Web | Python 3.11+ / FastAPI / Uvicorn | 异步、自带 OpenAPI 文档 |
| 编排 | LangGraph | 状态机式 Agent 编排 |
| 意图识别 | fastText（主）+ LLM（兜底） | 轻量分类器，本地加载（唯一本地模型） |
| 稀疏检索 | Elasticsearch 8.x（BM25） | ES 原生 |
| 向量检索 | ES 8.x `dense_vector` + kNN | 少一个中间件 |
| 融合 / 重排 | ES 原生 RRF + bge-reranker-v2-m3 | 重排走硅基流动云端 API |
| LLM | DeepSeek-V4-flash（主）/ mimo-v2.5（备 + 多模态） | 云端 API，主备降级 |
| Embedding | bge-m3（硅基流动 API，dim=1024） | 中文友好 |
| 文档解析 | MinerU 云端 API（mineru.net） | PDF/Word → Markdown，异步任务 |
| 存储 | PostgreSQL 16 / Redis 7 | 会话、工单、评测 / 缓存 |
| 前端 | Vue 3 + Vite + Element Plus | 构建产物由 FastAPI 托管 |
| 部署 | Docker Compose + Nginx | 多阶段构建，单镜像 |

## 开发进度（SDD/TDD 驱动）

| 模块 | 规格 | 优先级 | 状态 |
|---|---|---|---|
| M0 配置与骨架 | SP-CFG | P0 | **已交付** |
| M1 文档解析与索引 | SP-ING | P0 | 待开发 |
| M2 混合检索 | SP-RET | P0 | 待开发 |
| M3 意图识别 | SP-INT | P0 | 待开发 |
| M4 会话与对话 API | SP-CHAT / SP-SSE | P0 | 待开发 |
| M5 Agent 编排 | SP-AGENT | P0 | 待开发 |
| M6 退款服务 | SP-REF | P0 | 待开发 |
| M7 评测体系 | SP-EVAL | P1 | 待开发 |
| M8 前端页面 | SP-FE | P1 | 待开发 |
| M9 部署 | SP-DEP | P1 | 待开发 |
| M10 安全与限流 | SP-SEC | P0/P1 | 待开发 |

## 快速开始

### 环境要求
- Python 3.11+
- （可选）Docker Compose（集成测试 / 部署时需要 ES / PostgreSQL / Redis）

### 1. 安装依赖

```bash
python -m venv .venv
# Linux/macOS
.venv/bin/pip install -r requirements-dev.txt
# Windows
.venv\Scripts\pip install -r requirements-dev.txt
```

> 国内网络可加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 加速。

### 2. 配置环境变量

```bash
cp .env.example .env   # Windows: copy .env.example .env
```

编辑 `.env`，填写以下必填项（**真实密钥仅存本地，不入库**）：

| 变量 | 说明 | 必填 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 主模型 | 是 |
| `MIMO_API_KEY` | mimo 备用 + 图片理解 | 是 |
| `EMBEDDING_API_KEY` | 硅基流动 bge-m3（M1 起用） | 否 |
| `RERANKER_API_KEY` | 硅基流动 bge-reranker-v2-m3（M2 起用） | 否 |
| `MINERU_API_KEY` | mineru.net 文档解析（M1 起用） | 否 |

> 设计上 **fail fast**：缺失必填 Key 时应用启动即报错并指明缺失项，不静默使用假值。

### 3. 运行测试

```bash
pytest tests/unit                                    # 单元测试（快，不依赖外部服务）
pytest -k "SP-CFG-001"                               # 按规格 ID 过滤
pytest --cov=app/core --cov=app/services --cov-report=term-missing   # 覆盖率
```

### 4. 启动开发服务器

```bash
uvicorn app.main:app --reload
# 健康检查：GET http://localhost:8000/api/v1/health
# 接口文档：http://localhost:8000/docs
```

## 项目结构

```
rag-multi-agent-customer-service/
├── app/
│   ├── main.py              # FastAPI 入口（/api/v1/health）
│   ├── core/                # 配置(pydantic-settings) / 统一 JSON 日志（含脱敏）
│   ├── services/            # llm.py 统一 LLM 封装（主备路由/降级） / embedding.py
│   ├── api/  agents/  intent/  retrieval/  ingestion/  memory/  eval/  models/
│   └── ...                  # 后续模块按规格逐步交付
├── tests/
│   ├── unit/                # 单元测试（纯函数，<5s 全量）
│   ├── integration/         # 集成测试（需 ES/Redis/PostgreSQL）
│   ├── e2e/                 # SSE 全链路
│   └── bench/               # 压测脚本
├── data/                    # 原始文档 / 训练集 / 测试集
├── models/intent/           # fastText 意图模型产物
├── frontend/                # Vue3 前端
├── scripts/                 # 运维 / 批处理脚本
├── docs/                    # 文档
├── pyproject.toml           # pytest 配置（asyncio、spec marker）
├── requirements.txt / requirements-dev.txt
├── .env.example             # 环境变量模板（占位符，无真实值）
└── Spec_规格说明_SDD_TDD.md / 技术设计文档_智能客服多Agent系统.md
```

## 开发方法论：SDD + TDD

本项目采用**规格驱动开发 + 测试驱动开发**：先写可验证的行为规格（`Spec_规格说明_SDD_TDD.md`），再按 `规格 → 测试(Red) → 实现(Green) → 重构(Refactor)` 循环交付，每个测试用例以 `@pytest.mark.spec("SP-XXX")` 标注规格归属，可用 `pytest -k "SP-XXX"` 按规格回归。

## 文档

- [技术设计文档](技术设计文档_智能客服多Agent系统.md) — 架构 / 检索 / 意图 / Agent 编排 / 退款规范 / 部署
- [规格说明（SDD + TDD）](Spec_规格说明_SDD_TDD.md) — 逐模块可执行规格与验收标准

## 安全说明

- `.env` 已被 `.gitignore` 排除，真实密钥永不入库
- `.env.example` 仅含占位符（SP-DEP-002）
- 日志自动脱敏：手机号 / 订单号打码（SP-CFG-002）
- 退款链路：AI 只受理 + 预审 + 建单，不直接触达资金（SP-REF-007）

## License

MIT License（待定，可自行调整）
