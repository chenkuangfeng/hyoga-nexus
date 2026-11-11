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
  - 追加（2026-11-11，用户确认方案：知识库共享目标为共享空间，与智能体共享一致；企业空间提案「知识库共享（`knowledge_base_shares`）」在此落地）：
    - [x] K1.9a 后端：`knowledge_base_shares` 表与迁移（`kb_id`、`shared_space_id`、`level` viewer|editor|admin，唯一 `(kb_id, shared_space_id)`）；`nexus_platform/shared_spaces/kb_shares.py` 仿 `agent_shares`（共享 / 改级别 / 取消 / 有效级别 = min(共享级别, 成员空间在共享空间的角色, 调用者上限)）；`access.can_read` / `readable_bases` 纳入共享空间路径（任一有效级别可读，写仍只限所属空间）；接口 `POST/GET /knowledge/bases/{kb_id}/shares`（`shared_space_id` + `level`）、`DELETE /knowledge/bases/{kb_id}/shares/{shared_space_id}`、`GET /knowledge/shared-bases`；旧的租户授权共享接口 `/shares/{grant_id}` 移除，平台资源授权机制本身不动；审计。
    - [x] K1.9b 后端测试：共享 / 改级别 / 取消、越权（非所属空间管理员、非成员空间）、检索与列表可见性、撤销后不可读、旧接口移除。
    - [x] K1.9c 前端：`api/organization` 的知识库共享函数接 Nexus（适配层纯函数 + 单测）；`plannedEndpoints.ts` 去掉共享条目并改准解析引擎与图谱抽取的说明；共享设置页与「共享给我的知识库」列表可用。
      - 实施说明（2026-11-11）：`api/organization/nexusKnowledgeShares.ts` 纯映射（单测 6 项）；`api/organization/index.ts` 的 `listMyOrganizations`（改读共享空间）、`shareKnowledgeBase`、`listKBShares`、`updateSharePermission`、`removeShare`、`listSharedKnowledgeBases` 接 Nexus，共享的 `id` 即共享空间 id；`plannedEndpoints.ts` 去掉共享条目，解析引擎只拦 `check` / `docreader`，图谱抽取预览改为无阶段的待实现说明。「共享空间内知识库浏览」（`/organizations/{id}/shared-knowledge-bases`）与 `listOrgShares` 仍待实现。**未在浏览器里验证**，也未跑 `vue-tsc` 与 `pnpm build`（本机内存不足），仅 `tsc --strict` 检查新增映射模块并用故意出错探针确认检查有效。父任务 K1.9 与 K0.4 因此保持未勾选。
    - [x] K1.9d 文档：`packages/platform` 文档、`docs/architecture.md` 共享部分、规格。
- [x] K1.10 `evals/knowledge/` 与包文档（README、requirements、design）。
  - 评估门禁 `tests/test_knowledge_eval.py`（关键词通道命中率 ≥ 0.85、越权泄漏 0、引用解析）；向量与混合通道指标待真实 Embedding 模型。

## K2 图谱与 GraphRAG

> K2 后端进度：领域层 `nexus_knowledge.graph`（抽取提示与容错解析、保守合并——同名不同类型不合并、无类型提及只并入唯一类型实体、不按相似名合并；Louvain 社区与报告；有界扩展）；平台 `nexus_platform.knowledge.graph`（`SqlGraphStore` 内置存储、`build` 构建任务、`search` 图检索、`config` 图配置）。构建任务单独成表，文档变化后防抖 30 秒重建，等该库文档索引完成再构建；抽取按块内容哈希缓存，重建只对新文本调用模型。实体、关系、社区报告写入库的向量引擎第二个集合（`g` + 库 ID），由关键词与向量（有 Embedding 时）召回。图元素记录来源文档版本，检索按当前可读版本过滤，文档被替换或删除后立即不再返回。`search_knowledge` 自动附带图谱段（每条带 `[ID:n]`，指向来源块），新增 `query_knowledge_graph` 工具按名称精确查询；超出上限时明确提示截断，图检索失败只丢弃图谱段。三种模式在内置存储上都可用；Neo4j 仍待 K2.7。库的图配置在 `settings.graph`（mode、model_id、entity_types、relation_types、instructions）。测试 `tests/test_knowledge_graph.py`、`tests/test_knowledge_graph_domain.py`。

- [x] K2.0 技术验证：社区划分实现（Leiden / Louvain）在本机内存下的可行性。
  - 结论：networkx 3.6 的 `leiden_communities` 只是后端分派入口，没有安装原生后端（graspologic、igraph）时不可用，不引入原生依赖。改用纯 Python 的 `louvain_partitions`（分层）：1000 节点 0.14 秒、41MB；2 万节点 8 万边 18 秒、134MB，适合后台任务。依赖 `networkx==3.6.1` 加到 knowledge 包。
  - 设计取舍：构建任务单独成表（`knowledge_graph_builds`），不改 `knowledge_jobs` 的类型约束；按块内容哈希缓存抽取结果，文档变化触发的整库重建只对新增块调用模型；图元素记录来源文档版本，检索时按当前范围过滤，旧版本内容不会被召回。
- [x] K2.1 `graph_stores` 注册与 `GraphStore` 端口；`builtin` 图元素表（实体、关系、社区、社区报告，带来源与 schema 版本、构建版本）与迁移。
- [x] K2.2 抽取：`graphrag_light`（实体关系抽取、向量化）。
- [x] K2.3 `graphrag_general`（实体归并、社区划分、社区报告）。
- [x] K2.4 `entity` 模式（WeKnora ExtractConfig）与 `query_knowledge_graph` 工具。
- [x] K2.5 库级构建任务、重建、版本切换；有界图检索、截断提示、降级。
- [x] K2.7 `neo4j` 图存储实现（代码完成，未经真实 Neo4j 验证）；越权与连接测试待 Neo4j 测试环境（K2.7b）。
  - `Neo4jGraphStore` 走 HTTP 事务接口（无驱动依赖），节点/关系/社区均带 `build_id`，查询一律按构建过滤；图存储可在空间内登记（`graph_stores` 表、密钥加密、草稿连接测试、被库使用时不可删除），库的图配置里 `store` 选内置或登记的存储。能力目录标 `verified=false`。测试用假 HTTP 服务器验证请求形状与行映射。
- [ ] K2.7b 真实 Neo4j 验收：连接、写入/删除、越权与降级用例（需用户提供环境）。
- [x] K2.6 前端图存储管理、图谱设置、任务状态、图谱浏览。

> K2.6 进度：接口 `GET /knowledge/graph-stores`、`/bases/{id}/graph`、`/graph/rebuild`、`/graph/overview`；前端 `KBGraphConfig.vue`（模式、图存储、抽取模型、实体/关系类型、补充说明、构建状态、重新构建）、`KnowledgeGraphBrowser.vue`（列表式浏览，含社区报告与截断提示）已替换编辑器里的 WeKnora 抽取演练场；`updateKBConfig` 改为更新 Nexus 库的 Embedding 与分块。图存储注册表只列出引擎（neo4j 待实现），自定义图存储的增删待 K2.7。浏览器验证与整体 `pnpm build` 待在内存充足的环境执行。

## K3 FAQ 库

- [x] K3.1 FAQ 条目、相似问、索引模式、批量导入；检索命中直接返回答案；前端 FAQ 管理。
  - 表 `knowledge_faq_entries`（迁移 `e2f3a4b5c6d7`）；领域规则 `nexus_knowledge.faq`：标准问唯一（重复拦截）、相似问与其他条目冲突则移除、反例与本条问题相同则移除、`##` 分隔的 WeKnora CSV 导入导出、四种索引文本组合（`question_only|question_answer` × `combined|separate`）。检索：FAQ 库的 Pre-Filter 范围是启用且已索引的条目 id，命中返回「问/答」，查询与条目反例近似（相似度 ≥ 0.85）时该条目不返回；编辑条目后先退出检索，worker 重新索引后再恢复；停用/删除立即不可见。索引由 worker 的 `faq.index_tick` 完成，失败重试 3 次后标 `failed`，可手动重试。接口：`/bases/{id}/faq/entries`（增删改查、批量启停）、`import`、`import-file`（CSV）、`export`、`search`、`retry`。前端 FAQ 管理页改接这些接口；标签与按标签批量修改仍待 K5；类别以标签名形式显示。
  - 测试 `tests/test_knowledge_faq.py`、`tests/test_knowledge_faq_domain.py`；后端全量 998 通过，前端 2097 通过（既有字号检查失败除外）。

## K4 解析与分块增强

- [x] K4.1 解析引擎规则与 Office 文档；分块策略、父子分块、分块调试。
  - Office：`ingest/office.py` 用标准库解析 `.docx`（标题样式转章节）、`.pptx`（每页一段，页码=幻灯片号）、`.xlsx`（每个工作表一段，`列名: 值`）；拒绝 DTD 与超大解压（64MB）。分块：`ChunkConfig` 与策略 `auto|heading|heuristic|recursive|legacy`、自定义分隔符；`auto` 按文档特征选择并给出被否决的层级。父子分块：父块不索引、子块索引，命中子块返回父块文本（同一父块只返回一次）；块表新增 `parent_id`、`indexed`（迁移 `f3a4b5c6d7e8`），读取/块列表/图谱构建只看父块或普通块。接口 `POST /knowledge/chunk-preview`（分块调试）、`GET /knowledge/parser-engines`；解析引擎规则里选了未实现的引擎返回 `capability_planned`。外部引擎见 K4.3。
  - 测试：`tests/test_knowledge_domain.py`（Office、策略、父子、预览）、`tests/test_knowledge_service.py`（父子检索、docx 入库）、`tests/test_knowledge_api.py`；后端全量 1008 通过。
- [x] K4.2 OCR、VLM 图片描述、图片库；ASR（代码完成，未经真实模型服务验证，能力目录标 `verified=false`）。
  - 客户端 `nexus_runtimes/native/models/media.py`（OpenAI 兼容：视觉对话带图片、`/audio/transcriptions`，与对话模型同一受限传输）；平台 `nexus_platform/knowledge/media.py`：图片（png/jpg/webp/gif）由视觉模型输出描述与图中文字，作为文档文本入索引；扫描 PDF 无文字层时，按页取内嵌图片（pypdf，最多 30 页）逐页识别；音频（mp3/wav/m4a/flac/ogg/aac）由语音模型转写。配置 `settings.vlm_config`（model_id、description_language、custom_instructions）与 `asr_config`（model_id、language），模型须是创建者可用的 vision / speech 类型；未配置模型时上传图片/音频直接拒绝并说明原因。模型调用用库创建者的 Key。图片库：`GET /bases/{id}/images`（图片文档与模型写的描述，支持关键词），前端图片库接入；图片属性筛选与排序仍待实现。worker 注入视觉/语音客户端工厂。
  - 测试 `tests/test_knowledge_media.py` 只用假客户端验证流水线；真实 VLM / ASR 服务验证待环境（K4.2b）。
- [x] K4.3 外部解析引擎（移植 WeKnora `internal/infrastructure/docparser` 的 MinerU、PaddleOCR-VL，代码完成，未经真实服务验证）。
  - `nexus_knowledge/ingest/engines.py`：`mineru`（自建 `/file_parse` 多部分上传）、`mineru_cloud`（mineru.net v4：申请上传地址 → PUT 文件 → 轮询 → 内联 Markdown 或结果压缩包）、`paddleocr_vl`（自建 `/layout-parsing`）、`paddleocr_vl_cloud`（AI Studio 作业：提交 → 轮询 → JSONL 结果）；输出 Markdown 后按标题切成章节，丢弃指向本地图片的引用。每个主机单独建客户端并走与模型调用相同的受限传输（含私网白名单）。空间级连接配置表 `knowledge_parser_configs`（迁移 `c6d7e8f9a0b1`，密钥加密、读取时打码、回传打码值保留原密钥、仅管理员可写）；库规则 `parser_engine_rules` 按文件类型选引擎，未命中走 builtin；`simple` 引擎并入 builtin 的子集。接口 `GET/PUT /knowledge/parser-engine-config`、`GET /knowledge/parser-engines`（含未配置原因）。测试 `tests/test_knowledge_engines.py`（模拟传输）。
  - `anydoc` 已用 Python 原生实现（见 K4.4）。仍待实现：`markitdown`、`weknoracloud`（需要对应服务的协议资料或账号）。
- [x] K4.4 `anydoc` 引擎：进程内转换 Office 与电子书，无需外部服务（已用 WeKnora 测试用的同一批样本验证）。
  - WeKnora 的 anydoc 是第三方原生库（`firecrawl/anydoc`）的 cgo 绑定，源码不在仓库里，无法直接移植；`nexus_knowledge/ingest/anydoc.py` 用 Python 实现同一组文件类型：旧版二进制 `doc`（读 FIB 与分段表）、`ppt`（读文本原子）、`xls`（xlrd），`odt/odp/ods`（content.xml）、`rtf`（控制字分词，跳过字体表、样式、图片，解码 `\'hh` 与 `\uN`）、`epub`（按 spine 顺序，每章一节）、`html/htm`，以及 `docm/pptm/xlsm`（复用 OOXML 解析）；解包大小受限、拒绝 DTD。新增依赖 `olefile`、`xlrd`（纯 Python）。和 WeKnora 一样：没有规则时，builtin 读不了的格式自动走 anydoc，显式规则优先。夹具 `tests/fixtures/office/`（MIT，来自 firecrawl/anydoc v0.2.4，WeKnora 同款）；测试 `tests/test_knowledge_anydoc.py`；后端全量 1053 通过。
  - 局限：`.doc` 不读样式，所以标题层级不会被识别；`rtf`/`epub` 里的公式对象不转文字。
- [ ] K4.2b 真实视觉与语音模型验收：图片描述质量、扫描 PDF、音频转写、超大文件与超时（需用户提供模型服务）。

## K5 组织与增强

- [x] K5.1 标签、文件夹、置顶、自定义元数据（自动打标见 K5.2）。
  - 迁移 `a4b5c6d7e8f9`：`knowledge_tags`、文档 `tag_ids/folder_path/custom_metadata`、FAQ 条目 `tag_id`、库 `pinned`。`nexus_platform.knowledge.organize`：标签增删改（删除在被使用时需 `force`，只从文档上摘掉，不删文档）、批量设置文档标签/文件夹/元数据、文件夹由路径派生（树含直接与累计数量、重命名整棵子树、拒绝 `..` 与移入自身）、置顶（置顶库排前）。检索可按标签、文件夹、元数据缩小范围（`DocumentFilter`），只缩小不放宽 Pre-Filter；`search_knowledge` 新增 `tags`（标签名）、`folder`、`metadata` 参数。FAQ 导入的「分类」列自动建为标签；FAQ 条目可设标签并按标签筛选。接口：`/bases/{id}/tags`、`PATCH /bases/{id}/documents`、`PUT /document-tags`、`/bases/{id}/folders`、`/bases/{id}/pin`，文档列表支持 `tag_ids`、`folder_path`、`file_type`。前端标签/文件夹/置顶/FAQ 标签接口已改接。测试 `tests/test_knowledge_organize.py`。
- [x] K5.2 文档摘要、提问生成、自动打标、库画像。
  - 迁移 `b5c6d7e8f9a0`：块 `questions`、版本 `summary/enrichment`、作业类型 `enrich`。文档版本变为 `ready` 后，配置了模型的库排队 `enrich` 作业（`nexus_platform.knowledge.enrich`），按步骤幂等执行并记入 `version.enrichment`：`summary`（`settings.summary_model_id`）、`questions`（`question_generation_config`，每个问题是 `q:<块>:<n>` 的额外索引行，命中后还原为所属块，用户的措辞即使文档里没有也能召回）、`tags`（`auto_tag_config`，从已有标签中选或新建，默认已打标则跳过）。无版本的作业重生成库画像（`profile_config`），存入 `settings.generated_profile`，智能体的知识库目录在没有手写简介时使用它；文档列表工具附带摘要。全部模型调用用库创建者的 Key；失败按退避重试，不会把版本标为失败，也不影响检索。配置的模型必须是创建者可用的对话模型，问题数与标签数有范围校验。接口 `POST /bases/{id}/profile/generate`。测试 `tests/test_knowledge_enrich.py`、`tests/test_knowledge_enrich_domain.py`；后端全量 1021 通过。
  - 未做：手动编辑摘要/生成的问题（前端对应接口仍为待实现）、重排（K5.3b）。
- [x] K5.3a 元数据过滤（见 K5.1）、同义词、结构导航工具（RAGFlow `grep_chunks`、`navigate_structure`/大纲）。
  - 同义词：库设置 `settings.synonyms`（每组 2–10 个词，最多 200 组）；查询含其中一个词时关键词通道补充其余词，向量通道不变（`nexus_knowledge.retrieval.synonyms`）。编辑器高级设置里有同义词文本框（每行一组）。结构工具：`grep_chunks`（对可读绑定文档的当前块做精确子串匹配，返回带 `[ID:n]` 的片段）、`document_outline`（由块的章节路径生成标题/页码大纲与块区间）、`read_document` 新增 `section` 参数按标题路径读取。三者都是只读工具，同样受 Pre-Filter 约束；编辑器只把空间已启用的知识库工具加入智能体，`search_knowledge` 为必选。测试见 `tests/test_knowledge_tools.py`、`tests/test_knowledge_organize.py`。
- [x] K5.3b 重排（移植 WeKnora `internal/reranking` 与 `models/api` 重排协议，代码完成，未经真实模型验证）。
  - 策略 `nexus_knowledge.retrieval.rerank`：阈值（默认 0.2；无结果且阈值 > 0.3 时放宽到 ×0.7；仍无结果时保留得分 ≥ 0.15 的最高一条，否则返回空）、综合分 `0.6×模型分 + 0.3×检索分 + 0.1`、MMR（λ=0.7）去近似重复、候选截断与段落长度限制。客户端 `nexus_runtimes/native/models/rerank.py`：`cohere`（Cohere/Jina/智谱/SiliconFlow/vLLM）、`tei`、`dashscope` 三种线格式，由模型选项 `rerank_api` 选择。库设置 `rerank_config {enabled, model_id, threshold, top_k}`，模型为重排类型；重排属于查询时模型，使用检索者自己的 Key，用户无权/客户端缺失/供应商出错时保持原顺序并在检索结果 `rerank` 字段给出原因（不会使检索失败）。检索测试接口可传 `rerank=false` 跳过。编辑器高级设置有重排开关与模型选择。测试 `tests/test_knowledge_rerank.py`（策略、三种协议、检索接入）。
- [ ] K5.3c 真实重排模型验收（需环境）。

## K6 Wiki 库

- [x] K6.1 Wiki 合成、反向链接、修订、目录、Wiki 检索；前端 Wiki 浏览。
  - 数据：`knowledge_wiki_pages`（slug 唯一、乐观锁 `version`、`source_refs`、`in_links/out_links`、`index_state`）、`knowledge_wiki_revisions`（每次写入前快照）、`knowledge_wiki_folders`、`knowledge_wiki_issues`；任务类型增加 `wiki`；迁移 `d7e8f9a0b1c2`。
  - 领域 `nexus_knowledge.wiki`：提示词逐字移植自 WeKnora `prompts_wiki.go`（摘要、知识抽取、页面修改、目录规划、去重、首页简介及三档抽取粒度），`rules.py` 做 slug 规范化、`[[slug|名]]` 链接解析/清理、分类路径、模型回复解析、同名候选预选。
  - 合成 `wiki_ingest`（创建者 Key，库设置 `wiki_config.synthesis_model_id` 必填）：文档 ready 后排 `wiki` 任务 → 摘要页 `summary/<文档>` → 抽取实体/概念 → 词面预选 + 模型去重合并（新名并入别名）→ 以文档原文摘录为依据逐页写入（未知或自指链接去除）→ 一次调用规划目录并复用现有文件夹 → 本文档不再产出的页面去除来源 → 更新 `index` 页简介。删除文档排“撤回”任务：无来源页面删除、共享页面按“已删除/保留来源”提示词重写、其他页面指向已删页面的链接清除。开启 Wiki 或更换模型时对已有文档补跑。
  - 页面接口 `wiki.py` + `knowledge_wiki.py`：页面增删改（过期 `version` 回 409 与 `current_version`）、修订列表/读取/回退（回退本身是新修订）、文件夹增删改移（子树路径与页面分类跟随）、目录首页、链接图（总览/邻域）、统计、页面搜索、lint 问题（断链/孤页/空页）与状态、重建链接。读需读权限，改需写权限。
  - 检索：页面行写入库的向量索引（`w:<页面>:<n>`，页面 id 充当“版本”），Pre-Filter 范围含已发布且已索引的页面；命中带 slug，`read_document` 接受页面 id 返回全文。Wiki 页面默认不参与带标签/文件夹/元数据过滤的检索。
  - 前端：`api/wiki` 改指 Nexus；移除 Wiki 待实现拦截；能力 `kb_type/wiki`、`indexing/wiki`、`kb_feature/wiki_pages` 上线（`verified=false`，待真实模型验收）。
  - 测试 `tests/test_knowledge_wiki.py`（规则、合成端到端、去重合并与撤回、页面/修订/目录/图/lint/权限、HTTP）。
  - 未做：WeKnora 的“按块引用”二遍抽取（`WikiCandidateSlug`/`WikiChunkCitation`）与续写（`finish_reason=length`）——以文档摘录代替；智能体写 Wiki 的工具；与记忆演进 6.4 文档亲和度的衔接。
- [ ] K6.2 真实模型验收 Wiki 合成质量（需环境）。

## K7 数据源

> 2026-11-07 用户决定先跳过，暂不实施；能力目录中 18 个数据源保持「待实现」。

- [ ] K7.1 `packages/connectors` 同步框架：调度、增量、日志、保留。
- [ ] K7.2 连接器逐个接入（取得账号后）；未接入的转路线图第 9 步。

## 收尾

- [ ] 更新 `docs/architecture.md`、路线图进度；同步规格并归档；通知记忆演进变更实施 6.4 文档亲和度（K1 完成即可）。
