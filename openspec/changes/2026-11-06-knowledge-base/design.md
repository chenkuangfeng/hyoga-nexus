# 设计：知识库（路线图第 6 步 6.1–6.3）

按决定 1–7 的推荐方案编写；用户选择备选方案时同步修改本文。

## 1. 包结构与依赖方向

```text
packages/knowledge/src/nexus_knowledge/      纯领域逻辑，只依赖 nexus_core
├── domain/      值对象：KnowledgeBase、Document、DocumentVersion、Chunk、SearchHit、Citation
├── ingest/      parse（文本、Markdown、PDF）、chunk（标题切段 + 定长重叠）、hash
├── index/       VectorIndex、KeywordIndex 端口；InProcessVectorIndex（余弦）
├── retrieval/   fuse（加权 RRF、单通道缩放）、SearchPlan（范围 + 参数）、诊断结构
├── evidence/    EvidenceRegistry（[ID:n] 登记、序列化）、citations（解析与校验）
├── providers/   BlobStore 端口与本地目录实现
└── graph/       保留占位（6.4）

packages/platform/src/nexus_platform/knowledge/  持久化、授权、服务、作业
├── service.py   库与文档的增删改查、上传去重、版本切换、删除
├── scope.py     Pre-Filter：(principal, agent_version, 可选库子集) → 允许的 (库, 当前版本) 集合
├── search.py    在范围内跑关键词与向量通道、融合、降级、审计
├── jobs.py      knowledge_index_jobs 的推进（parse → chunk → embed → activate）
└── pg.py        pgvector 与 tsvector 的方言实现（仅 PostgreSQL 导入）

packages/tools/src/nexus_tools/builtins/knowledge.py   三个工具，经 services 端口调用平台
apps/api/.../http/knowledge.py                        HTTP 接口
apps/worker/.../knowledge_index.py                    作业循环、Embedder 工厂装配
```

`nexus_knowledge` 不导入 SQLAlchemy、平台或厂商 SDK；平台实现其端口。pypdf 是 `hyoga-nexus-knowledge` 的新依赖，锁定版本。

## 2. 数据模型

| 表 | 关键列 | 约束 |
| --- | --- | --- |
| `knowledge_bases` | tenant_id、name、description、embedding_model_version_id、chunk_size、chunk_overlap、status（active / deleting）、created_by | (tenant_id, name) 唯一 |
| `knowledge_documents` | kb_id、filename、current_version_id、status（active / deleting） | (kb_id, filename) 唯一 |
| `knowledge_document_versions` | document_id、version、content_hash、blob_key、size、mime、state（pending / parsing / chunked / embedding / ready / failed）、index_version、chunk_count、error | (document_id, version) 唯一；(kb_id, content_hash) 索引用于去重 |
| `knowledge_chunks` | version_id、ordinal、content、tokens、page、section、char_start、char_end | (version_id, ordinal) 唯一 |
| `knowledge_chunk_vectors` | chunk_id、model_version_id、vector（SQLite 为 JSON；PostgreSQL 为 `vector`） | (chunk_id, model_version_id) 唯一 |
| `knowledge_index_jobs` | version_id、stage、attempts、available_at、last_error、idempotency_key | 每个版本一条有效任务 |

SQLite 另建 FTS5 虚表 `knowledge_fts(tokens, content='', contentless_delete=1)`，rowid 对应块，与记忆 `memory_fts` 同样的建表与探测方式；PostgreSQL 在 `knowledge_chunks` 上加 `tsv tsvector` 生成列与 GIN 索引，pgvector 列加 HNSW 索引（余弦）。迁移按方言分支。

## 3. 上传与版本

1. API 接收文件，计算 SHA-256。库内已有相同哈希的版本（任一文档）→ 返回该文档，`deduplicated=true`。
2. 否则写入 BlobStore（键 `tenant/kb/document/version`），建文档（同名则复用）与新版本 `pending`，建作业。原文件写入失败时整体回滚。
3. 作业推进：
   - `parse`：取原文件解析为带位置的段落（页码 / 章节路径）；空文本 → 失败（`empty_text`）。
   - `chunk`：分块后一次性写入 `knowledge_chunks`（与阶段推进同一事务，幂等：先删本版本已有块）。
   - `embed`：按批计算缺失的向量，每批单独提交，中断后只补缺。库未配置模型时跳过此阶段。
   - `activate`：同一事务内把文档的 `current_version_id` 指向本版本、写 FTS 行、删除旧版本的 FTS 行；旧版本的块与向量交给清理任务。
4. 失败：`attempts` 加一，按 30s、2m、10m 退避，第 4 次失败标记 `failed` 并记录原因；API 可重试（重置次数）。

版本切换只发生在 `activate`，因此检索永远只看到完整索引的版本。

## 4. Pre-Filter 与检索

`scope.resolve(db, principal, tenant_id, agent_version_id, requested_kb_ids)`：

1. 取智能体版本绑定的库 ID；若给了 `requested_kb_ids`，取交集（超出部分忽略并在诊断中列出）。
2. 对每个库重新判断主体的读权限：库所属空间的成员，或经 `resource_grants` 授予本空间且未撤销；库与文档状态必须是 `active`。
3. 返回 `{kb_id: [current_version_id, ...]}`。空集合直接返回空结果，不执行检索。

检索只在这些版本 ID 内进行：
- 关键词：SQLite `knowledge_fts MATCH ? AND rowid IN (范围内块)`；PostgreSQL `tsv @@ query AND version_id = ANY(:ids)`。
- 向量：SQLite 读取范围内块的向量（同一模型版本），进程内余弦取前 k；PostgreSQL `ORDER BY vector <=> :q LIMIT k`，带 `version_id = ANY(:ids)` 条件。
- 融合：WeKnora `fuseWithRRF`（k=60，向量与关键词权重默认 1:1），只有一个通道时按该通道分数缩放。
- 返回每条结果的块、文档、版本、页码、章节、分数、`channels: {vector: rank, keyword: rank}`、`degraded`、`index_version`。

向量通道失败（无模型、查询者无权、供应商错误、维度不符）只关闭该通道，记录 `knowledge.search_degraded` 审计；权限错误永远不会触发「换一个范围再查」。

## 5. 工具与证据

- `search_knowledge(query, kb_ids?, limit=8)`：输出每条结果为

  ```text
  [ID:3] 《文件名》 第 2 页 · 章节
  正文片段……
  ```

  同一段正文在本 Run 中第二次出现时只输出 `[ID:3] 《文件名》（正文见前文）`。末尾附一句：回答中引用资料时在句末写对应的 `[ID:n]`，不要编造编号。
- `read_document(document_id, chunk_ordinal?, before=1, after=3)`：按块读取上下文，同样登记编号。
- `list_documents(kb_id?, limit=50, cursor?)`：只列出范围内文档的名称、ID、更新时间、状态。
- 登记表 `EvidenceRegistry` 存放在 Run 的 progress 里（`evidence: [{n, chunk_id, version_id, text_hash}]`），恢复时还原。
- Run 结束时解析最终回答的 `[ID:n]`：已登记的编号生成 `citations`（写入助手消息的元数据，前端渲染为可点击引用）；未登记的编号产生 `knowledge.citation_invalid` 事件，不生成引用。

## 6. 权限与审计

- 写操作（建库、改设置、上传、删除、重试）：空间管理员或库创建者。
- 读操作（列表、详情、块预览、检索测试）：空间成员或被授予共享的空间成员。
- 审计：`knowledge_base.created/updated/deleted`、`knowledge_document.uploaded/deleted/retried`、`knowledge.search_degraded`、`credential.resolved(purpose=knowledge.embedding)`。
- 检索测试接口与工具共用 `scope.resolve`，管理员也不能绕过 Pre-Filter。

## 7. 前端

- 复用 `views/knowledge/KnowledgeBaseList.vue`、`KnowledgeBase.vue`、`KnowledgeBaseEditorModal.vue` 和检索测试页，`api/knowledge-base` 改为调用 Nexus 接口（路径前缀 `/api/v1/tenants/{tenant_id}/knowledge-bases`）。
- 隐藏 FAQ、Wiki、图片、标签、文件夹、数据源同步等入口；文档状态展示 `pending / parsing / … / failed` 与失败原因、重试按钮。
- 对话消息渲染 `[ID:n]` 为引用标记，点击显示文档名、页码与块正文；无效引用以灰色标出。
- 智能体编辑器新增「知识库」分区：多选当前空间可读的库。

## 8. 配置

```toml
[knowledge]
storage_dir = "data/knowledge"     # BlobStore 本地目录
max_upload_mb = 50
index_concurrency = 1              # 本机内存小，默认串行（Octop 同）
```
