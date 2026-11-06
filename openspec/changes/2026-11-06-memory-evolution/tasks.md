# 实施任务

状态：已确认（2026-11-06），实施中。

每个阶段完成后单独提交并推送。阶段内发现的追加工作写入本文件对应阶段，不另开提案。

## 0. 准备

- [x] 0.1 用户确认 `proposal.md` 中"待确认的决定"1–7。
- [x] 0.2 精读参考源码并在本节记录取舍（第 1 阶段相关部分已读，其余阶段开始前补读并在此追加）：
  - WeKnora：`extract.go`（`collectSessionSegments`、`relevantExisting`、`buildExtractionPrompt`、`applyDecisions`）、`service.go`（`Recall`、`findContainedDuplicate`、`enforceCapacity`）、`consolidate.go`、`vector.go`、`topic_resolve.go`、`search_conversations.go`；
  - octop-memory：`checks.py`、`rerank.py`、`budget.py`、`suppress.py`、`consolidate.py`、`gc.py`；
  - hermes-agent：`background_review.py`、`memory_tool_store.py`、`memory_provider.py`、`memory_manager.py`。
  - 第 1 阶段取舍：
    - 来源筛选照 WeKnora 只取用户消息，但 Nexus 按 `origin` 白名单判断，而不是只看角色，因为运行时会以 `user` 角色补发合成消息。
    - 相关条目照 WeKnora 只给相关的 15 条；WeKnora 用向量检索选取，Nexus 第 1 阶段没有向量，改为按分词重合度在应用内打分（每人有字数预算，全量读取开销小）。
    - 证据校验取 octop-memory `check_evidence` 的思路（引用必须出自原始事件），校验方式改为规范化子串匹配。
    - 主题即身份、包含即重复照 WeKnora `MemoryItemKey` 与 `findContainedDuplicate`；但 WeKnora 直接替换已发布条目，Nexus 只生成编辑草稿（决定 E2）。
    - 冲突提示用 octop-memory 检查 5 的否定词加重合度规则，只作提示，不进入 `conflict` 状态，因为 Nexus 每条都要人工审核。
    - "不该保存"清单照 hermes `_DO_NOT_CAPTURE_BLOCK`，压缩成中文要点。
- [x] 0.3 核对 Run 起始用户消息的 `runtime_metadata.origin` 实际取值，确定 A1 的白名单。
  - 结果：起始消息写入时 `runtime_metadata` 为空（`message_repository.initial`）；回答追问为 `user_input`，运行中追加指令为 `user_steer`；运行时补发的续写、截断提醒、项目上下文、恢复提示是 `role='user'`、`origin='runtime'`（`orchestrator.py`、`recovery.py`），必须排除。白名单定为 `('', 'user_input', 'user_steer')`。会话分叉复制消息时保留原 `origin`。
- [x] 0.4 核对 `2026-11-05-memory-switches` 前端第 2 节的进度。第 2 阶段的界面任务在它完成后开始。
  - 结果（2026-11-06）：该提案前端任务 2.1–2.6 均未完成。第 2 阶段先做后端，界面任务排在它之后。

## 1. 第 1 阶段：抓取质量（A1–A9）

- [x] 1.1 迁移：`memory_drafts` 新增 `topic`、`importance`、`confidence`、`valid_until`、`evidence`、`annotations`；`memory_entries` 新增 `topic`、`importance`；`memory_tombstones` 新增 `topic` 和索引。测试升级与降级。
- [x] 1.2 `nexus_memory.capture.select_sources`：消息来源白名单、助手只读上下文、没有用户消息时跳过（A1、A9）。
- [x] 1.3 `validate_actions` 新协议：允许 `update` 加 `target`、证据校验、价值门槛、有效期、默认值、单窗口 8 项上限（A4、A5、A8）。
- [x] 1.4 `text.topic_key`、`text.normalize_for_match`、`text.NEGATIONS`；`propose` 中加入主题匹配转更新、包含重复、冲突提示（A6、A5）。
- [x] 1.5 `_plan`：按关键词检索相关条目（不足时补齐）；读取被拒主题（A2、A7）。
- [x] 1.6 worker `build_request` 新结构，`INSTRUCTIONS` 重写，并用测试锁定关键句（A3）。
- [x] 1.7 `review`：发布时把 `topic`、`importance`、`valid_until` 复制到条目；拒绝时把 `topic` 写入墓碑。
- [x] 1.8 前台 `propose_memory_draft` 参数增加 `topic`、`importance`、`valid_until`。
- [x] 1.9 接口：`GET /memory` 的草稿与条目返回新字段；审核时可修改 `importance`。
  - 追加：编辑草稿记录 `target_entry_id`，审核时未指定条目则按草稿记录的条目发布（迁移 1.1 中新增该列）。
- [x] 1.10 pytest：来源筛选、证据、门槛、主题转更新、包含重复、冲突提示、被拒主题、迁移、抓取端到端（假抽取器）。
  - `tests/test_memory_evolution_stage1.py`（22 项），并更新 `test_memory_capture.py`、`test_memory_capture_credentials.py`、`test_memory_rules.py` 的内存仓储；全量 808 通过。PostgreSQL 随路线图 2.9 验收。
- [x] 1.11 文档：`packages/memory/docs/design.md`、`docs/architecture.md` 2.8 节。

## 2. 第 2 阶段：注入与展示（B1–B6、E1）

- [x] 2.1 迁移：`memory_entries` 新增 `last_used_at`、`use_count`，`kind` 允许 `profile`；`memory_space_settings` 新增 `extract_instructions`。
  - 追加：`session_memory_snapshots.resident_entries` 记录常驻块中的条目，供每个 Run 发 `memory.used`。
- [x] 2.2 `snapshot_text`：容量头、`profile` 常驻块（1000 字）、新的索引排序；更新 `version_key`（B1、B2、B3）。
- [x] 2.3 检索打分加时效和重要度因子（B3）。
- [x] 2.4 使用统计更新与 `evict_auto` 新的淘汰顺序（B4）。
- [x] 2.5 Run 事件 `memory.used`、`memory.draft_proposed`，以及事件可见性（B5、E1）。
- [x] 2.6 空间设置 `extract_instructions`：校验、威胁扫描、写入抽取提示（B6）。
- [x] 2.7 前端：事件映射，时间线"引用了 N 条记忆"，对话内草稿确认卡片（发布、拒绝、已处理），历史回放状态校正（E1、B5）。
  - `memory.used` 汇总进 WeKnora 原有的 `ChatMemoryStep` 行（显示条目标题）；该行的"删除"在 Nexus 页面改为归档条目。卡片 `MemoryDraftCard.vue` 经 `useNexusChatActions` 调用审核接口，409 显示"已在别处处理"；历史回放时读 `GET /memory` 的待审草稿判断状态。
- [ ] 2.8 前端：空间记忆设置页增加自定义规则；我的记忆页增加 `profile` 类型、重要度、使用次数显示。
  - 阻塞：依赖 `2026-11-05-memory-switches` 前端第 2 节（两个设置页尚未接入 Nexus 接口）。接口已就绪：`GET/PUT /native/memory-settings` 返回并接受 `extract_instructions`；`GET /memory` 返回 `topic`、`importance`，审核可传 `importance`。
- [x] 2.9 文案：所有语言包补齐（`agentStream.memoryDraft.*`，6 种语言）。设置页文案随 2.8。
- [x] 2.10 pytest 与前端单元测试；文档同步。
  - 后端：`tests/test_memory_evolution_stage2.py`（11 项），全量 819 通过。前端：`nexusAgentEvents.test.ts`、`nexusChatTranscript.test.ts` 新增用例，语言包键一致性通过。
  - `pnpm build` 在本机因内存不足（1.8 GB，vite 进程被 OOM 终止）未能完成；已用 `@vue/compiler-sfc` 编译改动的三个组件，并对改动的 TS 模块做 `tsc` 类型检查，均无错误。需在内存充足的环境补跑 `pnpm build` 与 `pnpm test:browser`。

## 3. 第 3 阶段：去重与维护（C1–C4）

- [ ] 3.1 迁移：`memory_drafts.kind` 允许 `merge`；新表 `memory_consolidation_state`。
- [ ] 3.2 `propose` 中加入近似重复提示（C1）。
- [ ] 3.3 `nexus_memory.consolidate`（候选、聚类、限额）与平台编排；`merge` 草稿的发布与冲突处理；`POST /native/memory/consolidate`；worker 空闲调度（C2）。
- [ ] 3.4 `retention.run_retention` 与 worker 调度（C3）。
- [ ] 3.5 排序中对久未使用条目降级（C4）。
- [ ] 3.6 前端：相似与合并草稿的展示，"整理记忆"按钮（替换现有占位）。
- [ ] 3.7 pytest 与前端单元测试；文档同步。

## 4. 第 4 阶段：历史会话检索（D1）

- [ ] 4.1 迁移：SQLite `message_fts`（带版本探测）与分批回填；写消息时同步写入 FTS。
- [ ] 4.2 平台查询：本人、本空间、排除当前会话、`histories_allowed` 过滤、回退路径。
- [ ] 4.3 工具 `search_conversations`、`read_conversation`，加入 `MEMORY_TOOL_NAMES`，并写审计。
- [ ] 4.4 pytest：授权（他人会话、无权 Run）、FTS 与回退路径一致、记忆关闭时拒绝、翻页上限。
- [ ] 4.5 文档同步；路线图 3.11 节补充说明。

## 5. 第 5 阶段：语义能力（D2、D3、D7）

- [ ] 5.1 迁移：`memory_embeddings`；`memory_space_settings.embedding_model_version_id`；`memory_capture_jobs.usage`；`memory_capture_settings.review_mode`。
- [ ] 5.2 向量生成任务（发布后异步执行、更换模型后补齐）与应用内余弦检索；RRF 融合与退化路径（D2）。
- [ ] 5.3 `nexus_memory.recall` 与 `ContextAssembler` 第一回合注入；智能体 `budgets.memory.recall` 的校验与冻结；断言系统前缀不变（D3）。
- [ ] 5.4 抓取用量记录与"我的记忆"页统计；`same_model` 复盘模式（D7）。
- [ ] 5.5 前端：空间设置中的 Embedding 模型、智能体编辑器中的主动召回开关、我的记忆中的复盘模式与用量。
- [ ] 5.6 pytest（向量用假 Embedding）与前端单元测试；比较两种复盘模式并写入 `design.md` 6.3 节；文档同步。

## 6. 第 6 阶段：依赖外部条件的能力（D4、D5、D6）

- [ ] 6.1 迁移：`memory_topic_stats`；`memory_space_settings.interest_threshold`；`memory_entries.kind` 允许 `interest`。
- [ ] 6.2 主题计数、晋升为 `interest` 草稿、拒绝后停止计数；我的记忆中的主题列表（替换占位）（D4）。
- [ ] 6.3 `MemoryProviderPort`、`BuiltinMemoryProvider`、外部提供方注册、超时与卡死保护、测试替身（D6）。
- [ ] 6.4 门禁：路线图第 6 步知识检索与引用登记可用后，实施 `memory_doc_affinity`、Run 完成时的记录、重排加权、管理入口（D5）。门禁不满足时保持未勾选。
- [ ] 6.5 pytest 与前端单元测试；文档同步。

## 7. 规格与归档

- [ ] 7.1 新增 `openspec/specs/memory-evolution/spec.md`，由本变更的 `specs/` 归档生成。
- [ ] 7.2 `docs/roadmap.md`：第 3 步记忆相关子项和第 9.3 节的状态。
- [ ] 7.3 全部阶段完成后归档本变更。D5 未满足门禁时，说明保留项后再归档，或者等门禁满足后归档。
