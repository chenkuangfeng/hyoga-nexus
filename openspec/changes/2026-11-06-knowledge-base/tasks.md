# 实施任务

状态：草案，等待用户确认决定 1–7。

## 0. 准备

- [x] 0.1 阅读 Octop `infra/knowledge/`（gate、parse、chunk、jobs、pg_index、retrieve、citations、tools）。
- [x] 0.2 阅读 RAGFlow `agentic_rag/evidence_registry.go`、`citations.go`。
- [x] 0.3 阅读 WeKnora `knowledgebase_search_fusion.go`、`retriever/sqlite/repository.go`。
- [ ] 0.4 阅读 WeKnora `agent/tools/search_knowledge.go`、`read_document.go`、`list_documents.go`、`knowledgebase_access.go`，确定工具参数与输出形状。
- [ ] 0.5 用户确认决定 1–7。
- [ ] 0.6 先更新文档：`docs/architecture.md` 2.10（存储选型、引用处理）、路线图第 6 步「待确认」改为已确定。

## 1. 领域包 `nexus_knowledge`

- [ ] 1.1 `domain` 值对象与 `ingest.parse`（文本解码 UTF-8 → GB18030、Markdown 章节、pypdf 按页）及单元测试。
- [ ] 1.2 `ingest.chunk`（标题切段 + 定长重叠，记录页码、章节、字符起止）及单元测试。
- [ ] 1.3 `retrieval.fuse`（加权 RRF、单通道缩放）移植 WeKnora 测试样例。
- [ ] 1.4 `evidence.EvidenceRegistry` 与 `citations`（登记、重复正文、序列化恢复、解析与校验）移植 RAGFlow 测试样例。
- [ ] 1.5 `index` 端口与 `InProcessVectorIndex`；`providers.BlobStore` 端口与本地目录实现。

## 2. 持久化与迁移

- [ ] 2.1 SQLAlchemy 模型与 Alembic 迁移（SQLite：FTS5 虚表与探测；PostgreSQL：pgvector、tsvector、GIN、HNSW），升降级测试。
- [ ] 2.2 `[knowledge]` 配置项、`configs/nexus.example.toml` 与 configs 说明。

## 3. 平台服务

- [ ] 3.1 库与文档服务：增删改查、上传去重、版本、删除标记、资源注册、审计。
- [ ] 3.2 作业：parse → chunk → embed → activate，阶段提交、退避重试、恢复；worker 装配 Embedder 工厂（复用记忆的客户端）。
- [ ] 3.3 清理任务：删除标记的库与文档、被替换的旧版本。
- [ ] 3.4 `scope.resolve` Pre-Filter 与 `search`（双通道、融合、降级、诊断）；越权测试逐路径覆盖。

## 4. 工具与 Runtime

- [ ] 4.1 `search_knowledge`、`read_document`、`list_documents`，工具组 `knowledge`，绑定库时自动可用；目录与编辑器标签。
- [ ] 4.2 证据登记存入 Run progress，挂起恢复测试。
- [ ] 4.3 Run 结束解析引用，写入消息元数据；`knowledge.citation_invalid` 事件。
- [ ] 4.4 智能体版本绑定 `knowledge_base`，发布时校验读权限。

## 5. API

- [ ] 5.1 库、文档、版本、重试、删除、块预览接口与权限测试。
- [ ] 5.2 检索测试接口（返回通道名次、分数、降级原因）。

## 6. 前端

- [ ] 6.1 `api/knowledge-base` 改接 Nexus 接口；列表、编辑弹窗、详情、上传、状态与重试。
- [ ] 6.2 检索测试页；隐藏 Nexus 不提供的 WeKnora 功能入口。
- [ ] 6.3 对话消息的引用渲染与无效引用标记。
- [ ] 6.4 智能体编辑器「知识库」分区。
- [ ] 6.5 单元测试；完整 `pnpm build` 与浏览器验证在内存充足的环境执行（本机 1.8GB 会 OOM）。

## 7. 评估与文档

- [ ] 7.1 `evals/knowledge/` 小语料与问答对：召回命中率、引用有效率、越权泄漏数。
- [ ] 7.2 `packages/knowledge/README.md`、`docs/requirements.md`、`docs/design.md`；更新 `docs/architecture.md` 2.10、路线图 6.1–6.3 进度。
- [ ] 7.3 全量 pytest 通过后同步规格并归档；通知记忆演进变更可以实施 6.4 文档亲和度。
