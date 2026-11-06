# 记忆包设计

## 职责与边界

- 规则：草稿只能由所有者审核发布；发布、编辑、恢复都追加版本，不改写历史；归档只隐藏条目，不删除来源。
- 提议：`propose()` 先经 `text.screen` 拒绝威胁、脱敏敏感值，再做指纹去重、墓碑检查、预算检查与编辑基线检查；拒绝与重复是结果而非异常，模型据此调整。
- 更新优先于新增（openspec 2026-11-06-memory-evolution 第 1 阶段）：新提议的主题与同类型已发布条目的主题规范化后相同（`text.topic_key`），或其内容包含该条目的内容，就转为对该条目的编辑草稿（记录 `target_entry_id` 与 `base_version`）；内容被已发布条目或待审草稿包含时视为重复。与某条目重合度 ≥ 0.3 且只有一方含否定词时，在草稿 `annotations.conflict` 上标注，只作审核提示。参考 WeKnora `MemoryItemKey`、`findContainedDuplicate` 与 octop-memory 晋升检查 5。
- 草稿元数据：主题、重要度（1–5）、置信度、有效期、原文证据，均为可选；发布时把主题、重要度（审核人可改）、有效期复制到条目。拒绝时墓碑记录主题，供抽取提示列出"用户拒绝过的主题"。
- 索引：`index()` 只列出启用、未归档、未过期的条目，输出上限 6000 字符，超限时按行截断并注明省略数量；排序为重要度降序、最近使用优先（未使用的最后）、最近发布优先，截断时先丢掉最不常用的条目。正文由模型按授权逐条读取，读取结果以 `<user_memory>` 包裹。
- 会话快照：`snapshot()` 生成冻结进系统提示的文本，依次为容量行（"已用 x/6000 字（y%）"，超过 80% 提示先合并）、`profile` 常驻块（画像正文整条放入，按索引顺序，总长不超过 1000 字，用 `<user_memory kind="profile">` 包裹并转义）、其余条目的索引。常驻条目在生成快照时计一次使用。参考 WeKnora 常驻块与 hermes-agent 容量头。
- 检索：`search()` 为关键词检索，只返回指针与片段；可用性（启停、有效期）由检索规则与仓储查询共同保证。通过阈值的命中按"0.6×相对关键词分 + 0.2×重要度 + 0.2×时效（发布或最近使用起 30 天半衰期）"重排（参考 octop-memory `rerank.py`）。
- 使用统计：`read_for_run()`、`search()` 命中和常驻注入都会调用端口 `touch()` 更新 `last_used_at`、`use_count`；自动抓取超出预算时的淘汰顺序为重要度低、久未使用、发布早。
- 停用与有效期：`set_availability()` 与归档分开，停用保留版本，只影响索引与检索。
- 开关：`switches.resolve()` 合并空间、成员、智能体三级开关，三者都允许时记忆才可用；任一级关闭时，平台不注入索引、移除 `MEMORY_TOOL_NAMES` 中的工具、拒绝记忆调用、不排队自动抓取。写入方式 `explicit` 只禁止自动抓取。关闭不删除任何数据。参考 WeKnora `enabledScope`。
- 边界：不导入 SQLAlchemy 或平台包；不解析主体。调用方传入已解析的 `owner_id`。

## 去重与维护（第 3 阶段）

- 近似重复：提议时与同类型条目的分词 Jaccard ≥ 0.6，在草稿 `annotations.similar` 上标注，照常创建草稿。
- 整理（`consolidate.py`）：同类型条目两两比较，Jaccard 超过阈值（后台 0.45，手动 0.3）的用并查集聚成簇（每簇最多 6 条，后台每次最多 3 簇，手动 8 簇），由模型判断是否同一件事并给出合并内容与保留条目；`service.propose_merge()` 生成合并草稿：对保留条目的编辑草稿（`origin='background'`），`annotations.merge.archive` 列出发布时归档的条目及其版本。发布时任一条目版本已变化即冲突；已在待审合并草稿中的条目不再参与整理。参考 octop-memory `consolidate.py`、WeKnora `consolidate.go`。
- 久未使用：没有有效期、且 45 天内未使用（或未发布更新）的条目，在索引排序中重要度减 1。

## 自动抓取规则（`capture.py`）

- 来源：`select_sources()` 只把用户本人写的消息作为来源（`role='user'` 且来源属于 `USER_ORIGINS`：起始消息、`user_input`、`user_steer`）；运行时补发的 `user` 消息（`origin='runtime'`）和工具消息排除，助手文字只作只读上下文。参考 WeKnora `collectSessionSegments`。
- 相关条目：`rank_related()` 按与用户消息的分词重合度挑选最多 15 条已发布条目，不足时按最近更新补齐；抽取输出用编号 `target` 引用其中一条来生成编辑草稿。
- 校验：`validate_actions()` 要求自动抓取的每一项带 1–3 条原文证据，引用规范化后必须出现在对应的来源消息中；重要度 ≤2 且置信度 low 的项只计数不建草稿；单次最多保留 8 项。参考 octop-memory `check_evidence`。
- 抽取提示在 worker（`apps/worker/src/nexus_worker/memory_capture.py`）中，包含"不该保存"清单（参考 hermes-agent `_DO_NOT_CAPTURE_BLOCK`），关键句由测试锁定。

## 依赖方向

```text
nexus_platform.memory (门面 + SqlMemoryRepository)  ──>  nexus_memory (规则 + 端口)  ──>  nexus_core
```

平台的 `runs` 只通过门面调用记忆，不直接导入仓储。门面把 `MemoryNotFound` / `MemoryConflict` 转为平台的 `NotFound` / `Conflict`，HTTP 响应不变。

## 事务

规则函数不开启或提交事务。门面在 `db.begin()` 内解析用户并调用规则，使身份检查与写入处于同一事务。行锁由端口的 `lock=True` 或 `draft_for_review` 请求。

## 测试

- `tests/test_memory_rules.py`、`tests/test_memory_stage1_rules.py`：内存仓储实现端口，覆盖审核、越权、重复审核、版本冲突、类型冲突、恢复、归档、提议筛查、去重、墓碑、预算、索引截断、读取包裹与检索，不依赖数据库。
- `tests/test_memory_text.py`：分词、威胁规则、脱敏、指纹。
- `tests/test_memory_evolution_stage2.py`：快照容量行与常驻块、索引排序、检索重排与使用统计、Run 事件（常驻、读取、检索、草稿）、空间抽取规则、淘汰顺序与迁移。
- `tests/test_memory_evolution_stage1.py`：来源筛选、证据、价值门槛、相关条目排序、有效期、主题转编辑、包含重复、冲突提示、墓碑主题、抽取请求结构、SQLite 端到端与迁移。
- `tests/test_memory_switches.py`：三级开关组合、接口授权与校验、Run 准备与工具授权、自动抓取、迁移升降级。
- `tests/test_memory_search_sqlite.py`：真实 SQLite 上的 FTS5 与回退路径一致性、版本替代、启停与有效期、时区、回滚、模型工具端到端。
- `tests/test_memory_stage1_migration.py`、`tests/test_memory_stage1_api.py`：迁移回填与升降级；启停与有效期的 HTTP 契约。
- `tests/test_native_parity.py` 仍通过 API 覆盖完整流程，包括审核、读取、恢复与归档。

## 会话内快照（阶段二）

快照由平台层保存与刷新（`nexus_platform.memory.snapshots`），本包只提供索引文本。第一个 Run 生成索引并存入会话快照表，之后的 Run 复用同一文本；刷新即删除该行。`version_key` 为所有者已发布条目的指纹，只用于提示快照是否过时，不会自动刷新。
