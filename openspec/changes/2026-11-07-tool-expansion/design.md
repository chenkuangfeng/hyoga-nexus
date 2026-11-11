# 设计：工具扩展

状态：待确认。以下为推荐方案下的设计，决定变更后同步修改。

## 1. 工具分组与两层门控

```text
ToolDefinition.group ──► ToolGroupRegistry (id, label, default_enabled, availability)
                               │
Run 准备（preparation.py）：  绑定 ─► 过滤1：group.availability(ctx) 为假 → 丢弃（编辑器显示原因）
                                   └► 过滤2：NativePolicy.tool_groups_enabled[group] 为假 → 丢弃
                               │
网关（每次调用）：            实时授权 → 访问级别 → 参数 → 守卫 → 审批 → 执行   （不变，开关不放宽）
```

- `availability(ctx) -> Availability(ok, reason)` 是纯函数，输入是部署状态与 Run 上下文，不做 IO 的部分由调用方预先装配进 `ctx`：沙箱验收结果、已配置的搜索后端、智能体绑定的知识库类型。reason 是稳定代码（`sandbox_disabled`、`sandbox_not_accepted`、`web_backend_missing`、`wiki_kb_not_bound`），前端翻译成文案。
- 现有门控（`script_tool_on`、`memory_on`、`knowledge_bound`）改为各组的 `availability`，行为不变，用现有测试证明。
- `tool_groups_enabled` 缺省值取各组 `default_enabled`；老智能体版本没有这个字段，按缺省处理，因此 `sandbox`、`web` 等新组对既有智能体默认不出现。智能体版本是不可变的，开关变化产生新版本，已发布版本不被悄悄改变。
- 一致性测试：遍历 `builtins()` 注册表，断言每个工具有合法 `group`、属于 `BUILTIN_TOOL_NAMES`，且 `BUILTIN_TOOL_NAMES` 里每个名字要么已注册，要么在「待实现」清单里（如 Wiki 工具）。

## 2. 沙箱

### 2.1 包结构（`packages/sandbox`）

| 模块 | 职责 |
| --- | --- |
| `contracts` | `CommandExecutorPort`（`run(spec) -> Result`、`start/poll/cancel` 后台作业）、`FileStorePort`（`read/write_atomic/list/stat/search`）、`SandboxLease`、`VirtualPath` |
| `backends/docker` | 每个（租户，会话）一个容器；工作区为命名卷；`exec` 进入容器 |
| `backends/local` | 仅开发模式，不能用于多用户；首版只作为端口的测试替身，不开放给工具组 |
| `paths` | 虚拟路径 ↔ 容器路径；拒绝 `..`、符号链接逃逸、绝对宿主路径 |
| `lease` | 租约：Run 持有，结束或取消释放；空闲 `idle_seconds` 后回收容器，卷保留到配额与保留期 |
| `acceptance` | 隔离验收与连通探测 |
| `artifacts` | 扫描 `/outputs` 并登记 |

### 2.2 Docker 后端参数

非 root 用户；`--network none`（部署可改）；只读根文件系统，`/workspace`、`/outputs` 为可写卷，`/tmp` 为 tmpfs；`--cap-drop ALL`、`no-new-privileges`、默认 seccomp；`--cpus`、`--memory`（含 swap 上限）、`--pids-limit`；每次 `exec` 有墙钟超时，超时或取消时杀掉整个进程组；输出每流上限，超出丢弃并标记；不挂载宿主目录，不继承服务进程环境变量，子进程环境从零构造（沿用 `skill_scripts` runner 的做法）。

### 2.3 验收（`acceptance`）

每项是一个真实的容器内探测，不是配置检查：

| 项 | 探测 |
| --- | --- |
| 资源限制 | 内存分配超限被 OOM 杀；`while true` 超时被终止；fork 炸弹被 pids 限制；超大输出被截断 |
| 网络隔离 | 配置为 `none` 时，TCP 连接与 DNS 解析都失败 |
| 租户隔离 | 租户 A 写入的文件在租户 B 的租约里不可见；路径穿越被拒绝 |
| 清理 | 租约释放后容器与进程消失，卷按保留期处理 |
| 崩溃残留 | 强制杀掉 worker 后重启，能发现并回收遗留容器 |
| 连通 | 写 → 读 → 删一个探测文件 |

结果写表 `sandbox_acceptance`（每个档位一行，列见 2.3.1）。镜像摘要变化、后端配置变化时旧结果失效。入口：worker 启动自检（只读：未通过的档位打警告，不自动运行探测），以及 `uv run python -m nexus_worker sandbox-check` 手动执行。`sandbox` 组可用性 = `[sandbox].enabled` 且最近一次验收对当前镜像与配置通过。

#### 2.3.1 验收结果入库（追加，待确认）

**为什么改**：验收报告目前写在 `<workspace_root>/acceptance[-<profile>].json`，读取方是 `tool_gates.profile_facts`（API 的智能体编辑器与 worker 的 Run 准备都会读）。单机部署共用一个 `workspace_root`，现状可用；API 与 worker 分机部署时，API 读不到 worker 写的文件，编辑器会显示"未验收"，而 worker 实际认为已通过。2.3 原设计本就是写表，只是当时迁移链上有未提交的知识库迁移，临时改成了文件。迁移链现在只有一个 head（`c2d3e4f5a6b7`），可以补上。

**表**：`sandbox_acceptance`，每个档位一行（`profile` 唯一）。

| 列 | 说明 |
| --- | --- |
| `profile` | 档位名，主键。`default` 沿用旧档位名 |
| `backend` | `docker` / `bwrap` |
| `fingerprint` | 现有 `acceptance.fingerprint(settings)`（后端、镜像、限制的哈希），沿用不变；2.3 原写的 `image_digest` 已包含在内 |
| `passed` | 全部探测项通过 |
| `items` | 逐项结果（JSON） |
| `checked_at` | 验收时间 |

结果有效 = 有该档位的行、`passed` 为真、`fingerprint` 等于当前配置的指纹。再次验收按档位覆盖（upsert），不保留历史。

**分层**：`nexus_sandbox` 不能依赖平台包。`acceptance.run` 通过一个存储端口（`ReportStore`：`save(settings, report)`、`load(settings)`）保存与读取，包内默认实现仍是现有的 JSON 文件；平台包提供数据库实现，由 worker 与 API 的装配处注入。`--sandbox-check` 仍打印逐项结果，并继续写文件副本供运维查看（不再作为判断依据）。

**读取方式（已确认：方案 B）**：数据库会话逐层传入，没有缓存，验收刚通过就对所有进程生效。`profile_facts`、`deployment_gate_facts`、`sandbox_profiles` 增加 `db` 参数（读取失败按"未验收"，不放行）。调用点：

| 调用点 | 做法 |
| --- | --- |
| 智能体编辑器（`agent_editor.py`） | 已有会话，直接传入 |
| Run 准备（`runs/preparation.py`） | 已在事务内，传入 |
| `exec_skill` 执行（`runs/store.py`） | `prepare()` 事务内取得 `accepted`，随后在事务外判定 `execution_allowed(prepared, profile, accepted=...)`，不重新开会话 |
| 技能服务（`skills/service.py` 的 `exec_skill_available`、`sandbox_can_build`、`_script_fit`）与私有技能（`skills/private.py`） | 签名增加 `db`，调用方已有会话 |
| worker 的 Run 启动（`native.py`） | 经 `run_db` 在短会话内读取 |

**旧报告**：表里没有该档位的行时退回读取旧的 JSON 文件（指纹仍须匹配），升级后不必立刻重跑验收；一旦有行，以表为准（行的指纹不符不再退回文件）。

**迁移与测试**：新增一个 Alembic 迁移（空库升级、升降级往返）；测试覆盖存取往返、指纹变化使结果失效、数据库读失败不放行、旧文件退回、行优先于文件、`nexus_sandbox` 不导入平台包。

### 2.4 工具实现要点

- 文件：`sandbox_read_file` 按行或字符分页，返回总大小；二进制拒绝并提示用别的方式；`sandbox_write_file` 临时文件加原子替换；`sandbox_edit_file` 要求 `old` 在文件中恰好出现一次，否则返回出现次数让模型加上下文（参考 DeepSeek `tool-str-replace-editor`）。
- 命令：参数 `command`、`cwd`（虚拟路径）、`timeout_seconds`（不超过智能体上限）；返回 `exit_code`、截断标记、`duration`；stdout 与 stderr 分开保留头尾。
- 后台作业：`sandbox_exec_async` 立即返回 `job_id`；`sandbox_job_wait(job_id, timeout)` 返回新增输出与状态；作业生命周期不超过所属 Run，Run 终态时取消仍在跑的作业并标记。与路线图 3.24（异步工具）的关系：本变更只做 Run 内作业，不做跨 Run 的结果回投；3.24 评估时再合并。
- 公开投影：命令与文件工具的 `public_result` 只返回上述摘要字段，不含宿主路径。

### 2.5 配置

`configs/nexus.toml`：

```toml
[sandbox]
enabled = false            # 部署开关
backend = "docker"
image = "..."              # 实施时固定镜像与摘要
cpus = 1.0
memory_mb = 512
pids = 128
network = "none"           # none | bridge（打开后 sandbox_exec 风险升为 destructive）
idle_seconds = 900
workspace_quota_mb = 512
exec_timeout_max_seconds = 120
```

`NativePolicy` 新增 `tool_groups_enabled: dict[str, bool]`、`sandbox_exec_timeout_seconds`（默认 30）、`sandbox_output_limit`（默认 20000 字符）。设置页标签同步补齐。

### 2.6 产物登记（4.6）

`/outputs` 下的文件在 Run 结束时**复制**成不可变的产物并登记；之后下载读的是副本，不受工作区里后续改动影响。

- **表 `artifacts`**：`id`、`tenant_id`、`session_id`（会话删除时级联）、`run_id`、`owner_user_id`（Run 的发起人）、`path`（虚拟路径，如 `/outputs/report.pdf`）、`name`、`size`、`sha256`、`mime`、`storage_key`（相对产物根目录的路径）、`created_at`、`deleted_at`；唯一 `(run_id, path)`，索引 `(tenant_id, session_id, created_at)`。
- **存放**：`<[sandbox].workspace_root>/_artifacts/<tenant_id>/<artifact_id>`。API 与 worker 需共享该目录（单机或共享卷部署）；与知识库本地文件存储同样的约束，写入文档。
- **登记时机**：worker 的 Run 收尾（`close_jobs` 之后、不论成功、失败或取消），失败只记日志、不影响 Run 终态。
- **登记规则**：只收普通文件（符号链接、非常规文件跳过），复制时流式计算 `sha256`，并再次确认没有越出 `/outputs`。同一会话里同一路径、内容哈希与最近一次登记相同的文件不重复登记。
- **上限**（超出的跳过并记入 `artifacts.registered` 事件的 `skipped`，原因 `too_large` / `too_many` / `run_quota` / `tenant_quota`）：单文件 50 MB、每 Run 50 个、每 Run 200 MB、每空间未删除产物合计 2 GB。
- **授权**：与会话一致——会话所有者可读写自己会话的产物，空间 owner / admin 可读写全空间的；其他人、其他空间一律「不存在」。
- **接口**（`/api/v1/tenants/{tenant_id}/artifacts`）：`GET ?session_id=&run_id=&limit=&offset=` 列表、`GET /{id}` 元数据、`GET /{id}/download`（`Content-Disposition: attachment`、`X-Content-Type-Options: nosniff`、统一按 `application/octet-stream` 返回以免被浏览器当页面执行）、`DELETE /{id}`（软删除并删除副本）。
- **审计**：`artifact.registered`（每 Run 一条，含数量与跳过数）、`artifact.downloaded`、`artifact.deleted`。
- **不做**：前端界面（先有接口）、跨会话共享、保留期自动清理、对象存储后端。

## 3. 调度

```python
class ConcurrencyHint(NamedTuple):
    mode: Literal['parallel', 'exclusive', 'serial']
    key: str | None = None   # serial 时同 key 排队，例如 sandbox 虚拟路径
```

`execute_batch` 从当前位置起逐个取调用，按 `definition.concurrency(arguments)`（未声明则按现有 `read_only and idempotent` 推出）分类：连续的 `parallel` 组成并行批（上限仍为 8），`serial` 调用按 key 排队、不同 key 可并行，`exclusive` 先排空再单独执行。结果与 `tool.before/after` 钩子仍按模型顺序。参数在分类前已由网关规范化（`prepare_arguments`），分类函数接收规范化后的参数；解析失败的调用按 `exclusive` 处理。审批挂起沿用现有恢复路径（`recovery.resume_tools`），串行 key 不跨恢复保存。

## 4. 渐进加载

触发：绑定工具的 schema 估算 token 数超过上下文窗口的 `tool_search_threshold_pct`（默认 10%）。被延迟的工具：`source == 'mcp'` 和声明 `deferrable=True` 的大型工具组；`base` 与现有内置工具永不延迟。

- Run 开始时：工具块 = 非延迟工具 + `tool_search` + `tool_describe` + `tool_call`；系统提示附一份名称加一句话的目录，受 `listing_max_tokens` 约束，超限降级为只列组名。
- `tool_search(queries)`：在延迟目录里做关键词检索，返回名称与摘要，次数与结果数有上限。
- `tool_describe(names)`：返回完整 schema（经 sanitize）。
- `tool_call(name, arguments)`：网关先解开，再按真实工具名执行 `authorize → 访问级别 → 预处理 → 守卫 → 审批 → 执行`。真实工具必须在智能体绑定里；未绑定或被组开关过滤的工具即使知道名字也调不通。循环检测、审计、事件使用真实工具名。
- 三个桥接工具自身为 `read`、可并行，其中 `tool_call` 的调度提示取自被调用的真实工具。

## 5. Schema 清洗

`sanitize(schema, provider)` 返回深拷贝，规则从 Hermes `schema_sanitizer.py` 移植：属性名不匹配 `^[a-zA-Z0-9_.-]{1,64}$` 时改写并保留映射（调用返回时还原）；对象缺 `properties` 时补空；顶层 `anyOf` / `oneOf` 展开或合并；`default` 与 `$ref` 并存时去掉 `default`；布尔式 `required` 提升。按供应商开关，调用点在 `nexus_runtimes/native/models` 序列化工具定义之前。

## 6. Web

- `nexus_tools/web/` 下 `search`（后端注册表 `SearchBackend.search(query, limit, ctx) -> list[Hit]`）、`fetch`（HTTP 抓取 + 正文抽取）。
- 出站校验：把 `runtimes/native/models/network.py` 的地址校验抽到 `nexus_core.net`（只依赖标准库），模型连接与 `web_fetch` 共用。每一跳（含重定向）都校验解析后的 IP，拒绝回环、私网、链路本地、元数据地址；限制协议与端口；总大小与超时上限。
- 返回：`{url, title, text}`，文本经注入扫描并带外部内容前缀；搜索结果同样带前缀。

## 7. Wiki 组

本变更交付：组与子组定义、`availability = 智能体绑定了 wiki 类型库`、风险映射、目录占位（「待实现 · K6」）。九个工具的实现、持久化与前端属于知识库提案 K6.1。读类可并行；`wiki_write_page` / `wiki_replace_text` / `wiki_rename_page` 以页面路径为 `serial` key。

## 8. 协作与定时（阶段 G，实施前补充）

此处只记录已定的约束，具体接口在阶段开始前补全并再次确认。

- `delegate_task`：子 Run 的 `NativePolicy` = 父级策略收紧后的副本（`tool_access` 不低于父级，工具集 ⊆ 父级绑定，`collab` 组本身不继承以禁止递归）；子 Run 的审批请求冒泡为父会话的审批；预算从父预算扣除；结果以单条工具结果返回父级，过长走外置。
- `cronjob`：任务保存（所有者、智能体版本、提示、计划、时区、状态）；worker 的调度器按计划创建 Run；无人值守 Run 的 `tool_access` 强制 `read_only` 或「不允许需要审批的工具」，拒绝时记录审计而不是挂起；创建与修改需要审批（`write`）；每用户任务数、最小间隔与每日运行数有上限；提示入库前扫描。

### 8.2a 定时任务的 REST 与界面（用户 2026-11-11 确认 C1–C6）

**现状**：`cron_jobs`、规则（interval / daily / weekly）、服务（创建、列表、暂停 / 恢复 / 删除、到点触发）和 `cronjob_*` 工具已实现，但只有模型能创建和管理任务，用户看不到、改不了。前端 `/platform/automations` 仍是占位页；仓库里复制了 WeKnora 的 `views/automation/*` 与 `api/automation.ts`，面向 WeKnora 的完整自动化模型。

**已确认的决定**：

| 编号 | 决定 |
| --- | --- |
| C1 | 适配 WeKnora 自动化页到 Nexus（不新建精简页）；不支持的控件保留并标「待实现」，不隐藏 |
| C2 | 创建时选一个已发布智能体，任务固定在其当前已发布版本；创建后不能换智能体（会话绑定智能体版本） |
| C3 | 本人管理自己的任务；空间 owner / admin 另可**查看**本空间所有人的任务并**暂停**它们，不能改内容、立即运行、恢复或删除 |
| C4 | 纳入「立即运行」：不改变下次触发时间，距上次运行不足 60 秒拒绝 |
| C5 | 运行记录取任务会话里的 Run 列表，点击进入该会话，不新建表 |
| C6 | 触发规则沿用 interval / daily / weekly，提供预览接下来的触发时间；不加 cron 表达式 |

**后端接口**（`/api/v1/tenants/{tenant_id}/schedules`，空间成员；他人的任务对非管理员一律按不存在处理）：

| 方法与路径 | 用途 |
| --- | --- |
| `GET /?scope=mine\|all` | `mine`（默认）本人任务；`all` 仅 owner / admin，返回全空间任务并带 `owner_user_id` 与 `owner_name` |
| `POST /` | 创建：`name`、`prompt`、`agent_id`、`schedule`、`timezone`；取该智能体当前已发布版本，没有则 `schedule_agent_unpublished` |
| `GET /{id}` | 详情：完整 `prompt`、规则对象、智能体名称与固定版本号、任务会话 id；管理员可看他人 |
| `PATCH /{id}` | 仅所有者：改 `name`、`prompt`、`schedule`、`timezone`；改规则或时区按当前时间重算 `next_run_at`；改 `prompt` 重新扫描；`suspended` 的任务编辑后仍需 `resume` |
| `POST /{id}/pause` | 所有者或管理员 |
| `POST /{id}/resume`、`DELETE /{id}` | 仅所有者 |
| `POST /{id}/run` | 仅所有者：立即以任务会话发起一次运行（幂等键 `cron-now:{id}:{随机}`），更新 `last_run_at`、`last_run_id`、`run_count`，不改 `next_run_at`；不足 60 秒拒绝 `schedule_run_too_soon` |
| `GET /{id}/runs?limit=` | 任务会话里的 Run（状态、创建与结束时间、错误码），新的在前，最多 50 条；所有者或管理员 |
| `POST /preview` | 校验 `schedule` + `timezone`，返回接下来最多 5 次触发（UTC），不写库 |

- 错误码沿用 `ScheduleError.code`：`schedule_not_found` → 404，`schedule_forbidden` → 403，`schedule_limit_reached` → 409，`schedule_run_too_soon` → 429，其余 `schedule_*` → 422。
- 服务层新增 `get_job`、`update_job`、`run_now`、`list_runs`、`preview`，列表增加 `all` 范围；管理员暂停写审计 `schedule.paused`（记录操作者与所有者）。REST 与工具共用规则、限额（每人 10 个活跃）、提示扫描。
- 不要求智能体开启 `schedule` 工具组：该开关只管模型能否创建任务。
- 无人值守不变：任务运行拿不到审批与提问机会，界面固定提示。

**前端：适配 WeKnora 自动化页**（路由 `automations/:automationId?` 由占位页改为 `AutomationList.vue`；沿用知识库的做法：`api/automation.ts` 保留 WeKnora 形状的函数，内部改调 Nexus 并经纯函数适配器转换）：

- 适配器 `api/nexusAutomationAdapter.ts`（纯函数，单测）：Nexus 任务 ↔ WeKnora `Automation`。`name`、`instruction` ↔ `prompt`（上限 4000）、`enabled` ↔ `state === 'active'`、`paused_reason` ↔ `last_error`、`next_run_at`、`last_run_at`、`session_id`；`trigger` ↔ 规则；`model_id` 位置改为智能体（`agent_id`）。
- 触发器映射：WeKnora 表达式只接受能无损对应 Nexus 规则的形态——`daily`、`weekly`（仅选一天）；新增 Nexus 独有的「每 N 分钟」类型。其余类型（每小时、工作日、多选星期、每月、一次性、自定义 cron）在编辑器里保留为不可选项并标「待实现」；已存在的无法表达的触发器不会出现（后端只存三种）。
- 编辑器：模型选择器换成智能体选择器（只列已发布，编辑时只读）；指令框上限改为 4000；会话方式、携带上次结果、重叠与漏触发策略、最长时长、审批超时、成功通知等控件保留，显示「待实现」并禁用，值不提交。
- 列表与详情：列表、暂停 / 恢复、删除、立即运行、编辑接 Nexus；详情的运行记录来自 `GET /{id}/runs`（行内进入会话），「取消运行」接现有运行取消；授权（grants）与通知（notifications）相关调用不发请求，返回空并标「待实现」；管理员在列表顶部有「我的 / 全部」切换，他人的任务只显示暂停。
- 触发预览接 `POST /preview`；时区沿用页面已有的时区工具。
- 文案：复制页已有 `automation.*` 文案；新增键（智能体、每 N 分钟、待实现说明、管理员视图、错误码）六种语言一次加齐。

**不做**：cron 表达式、一次性触发、每小时 / 每月 / 工作日 / 多日 weekly（待实现标记）、漏触发与重叠策略、授权、通知中心、每次新会话、管理员改内容 / 恢复 / 删除他人任务。留给路线图 9.4 一并评估。

**测试**：服务层（更新重算下次时间、更新触发扫描、`run_now` 不改 `next_run_at` 且节流、`list_runs` 只见本任务会话、非所有者非管理员 404、管理员只能暂停）；接口（权限、错误码映射、`preview` 不写库、未发布智能体、`scope=all` 的权限）；前端适配器与规则映射的纯函数单测、列表与编辑器交互测试（沿用 `automationInteractions.test.ts` 惯例）。

**风险**：立即运行在会话忙时排队（沿用忙会话队列），文案需说明；任务固定版本，智能体后来更新不影响它，界面显示固定版本号并提示新建任务以使用新版本；复制页体量大（约 2300 行），只改数据层与受影响控件，其余保持原样以便对照 WeKnora。

## 9. 迁移与兼容

- 新表：`sandbox_acceptance`、`artifacts`（若与产物提案重合，复用其结果）。沿用 Alembic 升降级并测试。
- `ToolDefinition` 新增字段全部带默认值（`group='base'`、`source='builtin'`、`concurrency=None`、`deferrable=False`），旧调用点和测试不改。
- `catalog.TOOL_GROUPS` 删除后，`/tools/catalog` 响应字段 `group` 保持，另增 `availability` 与 `reason`。
- 老智能体版本无 `tool_groups_enabled`：按缺省处理。

## 10. 测试

`tests/test_tool_groups.py`（分组、两层门控、一致性）、`tests/test_sandbox_*.py`（路径、租约、工具；容器相关测试在无 Docker 时跳过并标明）、`tests/test_tool_scheduling.py`、`tests/test_tool_search.py`、`tests/test_schema_sanitize.py`、`tests/test_web_tools.py`；沙箱验收报告作为文件留存。
