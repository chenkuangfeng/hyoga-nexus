# 知识库：完整保留 WeKnora 功能，可配置向量库与库类型，增加 GraphRAG（路线图第 6 步）

## 状态

草案第 2 版（2026-11-06）。用户要求：
- 知识库完整保留 WeKnora 的功能；
- 可以选择和配置向量库；
- 可以配置知识库类型；
- 增加 GraphRAG 选项；
- 前端不隐藏未实现的功能，统一标记「待实现」；
- 在此基础上参考其他项目做增强和优化。

本版按这些要求重写了第 1 版（只覆盖 6.1–6.3 并隐藏 WeKnora 独有功能）。等用户确认决定 1–8 后再编码。

## 原因

1. `packages/knowledge` 只有占位目录。智能体不能引用资料，路线图 3.10 预留的知识工具、记忆演进 6.4 文档亲和度、共享空间的知识库共享、智能体编辑器的知识库分区，都在等这个模块。
2. 前端 `apps/web/src/views/knowledge/` 和设置页的向量库、存储后端、解析引擎、检索设置，都是照 WeKnora 复刻的界面，调用的是 WeKnora 接口，在 Nexus 上不能用。
3. WeKnora 的知识库功能面很大，不可能一次做完。需要一个总变更，把全部功能列成分阶段任务，前端先完整接上，再逐阶段换成真实能力。

## 参考源码

本地副本 `/project/opensource/`。

| 项目（版本） | 位置 | 借鉴点 |
| --- | --- | --- |
| WeKnora `e1f9a6166`（功能基线） | `internal/types/knowledgebase.go`、`indexing_strategy.go` | 库类型 document / faq / wiki；索引策略开关（向量、关键词、Wiki、图谱）；分块、解析引擎规则、父子分块、图片处理、VLM、ASR、摘要模型、提问生成、自动打标、库画像、置顶 |
| | `types/vectorstore.go`、`retriever/*` | 向量库注册：引擎类型、连接配置（密钥加密）、索引配置；postgres、sqlite、elasticsearch、opensearch、qdrant、milvus、weaviate、doris、tencent_vectordb、infinity |
| | `types/storagebackend.go` | 原文件存储后端注册 |
| | `types/faq.go`、`knowledge_faq*.go` | FAQ 库：问题与答案的索引模式、批量导入、相似问 |
| | `types/wiki_page.go`、`wiki_*` | Wiki 库：从文档合成页面、反向链接、修订记录 |
| | `types/extract_graph.go`、`retriever/neo4j`、`agent/tools/query_knowledge_graph.go` | 实体关系抽取配置、Neo4j 图存储、图查询工具 |
| | `types/datasource.go`、`datasource_*` | 18 种外部数据源连接器与同步日志 |
| | `knowledgebase_search_fusion.go`、`knowledgebase_search_rerank.go` | 加权 RRF 融合、重排 |
| | `agent/tools/search_knowledge.go`、`read_document.go`、`list_documents.go` | 三个工具的参数与输出 |
| RAGFlow `e5a5060c4` | `internal/service/graph/`（`pipeline.go`、`search.go`、`scoring.go`） | GraphRAG 检索：实体、关系、社区报告按向量召回，n 跳邻居加权，按 token 预算组装；图数据与文本块存在同一检索引擎中，不需要图数据库 |
| | `internal/entity/dataset.go` | GraphRAG、RAPTOR、思维导图作为库级后台任务，记录任务 ID 与完成时间 |
| | `internal/agentic_rag/evidence_registry.go`、`citations.go` | 每个 Run 的 `[ID:n]` 证据登记与引用校验 |
| | `internal/agentic_rag/tool_grep_chunks.go`、`tool_navigate_structure.go`、`tool_doc_outline.go`、`decision_breaker.go` | 精确匹配检索、按文档结构导航、目录大纲、检索判断与断路 |
| Octop `4811eb4` | `src/octop/infra/knowledge/`（`gate.py`、`jobs.py`、`parse.py`、`citations.py`、`tools.py`） | 能力门控与可区分的不可用原因；作业恢复；GB18030 解码；工具描述列出挂载的库 |
| FastGPT | `packages/service/core/dataset/`（`training/`、`synonym/`、`search/`） | 训练队列与重试、同义词扩展 |
| Dify | `api/core/rag/`（`retrieval/`、`rerank/`、`summary_index/`） | 元数据过滤、按库选择检索模式、摘要索引 |

## 范围

本变更是第 6 步的总变更，替代 `2026-11-02-weknora-parity` 第 3 阶段。按下列阶段实施，每个阶段单独验收、提交和推送；同一阶段内追加的工作写回本变更的 `tasks.md`。

### K0 前端全量接入与能力目录（先做）
1. 后端提供能力目录接口 `GET /api/v1/knowledge/capabilities`，逐项返回 `available` 或 `planned`，并附所属阶段。覆盖库类型、索引策略、向量引擎、存储后端、解析引擎、数据源类型和各项库设置。
2. 前端保留 WeKnora 的全部入口：库列表与详情、FAQ、Wiki、图谱、标签、文件夹、图片库、数据源、共享、活动日志，以及设置页的向量库、存储后端、解析引擎和检索设置。所有入口按能力目录渲染。未实现的项显示「待实现」标记，表单可以查看但不能提交，操作按钮禁用并提示所属阶段。不隐藏任何入口。
3. `api/knowledge-base` 等接口模块改为调用 Nexus 接口。Nexus 没有的接口不发请求，直接按「待实现」处理，避免出现 404 报错。

### K1 文档库核心（原 6.1–6.3）
4. 数据模型：知识库（含 `type`、`indexing_strategy`、`vector_store_id`、`storage_backend_id`、Embedding 模型、分块配置）、文档、不可变文档版本、文本块、索引作业。
5. 上传按内容哈希去重。新版本索引完成后才切换为当前版本。解析、分块、向量化由 worker 分阶段执行，可以恢复，失败按退避重试。删除先标记，再由后台清理。
6. 解析：纯文本、Markdown、CSV、JSON、文本型 PDF。分块：Markdown 先按标题分段，PDF 按页分；段内按定长重叠切分，并记录页码和章节。
7. 向量库注册：`vector_stores` 表（引擎、连接配置、索引配置，密钥加密存储），支持连接测试。每个库选择一个向量库，创建后不能更换引擎，只能重建索引。首批实现的引擎见决定 1。
8. 存储后端注册：`storage_backends` 表，首批实现本地目录。
9. 授权先于检索（Pre-Filter）：先算出调用者此刻可访问的库和当前版本，只在这个范围内检索；范围以过滤条件的形式下推到向量引擎。
10. 混合检索：关键词通道与向量通道按库的索引策略开启，结果按加权 RRF 融合。向量通道不可用时退化为关键词检索，并标注原因。
11. 工具：`search_knowledge`、`read_document`、`list_documents`。`[ID:n]` 证据登记，Run 结束时校验引用。智能体版本可以绑定多个库。
12. 共享（`resource_grants` 只读）与活动日志（审计）。
13. 检索测试页，评估集 `evals/knowledge/`。

### K2 图谱与 GraphRAG
14. 库的索引策略开启「图谱」后，可以选择图谱模式：
    - `entity`：WeKnora 方式，按 `ExtractConfig` 抽取实体和关系，用 `query_knowledge_graph` 查询。
    - `graphrag_light`：RAGFlow / LightRAG 方式，抽取实体和关系并做向量化，检索实体、关系及其 n 跳邻居。
    - `graphrag_general`：Microsoft GraphRAG 方式，在 light 的基础上增加实体归并、社区划分（Leiden）和社区报告，检索时加入社区报告。
15. 图谱构建是库级后台任务，记录任务状态、进度和完成时间，可以手动重建。图元素记录来源文档版本、来源块和 schema 版本。新版本构建完成后才切换可见。
16. `search_knowledge` 在开启图谱的库上合并图谱结果。图检索有上限（种子实体数、关系数、跳数、token、耗时），被截断时明确告知模型。图检索失败时退化为基础检索，并记录降级。
17. 前端：图谱设置（模式、实体类型、关系类型、抽取模型、自定义指令）、构建任务状态、图谱浏览。

### K3 FAQ 库
18. FAQ 类型库：问答条目的增删改查、相似问、批量导入（CSV / Excel）、索引模式（只索引问题 / 问题加答案；相似问合并或分开索引）。检索时 FAQ 命中直接返回答案。

### K4 解析与分块增强
19. 解析引擎规则：按文件类型选择引擎（内置、markitdown、MinerU 等）。支持 Office 文档（docx、pptx、xlsx）。分块策略 auto / heading / heuristic / recursive，父子分块，分块调试页。
20. 图片处理：OCR、VLM 生成图片描述，图片库。ASR 用于音视频转写。

### K5 组织与增强功能
21. 标签与自动打标、文件夹、置顶、文档摘要（摘要模型）、提问生成（为块生成假设问题）、库画像（自动生成库简介，用于工具描述）。
22. 重排模型（库级可选）、元数据过滤（Dify）、同义词扩展（FastGPT）。

### K6 Wiki 库
23. Wiki 类型库：从文档合成页面，提取粒度和内容指令可配置，包含反向链接、修订记录和目录，可以按 Wiki 检索。

### K7 数据源
24. WeKnora 的 18 种数据源（飞书、Notion、Confluence、语雀、GitHub、GitLab、网页抓取、RSS、IMAP 等）。连接器实现放在 `packages/connectors`，统一提供同步调度、增量同步、同步日志和保留策略。每个连接器在用户提供账号和接入条件后逐个实现，未实现的显示「待实现」。

### 增强与优化（贯穿各阶段，参考其他项目）
- **RAGFlow agentic 工具**：`grep_chunks`（精确匹配）、`navigate_structure` / 文档大纲（按章节读取），在 K1 之后作为可选工具加入。证据登记里重复的正文只返回编号，节省 token。
- **Octop 能力门控**：向量库、Embedding、图谱各自返回可区分的不可用原因，能力目录和检索降级共用同一套判断。
- **作业队列**：统一的知识作业表，涵盖解析、向量化、图谱、摘要、提问生成、Wiki 合成、数据源同步。所有作业都可以恢复、退避重试、手动重试和取消，并发数可配置（本机默认 1）。
- **一致性**：文档更新、删除、撤权和重建索引同时作用于关键词、向量和图谱三类索引，旧版本不再被召回。这条由测试逐路径断言。

### 范围外

- 记忆演进 6.4 文档亲和度：K1 完成后在原记忆变更里实施。
- 制品库、自动化、工具箱等其他 WeKnora 页面：不属于知识库。

## 待确认的决定

1. **首批实现的向量引擎**
   - 推荐：K1 先实现 `sqlite`（向量以 JSON 存储，在授权范围内进程内计算余弦，用于本地开发）和 `postgres`（pgvector，生产）。其余 9 种引擎（elasticsearch、opensearch、qdrant、milvus、weaviate、doris、tencent_vectordb、infinity，以及 neo4j 图存储）在目录和配置表单里全部可见，标记「待实现」。你提供对应服务的测试环境后，按 `VectorIndex` 端口逐个实现并做连接验收。
   - 备选：K1 同时实现 Qdrant 和 Elasticsearch。需要你先提供这两个服务；本机内存 1.8GB，跑不起来。

2. **图谱的存储**
   - 推荐：参考 RAGFlow，把实体、关系、社区报告存在 PostgreSQL / SQLite 的关系表里，向量与文本块用同一个向量库。不需要额外部署图数据库，权限过滤与文本块共用同一套 Pre-Filter。Neo4j 作为可选的图存储引擎，标记「待实现」。
   - 备选：与 WeKnora 一样使用 Neo4j，需要部署 Neo4j。

3. **GraphRAG 模式**
   - 推荐：三种模式（`entity`、`graphrag_light`、`graphrag_general`）都可以选。K2 先实现 `graphrag_light`，再实现 `general`（社区划分和社区报告）和 `entity`。社区划分使用纯 Python 的 Leiden 实现或 networkx 的 Louvain，具体在 K2 开始前做技术验证。
   - 备选：只实现 `graphrag_general` 一种。

4. **阶段顺序**
   - 推荐：K0 → K1 → K2 → K3 → K4 → K5 → K6 → K7。先把前端全部接上并完成核心检索，然后做你点名的 GraphRAG，再做其他库类型和增强。
   - 备选：其他顺序，比如 FAQ 先于图谱。

5. **「待实现」的呈现方式**
   - 推荐：由后端能力目录驱动。入口和表单可见，标记「待实现 · K3」这类徽标，提交和操作按钮禁用并给出提示；某项能力实现后，后端改为 `available`，前端不用改代码。
   - 备选：前端写死一份待实现清单。

6. **Embedding 用谁的 Key**（沿用第 1 版推荐）
   - 推荐：建库时用库创建者的 Key 做索引，检索时用查询者自己的 Key。查询者无权使用该模型时，退化为关键词检索。图谱抽取、摘要等模型调用，同样使用库创建者的 Key。
   - 备选：由空间管理员配置一个空间级共用凭据。

7. **检索方式与无效引用**（沿用第 1 版推荐）
   - 推荐：只通过工具检索，不在每轮自动注入。回答里的无效 `[ID:n]` 不导致 Run 失败：在界面上标为无效，记录 `knowledge.citation_invalid` 事件，评估时计为失败。同步修改架构文档中「判为失败」的措辞。
   - 备选：每轮自动检索一次；或者出现无效引用时 Run 失败。

8. **数据源连接器的归属**
   - 推荐：连接器放在 `packages/connectors`，与路线图第 9 步的渠道共用凭据和调度。本变更里只做 K7 的同步框架，具体连接器有了账号再逐个接入；没接入的连接器不影响本变更归档，转到第 9 步继续。
   - 备选：全部连接器都在本变更内完成后才归档。

## 验收（按阶段）

- **K0**：前端所有知识库入口可以打开，没有请求 404。未实现的项都显示「待实现」，并且不能提交。能力目录的单元测试覆盖每一项。
- **K1**：上传去重和版本切换正确；作业中断后可以恢复；无权、撤权、已删除的内容在关键词、向量、降级三条路径下都不会返回；向量库连接测试和引擎选择生效；`[ID:n]` 编号稳定，挂起恢复后不变；评估集中越权泄漏数为 0。
- **K2**：三种图谱模式可以选；图谱构建可以恢复、可以重建；图检索的上限和截断提示生效；图服务故障时退化为基础检索，并能看到降级记录；权限过滤对图谱结果同样生效。
- **K3–K7**：各阶段在 `tasks.md` 中列出验收项，完成后对应的能力在目录里变为 `available`。
- 每个阶段：后端 pytest 全量通过，并包含迁移的升级与降级；前端单元测试通过；完整 `pnpm build` 和浏览器验证在内存充足的环境执行，未执行时明确说明。
