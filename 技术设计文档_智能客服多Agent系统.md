# 企业级智能客服多智能体系统 · 技术设计文档

> 版本：v1.4
> 日期：2026-08-11
> 定位：毕业设计（核心系统）+ 秋招项目
> 技术基线：RAG + BM25 混合检索 / 意图识别 / 多智能体协作 / 可线上部署
> LLM 基线：DeepSeek-V4-flash（主模型）/ mimo-v2.5（备用模型 + 多模态图片理解）
>
> 修订记录（v1.0 → v1.1）：统一意图识别决策树；新增认证与鉴权（§7.5）；退款接口路径统一；时效预审三档化（0-7/7-15/>15 天）；幂等改部分唯一索引；审计日志字段对齐；会话记忆与消息历史职责分离；新增 CONFIRM 二次确认节点；query_order 增加归属校验；SSE 补充可选事件（vision）/错误路径/事件重放；模型主备路由（DeepSeek-V4-flash / mimo-v2.5）；限流与压测路径明确；部署资源建议 4C8G。
> 修订记录（v1.1 → v1.2）：解析引擎换用 MinerU（§3.2，PDF/Word → Markdown，离线批处理）；新增图片理解注入（mimo-v2.5，规格 SP-ING-005）。
> 修订记录（v1.2 → v1.3）：取消 Ollama 本地兜底，LLM 全部走云端 API（DeepSeek-V4-flash 主 / mimo-v2.5 备 + 多模态）。
> 修订记录（v1.3 → v1.4）：MinerU 解析改为云端 API（mineru.net 异步任务：提交 → 轮询 → 拉取 Markdown + 图片），取消本地模型权重与离线批处理脚本，PDF/Word 解析全程在线；并同步清理 §2.2/§2.4/§4.4/§10.3 中 embedding/重排的"本地"表述（均走硅基流动云端 API）。

---

## 1. 项目概述

### 1.1 背景与目标

传统企业客服依赖规则脚本 + 人工，存在响应慢、无法处理长尾问题、知识库更新滞后等问题。本项目构建一个**面向电商/零售企业场景**的智能客服多智能体系统：

- 用户以自然语言咨询售前、售后、物流、退款等问题
- 系统通过 **意图识别** 判断用户诉求，路由到对应 **子 Agent**
- 子 Agent 通过 **BM25 + 向量混合检索** 召回企业知识库内容，结合 **工具调用**（订单查询、工单创建）完成真实业务闭环
- 全过程**可解释、可评测、可部署**

### 1.2 核心亮点（简历 / 答辩卖点）

| 亮点 | 说明 |
|---|---|
| 混合检索 | BM25 + 向量检索 + RRF 融合 + 重排，多组消融实验证明效果 |
| 意图识别双路兜底 | 轻量分类器（主）+ LLM 兜底（辅），置信度分级 + 拒答策略 |
| 多 Agent 协作 | LangGraph 状态机驱动的路由/问答/工具/工单 Agent 协作 |
| 可观测 | Agent 全链路过程追踪（意图→检索→工具→决策），前端可视化 |
| 可评测 | RAGAS 指标 + 自建 100 条测试集 + 消融对比实验 |
| 可部署 | Docker Compose 一键部署，Nginx 反向代理，SSE 流式输出 |

### 1.3 名词约定

- **RAG**：Retrieval-Augmented Generation，检索增强生成
- **BM25**：经典稀疏检索算法（ES 内置），擅长关键词精确匹配
- **RRF**：Reciprocal Rank Fusion，倒数排名融合，用于混合检索结果合并
- **Agent**：具备"感知-决策-行动"能力的智能体，可调用工具
- **SSE**：Server-Sent Events，服务端单向事件流，用于流式输出

---

## 2. 总体架构

### 2.1 架构图

```
┌────────────────────────────── 前端 (Vue3 + Element Plus) ──────────────────────────────┐
│  [客服对话页]  [Agent 追踪面板]  [评测看板]  [工单管理]                                      │
└──────────────┬───────────────────────────────────────────────────────────────┘
               │ HTTPS / SSE 流式
┌──────────────▼────────────────────────────┐
│ 接入层  Nginx（反代 / 静态资源 / 限流）      │
└──────────────┬────────────────────────────┘
┌──────────────▼──────────────────────────────────────────────────────────────┐
│ 服务层  FastAPI (Python 3.11)                                                │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐                 │
│  │ 意图识别 │ │ 路由     │ │ 问答     │ │ 工具调用 │ │ 工单     │   Agent 层     │
│  │ 双路分类 │ │ Agent   │ │ Agent   │ │ Agent   │ │ Agent   │                 │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘                 │
│  ┌────────────────────────────────────────────────────────────┐              │
│  │ 编排：LangGraph 状态机 / 会话记忆(Redis) / SSE 流式引擎       │              │
│  └────────────────────────────────────────────────────────────┘              │
│  ┌────────────────────────────────────────────────────────────┐              │
│  │ 检索：BM25(ES) + 向量(ES dense_vector) + RRF + reranker    │              │
│  └────────────────────────────────────────────────────────────┘              │
└──────────────┬──────────────────────────────────────────────┬───────────────┘
               │                                              │
┌──────────────▼──────────────┐             ┌─────────────────▼──────────────┐
│ 数据层                       │             │ 外部依赖                       │
│ PostgreSQL: 会话/工单/评测     │             │ LLM: DeepSeek-V4-flash(主)     │
│ Redis: 会话上下文/限流计数     │             │ mimo-v2.5(备+多模态)           │
│ ES 8.x: 知识库索引(文档/分块)  │             │ 模拟 ERP API(订单查询)          │
└─────────────────────────────┘             └────────────────────────────────┘
```

### 2.2 技术栈清单

| 层次 | 选型 | 备注 |
|---|---|---|
| 语言 | Python 3.11 | 熟练 |
| Web 框架 | FastAPI | 异步、自带 OpenAPI 文档 |
| 编排 | LangGraph | 状态机式 Agent 编排 |
| 意图识别 | fastText（主）+ LLM（兜底） | 微调 fastText 或轻量 BERT |
| 稀疏检索 | Elasticsearch 8.x（BM25） | 需新学，见 §3.4 |
| 向量检索 | ES 8.x `dense_vector` + kNN | 减少服务数量；备选 Qdrant |
| 融合/重排 | ES 原生 RRF + bge-reranker-v2-m3 | RRF 需 ES ≥ 8.11 |
| Embedding | bge-m3（硅基流动 API） | 中文友好，dim=1024 |
| LLM | DeepSeek-V4-flash（主）/ mimo-v2.5（备 + 多模态图片理解） | 主备降级 + 多模态路由，见 §2.4 |
| 关系库 | PostgreSQL 16 | 会话、工单、评测 |
| 缓存 | Redis 7 | 会话上下文、流控 |
| 前端 | Vue 3 + Vite + Element Plus | 需新学，见 §8 |
| 部署 | Docker Compose + Nginx | 需新学，见 §10 |

### 2.3 关键设计决策

| 决策 | 理由 |
|---|---|
| ES 一肩挑 BM25 + 向量 | 少一个中间件，降低学习与运维成本；ES 8.11+ 原生支持 RRF |
| SSE 而非 WebSocket | 单向下行足够、代码简单、断线重连容易；面试可讲清取舍 |
| 意图识别"轻分类器 + LLM 兜底" | 主路径快、可控、可离线评测；LLM 兜底提高泛化；置信度分级防误判 |
| 前端由 FastAPI 托管静态产物 | 无跨域、部署单镜像 |
| 模拟 ERP 接口 | 订单/工单走真实 API 契约，数据用模拟服务，不依赖真实业务 |
| 模型主备 + 多模态路由 | DeepSeek-V4-flash 承担文本主路径，mimo-v2.5 承担备用与图片理解 | 主模型故障/超时自动降级；图片理解不挤占文本路径 |

### 2.4 模型路由策略

| 场景 | 模型 | 说明 |
|---|---|---|
| 文本生成 / Function Calling / 意图二次确认 / 兜底分类 | DeepSeek-V4-flash（主） | 默认路径；超时或连续失败（≥ 2 次）自动降级 |
| 备用降级 | mimo-v2.5 | 主模型不可用（5001 前置）时接管文本任务 |
| 多模态图片理解 | mimo-v2.5 | 用户上传图片（商品照片/发票/凭证）时调用，结果注入消息上下文，经 SSE `vision` 事件透出 |
| Embedding | bge-m3（硅基流动 API） | 中文友好，dim=1024 |

- 统一封装在 `app/services/llm.py`：模型路由、超时（首 token / 总时长）、指数退避重试（2 次）、错误码映射（5001）
- 主备均失败 → 按场景降级：意图 → clarify；问答 → 拒答模板；工具 → 澄清
- **测试注入**：`llm.py` 必须支持 FakeLLM 注入，CI/单元测试不依赖真实 API（对应规格 SP-CFG-004）
- 配置项：`MODEL_MAIN（deepseek-v4-flash）/ MODEL_FALLBACK（mimo-v2.5）/ MODEL_VISION（mimo-v2.5）/ DEEPSEEK_API_KEY / MIMO_API_KEY`

---

## 3. 知识库构建（Ingestion）

### 3.1 数据来源

毕设采用**合成 + 公开**数据，避免真实隐私问题：

1. 电商客服 FAQ（自撰 100~200 条）
2. 售后政策文档（公开的电商平台售后规则，脱敏改写）
3. 商品知识文档（虚构 SKU 手册，含表格）
4. 订单系统模拟数据（Redis/PostgreSQL 中 100 条虚拟订单）

### 3.2 文档解析与清洗

```python
# app/ingestion/parser.py —— 职责划分
PDF/Word → MinerU 云端 API（mineru.net：版面解析/标题层级/表格→MD/公式→LaTeX/多栏重排/扫描件 OCR）
   └─ 图片 → mimo-v2.5 多模态理解 → 【图N 内容：…】文本块注入（图片不可直接索引）
Markdown/HTML → 直接读取/轻量转换
清洗：去页眉页脚、去水印噪声、统一全半角、纠错乱码
产出：结构化文档对象（元数据: 来源/版本/更新时间）
```

- MinerU 走**云端 API**（`POST /api/v4/extract/task` 异步提交 → 轮询 `GET /api/v4/extract/task/{task_id}` → 拉取 `full.md` + 图片），无需本地模型权重与离线批处理脚本；解析产物缓存至 `data/parsed/`，坏文档只重解析单篇
- 表格必须结构化保留（转 Markdown 表格），否则 BM25 与向量都检索不到
- 图片必须"转文本"才能被 Embedding 检索：信息图经 mimo-v2.5 描述后以 `【图N 内容：…】` 注入原图位置，装饰性图片（<300px/纯色/logo）跳过以控成本，单文档 ≤ 20 张（规格 SP-ING-005）
- 每条产出带 `source` 元数据，用于最终答案的**引用溯源**

### 3.3 分块策略（结构感知）

- 按标题层级（H1/H2/H3）切分，块大小 **300~500 token，重叠 50 token**
- 段落级语义完整：不把一条 FAQ 拆进两个块
- 为每条 chunk 附加索引元数据：`{doc_id, title, heading_path, seq}`

> 面试点：分块大小是召回率的敏感超参，毕设实验章节做 3 组对比（200/400/800 token），用 §9 的评测体系量化。

### 3.4 索引设计（ES）

```
index: kb_chunks
mapping 要点:
  title          text (BM25)
  content        text (BM25)  +  dense_vector (dim=1024, bge-m3)
  heading_path   text
  doc_id         keyword
  source         keyword
  seq            integer
```

写入流程：`解析 → 分块 → embedding 化 → bulk 写入 ES`。幂等（按 doc_id 覆盖，chunk `_id = doc_id-seq` 确定性生成），支持增量更新；embedding 模型升级时按 `embedding_ver` 全量重建索引。

**新学 ES 的最低范围**：建索引 mapping、`bm25` 查询（match/multi_match）、`knn` 查询、RRF 融合查询（`rank: {rrf: {}}`）、bulk 写入。集群/生命周期/权限均不用碰。

---

## 4. 混合检索模块（核心创新点之一）

### 4.1 检索管线

```
用户查询 q
  ├─ BM25 查询 (multi_match: title^2 + content)  → top-k1
  ├─ 向量查询 (query embedding → knn)           → top-k2
  └─ RRF 融合（k=60, k1=k2=10）                  → top-k   # 静态：ES 原生 rank:{rrf:{}}；动态：自研 Python 加权融合
        ↓
  bge-reranker-v2-m3 重排（query × 20 候选）      → top-5
        ↓
  送入问答 Agent（附带分数与来源）
```

### 4.2 RRF 公式

$$RRF(d) = \sum_{r \in \mathcal{R}} \frac{1}{k + r(d)}$$

- `k` 取 60（经验值），`r(d)` 为文档 d 在各路检索中的排名
- 优点：不依赖分数归一化，两路"尺度不同"的检索可直接融合
- **实现约定**：静态 RRF 用 ES 原生 `rank: {rrf: {}}`（ES ≥ 8.11）；`app/retrieval/fusion.py` 纯函数实现（规格 SP-RET-003）用于单元测试对标与动态权重策略（ES 原生 RRF 不支持按路加权）

### 4.3 动态权重策略（毕设创新点）

- 对查询做**粗分类**：`{实体查询, 关键词查询, 语义查询, 闲聊}`（规则为主：实体库匹配 + 关键词密度 + 长度启发式，fastText 兜底）
- 实体/关键词查询提高 BM25 权重：加权 RRF `score = w_bm25·1/(k+r_bm25) + w_vec·1/(k+r_vec)`（默认 `w_bm25=1.5, w_vec=1.0`）
- 语义查询提高向量权重（`w_bm25=1.0, w_vec=1.5`）
- 实现为**自研 Python 融合**（与 SP-RET-003 纯函数同源），不依赖 ES 原生 RRF 的加权能力
- 以静态 RRF 为基线，对比"动态融合"在测试集上的提升

> 预期输出：一张"查询类型 × 检索策略"对比表，作为毕设实验数据。

### 4.4 重排

- bge-reranker-v2-m3 对 top-20 重排取 top-5，用 Cross-Encoder 提升"问答匹配"精度
- 重排走硅基流动 bge-reranker-v2-m3 云端 API（备选 Cohere Rerank）

---

## 5. 意图识别模块

### 5.1 意图体系（v1 收敛为 6 类）

| 意图 ID | 名称 | 示例 | 路由目标 |
|---|---|---|---|
| `pre_sales` | 售前咨询 | "这款手机支持5G吗？" | 问答 Agent |
| `after_sales` | 售后咨询 | "用了三天就坏了怎么办" | 问答 Agent |
| `order_query` | 订单/物流查询 | "我的订单到哪了？" | 工具 Agent |
| `refund` | 退款/售后申请 | "我要退款" | 工单 Agent（预审 + 建申请单） |
| `complaint` | 投诉/情绪升级 | "你们太差了我要投诉" | 转人工 Agent |
| `human` | 直接要求人工 | "转人工" | 转人工 Agent |

### 5.2 双路方案

```
输入文本
 ├─ ① fastText 微调分类器（主路径）
 │    训练集：每类 200~300 条 + 增强（同义词替换/句式变换）
 │    输出：类别 + 置信度 conf（验证集上做阈值校准）
 ├─ ② LLM 二次确认（0.6 ≤ conf < 0.85 时触发，主模型 DeepSeek-V4-flash）
 │    验证/修正意图，结构化输出：{"intent": "...", "reason": "..."}
 ├─ ③ LLM 兜底分类（conf < 0.6 时触发，主 → 备 mimo-v2.5 降级）
 │    由 LLM 再判一次；结果仍低置信或解析失败 → 澄清
 └─ 决策
     conf ≥ 0.85        → 直接路由（不依赖 LLM）
     0.6 ≤ conf < 0.85  → LLM 二次确认后按 LLM 结果路由
     conf < 0.6         → LLM 兜底分类；仍低置信 → 澄清反问 / 转人工
     LLM 不可用（5001） → 降级澄清（conf ≥ 0.85 档不受影响）
```

### 5.3 拒答与兜底策略（毕设重点）

- **低置信拒绝**：不猜，反问澄清（"您是想查订单还是申请退款呢？"）
- **知识库无命中**：`top-1 相似度 < RETRIEVAL_REJECT_THRESHOLD`（默认 0.45，bge-m3 余弦，评测标定可调）时，回答"暂无该信息"，不编造
- **情绪识别**：简单规则（辱骂词表 + 标点/重复强度）触发优先转人工

> 面试点：意图识别误判成本不对称——把"售后"判成"售前"代价小，把"投诉"压成"售后"代价大，所以置信度分级要按类调整阈值。

- 训练产物落盘 `models/intent/fasttext.bin`，应用启动时加载；重新训练后由部署脚本更新
- fastText 的 softmax 概率**未校准**，0.85 / 0.6 阈值需在验证集上按类校准

---

## 6. 多智能体协作

### 6.1 Agent 体系

| Agent | 职责 | 依赖 |
|---|---|---|
| 路由 Agent | 根据意图分派任务，维护会话上下文 | 意图识别模块 |
| 问答 Agent | 基于检索结果生成答案，强制引用来源 | 混合检索 |
| 工具 Agent | 解析订单号 → 调用模拟 ERP 接口 → 返回结构化结果 | 模拟 ERP |
| 工单 Agent | 身份/订单归属/状态/时效预审 → 创建退款申请单（状态机）→ 返回单号 | PostgreSQL |
| 转人工 Agent | 收集上下文 → 生成人工会话摘要 → 标记转接 | Redis |
| 质检 Agent（可选扩展） | 对话结束后抽样评估回复质量 | 评测模块 |

### 6.2 状态机设计（LangGraph）

```
                    ┌─────────────┐
                    │  入口/接收消息 │
                    └──────┬──────┘
                           ▼
                 ┌─────────────────┐   低置信
                 │  意图识别+路由节点  │──────────▶ 澄清反问节点 ──┐
                 └───────┬─────────┘                          │
                         ▼ 意图分发                            │
              ┌──────────┼──────────┬─────────────┐           │
              ▼          ▼          ▼             ▼           │
        ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐      │
        │ 问答     │ │ 工具     │ │ 工单     │ │ 转人工   │      │
        │ Agent   │ │ Agent   │ │ Agent   │ │ Agent   │      │
              └────┬────┘ └────┬────┘ └────┬────┘ └────┬────┘      │
                   └───────────┴────┬──────┴───────────┘            │
                                   ▼（工单 Agent 敏感操作建单）        │
                        ┌─────────────────────┐                   │
                        │  二次确认 CONFIRM 节点  │──(拒绝→澄清/放弃)──┘
                        │  （挂起等待用户确认）    │
                        └──────────┬──────────┘
                                   ▼
                         ┌─────────────────┐
                         │  回复生成 + SSE 流 │
                         └─────────────────┘
```

状态：`{messages, intent, conf, route, tool_calls[], retrieved_docs[], ticket_id, transfer_needed, pending_confirm}` —— 每个字段都会透传到前端追踪面板；`pending_confirm=true` 表示等待用户对敏感操作（建单）的二次确认，挂起期间新消息仅接受"确认/取消"。

### 6.3 工具调用（Tool Calling）

```python
TOOLS = {
  "query_order": {   # 订单查询（模拟 ERP）
      "description": "按订单号查询订单状态与物流信息",
      "parameters": {"order_id": "string(必填)"}
  },
  "create_refund_request": { # 创建退款申请单（不直接退款！）
      "description": "发起退款/售后申请。仅创建申请单，服务端会强制校验订单归属/状态/时效，资金操作需人工审核",
      "parameters": {"order_id": "string", "refund_type": "only_refund|return_refund", "reason": "string", "amount": "number"}
  },
  "search_kb": {     # 知识库检索（供 LLM 自行补充检索）
      "description": "检索企业知识库，返回相关条款",
      "parameters": {"query": "string"}
  }
}
```

- 工具 Agent 使用 LLM Function Calling 解析参数，校验后调用模拟 ERP
- `query_order` 调用前校验 `order.user_id == 当前用户`，不符返回 4030 且不返回任何订单数据
- `create_refund_request` 为敏感操作：调用前必须经过二次确认（CONFIRM 节点），未确认不得创建
- 模拟 ERP 实现为 FastAPI 内部服务 `app/services/erp_sim.py`，返回 `{code, data, msg}` 契约

### 6.4 会话记忆

- 短期记忆：当前会话最近 N 轮上下文（Redis，TTL 30 分钟）——TTL 只影响"上下文注入"，不影响消息历史查询
- 长期记忆：消息历史与用户订单上下文存 PostgreSQL（`messages`/`sessions` 表），演示环境不设自动清理
- 记忆注入：组装成消息序列传入 Agent 状态，不靠 RAG
- SSE 事件重放：每条消息的事件序列持久化至 Redis（`session:{id}:events`），断线重连时可重放

### 6.5 典型完整流程（用户："我昨天买的手机怎么还没发货？"）

1. 意图识别 → `order_query`（conf=0.93）
2. 路由 Agent → 工具 Agent，并保留"手机"实体
3. 工具 Agent 调用 `query_order`（订单号需追问或从会话上下文取）
4. 若无订单号 → 澄清反问；有 → 返回物流状态
5. 若用户追加"那我要退款" → 意图切换 `refund` → 工单 Agent
6. 工单 Agent 预审（归属/状态/时效/金额上限）→ 通过则创建退款申请单并返回单号；超阈值或校验失败 → 转人工审核
7. 全流程状态写回前端追踪面板

### 6.6 退款功能的企业规范设计（重点审查项）

> 原则：**Agent 只做"受理 + 预审 + 建单"，绝不直接执行资金操作**。真实企业不会让 AI 直接调用退款接口，此边界也是答辩时评审最可能追问的点。

#### 6.6.1 退款申请单状态机

```
CREATED(已提交) ──▶ APPROVING(审核中) ──▶ APPROVED(审核通过) ──▶ REFUNDING(退款执行) ──▶ REFUNDED(完成)
                     │                                                        │
                     └──▶ REJECTED(已驳回，附 reject_reason)                  └──▶ FAILED(失败→重试/转人工)
```

- 每次状态流转写入 `refund_audit_log`（操作人/时间/动作/from_status/to_status/原因）
- 状态迁移由服务端校验合法性，非法迁移一律拒绝（4091）
- 终态（REJECTED/REFUNDED/FAILED）后同一 `(user_id, order_id, refund_type)` 允许重新申请（幂等键仅约束进行中的单，见 §6.6.4）

#### 6.6.2 预审规则（建单前强制校验，规则引擎实现）

| 校验 | 规则 | 不通过处理 |
|---|---|---|
| 身份 | 必须登录，`order.user_id == session.user_id`（只能退自己的单） | 拒绝 + 提示登录 |
| 订单状态 | 未发货 → 仅 `only_refund` 可退；已发货未签收 → 仅可"拦截/拒收" | 拒绝 + 引导正确路径（4220 + rule） |
| 时效（签收后） | ≤ 7 天 → 无理由退货或质量问题；7~15 天 → 仅质量问题（附凭证）；> 15 天 → 拒绝 | 4220 + 转人工（> 15 天） |
| 金额/频次 | 单笔 > ¥2000 或 30 天内退款 > 3 次 | 转人工审核，Agent 不自动放行（4220 + review_required） |
| 幂等 | 同一 `(user_id, order_id, refund_type)` 已有**进行中**申请单 | 4090 + existing_ticket_id；部分唯一索引兜底，终态不阻塞重新申请 |

#### 6.6.3 资金操作边界

- Agent 产出物 = 退款申请单（`status=CREATED`），之后进入审核状态机
- 仅小金额 + 白名单商品可自动审核通过 → `REFUNDING`（模拟支付渠道打款），操作人记为 `system_auto`
- 其余一律走人工审核节点（模拟坐席，操作人必填）；驳回必须带原因，由 Agent 转达用户并可引导申诉
- 前端"工单页状态流转"仅允许模拟坐席执行受限迁移（APPROVING→APPROVED/REJECTED），不得直接触发 REFUNDING

#### 6.6.4 幂等与防重（工程规范）

- 建单接口幂等键 `{user_id, order_id, refund_type}`，并发重复请求只建一单
- 前端"提交中"禁用按钮 + **部分唯一索引**双保险：`CREATE UNIQUE INDEX uq_refund_active ON tickets(user_id, order_id, refund_type) WHERE status IN ('CREATED','APPROVING','APPROVED','REFUNDING')`（普通唯一约束会永久封死"驳回后重新申请"）
- 并发冲突：唯一索引命中后捕获冲突返回 4090 + existing_ticket_id（不得把 5000 抛给用户）

#### 6.6.5 审计与留痕

- 申请单全生命周期写入 `refund_audit_log`，答辩可演示"某单被谁在何时驳回"
- 客服 Agent 操作日志与退款单解耦存储，便于回溯与对账

---

## 7. 后端服务设计（FastAPI）

### 7.1 项目目录结构

```
smart-agent/
├── app/
│   ├── main.py              # FastAPI 入口，挂载静态资源
│   ├── api/                 # 路由层
│   │   ├── chat.py          # POST /api/v1/chat（SSE）
│   │   ├── sessions.py      # 会话历史
│   │   ├── kb.py            # 文档上传/检索调试
│   │   ├── tickets.py       # 工单管理
│   │   └── eval.py          # 评测触发与结果
│   ├── core/                # 配置(pydantic-settings)/常量/日志
│   ├── agents/              # 各 Agent 定义 + graph.py(LangGraph)
│   ├── intent/              # 意图识别（fasttext + LLM 兜底）
│   ├── retrieval/           # hybrid_search.py / rerank.py
│   ├── ingestion/           # parser.py / chunker.py / indexer.py
│   ├── memory/              # redis 会话记忆
│   ├── services/            # erp_sim.py / llm.py(统一 LLM 封装)
│   ├── eval/                # ragas_eval.py / case_loader.py
│   └── models/              # Pydantic / SQLAlchemy 模型
├── frontend/                # Vue3 + Vite + Element Plus
├── tests/                   # pytest：检索/意图/接口
├── data/                    # 原始文档与测试集
├── docker-compose.yml
├── Dockerfile
├── .env.example             # 密钥与环境变量模板
└── docs/                    # 本设计文档 + 部署手册
```

### 7.2 核心 API 清单

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/chat` | 对话入口，SSE 流式返回（含过程事件） |
| GET | `/api/v1/sessions/{sid}/messages` | 会话历史 |
| DELETE | `/api/v1/sessions/{sid}` | 清空会话 |
| POST | `/api/v1/kb/documents` | 上传文档（异步解析索引） |
| GET | `/api/v1/kb/search?q=...` | 调试用：查看混合检索原始结果 |
| POST | `/api/v1/refund-requests` | 创建退款申请单（供工单 Agent/用户调用，全量预审，见 SP-REF-001） |
| GET | `/api/v1/tickets?status=...` | 工单列表（人工坐席/前端） |
| GET | `/api/v1/tickets/{id}` | 工单详情（状态/金额/驳回原因） |
| GET | `/api/v1/tickets/{id}/audit` | 审计回溯（全生命周期） |
| POST | `/api/v1/tickets/{id}/transition` | 状态流转（仅模拟坐席/内部审核服务，带操作人，受限迁移） |
| POST | `/api/v1/eval/runs` | 触发评测（跑测试集） |
| GET | `/api/v1/eval/runs/{id}` | 评测结果（指标+逐条明细） |
| GET | `/api/v1/health` | 健康检查（Docker 探活用） |
| POST | `/api/v1/auth/login` | 演示环境登录（一键/账号密码），返回 user_id + token |

### 7.3 SSE 事件协议

```
POST /api/v1/chat  body: {"session_id": "...", "message": "...", "attachments": [{"type": "image", "url": "..."}]}
响应 Content-Type: text/event-stream，事件序列（正常链路）：

event: intent      data: {"intent": "order_query", "conf": 0.93}        # 首事件 = fastText 结果（P95 < 2s 预算内）
event: route       data: {"agent": "tool_agent", "reason": "订单物流查询", "intent": "order_query", "conf": 0.93}  # 携带 LLM 修正后的最终意图/置信度
event: vision      data: {"description": "...", "model": "mimo-v2.5"}   # 可选：有图片附件时的异步理解结果
event: retrieval   data: {"docs": [{"title":..., "score":...}], "strategy": "rrf+rerank"}
event: tool_call   data: {"tool": "query_order", "args": {...}, "result": {...}}
event: message     data: {"content": "您的订单#1024已于 08-10 发货，预计 08-13 送达。", "delta": true}
event: done        data: {"ticket_id": null, "transfer": false}         # 必须兜底发送

事件规则：
- 顺序固定：intent → route → (vision) → (retrieval) → (tool_call) → message → done；vision/retrieval/tool_call 按路径可选（澄清/转人工路径无 retrieval 与 message，转人工由 done.transfer 标记）
- 参数校验失败（4001 等）：流开始前返回统一 JSON 包装（非 SSE），不产生任何事件
- 流开始后任何异常：仍必须发送 done，data 含 `{"error": {"code": 5001, "message": "..."}}`
- 事件序列持久化至 Redis（`session:{id}:events`），断线重连时前端携带 `Last-Event-ID` 重放
- 图片理解：attachments 含图片时由 mimo-v2.5 异步理解（不影响首响），结果经 vision 事件透出并注入检索/回答上下文
```

前端按事件渲染：消息区 + 右侧追踪面板。

### 7.4 数据模型（核心表）

```sql
sessions(id, user_id, created_at, status)                          -- 会话元数据；短期上下文在 Redis（TTL 30min）
messages(id, session_id, role, content, intent, conf, agent_route, created_at)  -- 历史持久（PG），不受 TTL 影响
documents(id, title, source, version, indexed_at)                  -- 文档元数据；chunk 以 ES 索引 kb_chunks 为准（PG 不冗余存储 chunk）
tickets(id, user_id, order_id, refund_type, amount, status, reject_reason, created_by, session_id, created_at, updated_at)
  -- 工单=退款/售后申请单；部分唯一索引 uq_refund_active(user_id, order_id, refund_type) WHERE status 为进行中
refund_audit_log(id, ticket_id, operator, action, from_status, to_status, reason, created_at)  -- 全生命周期审计
eval_cases(id, question, expected_intent, gold_docs, created_at)
eval_runs(id, strategy, metrics_json, started_at, finished_at)
```

### 7.5 认证与鉴权（演示级，v1.1 新增）

- 认证载体：`POST /api/v1/auth/login` 返回 `user_id + token`；请求经 `Authorization: Bearer <token>`（演示环境内部简化为 `X-User-Id` 请求头，前端登录页设置）
- 判定：未认证 → 4010；资源归属不符（订单/工单/会话不属于当前用户）→ 4030
- 范围：退款链路（SP-REF-002）、订单查询工具（SP-AGENT-003）、会话历史（SP-CHAT-001）必须校验
- 生产建议：JWT + 中间件统一鉴权（答辩口径："真实环境替换为网关/JWT，本项目聚焦业务闭环"）

---

## 8. 前端设计

### 8.1 选型

Vue 3 + Vite + Element Plus + Pinia（状态管理）+ axios/SSE。构建产物由 FastAPI 托管。

### 8.2 页面与路由

| 路由 | 页面 | 核心内容 |
|---|---|---|
| `/` | 客服对话页 | 聊天气泡、Markdown 渲染、SSE 流式、快捷指令 |
| `/trace` | Agent 追踪面板 | 与对话页联动：意图/置信度/检索文档/工具调用时间线 |
| `/eval` | 评测看板 | 测试集、指标卡（RAGAS）、消融对比表、逐条明细 |
| `/tickets` | 工单管理 | 工单列表、状态流转（模拟） |

> 建议"追踪面板"作为对话页的右侧抽屉而非独立页面，答辩演示时一条消息点开即可看到全链路。

### 8.3 前端亮点实现

- 打字机效果：SSE 增量渲染 + 保留 Markdown
- 引用角标：回答中 `[1][2]` 角标 hover 显示对应文档片段（溯源可视化）
- 追踪时间线：意图 → 路由 → 检索(附分数) → 工具 → 回复，每步耗时标注

---

## 9. 评测体系

### 9.1 测试集（毕设实验基础）

- **100 条真实风格问题**：60 条常见 + 30 条长尾 + 10 条需拒答/转人工的对抗样本
- 每条标注：`question / expected_intent / gold_docs / ideal_answer`

### 9.2 指标

| 层面 | 指标 | 工具 |
|---|---|---|
| 意图 | Accuracy、宏平均 F1、混淆矩阵 | sklearn |
| 检索 | Recall@5、MRR、NDCG@5 | 自研脚本 |
| 生成 | RAGAS：faithfulness、answer_relevancy、context_precision/recall | RAGAS 库 |
| 系统 | 解决率（拒答/转人工率反推）、首响延迟、P95、token 成本 | 日志统计 |

> 注：faithfulness / answer_relevancy 由 LLM 判官计算（主模型 DeepSeek-V4-flash），存在随机性——评测门槛以多次运行均值计，CI 中该组测试标 `slow` 且支持 FakeLLM 降级。

### 9.3 消融实验矩阵（答辩核心数据）

| 实验 | 配置 | 预期结论 |
|---|---|---|
| E1 | 仅 BM25 | 关键词命中强、语义泛化弱 |
| E2 | 仅向量 | 语义泛化强、精确条款易丢 |
| E3 | BM25 + 向量 + RRF | 全面优于 E1/E2 |
| E4 | E3 + reranker | 生成质量（faithfulness）进一步提升 |
| E5 | E3 + 动态权重 | 在实体/关键词类查询上优于静态 RRF |

结论章节模板：每项差异给出统计意义与典型失败案例（附证据），这是毕设最硬的增量。

---

## 10. 部署方案

### 10.1 Docker Compose 服务编排

```yaml
services:
  app:            # FastAPI + 前端静态产物（单镜像）
    build: .
    ports: ["8000:8000"]
    depends_on: [postgres, redis, es]
  postgres:        # PostgreSQL 16
  redis:           # Redis 7
  es:              # ES 8.x 单节点（演示环境关闭安全特性或配置简单认证）
  nginx:           # 443/80 反代 → app
```

> 新学 Docker 最低范围：`docker compose up -d`、Dockerfile（python:3.11-slim + 多阶段构建前端）、日志与重启。K8s 不碰。
> Nginx 要点：SSE 需 `proxy_buffering off`、调大 `proxy_read_timeout`（≥ 120s）、对 `text/event-stream` 禁用 gzip；限流 `limit_req` 默认 30 req/s，触发 429 时用 `error_page` 返回统一 JSON（code=4290）。

### 10.2 上线 Checklist

1. `.env` 管理密钥（DEEPSEEK_API_KEY / MIMO_API_KEY / 数据库密码），**不入库**
2. Nginx：HTTPS + 限流（`limit_req`，默认 30 req/s，429 返回统一 JSON 含 4290）+ gzip（SSE 除外）
3. 健康检查 `/api/v1/health` 接入 compose `healthcheck`
4. 日志：结构化 JSON 落盘 + 脱敏（订单号/手机号打码）
5. 演示数据就绪：知识库已索引、模拟订单已造好、测试集可一键跑评测
6. 压测路径约定：`bench_chat` 直连 `app:8000` 验证 20 并发；Nginx 层单独压测验证 4290

### 10.3 资源建议

- 云服务器：建议 4C8G（阿里云/腾讯云轻量即可）。2C4G 跑 ES（≥2G heap）+ PG + Redis + 应用已吃紧；embedding / 重排均已走云端 API（硅基流动），不加载本地模型，2C4G 亦可支撑
- 模型：文本主路径 DeepSeek-V4-flash API；备用与图片理解 mimo-v2.5 按需启用；全部走云端 API，不依赖本地模型
- 重排性能提示：bge-reranker-v2-m3 走硅基流动云端 API，满足 P95 < 800ms 的 SLA；本地 CPU 推理不达标不作为验收阻塞（SP-RET-006 豁免口径）

---

## 11. 安全与合规

| 风险 | 对策 |
|---|---|
| Prompt 注入（用户让"忽略规则"） | System Prompt 加固 + 用户输入前加分隔标记 + 敏感操作（建单）前二次确认（CONFIRM 节点） |
| 越权访问 | 认证（4010）+ 归属校验（订单/工单/会话，4030）；query_order 与退款建单强制校验 |
| 幻觉（编造条款） | 强制引用来源 + 低相似度拒答 + faithfulness 评测把关 |
| 个人信息 | 演示用合成数据；日志脱敏；不采集真实订单 |
| 滥用/刷接口 | Nginx 限流（30 req/s，4290）+ 单会话频率限制 |
| Key 泄露 | 只存 `.env` / 容器环境变量，绝不进前端代码 |

---

## 12. 开发计划（4 周）

| 周 | 里程碑 | 验收标准 |
|---|---|---|
| W1 | 数据 + 检索管道 | 100 文档完成解析分块入 ES；`/kb/search` 返回混合检索结果；召回指标脚本可跑 |
| W2 | 意图识别 + 单 Agent 问答 | fastText 分类器 acc ≥ 85%；一条问题走通"意图→RAG 问答→带引用回答" |
| W3 | 多 Agent + 工具 + 退款闭环 | 订单查询/建单闭环；SSE 用简单 HTML 联调页验证全链路 |
| W4 | 前端正式页 + 评测 + 部署 + 文档 | 追踪面板/工单页完成；消融实验完成；Docker Compose 一键起；答辩 PPT 与部署手册成稿 |

风险应对：W1 若 ES 卡壳 → 向量检索先用 Qdrant 或 FAISS 顶上；W3 前端若延期 → 先保证后端 SSE 可用（用简单 HTML 页联调）；LLM 主模型超时/失败 → 自动降级 mimo-v2.5。

---

## 13. 附录：面试高频追问预案

1. **为什么用 RRF 不用加权求和？** 不同检索器分数分布不可比，RRF 只看排名，鲁棒且无需归一化。
2. **混合检索和 Rerank 都做了，是否冗余？** RRF 做召回融合（广），Rerank 做精排（准），各有作用，消融 E3 vs E4 数据支撑。
3. **意图分类为什么不用纯 LLM？** 成本、延迟、可离线评测；fastText 主路径覆盖高频意图，LLM 只兜底长尾。
4. **多 Agent 为什么用 LangGraph 而非 ReAct 循环？** 状态显式、流程可观测可回退，符合客服"流程固定+步骤可控"的特性。
5. **如何防止幻觉？** 检索强约束（低相似度拒答）+ 强制引用 + 生成后 faithfulness 评测，三重防线。
6. **SSE 断线怎么处理？** 前端重连 + 幂等 session_id，服务端按 `session:{id}:events` 持久化事件序列支持重放。
7. **为什么主备模型 + 多模态分流？** 主模型（DeepSeek-V4-flash）承担高频文本路径（成本/延迟可控）；备用（mimo-v2.5）在主模型超时/失败时自动降级（5001 前置）；图片理解固定走 mimo-v2.5，避免挤占文本路径；三层职责清晰、可独立替换与评测。
