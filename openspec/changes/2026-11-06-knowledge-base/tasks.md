# 实施任务

状态：决定 1–8 已确认（2026-11-06），实施中。每个阶段单独提交推送；阶段内追加工作写回本文件。

## 0. 准备

- [x] 0.1 阅读 Octop `infra/knowledge/`、RAGFlow `agentic_rag/` 证据与引用、WeKnora 融合与 SQLite 检索。
- [x] 0.2 梳理 WeKnora 知识库功能面（库类型、索引策略、向量库、存储后端、解析引擎、FAQ、Wiki、图谱、数据源、标签、文件夹、图片、共享、活动）。
- [x] 0.3 阅读 RAGFlow `service/graph/`（GraphRAG 检索）。
- [x] 0.4 用户确认决定 1–8（2026-11-06）。
- [x] 0.5 更新文档：`docs/architecture.md` 2.10（向量库注册、图谱存储、GraphRAG、引用处理）、路线图第 6 步子计划改为 K0–K7、`2026-11-02-weknora-parity` 第 3 阶段指向本变更。

## K0 前端全量接入与能力目录

- [x] K0.1 `nexus_knowledge.capabilities`：能力项清单（库类型、索引策略、向量引擎、存储后端、解析引擎、数据源类型、库设置项），每项 `available | planned` 与阶段；接口与单元测试。
  - `GET /api/v1/tenants/{tenant_id}/knowledge/capabilities`（空间成员）；`mark_available(group, key, verified=)` 由实现模块调用，`require_available` 抛 `CapabilityPlanned`，API 统一转 422 `capability_planned`。另含图存储、图谱模式两组。测试 `tests/test_knowledge_capabilities.py`；全量 930 通过。
- [x] K0.2 前端能力目录 store 与 `PlannedBadge`、禁用提交的通用处理。
  - `api/nexus-knowledge-capabilities.ts`（纯解析，`capabilityState`、`isAvailable`，目录未加载时一律按待实现处理）与单元测试、`api/nexus-knowledge.ts`、`stores/knowledgeCapabilities.ts`、`components/knowledge/CapabilityBadge.vue`，六种语言新增 `planned.badge*` 文案。本机内存不足，未运行 `vue-tsc` 与 `pnpm build`。
- [x] K0.3（与 K1.9 合并实施：页面需要 K1 的库与文档接口才能不 404，目前知识库路由仍渲染 PlannedPage）`api/knowledge-base`、向量库、存储后端、解析引擎、检索设置的接口模块改接 Nexus；Nexus 未提供的调用短路为「待实现」。
- [ ] K0.4 逐页核对：知识库列表与详情、FAQ、Wiki、图谱、标签、文件夹、图片库、数据源、共享、活动、设置页四项；无 404，未实现项均有标记。

## K1 文档库核心

> K1.9 进度：API 模块与适配层、向量库/存储后端/检索设置的 API、设置页向量库引擎选择器（待实现禁用 + 徽标）、编辑器的库类型/索引策略（FAQ、Wiki、图谱标待实现）、知识库路由已切到真实页面。本机内存不足，`.vue` 文件未做 vue-tsc 与 `pnpm build`，需在内存充足的环境验证。智能体编辑器已增加「知识库」分区（绑定库时一并绑定三个知识工具，共享库默认授予 read+use）。创建流程的向量库选择器（系统默认 = 内置 SQLite，登记的库带「未验证」徽标）已接通；`listModels` 改读 Nexus 模型设置（模型版本 ID 作为 id），Embedding 选择器可用。详情页：未实现的 WeKnora 接口（数据源、Wiki、图谱抽取、分块调试、解析引擎、共享界面等）由请求层集中拦截（`plannedEndpoints.ts`），不发请求并以「待实现 · 阶段」拒绝。仍待：知识库共享界面接入 `/knowledge/bases/{id}/shares`（后端已有）、在浏览器里逐页确认交互。对话引用渲染已完成。前端单测 2094 通过，仅 `style guard: font-size-literal`（45 > 基线 33，非本变更文件）为既有失败。

- [x] K1.1 领域：`ingest.parse`（文本、Markdown、CSV、JSON、pypdf）、`ingest.chunk`（标题/页 + 定长重叠）、`retrieval.fuse`、`evidence`，移植参考项目测试样例。
  - `nexus_knowledge.text`（与记忆相同的 CJK 二元分词，复制以免跨包依赖）、`ingest.parse`（Section 带页码与标题路径；docx 等返回 `unsupported_type`，扫描 PDF 返回 `empty_text`）、`ingest.chunk`（段内定长重叠，切点优先段落、句末、空白）、`retrieval.fuse`、`evidence.registry`（编号从 1 开始）。新依赖 `pypdf==6.21.4`。测试 `tests/test_knowledge_domain.py`。
- [x] K1.2 端口：`VectorIndex`（含范围过滤下推）、`KeywordIndex`、`BlobStore`；实现 sqlite（测试）、本地目录。
  - `VectorIndex` 按知识库分 collection，`search_vector/search_keyword` 必须带 `Scope`（版本 ID）并在引擎内过滤，空范围直接返回空。sqlite 引擎是独立文件（`connection_config.path`），FTS5 无内容表 + float32 向量 + 进程内余弦；`register_engine` 同时标记能力目录。`KeywordIndex` 不单独建端口，关键词通道由同一引擎提供（`supports_keyword`）。测试 `tests/test_knowledge_sqlite_index.py`。
- [x] K1.2b 引擎代码：postgres（pgvector + tsvector）、qdrant、elasticsearch、milvus；只实现不测试，能力目录标 `verified=false`，真实环境后补验收。
  - postgres（psycopg 异步、按维度的部分 HNSW 索引、`tsvector('simple')` 关键词）、qdrant / elasticsearch / milvus（httpx 调 REST；Milvus 2.5+ 用 BM25 函数做关键词通道；ES kNN 带 `filter`）。Qdrant、Milvus `requires_vectors=True`，库必须配置 Embedding 模型。新增依赖 httpx、psycopg 到 knowledge 包。只验证了能构造与注册，未连接真实服务。
- [ ] K1.2c 真实环境验收：postgres、qdrant、elasticsearch、milvus 连接、增删查与越权用例（需用户提供环境）。
- [x] K1.3 持久化与迁移：`knowledge_bases`、`knowledge_documents`、`knowledge_document_versions`、`knowledge_chunks`、`knowledge_chunk_vectors`、`knowledge_jobs`、`vector_stores`、`storage_backends`；升降级测试。
  - 迁移 `c8d9e0f1a2b3`。向量不进平台库（不建 `knowledge_chunk_vectors`），由所选向量库保存；`indexed_count` 记录已写入索引的块数用于断点续做。库与文档名称在 active 范围内唯一（部分索引）。`[knowledge]` 配置：`data_dir`、`max_upload_mb`、`index_concurrency`。
- [x] K1.4 服务：库与文档增删改查、上传去重、版本切换、删除标记与清理、资源注册、共享、审计。
  - `nexus_platform.knowledge`：`access`（读：本空间成员或共享进来的空间成员；写：空间 owner/admin 或创建者）、`stores`（向量库与存储后端注册，密钥按 id 绑定加密、列表打码；未登记时用内置 SQLite 与本地目录）、`service`。共享直接复用 `resource_grants`。SQLite 不强制外键级联，清理任务显式删除子行。
- [x] K1.5 作业：parse → chunk → embed → activate，阶段提交、退避重试、恢复、取消。
  - `jobs.claim` 以租约（10 分钟）领取；解析错误直接失败（`empty_text`、`unsupported_type`），其他错误 30s/2m/10m 退避，第 4 次失败；文档或库删除后作业取消。Embedding 通过 `knowledge.embedding.set_embedder_factory` 注入，索引用创建者 Key、查询用查询者 Key。
- [x] K1.6 向量库与存储后端注册：增删改查、密钥加密、连接测试、库创建时选择。
  - 接口 `/knowledge/vector-stores`（含 `builtin`、草稿连接测试）与 `/knowledge/storage-backends`。
- [x] K1.7 Pre-Filter 与混合检索、降级、诊断；越权测试逐路径。
  - `search.resolve_scope` + `search.search`；命中后在平台库按范围再过滤一次。测试 `tests/test_knowledge_service.py`（去重、版本切换时机、跨空间/共享/撤权/绑定/删除、解析失败与重试、混合检索与向量降级审计）。
- [x] K1.8 工具 `search_knowledge`、`read_document`、`list_documents`；证据登记存 Run progress；Run 结束引用校验；智能体绑定与发布校验。
  - 工具与其他内置工具一样需在空间启用并绑定（编辑器选库时一并勾选）；未绑定知识库时准备阶段移除这三个工具，系统提示列出可读的已绑定库。发布时绑定了知识库却没绑 `search_knowledge` 返回 `knowledge_dependency_missing`。证据存 `progress.state['knowledge_evidence']`；Run 完成时有效编号写入助手消息 `runtime_metadata.citations`，无效编号记 `knowledge.citation_invalid` 事件。测试 `tests/test_knowledge_tools.py`；`tests/test_platform.py` 旧用例补绑 `search_knowledge`。
- [ ] K1.9 前端（进行中）：列表、创建/编辑（类型、索引策略、向量库、存储、模型、分块）、详情、上传、状态与重试、块预览、检索测试、共享、活动、引用渲染、智能体编辑器知识库分区。
- [x] K1.10 `evals/knowledge/` 与包文档（README、requirements、design）。
  - 评估门禁 `tests/test_knowledge_eval.py`（关键词通道命中率 ≥ 0.85、越权泄漏 0、引用解析）；向量与混合通道指标待真实 Embedding 模型。

## K2 图谱与 GraphRAG

- [x] K2.0 技术验证：社区划分实现（Leiden / Louvain）在本机内存下的可行性。
  - 结论：networkx 3.6 的 `leiden_communities` 只是后端分派入口，没有安装原生后端（graspologic、igraph）时不可用，不引入原生依赖。改用纯 Python 的 `louvain_partitions`（分层）：1000 节点 0.14 秒、41MB；2 万节点 8 万边 18 秒、134MB，适合后台任务。依赖 `networkx==3.6.1` 加到 knowledge 包。
  - 设计取舍：构建任务单独成表（`knowledge_graph_builds`），不改 `knowledge_jobs` 的类型约束；按块内容哈希缓存抽取结果，文档变化触发的整库重建只对新增块调用模型；图元素记录来源文档版本，检索时按当前范围过滤，旧版本内容不会被召回。
- [ ] K2.1 `graph_stores` 注册与 `GraphStore` 端口；`builtin` 图元素表（实体、关系、社区、社区报告，带来源与 schema 版本、构建版本）与迁移。
- [ ] K2.2 抽取：`graphrag_light`（实体关系抽取、向量化）。
- [ ] K2.3 `graphrag_general`（实体归并、社区划分、社区报告）。
- [ ] K2.4 `entity` 模式（WeKnora ExtractConfig）与 `query_knowledge_graph` 工具。
- [ ] K2.5 库级构建任务、重建、版本切换；有界图检索、截断提示、降级。
- [ ] K2.7 `neo4j` 图存储实现与越权测试（需 Neo4j 测试环境）。
- [ ] K2.6 前端图存储管理、图谱设置、任务状态、图谱浏览。

## K3 FAQ 库

- [ ] K3.1 FAQ 条目、相似问、索引模式、批量导入；检索命中直接返回答案；前端 FAQ 管理。

## K4 解析与分块增强

- [ ] K4.1 解析引擎规则与 Office 文档；分块策略、父子分块、分块调试。
- [ ] K4.2 OCR、VLM 图片描述、图片库；ASR。

## K5 组织与增强

- [ ] K5.1 标签、自动打标、文件夹、置顶。
- [ ] K5.2 文档摘要、提问生成、库画像。
- [ ] K5.3 重排、元数据过滤、同义词；RAGFlow `grep_chunks`、`navigate_structure`、文档大纲。

## K6 Wiki 库

- [ ] K6.1 Wiki 合成、反向链接、修订、目录、Wiki 检索；前端 Wiki 浏览。

## K7 数据源

- [ ] K7.1 `packages/connectors` 同步框架：调度、增量、日志、保留。
- [ ] K7.2 连接器逐个接入（取得账号后）；未接入的转路线图第 9 步。

## 收尾

- [ ] 更新 `docs/architecture.md`、路线图进度；同步规格并归档；通知记忆演进变更实施 6.4 文档亲和度（K1 完成即可）。
