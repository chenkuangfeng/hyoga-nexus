# 知识库：文档生命周期、授权后混合检索、证据引用（路线图第 6 步 6.1–6.3）

## 状态

草案（2026-11-06），等待用户确认决定 1–7 后再编码。

## 原因

路线图第 6 步「知识库」尚未开始：`packages/knowledge` 只有占位目录，没有数据模型、解析、索引、检索或工具。依赖它的工作因此停滞：

1. 智能体不能引用资料：内置工具里没有 `search_knowledge`、`read_document`、`list_documents`（路线图 3.10 预留）。
2. 记忆演进提案 `2026-11-06-memory-evolution` 的 6.4 文档亲和度要等知识检索完成，该变更因此无法归档。
3. 前端 `apps/web/src/views/knowledge/` 是按 WeKnora 复刻的界面，调用的是 WeKnora 的接口，在 Nexus 上不能用。
4. 共享空间的知识库共享（`2026-11-03-enterprise-personal-spaces` 第 79 行）和智能体编辑器的知识库分区都在等这个模块。

## 参考源码

本地副本 `/project/opensource/agents/`。

| 项目（版本） | 文件 | 借鉴点 |
| --- | --- | --- |
| Octop `4811eb4` | `src/octop/infra/knowledge/gate.py` | 能力门控：开关和 Embedding 前置条件分开检查，不可用时返回可区分的原因 |
| | `parse.py`、`chunk.py` | 文本解码先 UTF-8 再 GB18030；PDF 用 pypdf；定长重叠分块 |
| | `jobs.py` | 解析 → 分块 → 向量 → 原子替换文档的全部块；进程重启后恢复未完成任务；并发 1 |
| | `pg_index.py` | pgvector 表结构与余弦检索，按库过滤 |
| | `citations.py`、`tools.py`、`retrieve.py` | 工具结果附带机器可读引用；工具描述列出本轮挂载的库名与简介；字符预算 |
| RAGFlow `e5a5060c4` | `internal/agentic_rag/evidence_registry.go` | 每个 Run 的证据登记：首次出现分配 `[ID:n]`，重复出现沿用同一编号，重复正文只给编号不重发 |
| | `citations.go` | 从最终回答中提取 `[ID:n]`，只解析已登记的编号，无效编号不生成引用 |
| WeKnora `e1f9a6166` | `internal/application/service/knowledgebase_search_fusion.go` | 关键词与向量结果按加权 RRF 融合，分数归一到 [0, 1]；单通道时保留原分数或按最大值缩放 |
| | `internal/application/repository/retriever/sqlite/repository.go` | SQLite 下 FTS5 关键词索引（CJK 二元分词）与向量索引并存；FTS5 不可用时关闭关键词通道而不是报错 |
| | `internal/agent/tools/search_knowledge.go`、`read_document.go`、`list_documents.go` | 三个工具的参数和返回形状 |
| | `internal/application/service/knowledge_caller_scope_test.go`、`knowledgebase_access.go` | 先按调用者可访问的库确定范围再检索 |

## 范围

### 范围内

**A. 数据模型与生命周期（6.1，持久化与 API 变化）**
1. 新表：`knowledge_bases`（所属空间、名称、简介、分块参数、Embedding 模型版本、状态）、`knowledge_documents`（库、文件名、内容哈希、当前版本、状态）、`knowledge_document_versions`（不可变：原文件存储键、大小、MIME、解析状态、索引版本、块数、失败原因）、`knowledge_chunks`（版本、序号、正文、页码或章节、字符起止、分词文本、索引版本）、`knowledge_chunk_vectors`（块、模型版本、向量）、`knowledge_index_jobs`（可恢复任务：阶段、尝试次数、失败原因、幂等键、下次可执行时间）。
2. 上传：同一库内按内容哈希去重（相同内容返回已有文档，不新建版本）；同名不同内容生成新版本，新版本索引完成后才切换为当前版本，旧版本的块随即不再被检索。
3. 原文件存放在可替换的对象存储端口 `BlobStore` 后面，首期实现为本地目录（`configs/nexus.toml` 新增 `[knowledge] storage_dir`）。数据库只存元数据和状态。
4. 解析首期支持纯文本（`.txt`、`.md`、`.markdown`、`.csv`、`.json`）和文本型 PDF（pypdf）。扫描 PDF 不做 OCR，解析出空文本时任务失败并写明原因。
5. 解析、分块、向量化由 worker 执行，按阶段提交，崩溃后从最后提交的阶段继续；失败按退避重试，超过上限标记失败，可手动重试。
6. 删除文档或库：先标记删除并立即从检索中排除，再由 worker 清理块、向量和原文件。

**B. 授权与检索（6.2，Runtime 行为变化）**
7. 知识库作为平台资源注册（`platform_resources.kind='knowledge_base'`）。空间成员可读，空间管理员和库的创建者可写；跨空间共享沿用 `resource_grants`（只读）。
8. Pre-Filter：每次检索先在数据库里算出调用者（Run 的主体 + 智能体版本绑定的库）此刻有权访问且状态正常的库和当前文档版本集合，只在这个集合内检索。撤权、删除、版本切换在下一次检索立即生效。
9. 混合检索：关键词通道（SQLite 用 FTS5 + CJK 二元分词，复用 `nexus_memory.text.tokenize`；PostgreSQL 见决定 2）和向量通道分别召回，按加权 RRF 融合并归一到 [0, 1]。结果保留通道、各通道名次、分数、文档版本和索引版本，便于诊断。
10. 降级：未配置 Embedding 模型、调用者无权使用该模型、供应商报错时，只走关键词通道，结果里标注 `degraded` 和原因并写审计；任何降级都不会扩大检索范围。
11. 工具：`search_knowledge`（查询、可选库 ID 子集、条数）、`read_document`（按文档或块读取一段正文，分页）、`list_documents`（列出可访问库中的文档）。三者都是只读工具（`risk='read'`），归入新的工具组 `knowledge`。`search_knowledge` 的描述列出本次绑定的库名与简介（Octop 做法）。
12. 证据登记：同一 Run 内，进入模型上下文的每个块按首次出现分配 `[ID:n]`，重复出现沿用原编号，同一段正文第二次出现只给编号和一句「见前文」（RAGFlow 做法）。登记表随 Run 进度持久化，挂起恢复后编号不变。
13. 引用校验：Run 结束时解析最终回答中的 `[ID:n]`，生成引用列表（文档、版本、块、页码）写入消息；指向未登记编号的引用不进入列表，并产生 `knowledge.citation_invalid` 事件（处理方式见决定 5）。

**C. 智能体绑定**
14. 智能体版本通过 `agent_resource_bindings(kind='knowledge_base')` 绑定多个库；绑定了库的智能体自动获得三个知识工具（与记忆工具组相同的开关方式）。发布时校验发布者对每个库有读权限。

**D. 管理页与评估（6.3）**
15. API：库的增删改查、文档上传与列表、版本列表、重试解析、删除、块预览、检索测试（返回各通道的名次与分数、是否降级）。
16. 前端：把现有 `views/knowledge/` 的列表、详情、上传、文档状态、检索测试接到 Nexus 接口；WeKnora 独有而 Nexus 不提供的功能（FAQ、Wiki、图片管线、标签、文件夹等）先隐藏。智能体编辑器增加「知识库」分区。
17. 评估集 `evals/knowledge/`：固定小语料与问答对，指标为召回命中率、引用有效率、越权泄漏数（必须为 0）。

**E. 文档**
18. 新建 `packages/knowledge/README.md`、`docs/requirements.md`、`docs/design.md`；更新 `docs/architecture.md` 2.10 的存储选型与实现要点、路线图第 6 步的进度与「待确认」项。

### 范围外

- 6.4 图谱增强（图谱抽取、归一、图检索）：需要另选图数据库，本变更完成后单独提案。
- OCR、Office 文档（docx、pptx、xlsx）、网页抓取、外部数据源同步：后续按需追加。
- 独立向量服务（Milvus、Qdrant 等）：本变更只定义 `VectorIndex` 端口，见决定 1。
- 重排模型（rerank）：端口预留，默认关闭。
- 每轮自动注入检索结果（不经工具）：本变更只做工具形式的检索，见决定 4。
- 记忆演进 6.4 文档亲和度：本变更完成后在原记忆变更里实施。

## 待确认的决定

1. **向量存储**
   - 推荐：定义 `VectorIndex` 端口，首期两个实现。PostgreSQL 用 pgvector（需在数据库上执行 `CREATE EXTENSION vector`，与 Octop 一致）；SQLite（本地开发与测试）把向量以 JSON 存在 `knowledge_chunk_vectors`，在 Pre-Filter 后的候选范围内进程内计算余弦（与记忆 D2 相同，适合小库）。PostgreSQL 环境缺少 pgvector 时启动报错并给出处理办法，不静默退化。
   - 备选 A：SQLite 也用 sqlite-vec 扩展（WeKnora 做法）：本地检索更快，但新增一个需要编译的原生依赖。
   - 备选 B：现在就接独立向量服务（如 Qdrant）：部署多一个组件，而且 Pre-Filter 要把授权范围下推成服务端过滤条件。

2. **PostgreSQL 上的关键词索引**
   - 推荐：块的分词文本（CJK 二元 + 小写词）存进 `tsvector('simple', …)` 列并建 GIN 索引，SQLite 与 PostgreSQL 用同一套分词，排序用 `ts_rank`。不依赖中文分词扩展。
   - 备选：引入 `zhparser` 或 `pg_jieba` 中文分词扩展，召回更准，但需要数据库安装扩展。

3. **Embedding 用谁的 Key**
   - 推荐：库设置里选一个 Embedding 模型版本。建库索引时用库创建者的 Key（`owner_model_call`，用途 `knowledge.embedding`）；检索时用查询者自己的 Key 计算查询向量。查询者无权使用该模型时退化为关键词检索并标注原因（与记忆决定 5 一致，不代用别人的 Key）。
   - 备选：空间级统一的 Embedding 凭据，由空间管理员配置，所有人共用。

4. **检索进入上下文的方式**
   - 推荐：只通过工具（`search_knowledge` 等）检索，由模型决定何时查。不在每轮自动注入。
   - 备选：绑定了知识库的智能体每轮先自动检索一次，把结果放进提示（Octop `retrieve_context` 的旧路径），再保留工具供追问。

5. **无效引用的处理**（架构 2.10 写的是「无效引用判为失败」）
   - 推荐：Run 不失败。无效编号不进入引用列表、在界面上显示为无效引用，并产生 `knowledge.citation_invalid` 事件；评估集把它计为失败。同步修改架构文档的措辞。
   - 备选：严格执行架构原文，出现无效引用时 Run 以 `citation_invalid` 失败。

6. **分块策略**
   - 推荐：Markdown 先按标题切段并记录章节路径，段内再按字符定长重叠切分（默认 800 字符、重叠 120，库级可调）；PDF 按页切，页内同样定长切分并记录页码。
   - 备选：所有格式都只按定长重叠切分（Octop `chunk_text`），不记录章节。

7. **前端范围**
   - 推荐：本变更内完成知识库列表、详情（文档、状态、重试、删除、块预览）、上传、检索测试和智能体编辑器的知识库分区；其他 WeKnora 功能隐藏。本机内存不足以跑 `pnpm build`，前端以单元测试和类型检查片段验证，完整构建与浏览器验证记为待办。
   - 备选：本变更只做后端与工具，界面另起子提案。

## 验收

- 上传相同内容不产生新版本；新版本索引完成前检索仍返回旧版本，完成后只返回新版本。
- worker 在任一阶段被中断后重启，任务从中断的阶段继续，块不重复、不缺失。
- 无权的库、已撤权的共享库、已删除的文档，在关键词、向量和降级三条路径下都不会出现在结果里（测试逐路径断言）。
- 没有 Embedding 模型或查询者无权使用时，检索仍返回关键词结果并标注降级原因。
- 同一 Run 中同一块的编号保持不变，挂起恢复后不变；回答中的有效 `[ID:n]` 生成指向文档版本与块的引用，无效编号按决定 5 处理。
- 同一智能体绑定多个库时，`search_knowledge` 合并多个库的结果；可通过参数限定其中几个库，但不能超出绑定范围。
- 后端 pytest 覆盖上述各项和迁移升降级；评估集越权泄漏数为 0。
