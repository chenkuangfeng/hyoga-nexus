# 长期记忆演进：抓取质量、注入与展示、去重维护、历史会话检索与语义能力

## 状态

草案，待确认（2026-11-06）。

- 范围已确认：参考项目对照清单的第 1–4 组全部纳入，"未来考虑"的各项也纳入；E1（对话内一键确认）纳入；E2 否决，即任何路径都不自动发布记忆。
- 本提案在编码前需要确认第"待确认的决定"一节。
- 实施分 6 个阶段。每个阶段单独验证、提交，并在 `tasks.md` 中勾选；不再另开新的提案。

前置变更：

- `openspec/changes/2026-11-01-memory-optimization/`：草稿审核、版本、墓碑、预算、索引、检索、快照、自动抓取。
- `openspec/changes/2026-11-05-memory-switches/`：三级开关。其前端任务第 2 节尚未完成，本提案第 2 阶段的界面工作在它之后进行。

## 原因

对照 octop-memory、WeKnora、hermes-agent 三个项目的记忆实现后，发现 Nexus 现有记忆有以下问题：

- **抽取输入不对**：抓取把所有角色的消息拼进提示（`apps/worker/src/nexus_worker/memory_capture.py:46`），助手的说法和工具结果会被当成用户的记忆。
- **相关条目与对话无关**：交给抽取模型的"相关条目"取自 `published_entries(...)[:RELATED_LIMIT]`，仓储按标题排序（`packages/platform/src/nexus_platform/memory/repository.py:51`），与当前对话无关。
- **提示词过于简单**：抽取提示只有 5 句（`memory_capture.py:35`）。没有"不该保存"的规则，环境性失败、"某工具不可用"这类结论会被提成 SOP。
- **草稿缺少依据**：草稿没有原文证据，也没有重要度和置信度，审核人只能逐条判断。
- **只能新增、去重太弱**：
  - 抓取只能新增，不能更新（`UNATTENDED_OPS = ('add',)`）；
  - 去重只认完全相同的指纹，换个说法就会出现重复草稿；
  - 被拒的内容换个说法还会再被提出。
- **注入只有指针**：快照只列条目指针（`snapshots.py`），连用户画像也要模型调用 `read_memory` 才能看到；索引不显示容量占用；超长时按标题截断。
- **审核不便**：用户看不到本轮用了哪些记忆；模型在对话中提出的草稿，只能去记忆页审核。
- **没有维护**：没有语义合并、数据保留规则，长期不提的任务也不会降级。
- **找不到旧对话**：没有检索历史会话的工具，精选记忆以外的细节无法找回。
- **只有关键词检索**：没有向量召回、每轮主动召回、兴趣主题、文档亲和度和外部记忆提供方接口。

参考源码（本地副本，均位于 `/project/opensource/agents/`）：

| 项目 | 版本 | 主要文件 |
| --- | --- | --- |
| octop-memory | 本地副本 | `pipeline/promotion/checks.py`、`pipeline/recall/`（`rerank.py`、`budget.py`、`suppress.py`）、`pipeline/lifecycle/consolidate.py`、`pipeline/lifecycle/gc.py`、`domain/retention.py` |
| WeKnora | `e1f9a6166` | `internal/application/service/memory/`（`extract.go`、`service.go`、`consolidate.go`、`search.go`、`vector.go`、`topic_resolve.go`）、`internal/types/memory.go`、`chat_pipeline/memory_recall.go`、`memory_affinity.go`、`agent/tools/search_conversations.go` |
| hermes-agent | `eb1b4c5b61` | `agent/background_review.py`（`_DO_NOT_CAPTURE_BLOCK`、`_MEMORY_ROUTING_BLOCK`）、`tools/memory_tool_store.py`、`agent/memory_provider.py`、`agent/memory_manager.py`、`agent/memory_context.py`、会话检索 `session_search` |

## 不变的原则

1. **不自动发布（E2）**：记忆只能由所有者审核后发布。抽取、合并、兴趣晋升、外部提供方的产出一律成为草稿，草稿在发布前不进入任何提示。
2. **只追加**：发布、编辑、恢复、合并都追加版本或归档，不改写历史。
3. **快照稳定**：会话快照冻结后不变。每轮动态内容只放在本轮用户消息一侧，不改系统前缀。
4. **受开关控制**：所有新增读取和写入都受三级开关（`memory_state`）约束；记忆关闭时，新工具、新注入、新后台任务全部停止。
5. **范围**：只适用于 Native Runtime；外部 Runtime 不在范围内。

## 范围

### 第 1 阶段：抓取质量

| 编号 | 内容 | 来源 |
| --- | --- | --- |
| A1 | 抽取只把用户消息作为来源（`role='user'`，且来源为用户输入或用户追加指令）；助手消息只作只读上下文且截断，工具消息不进入。系统合成的消息按来源标记排除 | W `collectSessionSegments`；O `retention.py` |
| A2 | 相关条目按窗口内容做关键词检索，取最多 15 条，不足时用最近更新的条目补齐 | W `relevantExisting`；O 召回路由 |
| A3 | 抽取提示补"不该保存"规则，并区分画像、记忆、SOP 的存放规则 | H `_DO_NOT_CAPTURE_BLOCK`、`_MEMORY_ROUTING_BLOCK` |
| A4 | 抽取项必须带原文引用（来源消息序号 + 原文片段），校验片段确实出现在该用户消息中，否则丢弃。前台模型提议时可选 | O `check_evidence` |
| A5 | 抽取项带重要度（1–5）和置信度（low / medium / high）；重要度 ≤2 且置信度 low 的不建草稿，只计数。疑似与已发布条目冲突的，在草稿上标注提示 | O 检查 1、5 |
| A6 | 抽取项带主题；规范化主题匹配到已发布条目时，转为更新草稿（带 `base_version`）。新增"规范化后互相包含即重复"检查 | W `MemoryItemKey`、`findContainedDuplicate` |
| A7 | 墓碑增加主题字段；最近被拒的主题（最多 20 个）列给抽取模型，除非对话中有新内容，否则不要再提 | W `buildExtractionPrompt` forgotten |
| A8 | 抽取项可以给出有效期（ISO 日期），用于任务类内容；草稿带 `valid_until`，发布时写入条目 | W `ExpiresAt` |
| A9 | 并入 A1：按消息来源白名单抽取。系统合成的报错、合成回复不参与 | O ADR-041 |

### 第 2 阶段：注入与展示

| 编号 | 内容 | 来源 |
| --- | --- | --- |
| B1 | 新增条目类型 `profile`（用户画像与偏好）。快照包含常驻块：`profile` 正文按重要度排序，上限 1000 字，用 `<user_memory>` 包裹；其余仍是索引 | W 常驻块；H USER.md |
| B2 | 索引头显示"已用 x / 6000 字（y%）"；超过 80% 时提示先合并再提议 | H 容量头 |
| B3 | 索引超长时按"重要度 → 最近使用 → 最近更新"排序后截断；检索打分加时效（30 天半衰期）和重要度因子 | O `rerank.py` |
| B4 | 条目记录 `last_used_at` 和 `use_count`（`read_memory`、检索命中、常驻注入时异步更新）；`evict_auto` 淘汰顺序改为"重要度低 → 久未使用"，手写条目仍不淘汰 | W `touchAsync`、`ArchiveLowestRanked` |
| B5 | Run 事件 `memory.used`：本轮注入的常驻条目、`read_memory` 和检索命中的条目。对话时间线显示"本轮引用的记忆" | W `memory_recalled`；H recall 指示 |
| B6 | 空间级自定义抽取规则，最多 1000 字，owner 或 admin 设置，作为抽取提示中的 `<rules>` 资料段 | W `ExtractInstructions` |
| E1 | 前台 Run 中模型提出的草稿，发出 `memory.draft_proposed` 事件；对话中显示确认卡片（标题、内容、来源、冲突或相似提示），所有者可一键发布或拒绝，调用现有审核接口 | 用户决定 E1 |

### 第 3 阶段：去重与维护

| 编号 | 内容 | 来源 |
| --- | --- | --- |
| C1 | 提议时做近似重复检查（二元组 Jaccard ≥ 0.6）。命中时仍创建草稿，但标注相似条目，并建议改为更新 | O `suppress.jaccard` |
| C2 | 后台语义合并：每人每天最多一次，也可以手动触发（每分钟最多一次）。用 Jaccard ≥ 0.45 预筛候选对，每次最多 3 组（手动 8 组），交由抓取模型确认；产出"合并草稿"（更新保留条目，发布时归档其余条目），不自动生效 | O `consolidate.py`；W `consolidate.go` |
| C3 | 数据保留：被拒草稿 30 天后删除（墓碑保留），已完成或失败的抓取任务 14 天后删除，审计、版本、墓碑永久保留；每轮最多处理 500 行 | O `gc.py` |
| C4 | 有有效期的任务过期后自动失效（沿用 `valid_until`）；未设有效期、45 天未使用的条目在排序中降级（不归档） | W `staleTaskAge` |

### 第 4 阶段：历史会话检索

| 编号 | 内容 | 来源 |
| --- | --- | --- |
| D1 | 只读工具 `search_conversations`（关键词检索调用者本人在本空间的历史会话消息，返回会话、序号、片段）和 `read_conversation`（按会话与序号前后翻页）。遵守会话历史可见性与记忆开关；不经过模型摘要；排除当前会话 | H `session_search`；W `search_conversations.go` |

### 第 5 阶段：语义能力

| 编号 | 内容 | 来源 |
| --- | --- | --- |
| D2 | 向量召回：空间选择记忆 Embedding 模型后，为已发布条目的当前版本生成向量；检索时与关键词结果按名次融合（RRF）；未配置或失败时退回关键词 | W `vector.go` `fuseRankings` |
| D3 | 每轮主动召回：不调用模型，按本轮用户问题对 fact、memory 类条目做关键词（加可选向量）检索，最多 5 条、600 字，排除常驻块已有条目；作为本轮用户消息一侧的 `<user_memory>` 资料段注入，不改系统前缀，不持久化到消息 | W `Recall`；O 召回预算 |
| D7 | 抓取成本优化：记录每次抽取的 token 用量；提供可选的"同模型复盘"模式（抽取使用 Run 的模型与稳定前缀以命中缓存），默认关闭；以统计结果决定是否推荐开启 | H `background_review.py` |

### 第 6 阶段：依赖外部条件的能力

| 编号 | 内容 | 来源 | 前置条件 |
| --- | --- | --- | --- |
| D4 | 兴趣主题：统计抽取得到的主题在不同会话中出现的次数（`memory_topic_stats`），达到阈值（默认 3 个会话）时生成 `interest` 类草稿；用户删除的主题不再统计 | W `MemoryTopicStat`、`observeTopics` | 第 1 阶段 A6 |
| D5 | 文档亲和度：记录回答引用过的知识库文档，在知识检索重排时对常用文档小幅加权（≤1.15 倍，至少 2 次引用） | W `memory_affinity.go` | 路线图第 6 步知识库检索完成 |
| D6 | 外部记忆提供方端口：定义 `MemoryProviderPort`（快照块、预取、回合同步、会话结束、子任务结果钩子）；内置实现包装现有记忆；同时最多一个外部提供方；调用有超时（预取 8 秒）和卡死保护，失败退化为不使用 | H `memory_provider.py`、`memory_manager.py` | 无，接口先行；具体外部服务按需另行接入 |

### 范围外

- octop-memory 的实体页面、Episode、周期摘要、记忆树、便携迁移包。
- 任何自动发布路径（E2）。
- 外部 Runtime（Codex、Claude Code、DeepSeek Harness）的记忆。
- 具体的外部记忆服务（mem0、Honcho 等）的适配器。
- 向量数据库产品选型。D2 在应用内计算相似度（见设计第 6 节），与路线图第 6 步的选型无关。

## 待确认的决定（括号内为推荐）

1. **草稿新字段的存放**（推荐 A）
   - A：`memory_drafts` 新增列 `topic`、`importance`、`confidence`、`valid_until`、`evidence`（JSON），以及 `annotations`（JSON，冲突、相似、合并目标等提示）；`memory_entries` 新增 `importance`、`topic`、`last_used_at`、`use_count`。
   - B：全部放进一个 JSON 列。迁移更简单，但无法索引和排序。
2. **`profile` 类型的预算**（推荐 A）
   - A：常驻块上限 1000 字，计入每人 6000 字的总预算。
   - B：单独预算，不计入总预算。
3. **E1 确认卡片的范围**（推荐 A）
   - A：前台 Run 中模型通过 `propose_memory_draft` 产生的草稿都发卡片，不判断用户是否"明确要求"。模型无法伪造用户意图，判断也不可靠。
   - B：只有模型标注 `explicit=true` 的草稿才发卡片。
4. **D1 历史会话检索的开关归属**（推荐 A）
   - A：受记忆三级开关控制，记忆关闭时工具不可用。
   - B：作为独立工具，按智能体绑定授权，不受记忆开关影响。
5. **D2 向量的存放与计算**（推荐 A）
   - A：新表 `memory_embeddings`（条目、版本、模型版本、向量 JSON），在应用内对本人的已发布条目计算余弦相似度（每人上限约数百条，开销可控）；PostgreSQL 与 SQLite 行为一致。
   - B：等路线图第 6 步确定向量服务后再做。
6. **D3 主动召回的注入位置**（推荐 A）
   - A：作为本轮请求中用户消息之前的一段资料，不写入消息表，只在 `memory.used` 事件中记录条目 ID。
   - B：作为工具结果形式的虚拟消息，或写入消息表。
7. **C2 合并草稿使用的模型**（推荐 A）
   - A：使用成员自动抓取的模型。未开启自动抓取的成员不做后台合并，只能手动触发，手动触发时要求先选择模型。
   - B：空间级统一模型。

## 验收（汇总，分阶段细节见 `tasks.md`）

- **第 1 阶段**：
  - 助手和工具消息里的说法不会成为草稿；
  - 草稿带可校验的原文引用、重要度、置信度、主题；
  - 匹配到已有主题时生成更新草稿；
  - 被拒主题在抽取提示中出现；
  - 低价值项不建草稿，但有计数审计。
- **第 2 阶段**：
  - 快照包含 `profile` 常驻块和容量头，超长时按新规则截断；
  - 对话中能看到本轮引用的记忆，能在对话内一键发布或拒绝前台草稿；
  - 空间自定义规则进入抽取提示。
- **第 3 阶段**：
  - 近似重复草稿带相似提示；
  - 后台合并只产生草稿，发布后保留条目追加版本、其余条目归档；
  - 保留规则按期清理且不删审计、版本、墓碑。
- **第 4 阶段**：
  - 历史会话检索只返回调用者有权查看的会话；
  - 记忆关闭时工具不可见、调用被拒。
- **第 5 阶段**：
  - 配置 Embedding 后，换说法的问题能召回条目；
  - 未配置或失败时行为与关键词检索一致；
  - 主动召回不改变系统前缀（以提示缓存键或前缀哈希断言）；
  - 抽取用量有统计。
- **第 6 阶段**：
  - 兴趣只以草稿形式出现；
  - 文档亲和度只在知识检索可用后启用，加权有上限；
  - 外部提供方超时或报错不影响 Run 完成。
- **全部阶段**：
  - 三级开关关闭时，所有新增读写停止；
  - pytest 覆盖规则与 SQLite、PostgreSQL 行为（PostgreSQL 随目标环境验收）；
  - 前端单元测试覆盖新增映射与卡片；
  - 文档与规格同步更新。
