# RAG-based Multi-Agent Customer Service Agent

> 基于 RAG 的多 Agent 智能客服系统 — Hybrid Retrieval + Intent Recognition + Multi-Agent Orchestration

企业级智能客服系统：以 **BM25 + 向量混合检索** 为核心，结合 **意图识别双路兜底** 与 **多智能体协作**（LangGraph 状态机），实现订单查询、退款工单、转人工等完整业务闭环；全过程**可解释、可评测、可部署、可审计**。

> 定位：毕业设计（核心系统）+ 秋招项目 · LLM 全部走云端 API（DeepSeek-V4-flash 主 / mimo-v2.5 备 + 多模态）

---

## 核心亮点

| 亮点 | 说明 |
|---|---|
| 混合检索 | BM25 + 向量检索 + RRF 融合 + 重排（bge-reranker-v2-m3），E1~E5 消融实验证明效果 |
| 意图识别双路兜底 | fastText 轻量分类器（主）+ LLM 兜底（辅），置信度分级决策 + 拒答/情绪升级策略 |
| 多 Agent 协作 | LangGraph 状态机驱动：路由 / 问答 / 工具 / 工单 / 转人工 Agent，CONFIRM 二次确认 |
| 全链路可观测 | SSE 过程事件（intent → route → retrieval → tool_call → message → done），前端追踪面板可视化 + 事件重放 |
| 可评测 | RAGAS 指标 + 三格式自建测试集 + E1~E5 消融对比实验，评测结果落库（eval_runs） |
| 安全合规 | 登录认证 / Bearer Token 鉴权（4010/4030）、注入防护（样本集 41 条 + 规则检出 ≥90%）、回复统一脱敏 |
| 可部署 | Docker Compose 一键起（pg16/redis7/es8.8/app/nginx），Nginx 反代 + 限流，SSE 流式输出 |
| 企业规范 | 退款工单状态机 + 部分唯一索引幂等防重 + 审计留痕 + AI 不直接触达资金（资金边界 4091） |

## 架构总览

```
┌─────────────── 前端 (Vue3 + Element Plus + Pinia) ──────────┐
│  客服对话页 · Agent 追踪面板 · 评测看板 · 工单管理            │
└───────────────────────┬──────────────────────────────────┘
                        │ HTTPS / SSE 流式
┌───────────────────────▼──────────────────────────────────┐
│ 接入层  Nginx（反代 / 静态资源 / 限流 4290 / SSE 关闭缓冲）  │
┌───────────────────────▼──────────────────────────────────┐
│ 服务层  FastAPI (Python 3.11)                              │
│  认证鉴权 · 意图识别 · 路由/问答/工具/工单/转人工 Agent      │
│  编排：LangGraph 状态机 / 会话记忆(Redis) / SSE 流式引擎     │
│  检索：BM25(ES) + 向量(ES dense_vector) + RRF + reranker   │
│  退款：预审规则 · 状态机 · 幂等 · 审计 · 注入拦截            │
└──────────┬──────────────────────────────┬─────────────────┘
           │                              │
┌──────────▼──────────────┐  ┌────────────▼───────────────┐
│ 数据层                   │  │ 外部依赖（全部云端 API）      │
│ PostgreSQL: 会话/工单/    │  │ DeepSeek-V4-flash（主模型）  │
│   评测(eval_runs)/审计    │  │ mimo-v2.5（备 + 图片理解）   │
│ Redis: 会话上下文/限流计数  │  │ 硅基流动 bge-m3 / bge-reranker-v2-m3
│ ES 8.x: 知识库索引         │  │ MinerU 云端文档解析（mineru.net）
│ data/: 演示文档/测试集/安全 │  │                          │
└──────────────────────────┘  └────────────────────────────┘
```

## 技术栈

| 层次 | 选型 | 说明 |
|---|---|---|
| 语言 / Web | Python 3.11+ / FastAPI / Uvicorn | 异步、自带 OpenAPI 文档 |
| 编排 | LangGraph | 状态机式 Agent 编排 |
| 意图识别 | fastText（主）+ LLM（兜底） | 轻量分类器，本地加载（唯一本地模型） |
| 稀疏检索 | Elasticsearch 8.8（BM25） | ES 原生 |
| 向量检索 | ES 8.x `dense_vector` + kNN | 少一个中间件 |
| 融合 / 重排 | ES 原生 RRF + bge-reranker-v2-m3 | 重排走硅基流动云端 API |
| LLM | DeepSeek-V4-flash（主）/ mimo-v2.5（备 + 多模态） | 云端 API，主备降级 |
| Embedding | bge-m3（硅基流动 API，dim=1024） | 中文友好 |
| 文档解析 | MinerU 云端 API（mineru.net） | PDF/Word → Markdown，异步任务 |
| 存储 | PostgreSQL 16 / Redis 7 | 会话、工单、评测、审计 / 会话上下文 |
| 认证 | 登录接口 + Bearer Token | 全链路 4010/4030 鉴权 |
| 前端 | Vue 3 + Vite + Element Plus + Pinia | Vitest 单测，构建产物由 FastAPI 托管 |
| 部署 | Docker Compose + Nginx | 多阶段构建，单镜像 |

## 开发进度（SDD/TDD 驱动，P0/P1 全部交付）

| 模块 | 规格 | 优先级 | 状态 | 关键产出 |
|---|---|---|---|---|
| M0 配置与骨架 | SP-CFG-001~004 | P0 | ✅ 已交付 | 配置 fail-fast、JSON 日志（脱敏）、FakeLLM/FakeEmbedding 注入体系 |
| M1 文档解析与索引 | SP-ING-001~005 | P0 | ✅ 已交付 | Markdown/MinerU 解析、结构感知分块、幂等索引、KB API、图片理解 |
| M2 混合检索 | SP-RET-001~007 | P0 | ✅ 已交付 | BM25/向量/RRF 纯函数/动态权重/重排、hybrid_search、bench 脚本 |
| M3 意图识别 | SP-INT-001~004 | P0 | ✅ 已交付 | fastText 分类器（acc≥85%）、置信度分级决策、拒答与情绪升级 |
| M4 会话与对话 API | SP-CHAT / SP-SSE | P0 | ✅ 已交付 | SSE 事件协议（四路径）、会话管理（PG + Redis TTL）、事件重放、E2E 12 条 |
| M5 Agent 编排 | SP-AGENT-001~005 | P0 | ✅ 已交付 | LangGraph 状态机、工具契约（归属 4030）、CONFIRM 二次确认、转人工摘要 |
| M6 退款服务 | SP-REF-001~008 | P0 | ✅ 已交付 | 预审规则引擎、状态机+审计、幂等（部分唯一索引）、资金边界（4091） |
| M7 评测体系 | SP-EVAL-001~003 | P1 | ✅ 已交付 | 三格式测试集加载、纯函数指标（Recall@5/MRR/NDCG@5/宏F1）、RAGAS、eval_runs 落 PG、E1~E5 消融 |
| M8 前端页面 | SP-FE-001~003 | P1 | ✅ 已交付 | SSE 解析器+事件状态机（Vitest 20 例）、对话页角标溯源、追踪面板、评测看板、工单受限迁移 |
| M9 部署 | SP-DEP-001~003 | P1 | ✅ 已交付 | Compose 一键起、多阶段 Dockerfile、启动训练 fastText、Nginx 限流 4290、密钥扫描、冒烟 |
| M10 安全与限流 | SP-SEC-001~003 | P0/P1 | ✅ 已交付 | 认证鉴权（4010/4030）、注入防护（41 条样本检出 ≥90%）、回复统一脱敏 |
| W4 数据与联调 | T-API-101~106 等 | 收尾 | ✅ 已交付 | 102 份演示文档（售后政策/商品手册/FAQ + 噪声）、批量上传、api_smoke 逐项探测 |

**测试基线**：后端 340 个测试（311 passed + 29 skipped，skipped 均为外部服务守卫）+ 前端 Vitest 20 个全绿；核心模块覆盖率 90%+（app/eval 95%、app/security 90%）。

> 剩余收尾（服务在线后执行）：`pytest -m integration` 全量实跑、性能验收（100 文档 + bench 脚本）、真实 API Key 联调。详见 [docs/待开发文档_W4.md](docs/待开发文档_W4.md)。

## API 一览

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/v1/health` | 健康检查 |
| POST | `/api/v1/auth/login` | 登录，签发 Bearer Token |
| POST | `/api/v1/chat` | 对话（SSE 流式：intent/route/retrieval/tool_call/message/done） |
| GET/DELETE | `/api/v1/sessions/{session_id}/messages` | 会话消息读取 / 会话删除 |
| POST | `/api/v1/kb/documents` | 知识库文档上传与索引 |
| GET | `/api/v1/kb/search` | 知识库检索 |
| POST | `/api/v1/refund-requests` | 退款受理（预审 + 建单，幂等） |
| GET | `/api/v1/tickets` / `/tickets/{id}/audit` | 工单列表 / 审计留痕 |
| POST | `/api/v1/tickets/{id}/transition` | 工单状态流转（受限：仅合法状态迁移） |
| GET | `/api/v1/eval/runs` / `/runs/{run_id}` | 评测运行记录 |

## 快速开始

### 环境要求
- Python 3.11+
- （推荐）Docker Compose —— 一键起 ES / PostgreSQL / Redis / 应用 / Nginx

### 方式 A：Docker Compose 一键部署（推荐）

```bash
cp .env.example .env        # Windows: copy .env.example .env
docker compose up -d --build
scripts/smoke_test.sh       # 冒烟：服务健康 + 核心接口
# 前端（由 FastAPI/Nginx 托管）：http://localhost:8080
# 接口文档：http://localhost:8000/docs
```

### 方式 B：本地开发

```bash
python -m venv .venv
# Linux/macOS
.venv/bin/pip install -r requirements-dev.txt
# Windows
.venv\Scripts\pip install -r requirements-dev.txt
```

> 国内网络可加 `-i https://pypi.tuna.tsinghua.edu.cn/simple` 加速。

### 配置环境变量

编辑 `.env`，填写以下必填项（**真实密钥仅存本地，不入库**）：

| 变量 | 说明 | 必填 |
|---|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 主模型 | 是 |
| `MIMO_API_KEY` | mimo 备用 + 图片理解 | 是 |
| `EMBEDDING_API_KEY` | 硅基流动 bge-m3（索引/检索） | 否 |
| `RERANKER_API_KEY` | 硅基流动 bge-reranker-v2-m3（重排） | 否 |
| `MINERU_API_KEY` | mineru.net 文档解析 | 否 |

> 设计上 **fail fast**：缺失必填 Key 时应用启动即报错并指明缺失项，不静默使用假值。

### 运行测试

```bash
pytest tests/unit                                    # 单元测试（快，不依赖外部服务）
pytest -m integration                               # 集成测试（需 ES/Redis/PG 在线）
pytest -k "SP-REF-001"                              # 按规格 ID 过滤
pytest --cov=app/core --cov=app/services --cov-report=term-missing   # 覆盖率
```

### 启动开发服务器

```bash
uvicorn app.main:app --reload
# 健康检查：GET http://localhost:8000/api/v1/health
# 接口文档：http://localhost:8000/docs
```

## 项目结构

```
rag-multi-agent-customer-service/
├── app/
│   ├── main.py              # FastAPI 入口（/api/v1/health，路由挂载）
│   ├── core/                # 配置(pydantic-settings) / 统一 JSON 日志（含脱敏）
│   ├── services/            # llm.py 统一 LLM 封装（主备路由/降级） / embedding / es / erp_sim / refund_gateway / chat_flow
│   ├── api/                 # auth / chat(SSE) / sessions / kb / refund / eval
│   ├── agents/              # LangGraph 编排：router / qa / tool / transfer / graph
│   ├── intent/  retrieval/  ingestion/  memory/  eval/  refund/  security/
│   ├── auth/                # 登录 + Bearer Token 存储
│   └── seed/                # 演示用户种子数据
├── tests/
│   ├── unit/                # 单元测试（纯函数，<5s 全量）
│   ├── integration/         # 集成测试（需 ES/Redis/PostgreSQL）
│   ├── e2e/                 # SSE 全链路
│   └── bench/               # 检索 / 对话压测脚本
├── data/
│   ├── raw_docs/            # 演示文档（102 份：售后政策/商品手册/FAQ + 噪声）
│   ├── parsed/  seed/  train/  test_cases/  security/
├── models/intent/           # fastText 意图模型产物（启动时训练）
├── frontend/                # Vue3 前端（对话页/追踪面板/评测看板/工单）
├── deploy/nginx.conf        # Nginx 配置（反代/限流/SSE）
├── scripts/                 # 训练 / 数据生成 / 批量上传 / 冒烟 / api_smoke / 密钥扫描
├── docs/                    # 文档（含 W4 待开发清单）
├── docker-compose.yml       # 一键起：pg16 / redis7 / es8.8 / app / nginx
├── Dockerfile               # 多阶段构建，前端 dist 进 app/static
├── pyproject.toml           # pytest 配置（asyncio、spec marker）
├── requirements.txt / requirements-dev.txt
├── .env.example             # 环境变量模板（占位符，无真实值）
└── Spec_规格说明_SDD_TDD.md / 技术设计文档_智能客服多Agent系统.md
```

## 开发方法论：SDD + TDD

本项目采用**规格驱动开发 + 测试驱动开发**：先写可验证的行为规格（`Spec_规格说明_SDD_TDD.md`），再按 `规格 → 测试(Red) → 实现(Green) → 重构(Refactor)` 循环交付，每个测试用例以 `@pytest.mark.spec("SP-XXX")` 标注规格归属，可用 `pytest -k "SP-XXX"` 按规格回归。模块按序合回 main（M0 → M10 → W4），main 即完整交付基线。

## 文档

- [技术设计文档](技术设计文档_智能客服多Agent系统.md) — 架构 / 检索 / 意图 / Agent 编排 / 退款规范 / 部署
- [规格说明（SDD + TDD）](Spec_规格说明_SDD_TDD.md) — 逐模块可执行规格与验收标准
- [W4 待开发文档](docs/待开发文档_W4.md) — 已交付基线 / 剩余收尾清单（集成实跑、性能验收、真实 Key 联调）

## 安全说明

- `.env` 已被 `.gitignore` 排除，真实密钥永不入库；`.env.example` 仅含占位符（SP-DEP-002）
- 日志自动脱敏：手机号 / 订单号打码（SP-CFG-002）
- 登录认证 + Bearer Token 鉴权：未认证 4010、无权限 4030（SP-SEC-003）
- 注入防护：41 条样本集 + 规则检出 ≥90%，工具调用 / 退款建单前置拦截（SP-SEC-001/002）
- 退款链路：AI 只受理 + 预审 + 建单，不直接触达资金；工单状态迁移受限（SP-REF-007）

## License

MIT License（待定，可自行调整）
