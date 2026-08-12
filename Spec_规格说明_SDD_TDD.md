# 智能客服多Agent系统 · 规格说明（SDD + TDD）

> 版本：v1.4
> 日期：2026-08-11
> 配套文档：`技术设计文档_智能客服多Agent系统.md`（本文件为其可执行规格层）
> 开发规范：Spec-Driven Development + Test-Driven Development
> 模型基线：DeepSeek-V4-flash（主）/ mimo-v2.5（备用 + 多模态图片理解）
>
> 修订记录（v1.0 → v1.1）：统一意图决策树（SP-INT-003）；新增 SP-SEC-003 认证与鉴权；新增 SP-CFG-004 统一 LLM 封装；新增 SP-ING-004 知识库 API；拆分 SP-RET-005/007（动态权重独立成规）；SSE 补充可选事件（vision）/错误路径/事件重放/图片理解；会话 TTL 语义修正（上下文 vs 历史）；时效规则三档化（SP-REF-003）；幂等改部分唯一索引并允许终态后重新申请（SP-REF-005）；审计字段对齐（SP-REF-008）；限流与压测路径约定（SP-DEP-003 / SP-CHAT-003）；SP-EVAL-001 优先级降为 P1。
> 修订记录（v1.1 → v1.2）：SP-ING-001 增加 MinerU 解析适配器（PDF/Word → Markdown）；新增 SP-ING-005 图片理解注入（mimo-v2.5，含 T-ING-104~106）。
> 修订记录（v1.2 → v1.3）：取消 Ollama 本地兜底与 `LLM_PROVIDER` 配置项，LLM 全部走云端 API；SP-CFG-001 必填项固定为 `DEEPSEEK_API_KEY / MIMO_API_KEY`。
> 修订记录（v1.3 → v1.4）：SP-ING-001 MinerU 解析改走云端 API（mineru.net 异步任务），取消离线本地模型；PDF/Word 解析全程在线；SP-RET-004/006 重排表述统一为硅基流动云端 API。

---

## 0. 方法论与工作流

### 0.1 什么是 SDD + TDD（本项目如何执行）

- **SDD（规格驱动）**：先写"可验证的行为规格"，规格是**代码与需求之间的契约**。开发顺序：`规格 → 测试 → 实现`。
- **TDD（测试驱动）**：实现前先写测试，测试失败（Red）→ 最小实现（Green）→ 重构（Refactor）。

### 0.2 单模块开发循环

```
1. 阅读 Spec-XXX 与验收标准（Given-When-Then）
2. 编写对应测试 tests/test_xxx.py（此时必然失败 = Red）
3. 最小实现通过测试（Green）
4. 重构 + 跑全量回归（Refactor）
5. 满足该模块 DoD → 将 Spec 状态标记为「已交付」
```

> 铁律：**没有对应测试的代码不算完成**；测试先于实现，实现不得先于测试。

### 0.3 测试金字塔（本项目分层）

```
        ┌──────────┐
        │ E2E      │  tests/e2e/          chat API 全链路（SSE）
        ├──────────┤
        │ 集成     │  tests/integration/  检索/意图/退款服务（真 ES/真 Redis）
        ├──────────┤
        │ 单元     │  tests/unit/         纯函数：RRF/分块/预审规则/幂等/状态机
        └──────────┘
```

- 单元测试必须快（< 5s 全量），不依赖外部服务（用 fake/内存实现）
- 集成测试可依赖 ES/Redis/PostgreSQL（Docker Compose 启动）
- E2E 最少 10 条主流程用例

### 0.4 规格与测试命名规范

| 对象 | 命名 | 示例 |
|---|---|---|
| 规格 | `SP-<模块>-<序号>` | `SP-RET-003` |
| 测试文件 | `tests/<层>/test_<模块>.py` | `tests/unit/test_rrf_fusion.py` |
| 测试用例 | `T-<模块>-<序号>`（`@pytest.mark.spec("SP-RET-003")`） | `T-RET-301` |
| 错误码 | `SP-API-GEN` 统一定义 | `4090` 幂等冲突 |
| Spec 状态 | 待开发 / 开发中 / 已交付 | — |

### 0.5 Definition of Done（通用）

- [ ] 该 Spec 全部测试通过（`pytest -k "SP-XXX"` 全绿）
- [ ] 核心逻辑覆盖率 ≥ 80%（`pytest --cov=app/retrieval` 等）
- [ ] 无阻塞性 TODO / 无跳过未说明的测试
- [ ] 接口契约与 API 文档一致（`/docs` 自动生成）
- [ ] 关键路径日志已加 trace_id

---

## 1. 规格总览

### 1.1 模块 → 规格 → 优先级 → 状态

| 模块 | 规格范围 | 优先级 | 状态 |
|---|---|---|---|
| M0 配置与骨架 | SP-CFG | P0 | 已交付 |
| M1 文档解析与索引 | SP-ING | P0 | 已交付 |
| M2 混合检索 | SP-RET | P0 | 待开发 |
| M3 意图识别 | SP-INT | P0 | 待开发 |
| M4 会话与对话 API | SP-CHAT / SP-SSE | P0 | 待开发 |
| M5 Agent 编排 | SP-AGENT | P0 | 待开发 |
| M6 退款服务 | SP-REF | P0 | 待开发 |
| M7 评测体系 | SP-EVAL | P1 | 待开发 |
| M8 前端页面 | SP-FE | P1 | 待开发 |
| M9 部署 | SP-DEP | P1 | 待开发 |
| M10 安全与限流 | SP-SEC（SP-SEC-003 认证为 P0，其余 P1） | P0 | 待开发 |

> P0 = 核心闭环（W1~W3 必须交付）；P1 = 完善与上线（W4）；P2 = 可选扩展。

### 1.2 全局接口契约（所有 API 遵守）

**响应统一包装：**

```json
{ "code": 0, "message": "ok", "data": {...}, "trace_id": "t_01J..." }
```

**错误码（SP-API-GEN）：**

| code | HTTP | 含义 |
|---|---|---|
| 0 | 200 | 成功 |
| 4001 | 400 | 参数校验失败（缺字段/类型错） |
| 4010 | 401 | 未登录或会话无效 |
| 4030 | 403 | 无权访问（订单不属于当前用户） |
| 4040 | 404 | 资源不存在 |
| 4041 | 404 | 订单不存在 |
| 4090 | 409 | 幂等冲突（重复建单） |
| 4091 | 409 | 非法状态迁移（状态机） |
| 4220 | 422 | 预审规则不通过（data 内带 rule 与 reason） |
| 4290 | 429 | 限流 |
| 5000 | 500 | 内部错误 |
| 5001 | 502 | LLM 服务不可用 |
| 5002 | 503 | 检索服务不可用 |

---

## 2. 逐模块规格

---

### M0 配置与项目骨架（SP-CFG）

#### SP-CFG-001 配置加载（P0）
- **功能**：`app/core/config.py` 用 `pydantic-settings` 从环境变量/`.env` 加载全部配置。
- **规格**：
  - GIVEN 存在 `.env` 文件
  - WHEN 应用启动
  - THEN 加载 `DEEPSEEK_API_KEY / MIMO_API_KEY / POSTGRES_DSN / REDIS_URL / ES_HOST / MODEL_MAIN(deepseek-v4-flash) / MODEL_FALLBACK(mimo-v2.5) / MODEL_VISION(mimo-v2.5) / EMBEDDING_MODEL` 等，缺失必填项抛错并给出明确提示（必填项：`DEEPSEEK_API_KEY / MIMO_API_KEY`，仅云端 API，无本地模型分支）
- **测试**：`tests/unit/test_config.py` → `T-CFG-101`（缺 key 抛错）、`T-CFG-102`（默认值生效）。
- **DoD**：配置缺项启动即失败（fail fast），不静默使用假值。

#### SP-CFG-002 统一日志（P0）
- **规格**：GIVEN 任一请求, WHEN 记录日志, THEN 日志为 JSON 格式且必含 `trace_id / ts / level / module`；敏感字段（订单号、手机号）自动打码。
- **测试**：`T-CFG-201`（JSON schema 校验）、`T-CFG-202`（脱敏正则生效）。

#### SP-CFG-003 项目骨架（P0）
- **规格**：目录结构遵循设计文档 §7.1；`pytest` 可直接运行（`pytest.ini`/`pyproject.toml` 已配置 asyncio 模式与 spec marker）。
- **测试**：`T-CFG-301`（collect 数 > 0）、`T-CFG-302`（`import app` 无异常）。

#### SP-CFG-004 统一 LLM 封装与模型路由（P0）
- **功能**：`app/services/llm.py` 统一封装主/备/多模态模型路由。
- **规格**：
  - GIVEN 文本生成/工具调用/意图确认请求, WHEN 调用 `llm.chat(...)`, THEN 默认走主模型 `MODEL_MAIN`（deepseek-v4-flash）
  - GIVEN 主模型超时或连续失败 2 次, WHEN 重试, THEN 自动降级 `MODEL_FALLBACK`（mimo-v2.5）；主备均失败才映射错误码 5001
  - GIVEN 用户消息含图片附件, WHEN 调用 `llm.vision(...)`, THEN 使用 `MODEL_VISION`（mimo-v2.5）理解图片并返回结构化描述
  - THEN 所有调用支持 FakeLLM 注入（CI 单测不依赖真实 API）
- **测试**：`tests/unit/test_llm_router.py` → `T-CFG-401`（主模型正常）、`T-CFG-402`（主失败自动降级）、`T-CFG-403`（主备均失败 → 5001）、`T-CFG-404`（vision 路由 mimo-v2.5）、`T-CFG-405`（FakeLLM 注入生效）。

---

### M1 文档解析与索引（SP-ING）

#### SP-ING-001 文档解析（P0）
- **功能**：`app/ingestion/parser.py` 支持 Markdown / PDF / Word 输入，输出结构化文档；PDF/Word 走 MinerU 云端 API 适配器（mineru.net 异步任务）。
- **规格**：
  - GIVEN 一份含表格的 Markdown 文档
  - WHEN 调用 `parse(path)`
  - THEN 返回 `Document{title, source, version, sections[]}`，表格保留为 Markdown 表格字符串
  - THEN 页眉/页脚噪声被去除
  - GIVEN 一份 PDF 文档（文本型或扫描型）
  - WHEN 调用 `parse(path)`
  - THEN 经 MinerU 云端 API 解析为 Markdown（标题层级/表格/多栏重排/扫描件 OCR 由 MinerU 处理），再统一清洗输出结构化文档；抽取的图片走 SP-ING-005
- **测试**：`tests/unit/test_parser.py` → `T-ING-101`（表格保留）、`T-ING-102`（噪声去除）、`T-ING-103`（非法文件抛 `UnsupportedFormatError`）。

#### SP-ING-002 结构感知分块（P0）
- **功能**：`app/ingestion/chunker.py` 按标题层级切块。
- **规格**：
  - GIVEN 文档含 H1/H2/H3 层级
  - WHEN 调用 `chunk(doc, size=400, overlap=50)`
  - THEN 块不跨 H1 标题、默认块长 300~500 token、相邻块重叠 50 token、每块带 `heading_path` 元数据
  - THEN 一条完整 FAQ 不被拆进两个块
- **测试**：`tests/unit/test_chunker.py` → `T-ING-201`（不跨标题）、`T-ING-202`（重叠正确）、`T-ING-203`（FAQ 完整性）。

#### SP-ING-003 索引写入 ES（P0）
- **功能**：`app/ingestion/indexer.py` 幂等写入 ES `kb_chunks` 索引。
- **规格**：
  - GIVEN 分块列表与 `doc_id`
  - WHEN 调用 `index_chunks(chunks)`
  - THEN 全部写入成功，同 `doc_id` 重复索引覆盖旧数据（幂等，chunk `_id=doc_id-seq` 确定性生成）
  - THEN 每条含 embedding（bge-m3，dim=1024）与元数据字段（含 `embedding_ver`，模型升级时全量重建）
- **测试**：`tests/integration/test_indexer.py`（需 ES）→ `T-ING-301`（写入计数正确）、`T-ING-302`（重复索引无重复文档）。

#### SP-ING-004 知识库管理 API（P1）
- **规格**：`POST /api/v1/kb/documents` 上传文档（异步 解析→分块→索引，返回 `doc_id` 与状态）；`GET /api/v1/kb/search?q=` 调试用混合检索原始结果。
- **测试**：`tests/integration/test_kb_api.py` → `T-ING-401`（上传后索引完成）、`T-ING-402`（search 返回结果）。

#### SP-ING-005 图片理解注入（P0，v1.2 新增）
- **功能**：MinerU 云端解析抽取的文档图片经 `MODEL_VISION`（mimo-v2.5）多模态理解，转文本后注入 Markdown（图片本身不可被 BM25/向量检索，必须文本化）。
- **规格**：
  - GIVEN MinerU 云端解析结果含图片列表
  - WHEN 执行图片理解流程
  - THEN 装饰性图片（宽高 < 300px / 纯色占比高 / logo 类）被跳过，不调用 LLM
  - THEN 信息图（截图/表单/流程图等）经 `llm.vision()`（mimo-v2.5）生成结构化描述，以 `【图N 内容：...】` 文本块注入原图位置
  - THEN 单文档图片理解数 ≤ 20 张，超出部分跳过并计数报告
  - THEN 图片理解走 `llm.vision()` 封装，FakeLLM 可注入（SP-CFG-004），单元测试不依赖真实 API
- **测试**：`tests/unit/test_parser_images.py` → `T-ING-104`（信息图描述注入 md）、`T-ING-105`（装饰性图片跳过且无 LLM 调用）、`T-ING-106`（超上限计数报告）。

---

### M2 混合检索（SP-RET）

#### SP-RET-001 BM25 检索（P0）
- **规格**：GIVEN 已索引知识库, WHEN 调用 `bm25_search(q, top_k=10)`, THEN 返回 `[{chunk_id, title, content, score}]` 按相关度降序；标题字段权重为内容 2 倍。
- **测试**：`tests/integration/test_bm25.py` → `T-RET-101`（关键词精确命中排前）。

#### SP-RET-002 向量检索（P0）
- **规格**：GIVEN 查询 q, WHEN 调用 `vector_search(q, top_k=10)`, THEN 返回含 `score` 的结果并按相似度降序；中文语义近义查询（"退货" ↔ "退款"）能召回。
- **测试**：`T-RET-201`（语义召回）、`T-RET-202`（维度与 embedding 模型一致）。

#### SP-RET-003 RRF 融合（P0）核心
- **功能**：`app/retrieval/fusion.py` 纯函数。
- **规格**：
  - GIVEN BM25 与向量两路 `[(doc_id, rank)]`
  - WHEN `rrf_fuse(bm25_results, vector_results, k=60)`
  - THEN 按 `Σ 1/(k+rank)` 降序融合；只出现在一路的文档正常参与；空列表输入返回空
  - THEN 相同 doc_id 只出现一次
  - THEN 生产静态融合可用 ES 原生 `rank:{rrf:{}}`（行为对标）；动态权重必须走本函数（ES 原生不支持按路加权）
- **测试**：`tests/unit/test_rrf_fusion.py` → `T-RET-301`（公式正确）、`T-RET-302`（双路都在前列的排前）、`T-RET-303`（空输入）、`T-RET-304`（去重）。

#### SP-RET-004 重排（P1）
- **规格**：GIVEN top-20 候选, WHEN `rerank(q, docs, top_k=5)`, THEN 返回 top-5；与问答 Agent 输入顺序一致。
- **测试**：`T-RET-401`（候选数=5）、`T-RET-402`（无效输入抛错）。
- **备注**：重排走硅基流动 bge-reranker-v2-m3 云端 API；性能不达标不作为验收阻塞（SP-RET-006 豁免口径）。

#### SP-RET-005 混合检索入口（P0）
- **规格**：`hybrid_search(q, strategy="rrf"|"dynamic")` 返回 `{docs, strategy, elapsed_ms}`；默认 `rrf`（静态，ES 原生 RRF）；`dynamic` 走自研加权融合（见 SP-RET-007）。
- **测试**：`tests/integration/test_hybrid.py` → `T-RET-501`（默认 RRF 通路）、`T-RET-502`（结果非空且含来源）。

#### SP-RET-007 动态权重（P1）
- **规格**：查询粗分类（规则：实体库/关键词密度/长度，fastText 兜底）→ 实体/关键词查询 `w_bm25=1.5, w_vec=1.0`，语义查询 `w_bm25=1.0, w_vec=1.5`；加权 RRF 在 `fusion.py` 内实现（ES 原生 RRF 不支持按路加权）。
- **测试**：`T-RET-503`（dynamic 在关键词查询上 ≥ rrf 基线，消融数据）。

#### SP-RET-006 检索性能（P0）
- **规格**：本地 ES，单查询 P95 < 500ms（含融合，不含重排）；重排 P95 < 800ms（硅基流动 bge-reranker-v2-m3 API）。
- **测试**：`T-RET-601`（基准测试脚本 `tests/bench/bench_retrieval.py`）。

---

### M3 意图识别（SP-INT）

#### SP-INT-001 意图体系（P0）
- **规格**：分类器输出为 6 类之一：`pre_sales / after_sales / order_query / refund / complaint / human`；非法输入（空串/超长 >200 字符）返回 `invalid`。
- **测试**：`tests/unit/test_intent.py` → `T-INT-101`（6 类合法）、`T-INT-102`（空串/超长）。

#### SP-INT-002 轻量分类器（P0）
- **规格**：
  - GIVEN 训练集（每类 ≥ 200 条）
  - WHEN 训练 fastText 并预测
  - THEN 测试集 Accuracy ≥ 85%，`order_query` 与 `refund` 混淆可控（F1 ≥ 0.8）
- **测试**：`tests/integration/test_intent_model.py` → `T-INT-201`（acc 门槛）、`T-INT-202`（混淆矩阵断言）。
- **产物**：训练后落盘 `models/intent/fasttext.bin`，启动时加载；fastText softmax 概率未校准，0.85/0.6 阈值在验证集校准后写入配置。

#### SP-INT-003 置信度分级决策（P0）
- **规格**：决策函数 `decide(intent, conf, llm_result)`：
  - `conf ≥ 0.85` → 返回 `{action: "route", intent}`（不依赖 LLM，主备均不可用时仍可路由）
  - `0.6 ≤ conf < 0.85` → 触发 LLM 二次确认（主模型 DeepSeek-V4-flash），返回 LLM 结果；LLM 不可用 → `{action: "clarify"}`
  - `conf < 0.6` → 触发 LLM 兜底分类（主 → 备 mimo-v2.5 降级）；LLM 结果仍低置信或解析失败 → `{action: "clarify"}`
  - 主备均不可用（5001）→ 统一降级为 `{action: "clarify"}`
- **测试**：`tests/unit/test_intent_decision.py` → `T-INT-301`（高置信直路由）、`T-INT-302`（中置信二次确认）、`T-INT-303`（低置信兜底/澄清）、`T-INT-304`（5001 降级路径）。

#### SP-INT-004 拒答与情绪升级（P0）
- **规格**：辱骂词表或高强度重复标点 → 返回 `{action: "transfer"}`；知识库 top-1 相似度 < `RETRIEVAL_REJECT_THRESHOLD`（默认 0.45，可配置）→ 问答 Agent 拒答模板。
- **测试**：`T-INT-401`（辱骂触发转人工）、`T-INT-402`（低相似度拒答）。

---

### M4 会话与对话 API（SP-CHAT / SP-SSE）

#### SP-CHAT-001 会话管理（P0）
- **规格**：
  - GIVEN `session_id` 不存在的 POST 请求（客户端生成 UUID v4）, WHEN 发送消息, THEN 自动创建会话
  - 短期上下文 Redis TTL 30 分钟：过期后新消息不再注入旧上下文（记忆失效）；**消息历史在 PostgreSQL 持久保留**，不受 TTL 影响
  - `GET /sessions/{id}/messages` 返回按时间升序消息列表，含 `intent / conf / agent_route`；会话归属校验（4030）
  - `DELETE /sessions/{id}` 清空会话
- **测试**：`tests/integration/test_sessions.py` → `T-CHAT-101`（自动建会话）、`T-CHAT-102`（上下文 TTL 失效但历史可查）、`T-CHAT-103`（历史查询）。

#### SP-CHAT-002 消息入参校验（P0）
- **规格**：`POST /api/v1/chat` body：`{session_id: string(必填), message: string(必填, 1~500字符), attachments?: [{type: "image", url}]}`；不合法返回 4001（流开始前返回统一 JSON，非 SSE）。
- **图片理解**：含 `attachments` 图片时由 `MODEL_VISION`（mimo-v2.5）异步理解（不影响首响），结果经 `vision` 事件透出并注入检索/回答上下文。
- **测试**：`T-CHAT-201`（缺字段）、`T-CHAT-202`（超长）、`T-CHAT-203`（图片附件 → 出现 vision 事件）。

#### SP-SSE-001 SSE 事件协议（P0）
- **规格**：`POST /api/v1/chat` 返回 `text/event-stream`，事件顺序固定：`intent → route → (vision) → (retrieval) → (tool_call) → message(增量) → done`；`vision/retrieval/tool_call` 按路径可选：
  - 正常问答：`intent → route → retrieval → message → done`
  - 澄清路径：`intent → route → message → done`（无 retrieval）
  - 转人工路径：`intent → route → message → done`（由 `done.transfer` 标记）
  - 图片路径：`intent → route → vision → ...`（异步，不影响首响）
- 每条事件 `data` 为合法 JSON；`message` 事件 `delta=true` 时追加渲染，`delta=false` 为该条消息结束；**必须兜底发送 `done`**（含错误时 `data.error = {code, message}`）；`intent` 事件先发 fastText 结果（首响预算内），`route` 事件携带 LLM 修正后的最终 `intent/conf`
- 流开始前校验失败（4001）：返回统一 JSON（非 SSE），无任何事件
- 事件序列持久化至 Redis（`session:{id}:events`），断线重连支持重放（`Last-Event-ID`）
- **测试**：`tests/e2e/test_chat_sse.py` → `T-SSE-101`（事件顺序断言，覆盖正常/澄清/转人工/图片四路径，E2E 总用例 ≥ 10 条）、`T-SSE-102`（JSON 合法性）、`T-SSE-103`（错误路径必有 done）。

#### SP-CHAT-003 首响性能（P0）
- **规格**：首条 SSE 事件（intent）延迟 P95 < 2s；完整回复 P95 < 15s；20 并发不报错。
- **测试**：`T-CHAT-301`（并发压测脚本 `tests/bench/bench_chat.py`，**直连 app:8000 绕过 Nginx 限流**）。

---

### M5 Agent 编排（SP-AGENT）

#### SP-AGENT-001 路由规则（P0）
- **规格**：路由表：`order_query→tool_agent`、`refund→refund_agent(工单)`、`complaint/human→transfer_agent`、`pre_sales/after_sales→qa_agent`；未知意图不路由，走澄清。
- **测试**：`tests/unit/test_router.py` → `T-AGENT-101`（全映射正确）、`T-AGENT-102`（未知意图澄清）。

#### SP-AGENT-002 问答 Agent 强制引用（P0）
- **规格**：
  - GIVEN 检索结果 top-5 与用户问题, WHEN 生成回答
  - THEN 回答中每个事实性论点标注来源角标 `[n]`（n 对应检索文档）
  - THEN 无来源支撑的陈述不得出现（由提示词约束 + faithful 校验）
  - THEN 低相似度（top-1 < `RETRIEVAL_REJECT_THRESHOLD`，默认 0.45）时输出拒答模板，不编造
- **测试**：`tests/integration/test_qa_agent.py` → `T-AGENT-201`（引用角标存在）、`T-AGENT-202`（拒答触发）、`T-AGENT-203`（faithfulness 门槛 ≥ 0.8）。

#### SP-AGENT-003 工具调用契约（P0）
- **规格**：工具 `query_order(order_id)` 与 `create_refund_request(...)` 参数由 LLM Function Calling 解析；参数非法时**不得**调用真实服务，返回澄清；工具结果以结构化 JSON 进入回复上下文。
- **归属校验**：`query_order` 调用前校验 `order.user_id == 当前用户`，不符返回 4030 且不返回任何订单数据。
- **二次确认**：`create_refund_request` 为敏感操作，调用前必须经 CONFIRM 节点用户确认（未确认不得建单）；取消则澄清并放弃。
- **测试**：`tests/integration/test_tools.py` → `T-AGENT-301`（合法参数调用）、`T-AGENT-302`（非法参数不调用+澄清）、`T-AGENT-303`（他人订单 4030）、`T-AGENT-304`（未确认不建单）。

#### SP-AGENT-004 状态机编排（P0）
- **规格**：LangGraph 状态含 `{messages, intent, conf, route, tool_calls, retrieved_docs, ticket_id, transfer_needed, pending_confirm}`；敏感操作（建单）进入 CONFIRM 节点挂起等待用户确认（`pending_confirm=true`，挂起期间仅接受"确认/取消"）；每个节点执行后状态可序列化回放；异常节点不中断整条链（走兜底回复）。
- **测试**：`tests/integration/test_graph.py` → `T-AGENT-401`（全流程一次通过）、`T-AGENT-402`（中途异常走兜底）。

#### SP-AGENT-005 转人工（P0）
- **规格**：转人工时生成会话摘要（问题、已提供信息、订单号），摘要写入 Redis，前端显示"已转接人工坐席 1001"。
- **测试**：`T-AGENT-501`（摘要生成）、`T-AGENT-502`（状态落库）。

---

### M6 退款服务（SP-REF）企业规范核心

#### SP-REF-001 建单入参契约（P0）
- **规格**：`POST /api/v1/refund-requests` body：`{order_id, refund_type: only_refund|return_refund, reason, amount}`；`refund_type` 非法返回 4001；`amount` 必填（由前端/Agent 从订单实付金额取值），必须 > 0 且 ≤ 订单实付金额；未发货订单仅允许 `only_refund`（`return_refund` → 4220 + 引导）。
- **接口定位**：建单走 `/api/v1/refund-requests`；管理/审计走 `/api/v1/tickets*`（列表/详情/审计/受限流转，见 SP-REF-008）。
- **测试**：`tests/unit/test_refund_validate.py` → `T-REF-101`（类型枚举）、`T-REF-102`（金额边界）。

#### SP-REF-002 身份与归属校验（P0）
- **规格**：GIVEN 请求带 user_id, WHEN 校验, THEN `order.user_id == user_id` 否则返回 4030；订单不存在返回 4041；未登录返回 4010。
- **测试**：`tests/integration/test_refund_service.py` → `T-REF-201`（归属不符拒绝）、`T-REF-202`（订单不存在）、`T-REF-203`（正常通过）。

#### SP-REF-003 订单状态与时效预审（P0）
- **规格**：预审规则（规则引擎，非 LLM）：
  - 未发货 → 通过（`refund_type=only_refund`；`return_refund` → 4220 + 引导改 only_refund）
  - 已发货未签收 → 仅可"拦截/拒收"，直接退款拒绝（4220 + 引导）
  - 已签收，签收 ≤ 7 天 → 无理由退货或质量问题（`return_refund`）
  - 已签收，7 天 < 签收 ≤ 15 天 → 仅质量问题（附凭证）
  - 已签收，签收 > 15 天 → 4220 + 转人工
- **测试**：`T-REF-301~305`（各状态/时效分支，断言错误码与 rule 字段）。

#### SP-REF-004 金额/频次风控（P1）
- **规格**：单笔 > ¥2000 或 30 天内退款 > 3 次 → 4220 + `review_required=true`；该单进入人工审核。
- **测试**：`T-REF-401`（超阈值转审核）。

#### SP-REF-005 幂等防重（P0）
- **规格**：幂等键 `(user_id, order_id, refund_type)`；存在**进行中**申请单（CREATED/APPROVING/APPROVED/REFUNDING）→ 返回 4090 + `data.existing_ticket_id`；并发双请求只建一单（DB **部分唯一索引**兜底：仅约束进行中状态，捕获唯一冲突返回 4090 而非 5000）；终态（REJECTED/REFUNDED/FAILED）后同键允许重新申请。
- **测试**：`tests/unit/test_refund_idempotency.py` → `T-REF-501`（重复建单拒绝）、`T-REF-502`（并发竞态只建一单，用线程/异步并发测试）、`T-REF-503`（驳回后同键可重新申请）。

#### SP-REF-006 状态机（P0）
- **规格**：合法迁移：`CREATED→APPROVING→APPROVED→REFUNDING→REFUNDED`、`APPROVING→REJECTED`、`REFUNDING→FAILED`；其余迁移抛 4091；`REJECTED/REFUNDED/FAILED` 为终态；每次迁移写审计日志。
- **测试**：`tests/unit/test_refund_state_machine.py` → `T-REF-601`（合法链）、`T-REF-602`（非法迁移拒绝）、`T-REF-603`（终态不可再转）、`T-REF-604`（审计写入）。

#### SP-REF-007 资金操作边界（P0）
- **规格**：Agent/API 只能创建 `CREATED` 状态申请单；**没有任何接口允许 AI 直接触发打款**；`REFUNDING` 仅由内部审核服务（模拟人工）触发，且带操作人记录（自动审核通过时操作人记为 `system_auto`）；前端工单页状态流转仅允许受限迁移（APPROVING→APPROVED/REJECTED）。
- **测试**：`T-REF-701`（公开 API 无法绕过审核直接打款）。

#### SP-REF-008 审计留痕（P1）
- **规格**：`refund_audit_log` 记录每次流转 `{ticket_id, operator, action, from_status, to_status, reason, ts}`；`GET /api/v1/tickets/{id}/audit` 可回溯某单全生命周期；`GET /api/v1/tickets?status=` 支持列表查询；`POST /api/v1/tickets/{id}/transition` 仅模拟坐席/内部审核服务可调（带操作人，受限迁移）。
- **测试**：`T-REF-801`（全链路审计可查）、`T-REF-802`（列表/审计接口冒烟）。

---

### M7 评测体系（SP-EVAL）

#### SP-EVAL-001 测试集加载（P1）
- **规格**：`data/test_cases/` 支持 `intent.csv`、`retrieval.jsonl`、`chat_e2e.jsonl` 三种格式；非法行跳过并计数报告。
- **测试**：`tests/unit/test_case_loader.py` → `T-EVAL-101`（加载计数）、`T-EVAL-102`（非法行跳过）。

#### SP-EVAL-002 指标计算（P1）
- **规格**：意图 Accuracy/宏F1/混淆矩阵；检索 Recall@5/MRR/NDCG@5；RAGAS faithfulness/answer_relevancy；结果写入 `eval_runs`。
- **测试**：`tests/unit/test_metrics.py` → `T-EVAL-201`（Recall@5 手工样本验证）。

#### SP-EVAL-003 消融实验跑批（P1）
- **规格**：一键跑 E1~E5（仅BM25 / 仅向量 / RRF / RRF+重排 / 动态权重），输出对比表 JSON，可被前端看板渲染。
- **测试**：`tests/integration/test_ablation.py` → `T-EVAL-301`（5 组策略均可执行）。

---

### M8 前端页面（SP-FE）

#### SP-FE-001 对话页（P0）
- **规格**：消息气泡 + Markdown 渲染 + SSE 流式打字机；快捷指令；消息带引用角标 `[n]` hover 显示来源片段。
- **测试**：E2E 见下。

#### SP-FE-002 追踪面板（P0）
- **规格**：接收 SSE `intent/route/retrieval/tool_call` 事件渲染时间线（意图+置信度、检索 Top5+分数、工具参数与结果、每步耗时）；消息流与时间线自动滚动。
- **测试**：`tests/e2e/test_frontend.spec.js`（Playwright，P1 补充）。

#### SP-FE-003 评测看板与工单页（P1）
- **规格**：评测看板渲染 `eval_runs` 指标卡与消融对比表；工单页列表/详情/审计回溯/状态流转展示（流转仅限模拟坐席的受限迁移，不得直接触发 REFUNDING）。

> 前端测试策略：核心逻辑（事件解析、状态管理）用 Vitest 单测；页面交互用 Playwright 冒烟（P1，若时间不足可只保对话页 + 追踪面板冒烟）。

---

### M9 部署（SP-DEP）

#### SP-DEP-001 Docker Compose 一键起（P0）
- **规格**：`docker compose up -d` 后，`/api/v1/health` 返回 200 且依赖（postgres/redis/es）均 healthy；应用镜像为多阶段构建（前端产物打进 FastAPI 静态目录）。
- **测试**：`scripts/smoke_test.sh` → `T-DEP-101`（health 探测）、`T-DEP-102`（首页 200）。

#### SP-DEP-002 配置外置（P0）
- **规格**：所有密钥/地址仅来自环境变量；`docker-compose.yml` 无明文密钥；提供 `.env.example` 且不含真实值。
- **测试**：`T-DEP-201`（grep 检查仓库无密钥硬编码——CI 脚本）。

#### SP-DEP-003 Nginx 与限流（P1）
- **规格**：Nginx 反代 + `limit_req`（默认 30 req/s）+ gzip（`text/event-stream` 除外）+ HTTPS（证书可自签演示）；SSE 需 `proxy_buffering off` 与 `proxy_read_timeout ≥ 120s`；限流命中 429 时经 `error_page` 返回统一 JSON（`code=4290`）。
- **测试**：`T-DEP-301`（Nginx 层压测触发 4290 且响应体为统一包装）；`bench_chat` 直连 app 端口（20 并发不受限流影响，见 SP-CHAT-003）。

---

### M10 安全（SP-SEC）

#### SP-SEC-001 Prompt 注入防护（P0）
- **规格**：注入样本集（≥ 30 条，如"忽略以上指令"）通过率 ≥ 90%；用户输入与系统提示词之间加分隔标记；敏感工具（建单）执行前二次确认（编排层 CONFIRM 节点，见 SP-AGENT-004）。
- **测试**：`tests/integration/test_security.py` → `T-SEC-101`（注入样本门槛）、`T-SEC-102`（二次确认拦截）。

#### SP-SEC-002 敏感信息（P1）
- **规格**：日志与回复中手机号/订单号脱敏；演示数据无真实个人信息。
- **测试**：`T-SEC-201`（日志脱敏断言）。

#### SP-SEC-003 认证与鉴权（P0，v1.1 新增）
- **规格**：
  - GIVEN 未认证请求访问受保护接口（退款建单/订单查询/会话历史）, WHEN 请求到达, THEN 返回 4010
  - GIVEN 已认证用户访问他人订单/工单/会话, WHEN 归属校验, THEN 返回 4030 且不泄露数据
  - 演示环境：`POST /api/v1/auth/login`（一键/账号密码）返回 `user_id + token`；请求带 `Authorization: Bearer`（内部可简化为 `X-User-Id` 头）
- **测试**：`tests/integration/test_auth.py` → `T-SEC-301`（未认证 4010）、`T-SEC-302`（越权 4030）、`T-SEC-303`（登录后正常访问）。

---

## 3. 测试数据规范

| 数据 | 位置 | 用途 | 规格引用 |
|---|---|---|---|
| 原始文档 | `data/raw_docs/*.md` | 解析/分块/索引 | SP-ING |
| 解析产物缓存 | `data/parsed/`（MinerU 输出 md + images） | 坏文档只重解析单篇，避免整体重跑 | SP-ING-001 |
| 意图训练集 | `data/train/intent_train.csv` | fastText 训练 | SP-INT-002 |
| 意图测试集 | `data/test_cases/intent.csv` | 意图门槛 | SP-INT-002 |
| 检索标注 | `data/test_cases/retrieval.jsonl` | Recall/MRR/NDCG | SP-EVAL-002 |
| E2E 对话 | `data/test_cases/chat_e2e.jsonl` | 全链路 | SP-SSE-001 |
| 注入样本 | `data/security/prompt_injection.jsonl` | 安全门槛 | SP-SEC-001 |
| 模拟订单 | `data/seed/orders.py`（或 SQL） | 退款/工具测试 | SP-REF |
| 意图模型产物 | `models/intent/fasttext.bin` | 运行时加载 | SP-INT-002 |
| 模拟用户 | `data/seed/users.py`（演示账号） | 认证/归属测试 | SP-SEC-003 |

---

## 4. 开发排期（SDD/TDD 视角）

| 周 | 交付（按 Spec） | 测试目标 |
|---|---|---|
| W1 | SP-CFG、SP-ING、SP-RET(P0) | 单元测试全绿；`T-RET-601` 性能达标 |
| W2 | SP-INT、SP-CHAT、SP-SSE、SP-SEC-003 | 意图门槛 85%；SSE E2E 首条通过；认证闭环可用 |
| W3 | SP-AGENT、SP-REF | 退款全链路 E2E（含 4090/4220/4030 错误路径） |
| W4 | SP-EVAL、SP-FE、SP-DEP、SP-SEC（003 已于 W2 交付） | 消融 5 组跑通；Docker 一键起；覆盖率报告 |

---

## 5. 附录：pytest 配置骨架

```toml
# pyproject.toml (节选)
[tool.pytest.ini_options]
asyncio_mode = "auto"
markers = ["spec: 对应规格ID", "slow: 慢测试（默认跳过）", "integration: 需要外部服务"]
addopts = "-m 'not slow' --strict-markers"

# 常用命令
pytest tests/unit                                  # 单元（快）
pytest -m integration                             # 集成（需 docker compose up -d）
pytest -k "SP-REF-006"                           # 按规格跑（pytest 9 表达式语法）
pytest --cov=app/retrieval --cov-report=term-missing  # 覆盖率
```
