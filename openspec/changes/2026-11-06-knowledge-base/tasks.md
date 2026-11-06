# 实施任务

状态：草案第 2 版，等待用户确认决定 1–8。每个阶段单独提交推送；阶段内追加工作写回本文件。

## 0. 准备

- [x] 0.1 阅读 Octop `infra/knowledge/`、RAGFlow `agentic_rag/` 证据与引用、WeKnora 融合与 SQLite 检索。
- [x] 0.2 梳理 WeKnora 知识库功能面（库类型、索引策略、向量库、存储后端、解析引擎、FAQ、Wiki、图谱、数据源、标签、文件夹、图片、共享、活动）。
- [x] 0.3 阅读 RAGFlow `service/graph/`（GraphRAG 检索）。
- [ ] 0.4 用户确认决定 1–8。
- [ ] 0.5 更新文档：`docs/architecture.md` 2.10（向量库注册、图谱存储、GraphRAG、引用处理）、路线图第 6 步子计划改为 K0–K7、`2026-11-02-weknora-parity` 第 3 阶段指向本变更。

## K0 前端全量接入与能力目录

- [ ] K0.1 `nexus_knowledge.capabilities`：能力项清单（库类型、索引策略、向量引擎、存储后端、解析引擎、数据源类型、库设置项），每项 `available | planned` 与阶段；接口与单元测试。
- [ ] K0.2 前端能力目录 store 与 `PlannedBadge`、禁用提交的通用处理。
- [ ] K0.3 `api/knowledge-base`、向量库、存储后端、解析引擎、检索设置的接口模块改接 Nexus；Nexus 未提供的调用短路为「待实现」。
- [ ] K0.4 逐页核对：知识库列表与详情、FAQ、Wiki、图谱、标签、文件夹、图片库、数据源、共享、活动、设置页四项；无 404，未实现项均有标记。

## K1 文档库核心

- [ ] K1.1 领域：`ingest.parse`（文本、Markdown、CSV、JSON、pypdf）、`ingest.chunk`（标题/页 + 定长重叠）、`retrieval.fuse`、`evidence`，移植参考项目测试样例。
- [ ] K1.2 端口：`VectorIndex`（含范围过滤下推）、`KeywordIndex`、`BlobStore`；实现 sqlite、postgres（pgvector + tsvector）、本地目录。
- [ ] K1.3 持久化与迁移：`knowledge_bases`、`knowledge_documents`、`knowledge_document_versions`、`knowledge_chunks`、`knowledge_chunk_vectors`、`knowledge_jobs`、`vector_stores`、`storage_backends`；升降级测试。
- [ ] K1.4 服务：库与文档增删改查、上传去重、版本切换、删除标记与清理、资源注册、共享、审计。
- [ ] K1.5 作业：parse → chunk → embed → activate，阶段提交、退避重试、恢复、取消。
- [ ] K1.6 向量库与存储后端注册：增删改查、密钥加密、连接测试、库创建时选择。
- [ ] K1.7 Pre-Filter 与混合检索、降级、诊断；越权测试逐路径。
- [ ] K1.8 工具 `search_knowledge`、`read_document`、`list_documents`；证据登记存 Run progress；Run 结束引用校验；智能体绑定与发布校验。
- [ ] K1.9 前端：列表、创建/编辑（类型、索引策略、向量库、存储、模型、分块）、详情、上传、状态与重试、块预览、检索测试、共享、活动、引用渲染、智能体编辑器知识库分区。
- [ ] K1.10 `evals/knowledge/` 与包文档（README、requirements、design）。

## K2 图谱与 GraphRAG

- [ ] K2.0 技术验证：社区划分实现（Leiden / Louvain）在本机内存下的可行性。
- [ ] K2.1 图元素表（实体、关系、社区、社区报告，带来源与 schema 版本、构建版本）与迁移。
- [ ] K2.2 抽取：`graphrag_light`（实体关系抽取、向量化）。
- [ ] K2.3 `graphrag_general`（实体归并、社区划分、社区报告）。
- [ ] K2.4 `entity` 模式（WeKnora ExtractConfig）与 `query_knowledge_graph` 工具。
- [ ] K2.5 库级构建任务、重建、版本切换；有界图检索、截断提示、降级。
- [ ] K2.6 前端图谱设置、任务状态、图谱浏览。

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
