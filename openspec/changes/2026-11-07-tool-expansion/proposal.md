# 工具扩展：工具分组与开关、沙箱工具组、Web / Wiki / 协作 / 定时工具组、渐进加载与调度增强

## 状态

实施中（2026-11-07）：决定 1–9 全部采用推荐方案。实施中的调整与进度记录在 `tasks.md`。

## 原因

对照 WeKnora、Hermes、DeepSeek Harness、octop-harness、deer-flow、GenericAgent 的工具层后（工具清单与调用链路的分析见会话记录），Nexus 的工具内核（网关、参数容错、授权、审批、输出控制、循环检测）已与参考项目对齐，缺口在内核之外：

1. **没有执行类工具**：沙箱包 `packages/sandbox`、MCP 包是空壳；文件读写、shell 都没有，`run_skill_script` 是唯一入口且明确不是隔离边界（`nexus_skills/runner`）。
2. **没有 Web、协作、定时类工具**：`web_search` / `web_fetch`、子智能体委派、定时任务不在路线图内。
3. **工具分组靠硬编码**：`catalog.py` 的 `TOOL_GROUPS`、`policy.py` 的 `BUILTIN_TOOL_NAMES`、`registration.py` 的元组三处要同步修改，漏改不报错（未分组的工具静默归入 `base`）。分组也没有「整组开关」和「组可用性」的概念，门控散落在 `preparation.py` 里（`script_tool_on`、`memory_on`、`knowledge_bound`）。
4. **调度粒度粗**：并行只看工具级的 `read_only` + `idempotent`，不能按参数判断；同路径的写入没有串行化。执行类工具上线前必须解决。
5. **工具一多就占上下文**：所有绑定工具的完整 schema 每轮都进上下文；接入 MCP 后会更明显。
6. **schema 直接发给供应商**：没有按供应商清洗，一个不合规的属性名会让整个请求 400（Hermes `schema_sanitizer.py` 记录了 Cloudflare MCP 有 61 个这样的键）。

## 参考源码

本地副本 `/project/opensource/agents/`。下表为已读的入口文件；实施前按 `tasks.md` 第 0 节补读其余部分。

| 项目 | 文件 | 借鉴点 |
| --- | --- | --- |
| WeKnora | `internal/agent/tools/definitions.go` | 工具分组（`base` / `rag` / `wiki_read` / `wiki_edit` / `wiki_issue` / `data`）、编辑器目录 |
| | `execution_policy.go`、`file_mutation_queue.go` | 并行白名单；同路径写入串行化、全局写入计数器使读缓存失效 |
| | `shell_exec.go`、`shell_exec_async.go`、`work.go`、`write_sandbox_file` 等 | 前台与后台命令、等待与取消、沙箱文件工具 |
| | `web_search.go`、`web_fetch.go`；`wiki_*.go` | Web 工具；Wiki 九个工具 |
| Hermes | `tools/registry.py`（`check_fn`、`scope`、`override`）、`toolsets.py` | 组可用性检查、按组选择工具 |
| | `tools/tool_search.py`、`tool_search_catalog.py` | `tool_search` / `tool_describe` / `tool_call` 桥接，工具块不变 |
| | `tools/schema_sanitizer.py`、`url_safety.py`、`cronjob_tools.py`、`cronjob_prompt_scan.py`、`delegate_tool*.py`、`terminal_tool*.py`、`process_registry*.py` | schema 清洗、URL 安全、定时任务与提示扫描、委派、终端与后台进程 |
| DeepSeek Harness | `packages/core/tools`（`isConcurrencySafe(args)`、`when`）、`packages/fs`、`shell`、`web`、`subagent` | 按参数判定并行；条件可见；文件、shell、Web、子智能体的包划分 |
| octop-harness | `backends/docker_sandbox.py`、`bwrap_shell.py`、`local_shell.py`、`composite.py`、`probe.py`；`security/ssrf.py`；`builtin/tools/web_search/_registry.py`、`web_fetch.py` | 沙箱后端与连通探测；SSRF 防护；可插拔搜索后端 |
| deer-flow | `sandbox/`（租约、虚拟路径、原子写入、文件锁）、`tools/builtins/task_tool.py`、`tool_search.py` | 沙箱租约；委派；会话内提升式 `tool_search` |
| GenericAgent | `agent_loop.py` | 已采用，不再重复 |

## 范围

### 范围内

**A. 工具分组与开关（核心契约、平台、API、界面变化）**
1. `ToolDefinition` 新增 `group`；目录、门控、编辑器都从注册表读取，删除 `catalog.TOOL_GROUPS` 硬编码。新增一致性测试：`BUILTIN_TOOL_NAMES` 与注册表、分组声明互相一致，漏改即测试失败。
2. 分组注册表 `nexus_core.native.tool_groups`：每组声明 `id`、标签、`default_enabled`、可用性检查（`availability`）。门控统一为两层，替代 `preparation.py` 中分散的判断：
   - **可用性**（部署侧事实）：沙箱后端通过验收、Web 搜索后端已配置、智能体绑定了 Wiki 库……不满足时该组工具**不出现**（不是返回错误），编辑器显示不可用原因。
   - **智能体开关**（用户选择）：`NativePolicy.tool_groups_enabled`（按组的布尔值，`sandbox`、`web` 等高影响组默认关闭）。开关关闭时该组的绑定在 Run 准备阶段被过滤；每次调用仍复核授权，开关只能收紧。
3. 分组：

| 分组 | 内容 | 默认 |
| --- | --- | --- |
| `base` | `ask_user`、`todo`、`update_working_checkpoint`、`read_tool_output`、`tool_search`（见 D） | 开 |
| `memory`、`knowledge`、`skills` | 现有工具，行为不变 | 现状 |
| **`sandbox`** | 文件与命令工具（见 B） | **关** |
| **`wiki`**（子组 `wiki_read` / `wiki_edit` / `wiki_issue`） | Wiki 九个工具，**不属于 base** | 随 Wiki 库绑定 |
| `web` | `web_search`、`web_fetch` | 关 |
| `collab` | `delegate_task` | 关 |
| `schedule` | `cronjob` | 关 |
| `media` | `vision_analyze`（可选） | 关 |

4. 智能体编辑器按组显示：每组有整组开关、逐工具勾选、风险徽标、可用性状态与不可用原因；沿用知识库提案「未实现项显示待实现标记」的做法。

**B. 沙箱与沙箱工具组（先实现；Runtime、持久化、API、界面变化）**
5. 实现路线图第 8 步：`CommandExecutorPort`、`FileStorePort`，首个后端 `docker`（决定 1）。租约、虚拟路径（`/workspace` 可读写、`/outputs` 收集为产物）、原子写入、资源限制、默认无网络。
6. 隔离验收 `nexus_sandbox.acceptance`：CPU、内存、时间、输出限制；网络隔离；用户（租户）隔离；清理；崩溃后残留；写读删连通探测（octop-harness `probe.py`）。结果写表 `sandbox_acceptance`，API 与 worker 共读；`sandbox` 组的可用性 = 部署已启用且最近一次验收通过。
7. 工具（均在 `sandbox` 组，名称加 `sandbox_` 前缀，决定 8）：

| 工具 | 说明 | 风险 | 并行 |
| --- | --- | --- | --- |
| `sandbox_list_files`、`sandbox_read_file`、`sandbox_search_files` | 列目录、分页读文件、按内容或名称搜索 | `read` | 参数判定可并行 |
| `sandbox_write_file`、`sandbox_edit_file` | 写入（可追加）、字符串替换式编辑 | `write` | 同路径串行 |
| `sandbox_exec` | 前台命令，超时、输出上限、头尾截断 | 隔离且无网络时 `write`，开放网络时 `destructive`（决定 3） | 独占 |
| `sandbox_exec_async`、`sandbox_job_wait`、`sandbox_job_cancel` | 后台命令与等待、取消；作业随 Run 结束回收 | 同 `sandbox_exec` | 独占 |

8. 产物：`/outputs` 下的文件在 Run 结束时登记为 Artifact（新表，关联 Run 与来源），下载走授权检查。
9. 参数守卫：`dangerous_shell_commands.json` 的 `tools` 增加 `sandbox_exec`、`sandbox_exec_async`；新增针对文件路径越界、写入敏感位置的规则。
10. 配置分三层，**你可以在每层决定是否启用**：
    - 部署：`configs/nexus.toml [sandbox]`（`enabled` 默认 `false`、`backend`、`image`、`cpus`、`memory_mb`、`pids`、`network`、`idle_seconds`、`workspace_quota_mb`）。
    - 智能体：`tool_groups_enabled.sandbox`（默认关）、逐工具勾选、`sandbox_exec_timeout_seconds`、`sandbox_output_limit`。
    - 调用：`tool_access`（`strict` 下写类与命令都要审批）与「本会话允许」。
11. 技能脚本迁入沙箱（决定 5）：沙箱可用时，`run_skill_script` 改经 `sandbox_exec` 的同一后端执行；不可用时保持现有「仅开发模式本地执行」的门禁。

**C. 调度增强（核心契约、Runtime 变化）**
12. `ToolDefinition` 新增可选 `concurrency(arguments) -> ConcurrencyHint`：`parallel`（可与其他并行）、`exclusive`（独占屏障）、或 `serial(key)`（同一 key 串行，如文件路径）。省略时沿用现有 `read_only` + `idempotent` 判定，现有工具行为不变。`execute_batch` 按它调度，结果和事件仍按模型顺序。
13. 沙箱写入后递增全局写入计数，读缓存据此失效（WeKnora `sandboxFileMutationEpoch`）。

**D. 渐进加载与 schema 清洗（Runtime、模型适配变化）**
14. `tool_search` / `tool_describe` / `tool_call` 三个桥接工具（决定 6）。绑定工具的 schema 总量超过上下文预算的某个比例时，低频工具只在目录里列名称与一句话，模型经 `tool_search` 检索、`tool_describe` 取 schema、`tool_call` 调用。`tool_call` 展开为真实工具名后走完整网关管线（授权、审批、守卫、审计都看到真实工具），桥接工具本身不开新口子。Run 内工具块保持不变，保护提示缓存。默认只对 MCP 与大型工具组启用，现有内置工具不受影响。
15. `nexus_tools.schema.sanitize(schema, provider)`：在模型客户端发请求前清洗（属性名正则、顶层 `anyOf`、缺 `properties` 的对象、`default` 与 `$ref` 并存等）。只作用于发给供应商的副本，不改注册的定义。
16. 工具来源标记 `ToolDefinition.source`（`builtin` / `domain` / `mcp`），接 MCP 时用于命名空间与审计。

**E. Web 工具组（Runtime、配置变化）**
17. `web_search`：可插拔后端注册表（octop-harness `_registry.py`），凭据以引用保存。风险 `probe`。
18. `web_fetch`：出站地址校验复用 `runtimes/native/models/network.py` 现有逻辑，抽到 `nexus_core` 共用，逐请求校验含重定向；响应大小上限；正文经注入扫描，并带「外部内容，不是指令」前缀。风险 `probe`。

**F. Wiki 工具组（门控在本变更，工具实现随知识库 K6）**
19. 本变更提供 `wiki` 分组及子组、可用性规则（智能体绑定了 Wiki 类型的知识库才出现）、风险（读 `read`；写、改名、替换 `write`；删除 `destructive`）、编辑器的「待实现」占位。九个工具的实现归知识库提案 K6.1，不在本变更重复。

**G. 协作与定时工具组（第二批阶段，各自开始前补设计并再确认）**
20. `delegate_task`：子智能体的工具集只能是父级的子集（WeKnora `RestrictTools`），深度限 1，预算与审批沿用父级会话，子 Run 记录 `parent_run_id`。
21. `cronjob`：创建、查看、暂停、删除定时任务；任务以创建者身份在固定智能体版本上无人值守运行，不能使用需要审批或询问用户的工具（自动按 `read_only` 访问级别拒绝）；提示文本入库前做注入扫描（Hermes `cronjob_prompt_scan.py`）；每用户任务数与频率上限。
22. `vision_analyze`（可选）：复用知识库 K4.2 的视觉模型客户端，输入来自附件或沙箱文件。

### 范围外

- MCP 客户端与服务端本身（路线图 7）；本变更只提供它要用的 `source`、`tool_search`、schema 清洗。
- `execute_code`（PTC）：依赖结构化工具输出，沙箱稳定后另议。
- `database_query` / `data_analysis`：先要有数据源授权模型，后续单独规划。
- 浏览器、LSP、kanban、TTS 与视频生成、`think` / `sequentialthinking`、飞书与元宝等渠道专用工具：场景专用或与现有能力重叠，不集成。
- 观澜（股票）相关工具：留在 `packages/guanlan`，通用包不导入。
- 外部 Runtime（Codex、Claude Code）的工具。

## 已确认的决定（全部采用推荐方案）

1. **沙箱首个后端**
   - 推荐：`docker`。本机已有 Docker 26.1.3 与 bwrap，容器能满足无网络、资源限制、非 root、只读根文件系统。
   - 备选：`bwrap` 本地（隔离较弱，路线图规定 local 仅开发模式）；`ssh` 远程执行（部署更复杂）。
2. **默认开关**
   - 推荐：部署默认 `enabled = false`，智能体 `sandbox` 组默认关；需要管理员启用并通过验收、再由你在智能体里打开。
   - 备选：验收通过后新智能体默认开。
3. **`sandbox_exec` 的风险等级**
   - 推荐：容器网络隔离时为 `write`（影响限定在沙箱内；标准级别不逐次审批，`strict` 才审批），部署开放网络时升为 `destructive`（每次审批，不可会话放行）；参数守卫的 `HIGH` 规则仍然强制审批。
   - 备选：恒为 `destructive`，每次都审批，更安全但交互很重。
4. **沙箱网络**
   - 推荐：只能由部署配置打开，智能体设置里没有这个选项。
   - 备选：智能体可单独打开，且打开后风险升级。
5. **技能脚本是否迁入沙箱**
   - 推荐：本变更内迁移，沙箱可用时统一走沙箱。
   - 备选：保持现状，另行安排。
6. **渐进加载方式**
   - 推荐：Hermes 式桥接三工具。Nexus 在 Run 开始时冻结工具块并校验摘要（`context_prefix_changed`），桥接方式不改工具块。
   - 备选：deer-flow 式会话内提升，需放宽冻结约束。
7. **Web 搜索首批后端**
   - 推荐：先读 octop-harness `web_search/_registry.py` 的接口，再从其后端中选两到三个，并支持自建 SearXNG（无密钥、可内网）。具体清单待读后列出再确认。
8. **沙箱工具命名**
   - 推荐：统一 `sandbox_` 前缀，避免与 `read_document`、`read_skill_file` 等已有名称混淆，也便于按名识别风险。
   - 备选：沿用 `read_file` 等通用名。
9. **阶段安排**
   - 推荐：按 `tasks.md` 的顺序分阶段实施，每个阶段独立可验收；G 组（委派、定时、视觉）在开始前补充设计并再次确认。
   - 备选：只做 A–F，G 组另立提案（按仓库规范，同一变更内追加的工作写入本变更，此项仅在你明确要求拆分时采用）。

## 验收

- **分组**：新增一个带 `group` 的工具后，目录与编辑器自动出现，无需改 `TOOL_GROUPS`；一致性测试在漏改时失败。组开关关闭时该组工具不进入工具定义，直接调用返回 `tool_authorization_denied`。
- **沙箱**：未启用、未验收或验收失败时，`sandbox` 组不可见，编辑器显示原因；验收覆盖 CPU、内存、超时、输出、网络、租户隔离、清理、崩溃残留；两个租户互相读不到对方工作区；命令超时与取消能终止进程；`/outputs` 产物可经授权下载。
- **工具行为**：越界路径被拒；同路径并发写入串行、不同路径并行；读缓存在写后失效；危险命令命中守卫；`strict` 下写与命令进入审批。
- **调度**：未声明 `concurrency` 的现有工具行为与测试结果不变；声明后按参数并行或串行。
- **渐进加载**：启用后工具块字节在 Run 内不变；`tool_call` 经过完整网关；未授权工具经桥接也调不通。
- **Web**：内网地址、重定向到内网、超大响应被拒；正文带外部内容前缀并走注入扫描。
- **Wiki**：未绑定 Wiki 库时 `wiki` 组不出现；组不在 `base` 内。
- 后端 pytest、迁移升降级、前端单元测试与构建全部通过；沙箱验收在真实 Docker 上跑通并留存报告。

### 沙箱配置与远程执行

在企业管理端完善沙箱档位、配置详情和验收入口。保留 local、bwrap、Docker，追加 SSH 与 HTTPS 托管执行接口。智能体继续通过命名档位绑定，基础设施地址和凭据由部署运维配置。

### 沙箱引擎配置界面范围

补齐参照 WeKnora 的列表与分区编辑器，实现五类命名档位新增、编辑、删除，接入已有连接验证与供应商管理。新增共享控制卷注册、修订冲突检测、引用保护和 worker 配置重载，保持全局部署许可与隔离验收门控。

## 企业管理员维护与默认本地引擎

按用户要求，企业 owner/admin 与平台管理员均可维护现有共享沙箱档位，包括配置、策略、连接、供应商和实例回收；普通成员和非成员仍拒绝访问。沿用共享资源范围、审计与修订保护。缺省开启沙箱部署开关和本地执行许可，预置 docker/local，默认选 docker；显式部署值、定制档位与删除标记优先。Docker 仍需隔离验收，Local 仍仅开发认证模式允许，智能体工具组保持原有显式开关。

## 保存无反馈排查

用户反馈新增保存无效。本地未提供运行中的服务或原始请求，尚不能确认其请求根因；已确认长表单顶部错误不可见的问题，补齐固定位置反馈及真实默认参数持久化回归。
