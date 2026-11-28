# 每次对话的上下文装配设计

状态：已实施装配底座与 v1 兼容布局；真实模型质量评测和 v2 默认切换未完成，验证记录见 tasks.md 与 evals/context-performance/assembly-report.md。范围为 Native 的 messages/tools 装配，沿用本变更 P4、P8、P10、P11，不修改压缩算法、跨 Run 工具回放规则和累计 token 预算策略。其他 Runtime 继续由适配器驱动。

## 1. 已核对的对象与取舍

| 来源 | 已核对源码与行为 | 本方案采用与边界 |
| --- | --- | --- |
| Nexus | `ExecutionPreparer.prepare` 拼接历史、记忆、技能、知识目录、检查点；`execute_native` 注册 MCP；`AuthorizedToolGateway.definitions` 筛选排序；`model.started` 实时复核模型、成员和历史来源权限 | 保留平台授权、每 Run 执行对象、工具调用再授权；拆开装配职责，扩展来源依赖 |
| DeepSeek Harness | `packages/core/system-prompt/src/index.ts` 的 `PromptSection/PromptContext/PromptAssembly`，有序贡献、scope、provider 所有的工具声明；`agent-loop/src/agent.ts` 每步解析工具并装配；`core/tools/src/index.ts` 的 `ResolvedToolSet`；`skill/tool-skill` 以带来源的消息发布目录及更新 | 采用内容块、有序贡献、结构化来源；不照搬每 step 全量动态工具发现，也不把 scope 当租户授权 |
| Hermes | `agent/system_prompt.py` 的 stable/context/volatile 分层、会话 prompt 和插件 section 快照；`model_tools.py` 按 scope、配置和 registry generation 缓存工具定义并返回副本 | 采用确定性分层、内容缓存与副本隔离；不缓存 Agent 对象，不缓存权限判断 |
| WeKnora | `internal/agent/engine.go` 的每次执行引擎及 `internal/modelcontext/registry.go` 的请求级资源句柄边界 | 保留请求级句柄所有权，不把临时句柄当跨 Run 稳定身份 |
| GenericAgent | `ga.py` 的 `GenericAgentHandler` 与 `_get_anchor_prompt`；Nexus 已迁移的 `WorkingMemory` 和 `HookRegistry` | 保留工作检查点、回合提醒和 hook 语义；不把 handler 或可变全局状态放入共享缓存 |

参考源码位于 `/project/opensource/agents/`。以上为源码分析，不是实测性能结论。实现时再次核对锁定的源码版本与测试。

## 2. 关键决定

1. 内容按版本复用，权限每次模型请求和资源调用重新判断。权限失败不回退到缓存授权。
2. 区分 session、Run、step、attempt：用户一次提问产生 Run；一个 Run 有多个模型 step；模型重试是新的 attempt。每个实际 attempt 都走授权关卡。
3. 每 Run 冻结工具 schema、Agent 指令和选定的目录版本。普通发布/新增不在 Run 内热加入；删除、禁用、撤权、到期是安全失效，优先于缓存稳定。
4. 初版安全失效时终止当前 Run，返回既有 `run_authorization_denied`；MCP 执行继续沿用自身错误码。不尝试从自由文本删除敏感事实后继续，也不重放已经执行的工具。新 Run 按当前可见资源重建。
5. 一旦请求已发出，无法撤回供应商已接收的内容。撤权保证以请求授权检查的数据库快照为线性化点，提交后生效到下一次检查；工具仍在执行点复核。
6. 先以统一对象复现当前输入，再独立评测和切换消息布局，避免把对象重构与模型行为变化混为一项验证。

## 3. 对象与包边界

新增 `packages/core/src/nexus_core/runtime/context.py`，只定义不可变 DTO 与必要协议。名称为实施目标，不代表已有接口：

```python
@dataclass(frozen=True)
class ContextDependency:
    kind: str                 # resource/memory/skill/provider/plugin/mcp/knowledge/history
    resource_id: str
    version: str
    source_run_id: str | None = None
    permission: Literal['read', 'use'] = 'use'

@dataclass(frozen=True)
class ContextBlock:
    key: str                  # 唯一贡献名，插件带 provider 命名空间
    source: str
    role: Literal['system', 'user']
    placement: Literal['system_static', 'system_catalog', 'history_prefix', 'turn_tail']
    order: int
    text: str
    lifetime: Literal['session', 'run', 'step']
    trust: Literal['instructions', 'reference']
    dependencies: tuple[ContextDependency, ...]
    digest: str

@dataclass(frozen=True)
class AssemblyManifest:
    schema_version: int
    assembly_id: str
    layout_version: str
    source_watermark: int
    block_digests: tuple[tuple[str, str], ...]
    dependencies: tuple[ContextDependency, ...]
    tools_digest: str
```

补充 DTO `ContextBuildInput`（tenant/principal/session/run/agent_version/step、原始用户消息 ID、原始查询、逻辑 as_of 时间、资源版本引用）、`RunContextSnapshot`（块、冻结工具、历史引用和 manifest）。不携带凭据、ORM Session、客户端、回调或 SQLAlchemy 对象。可变 schema 深拷贝/规范化后进入快照，`frozen=True` 不被当成嵌套 dict 不可变的保证。

| 对象 | 归属 | 输入与输出/约束 |
| --- | --- | --- |
| `ContextPreparationService` | platform | 编排短事务读取、事务外工作、最终提交；取代大段准备器拼接，保留 prepare_execution 入口 |
| `ResourceAuthorizationBatch` | platform | 批量读取当前授权及选定版本，生成只读输入；不跨请求缓存 allow/deny |
| `_message_rows` / `histories_allowed` | platform | 消息行与来源权限生成历史；延续 P10；不静默丢弃未摘要用户/最终回答 |
| `MemoryContextProvider` | platform + memory 契约 | 生成常驻/索引、当前 Run recall；正文按需读取；原始用户查询不取自合成消息 |
| `SkillCatalogProvider` | platform | 合并绑定/私有技能，生成有限目录，正文仍由 load_skill 提供 |
| `KnowledgeCatalogProvider` | platform | 仅返回已绑定且当前可读知识库目录；检索仍走工具 |
| `AuthorizedToolGateway._offered` / `ToolAccess.authorize_many` | tools/worker | 复用 AuthorizedToolGateway 的过滤、审批风险与渐进加载；输出规范排序的 schema 快照 |
| `ContextProviderRegistry` | worker 装配，契约在 core | 只注册受信任应用提供方，返回内容块；不返回工具处理器或授权结论 |
| `RequestContextAssembler` | core/runtime/context_assembly（Native 复用） | 纯装配、去重、顺序、协议校验；不查数据库、不远程请求 |
| `require_context_access` / `sources_allowed` | platform，通过端口调用 | 每 attempt 校验 manifest 来源与当前权限，失败关闭；与既有 model.started 校验合并，避免双重遍历 |

目录/记忆数据从已有所属包读取，不把领域逻辑挪进 runtimes；工具定义仍由 tools/MCP 管理。当前 ContextAssembler 的历史拟合与预算处理保持独立。纯装配器放在 core，由准备和 Native 共用，避免 platform 导入 runtimes；没有另建只转发调用的 Loader/Projector 类。Agent 与模型来源由 Run 配置版本及现有授权关卡追踪。通用 resource 依赖使用 PlatformResourceRecord 的 UUID、版本和 read/use 权限，插件不能用显示名绕过资源授权。

## 4. 一次 Run 的准备流程

### A. 短事务读取

验证队首、租约、取消、用户、空间、Agent、模型及资源；批量读取来源 Run。捕获 session watermark、配置/目录依赖版本、选定快照与真实用户消息。只复制普通数据，结束事务后释放连接。此时不把 Run 改成 running、不发送模型请求，不在事务中调用外部 provider。

没有外部 provider 的路径在同一短事务中完成 A/C，避免空阶段造成重复查询和事务成本。

### B. 事务外工作

按原始用户查询执行召回和外部 prefetch，独立提供方有限并发。首版每 Run 最多 4 个 provider 同时运行，整组 deadline 沿用现有 prefetch 的 8 秒上限；受 worker 容量限制，不为每 Run 新建无限线程池。逻辑 query/as_of 固定；确定性排序后返回，异步完成顺序不得改变 prompt。

可选提供方超时或异常，仅跳过该块并记录失败，不返回原始异常。必要身份/安全约束块失败则终止准备。隔离并发任务：取消未开始工作，已运行同步 hook 即使超时也不再接收迟到结果；在终结前不释放容量令牌，避免超时后无限堆积。Run 租约续约继续运行，旧 worker 的结果不能提交。

### C. 短事务复核提交

重验 worker 租约、队首、取消、主体和权限；比较 watermark、配置和依赖版本。普通内容版本变化在一次准备内最多重建一次；再次变化安全失败，不覆盖并发状态；真实撤权立即失败。快照首次创建使用唯一约束与复读，重复准备不产生多份。

此处原子创建/保存 Run 快照引用、progress，并按现有状态机发布 run.started。无需新增公开 Run 状态，A/B 仍由现有账本和租约所有者负责。等待输入/审批的同 Run 恢复校验快照，不能使用 A/B 重执行工具；未知执行继续沿用现有 unknown 语义。

## 5. 每次模型请求的顺序

目标布局 `v2`：

```text
tools（独立请求字段，Run 内规范顺序）
system: 平台固定协议 → Agent 指令 → 有权注入的稳定目录/常驻记忆
messages:
  摘要/获准历史（沿用已有规则）
  当前 Run 的真实用户消息、assistant/tool 完整交换
  动态资料 envelope（本轮 recall、prefetch、检查点、WorkingMemory、hook）
```

动态块在完整工具交换之后追加，禁止在 assistant tool_calls 与 tool results 之间插入。带来源说明的独立 user envelope 不冒充用户新任务；它是宿主提供的资料。相同 step 的重试复用相同内容快照，仍再次授权。steer/用户答复形成新的 step 输入，必要时按新真实消息刷新动态资料；不是每个工具 step 都重跑远程记忆检索。

兼容布局 `v1` 先复现当前 placement；启用 `v2` 前在原提案 P1 与本节 eval 中独立验证。工作检查点也作为资料迁出 system，避免其中的用户/工具内容被提升为系统权威。该移动属于模型行为变更。

`(placement, order, key)` 稳定排序；重复 key、非法 role、缺失来源、超额必要块直接报配置错误。提供方得到自己的 byte/字符预算，只能裁剪可选目录并给出 search 入口；不能为凑预算截断用户消息或半组工具交换。总窗口交给现有预算流程。

## 6. 权限与安全失效

| 来源 | 内容冻结策略 | 每次 attempt 检查 | 调用时检查 |
| --- | --- | --- | --- |
| Agent/model | Run 固定版本 | 用户/成员、Agent 可运行、模型授权 | 模型发送前同一关卡 |
| 工具/MCP | Run schema，新增下个 Run 生效 | 已展示依赖的当前授权与启用状态 | 网关及 MCP resolve_call 实时复核 |
| 技能 | session 目录版本，可按现有刷新规则更新 | 已展示目录条目的当前可见性 | load_skill/资源文件重验 |
| 记忆 | session 冻结选定版本，Run 固定 recall | 被引用条目的所有权、启用、有效期、删除状态；外部 provider 当前启用 | read/search/write 沿用现有检查 |
| 历史/摘要/检查点 | 已有快照和水位 | 当前来源 Run 资源权限，摘要检查全部覆盖来源 | 历史检索仍重新授权 |
| 插件资料 | 按 session/run/step 声明 | provider 仍注册启用，tenant/principal scope 匹配 | 插件没有扩大工具权限的入口 |

普通编辑保持选定旧版本；显式记忆更正/刷新在下一 Run 重建。删除、禁用、过期、撤权使来源不可再注入；若已进入当前 Run 历史，直接终止 Run，不声称可以从助手文字中清除衍生事实。下一 Run 的历史依赖校验也要覆盖记忆、技能和插件来源，不能仅检查 Agent 最初绑定的 resources。

记忆/技能快照新增 `context_schema_version` 与依赖清单；Run 新增版本化 context manifest 数据记录（使用正式迁移，存哈希和引用，不复制全部消息正文）；provider 独有内容保存到 run_context_blocks，并由 manifest 引用其摘要，保证恢复不重跑提供方。当前 step 的新增来源在首次进入模型视图前并入 Run 依赖并持久化。原始消息仍是唯一对话来源。旧快照无依赖时不能沿用裸文本，需重新读取并授权生成；迁移把已执行的旧 Run 标为 schema_version=0，只从模型输入隐藏，不删除原始记录。新 Run 遇到已失效的 session provider 内容会重建，当前 Run 的失效来源则拒绝继续。

不承诺追踪用户自行粘贴内容的全部来源；只追踪宿主注入、工具和系统明确记录的来源。摘要、检查点继承输入依赖，不能用摘要洗掉权限限制。

## 7. 缓存键与数据库优化

只缓存不可变内容及原始投影，不缓存权限结论、凭据、授权后可见名单或执行对象。每次请求从当前数据库生成可见引用集合，再选择内容缓存。

| 缓存对象 | key | 失效/隔离 |
| --- | --- | --- |
| 原始历史投影 | tenant/session/watermark/projection_schema_version | 写消息推进水位；命中后授权过滤 |
| 技能内容 | tenant/resource_id/published_version/render_version | 私有技能另含 owner；不能只用技能名 |
| 记忆 session 内容 | tenant/owner/session/snapshot_id/render_version | 删除/禁用/到期每请求检查；显式刷新更换快照 |
| 工具原始 schema | tool_name/tool_version/schema_digest/provider_generation/renderer_version | 不包含 OAuth；对使用用户输入动态生成的 schema 禁止共享缓存 |
| 本 Run 工具快照 | run_id/config_digest/tools_digest | 仅 Run 内复用，实际执行仍查权限 |
| 插件内容 | provider_id/generation/tenant/principal/scope/内容版本 | 无版本声明则仅 Run 内；进程重启重建，不持久化回调 |

所有缓存有条目数、总字节数和单条上限，采用既有 ProjectionCache 模式；调用者取得不可变值或深拷贝。渲染器版本纳入 key，避免部署后错误复用旧格式。

历史读取按摘要切点与 P10 SQL 过滤：历史 Run 只取用户与最终回答，当前 Run 取完整交换；无可用摘要时分批读取全部应保留消息，不能用最近 N 条静默替代。权限来源批量加载，去重资源依赖；`allowed_runs` 改为集合。model.started 的逐 source db.get 改为批量 IN 分片读取；MCP 目录与策略改为批量查询，避免每工具一条 approval SQL。权限本身不引入 TTL allow 缓存，也不新建跨系统 permission_epoch。

## 8. 插件和 hook 的边界

`ContextProvider` 只由 worker 入口注册可信实现，注册时声明 provider_id、输出 placement、生命周期、可选/必要、大小和超时。普通插件只能贡献 user/reference 块；system 指令贡献由应用入口显式授予，不能靠 provider 返回 role 自行提升。

ContextProvider 不接收数据库 Session、凭据、可修改的共享 messages 或完整工具注册表；只接收已授权的 DTO。需要资源访问时通过已授权服务端口。工具扩展仍经过独立 ToolRegistry/MCP，不允许 prompt 插件直接修改 tools。

旧 HookRegistry 保留生命周期和异常隔离；把 HookTransform.append_messages 映射为命名的 user 块，保留 done_prompts 的完成语义，不反向解析文本猜测来源。卸载/停用使 generation 改变；跨 Run 内容不能继续引用卸载后的块。

## 9. 观察、验证与实施顺序

`context.assembled` 按新内容快照记录一次，而非每 token/每重试记录全文：assembly_id、layout_version、各 source 的字符/token 估算、耗时、缓存命中、工具数、依赖数、输入摘要。model.started 关联 assembly_id，重试和恢复都再次授权；`context.provider_failed` 只记录 provider_id、错误码、耗时，不记正文、查询或秘密。manifest 受现有 Run 权限保护，不作为跨空间枚举接口。

阶段一（A1–A4）：基线、DTO、兼容布局、请求关卡与事务拆分。阶段二（A5–A8）：来源持久化、安全失效、内容缓存、提供方统一接口。阶段三（A9–A12）：可观测性、真实模型评测、v2 布局和文档同步。任务存在依赖，不在第一阶段启用未追踪来源的跨 Run 内容缓存。

必须验证：相同输入重复装配字节一致；缓存不跨租户/用户泄露；目录权限撤销后下一请求拒绝；记忆删除/过期后旧 snapshot 不再注入；旧格式快照安全重建；MCP 禁用与审批保持生效；插件输出不能提升角色或扩大工具集；工具 schema 深层修改不污染另一 Run；等待恢复、重试、取消和旧租约提交安全。

性能验收使用至少 20 段现有固定语料，并增加 100/1000 工具、10k 消息、多 worker 和慢 provider 组合。记录 prepare/assemble/auth 的 p50/p95、SQL/事务数、连接占用、缓存字节、输入/cached_tokens。目标：非授权内容命中时不重复扫描技能正文、不重新远程发现 MCP；无网络调用占用数据库事务；SQL 按批量来源增长而非逐工具 N+1；无 provider 场景 p95 装配耗时对基线回退不超过 10%。超过门槛先定位修复，不为过线放宽权限。质量 eval 覆盖追问、技能选择、记忆使用和当前任务延续，通过后再启用 v2 默认值；真实供应商不可用时只报告平台指标，默认值不切换。

本方案不引入 Redis、任意第三方代码安装或新管理 UI；沿用现有开关和资源配置。新增用户可配项如实施需要，必须同时接入现有类型化 API 与设置界面。模块文档只描述已实施的 v1 与来源校验；v2 默认布局继续标为待评测，不提前归档。
