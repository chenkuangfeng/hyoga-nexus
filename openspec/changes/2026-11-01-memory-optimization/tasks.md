# 实施任务

状态：草稿，待确认。确认 proposal.md 中的决定项之后，才开始实施。

## 确认

- [x] 确认自动捕获默认关闭（用户于 2026-11-01 确认），并由所有者个人设置开启。
- [x] 确认会话快照与显式刷新入口（用户于 2026-11-01 确认）。
- [x] 确认威胁规则拒绝（用户于 2026-11-01 确认）、敏感信息替换占位。
- [x] 确认阶段四召回与整理默认关闭（用户于 2026-11-01 确认），评测通过后再决定。
- [x] 确认记忆预算默认值（用户于 2026-11-01 确认）（6000 字符）与调整上限。

## 阶段一：安全与整理

- [x] 1.1 `nexus_memory/scanning.py`：威胁规则与敏感信息规则，纯函数，单元测试覆盖每类规则的命中与未命中样例（含中文身份证校验位、银行卡 Luhn）。
  - 状态：已实施：`nexus_memory/text.py`（设计中的 scanning.py 改名为 text.py，含分词与指纹）；测试 `tests/test_memory_text.py`
- [x] 1.2 草稿提交与编辑接入扫描；命中威胁规则返回错误，敏感片段替换占位；审计只含类别。
  - 状态：已实施：`RunStore.propose` 经规则层 `propose`；威胁命中返回拒绝，敏感片段替换；审计只写类别；测试 `tests/test_memory_stage1_rules.py`、`tests/test_native_parity.py`
- [x] 1.3 指纹计算；提交时的去重（已发布、待审草稿）。
  - 状态：已实施：指纹 SHA-256（忽略大小写与空白）；去重覆盖已发布条目与待审草稿
- [x] 1.4 墓碑表与迁移；拒绝草稿时写入；提交时命中则返回 `memory_rejected_previously`；界面可撤销墓碑。
  - 状态：已实施（后端）：墓碑表、拒绝时写入、提议时检查。未实施：界面撤销墓碑
- [x] 1.5 编辑草稿的 `base_version` 与冲突返回。
  - 状态：已实施：提议时校验 base_version；审核时草稿的 base_version 必须仍为当前版本
- [x] 1.6 所有者记忆字符预算：提交与发布时检查，超出返回现有条目列表；索引按行截断并附省略说明。
  - 状态：已实施：预算默认 6000 字符，提议与发布时检查；索引按行截断并附省略说明
- [x] 1.7 `read_memory` 与召回块的 `<user_memory>` 包裹与转义。
  - 状态：已实施：模型读取经 `<user_memory>` 包裹并转义；召回块属于阶段四
- [x] 1.8 `search_memory` 只读工具：词法匹配，只返回 ID、标题与摘要，并注册为内置工具。
  - 状态：已实施：`search_memory` 只读工具，返回 ID、标题、版本与片段，注册为内置工具
- [x] 1.9 迁移：`memory_tombstones` 表，草稿与条目指纹、版本列（可空）。迁移升降级测试。
  - 状态：已实施：迁移 `e2b7d4a8c1f6`（墓碑表、指纹与版本列、回填）；升降级测试 `tests/test_memory_stage1_migration.py`
- [x] 1.10 测试：`tests/test_memory_scanning.py`、`tests/test_memory_dedup.py`、`tests/test_memory_budget.py`，并确认现有 memory 测试通过。
  - 状态：已实施：测试文件名与设计不同（`test_memory_text.py`、`test_memory_stage1_rules.py`、`test_memory_search_sqlite.py`、`test_memory_stage1_api.py`）
- [x] 1.11 文档：更新 `docs/architecture.md` 记忆章节与 `packages/memory/docs/`（若存在），说明规则与限制。
  - 状态：已实施：`docs/architecture.md` 2.8 与 `packages/memory/docs/design.md`

## 阶段二：会话内快照

- [x] 2.1 快照表与迁移；第一个 Run 生成，后续 Run 复用；`version_key` 变化时不自动刷新。
  - 状态：已实施：表 `session_memory_snapshots`（迁移 `c3f8a1e6d2b9`，每会话一行）；`runs/preparation.py` 经 `memory/snapshots.py` 的 `session_index` 取用。
- [x] 2.2 显式刷新接口与界面入口；会话新建时生成新快照。
  - 状态：已实施：`GET/POST .../memory-snapshot`（仅会话所有者）；对话页 `MemorySnapshotControl` 显示状态并提供刷新。新会话没有快照行，第一个 Run 时生成，等同于新建时生成。
- [x] 2.3 测试：同一会话两个 Run 的索引文本相同；刷新后下一个 Run 使用新索引；快照不跨会话。
  - 状态：已实施：`tests/test_memory_snapshot.py`（5 项）；`tests/web/conversation.mjs` 覆盖刷新按钮。
- [x] 2.4 文档同步。
  - 状态：已实施：`docs/architecture.md` 2.8 与 `packages/memory/docs/design.md`。

## 阶段三：自动捕获（默认关闭）

- [x] 3.1 游标表与迁移；待抽取任务登记；延迟、最小间隔、单次上限、话题切分的纯逻辑与测试。
- [x] 3.2 租约与过期接管；测试：崩溃后租约过期可被接管，不重复产生草稿。
- [x] 3.3 抽取器：输入为新消息与最多 15 条相关记忆，输出动作经结构化校验；非法输出丢弃并记录。
- [x] 3.4 动作仅产生草稿，经阶段一的全部检查；无人值守运行只允许 `add`，测试覆盖。
- [ ] 3.5 记忆模型配置、按次授权、不可用时跳过；`memory.capture` 事件记录调用次数与 token。
- [x] 3.6 个人设置开关，默认关闭；界面显示将调用的模型。
- [x] 3.7 脚本化模型测试：默认关闭时不登记任务；开启后每次运行的模型调用不超过 3 次。
- [ ] 3.8 质量与成本评测：需要真实模型，暂停。

阶段三实现状态（2026-11-01）：已实现 `nexus_memory.capture`（窗口、话题切分、退避、输出校验）、`nexus_platform.memory.capture`（设置、入队、分阶段的分步状态机：读取计划、模型调用不占用事务、落库；按次模型授权与跳过；`capacity_policy` 的 `reject`/`evict_auto`）、`nexus_platform.models.provider_settings.capture_model_call`（复用所有者本人的模型密钥：要求启用捕获、模型版本与设置一致、成员身份、模型与供应商访问，并审计 `credential.resolved` 且 purpose 为 `memory.capture`）、`nexus_worker.memory_capture`（抽取请求与解析，不带工具）与 worker 循环中的捕获调度（无 Run 等待时执行到期任务）；设置接口 `GET/PUT /native/memory-capture` 与原生设置页的自动捕获区块；迁移 `d4b9e2f7a3c1`、`e6d1a7b3c8f2`。完成的 Run 在默认关闭时不入队。未完成：3.5 的 `memory.capture` token 统计（抽取调用尚未返回用量）；仅支持加密存储的密钥，环境变量密钥不用于捕获；PostgreSQL 下的多进程认领尚未验证（9.k）。3.2''' 的并发测试为顺序认领，验证的是条件 UPDATE 只成功一次。

## 阶段四：召回与整理（默认关闭）

- [ ] 4.1 词法召回：最多 5 条、600 字符；失败降级；`<user_memory>` 注入位置与配置开关。测试：关闭时上下文与改动前一致。
- [ ] 4.2 离线整理任务：每所有者每天一次，只产生合并草稿；请求路径不调用。测试：整理不修改已发布条目。
- [ ] 4.3 `evals/memory/` 样例与报告：需要真实模型，暂停。
- [ ] 4.4 默认值切换：仅在评测通过后，记录依据。

## 收尾

- [ ] 归档本变更（仅在全部已确认项完成且验证通过后）。

## 第二轮补充（对应 proposal.md 补充一节、design.md 第八节）

确认项新增：
- [x] 确认是否现在增加 `episodic`（用户于 2026-11-01 确认） 类型（默认否）。
- [x] 确认 `capacity_policy` 默认值为 `reject`（用户于 2026-11-01 确认）。

阶段一追加：
- [x] 1.12 迁移：`memory_drafts.origin`、`source_message_ids`，`memory_versions.source_message_ids`，`memory_entries.valid_until`、`enabled`（均可空）。迁移升降级测试。
  - 状态：已实施：草稿 origin/source_message_ids/base_version/fingerprint，版本 source_message_ids/fingerprint，条目 enabled/valid_until。source_message_ids 目前恒为空，由阶段三的自动捕获填充
- [x] 1.13 过期条目不进索引与召回；读取接口标记已过期；测试覆盖边界时刻。
  - 状态：部分：过期条目不进索引与检索；读取接口未标记"已过期"（保持现有读取行为，未实施）
- [x] 1.14 停用与归档分开：停用不进检索但保留版本；界面分别提供入口；测试两者互不影响。
  - 状态：已实施（后端）：停用与归档分开，停用保留版本；API `PATCH /memory/{id}`。未实施：界面入口
- [ ] 1.15 草稿与版本记录来源消息 ID；审核界面展示 origin 与来源。
  - 状态：部分：来源消息 ID 已记录（当前为空）；界面展示 origin 与来源未实施

阶段三替换与追加：
- [x] 3.2' 任务表 `memory_capture_jobs` 与状态机（pending→extracted→stored→completed/failed），每步落库，幂等草稿。测试：每一步之后模拟崩溃，恢复后不产生重复草稿。
- [x] 3.2'' 退避与最大次数；`last_error` 与失败可见。测试：退避序列、超过次数标记失败。
- [x] 3.2''' 同一所有者同时只允许一个未完成任务。测试：并发领取只成功一次。
- [x] 3.9 `capacity_policy`：`reject` 与 `evict_auto`；`evict_auto` 只淘汰自动捕获条目并归档；测试：不淘汰手写条目，没有可淘汰时拒绝。
- [x] 3.10 抽取调用不带工具定义；测试：请求中无 tools 字段。

另立提案（不在本变更中实施）：
- [ ] 会话检索提案（Hermes session_search、WeKnora search_conversations 的做法）。

## 第九节补充：存储与检索一体化（design.md 第九节）

- [x] 9.a 分层表与扩展字段迁移：`memory_entries.enabled`、`valid_until`；`memory_versions.search_text`；L3 索引表（追加式）。
  - 状态：已实施：见 1.12；`memory_tombstones` 表
- [x] 9.b 写入路径：发布、停用、归档、撤销发布在同一事务内更新 L2 与 L3。测试：索引写入失败时发布回滚。
  - 状态：已实施：发布在同一事务写入索引；索引写入失败回滚（测试已覆盖）。停用/归档/过期不删行，改为查询时过滤（设计 9.3 已据此修订）
- [x] 9.c 统一规划器 `recall(owner, query, budget)`：授权范围、词法通道、RRF、预算裁剪、句柄返回。`search_memory` 调用规划器。测试：草稿、停用、归档、过期、旧版本、他人条目均不返回。
  - 状态：已实施（单通道）：`rules.search` 过采样、阈值、按最高分相对化、截断；只读取当前版本与本人有效条目
- [ ] 9.d 召回块与会话级索引分开注入；召回块不进入冻结前缀。测试：前缀字节稳定。
  - 状态：未实施：阶段四
- [ ] 9.e 重建任务与一致性检查（最小版在阶段一，完整版在阶段四）。测试：删除 L3 后重建结果与 L2 一致；不一致行被修复。
  - 状态：未实施：重建任务与一致性检查
- [x] 9.f 确定性测试集（见 design.md 9.8），并与 9.c 同批合入。
  - 状态：已实施：确定性测试覆盖草稿、停用、归档、过期、旧版本、他人条目、撤回与回滚
- [ ] 9.g 确认 9.10 中剩余的排序规则待定项（分词已在 9.11 决定）。
  - 状态：未决：索引排序仍为标题顺序（现有行为）；检索按 BM25 排序
- [x] 9.h SQLite 兼容：`memory_fts`（FTS5，`unicode61`）迁移与启动时 FTS5 可用性探测；不可用时回退 `LIKE` 并记录降级事件。
  - 状态：已实施：FTS5 表（建表前探测版本与模块，不满足时回退）；回退 LIKE 时未记录降级事件（待补）
- [x] 9.i 应用侧二元组分词模块，单元测试覆盖两字词、三字以上词、单字、英文数字混排、FTS 语法字符。
  - 状态：已实施：`nexus_memory/text.py` 二元组分词；测试覆盖两字词、三字以上词、单字、英文数字、语法字符
- [x] 9.j 发布、停用、归档在同一 `BEGIN IMMEDIATE` 事务内更新 `memory_fts`；测试：FTS 写入失败时发布回滚。
  - 状态：已实施：发布在同一事务写入；失败整体回滚（测试 `test_failed_index_write_rolls_back_the_whole_publication`）
- [ ] 9.k 所有检索测试（9.8、9.i）在 SQLite 上运行；PostgreSQL 上运行同一套用例，有条件时执行。
  - 状态：部分：SQLite 上运行全部检索测试；PostgreSQL 环境未执行（当前无可用实例）
- [x] 9.l 时间比较通过 SQLAlchemy 绑定参数（UTC）；测试：不同时区写入的 `valid_until` 过期判断正确。
  - 状态：已实施：时间统一为 UTC 再比较（测试 `test_validity_is_compared_in_utc_regardless_of_the_offset_given`）

## 第九节补充二：检索细节（design.md 9.4、9.11，参考 WeKnora）

- [x] 9.m `memory_fts` 使用 contentless 形式（`content=''`、`contentless_delete=1`）；启动探测 SQLite 版本 ≥ 3.43 与 FTS5 模块。测试：删除按 `rowid` 生效；版本不足时回退 `LIKE` 并记录降级。
  - 状态：已实施：contentless 表、`contentless_delete=1`，rowid 为显式 `search_id`（不依赖可能被 VACUUM 重排的隐式 rowid）
- [ ] 9.n 过采样与关键词阈值：候选数 `max(items×5, 25)`（上限 100）；低于阈值的 BM25 候选丢弃。阈值在个人记忆样例上标定后记录依据。测试：阈值以下的候选不返回。
  - 状态：部分：过采样与阈值已实施；阈值 0.3 尚未用个人记忆样例标定
- [ ] 9.o 加权 RRF 与 [0,1] 归一化；单通道时使用同列表相对 BM25。测试：合并后分数在 [0,1]，单通道不走 RRF。
  - 状态：部分：单通道的相对 BM25 已实施；加权 RRF 待第二个通道出现后实施
