# 实施任务

状态：实施中（2026-11-07，决定 1–9 已确认）。已完成的任务才勾选。

## 0. 准备

- [ ] 0.1 补读沙箱参考：octop-harness `backends/docker_sandbox.py`、`bwrap_shell.py`、`local_shell.py`、`composite.py`、`probe.py`；deer-flow `sandbox/`；Hermes `terminal_tool*.py`、`process_registry*.py`；WeKnora `shell_exec*.go`、`work.go`、沙箱文件工具、`file_mutation_queue.go`；DeepSeek `shell/`、`fs/`。
- [ ] 0.2 补读 Web 与其他参考：octop-harness `web_search/_registry.py`、`web_fetch.py`、`security/ssrf.py`；Hermes `url_safety.py`、`tool_search*.py`、`schema_sanitizer.py`、`cronjob_tools.py`、`delegate_tool*.py`；deer-flow `task_tool.py`；WeKnora `wiki_*.go`。
- [x] 0.3 用户确认决定 1–9（全部采用推荐方案）。
- [ ] 0.4 确认后先更新文档：`docs/architecture.md` 2.5、2.9、2.10、2.11；`docs/roadmap.md`（新增步骤 3.27，并在第 8 步标注先行实施）；`packages/tools/docs/design.md`；`packages/sandbox` 的 `docs/` 与 `README.md`。

## 1. 工具分组与开关（阶段 A，先做，沙箱依赖它）

- [x] 1.1 `ToolDefinition` 新增 `group`、`source`、`concurrency`、`deferrable`（均带默认值）；给现有工具补 `group`，删除 `catalog.TOOL_GROUPS`。
  - `ToolDefinition` 的四个新字段不进 `repr`，避免改动 `context_prefix_changed` 的工具块摘要。分组在 `registration.builtins()` 注册处声明（`replace(definition, group=...)`），删除了 `catalog.TOOL_GROUPS`。
- [x] 1.2 `nexus_core.native.tool_groups`：分组注册表、`Availability`、`default_enabled`。
  - `nexus_core.native.tool_groups`：`ToolGroup`、`TOOL_GROUPS`、`group_enabled`；`base` 锁定。
- [x] 1.3 `NativePolicy.tool_groups_enabled` 与设置页标签；老版本缺省处理。
  - `tool_groups_enabled` 只接受可切换的组 id；设置页字段类型为 `tool_groups`（前端渲染随 1.6）。
- [x] 1.4 `preparation.py` 的门控改为通过分组注册表；现有记忆、知识库、技能脚本测试保持通过。
  - 调整：记忆、知识库、技能脚本三处沿用 `preparation.py` 的按名过滤（行为不变，原测试保持通过）；新组经 `nexus_platform.runs.tool_gates` 与网关的 `hidden_groups` 两层门控。原因：平台包不依赖 `nexus_tools`，读不到注册表里的分组。
- [x] 1.5 一致性测试：注册表、`BUILTIN_TOOL_NAMES`、分组声明三者互相检查。
  - `tests/test_tool_groups.py`：注册表与 `BUILTIN_TOOL_NAMES` 一致、分组合法、门控与网关隐藏。
- [x] 1.6 目录接口返回 `availability` 与 `reason`（接口已完成：`/agent-tools` 的 `group_info`）；智能体编辑器按组显示整组开关、逐工具勾选、风险徽标与不可用原因。
  - 前端（2026-11-11）：实际使用的编辑器是 `views/agent/NexusAgentEditorModal.vue`（不是 6800 行的移植文件）。新增 `nexusToolGroups.ts`（开关状态、只存与默认值不同的选择、不可用原因码映射，单测 5 项）；`nexusAgentForm.ts` 增加 `tool_groups_enabled`（读写 `budgets.behavior.tool_groups_enabled`，单测 1 项）；编辑器新增「工具分组」块：每组一个开关，`base` 锁定，待实现组显示阶段，部署不可用时显示原因；逐工具勾选与风险徽标原本已有。六种语言文案已加齐。**未在浏览器里验证**，也未跑 `vue-tsc` / `pnpm build`（本机内存不足）；仅对两个纯 TS 文件做了 `tsc --strict` 检查并用故意出错探针确认有效，模板编译无错。

## 2. 调度增强（阶段 C，沙箱依赖它）

- [x] 2.1 `ConcurrencyHint` 与 `execute_batch` 分类调度；未声明时行为与现在完全一致（用现有并行测试证明）。
  - `classify` 与 `execute_batch`；网关新增 `may_suspend`，可能进入审批的调用不加入并行组（挂起后从第一个待处理调用恢复，并行出去的兄弟调用会被重复执行）。
- [x] 2.2 `serial(key)` 排队：同 key 串行、不同 key 并行；审批恢复路径覆盖。
- [x] 2.3 测试：同路径并发写入不丢失；解析失败按独占处理；结果顺序不变。
  - `tests/test_tool_scheduling.py`；全量 pytest 1067 通过。

## 3. 沙箱后端（阶段 B）

- [x] 3.1 `nexus_sandbox.contracts`：`CommandExecutorPort`、`FileStorePort`、`VirtualPath`、`SandboxLease`。
  - 契约放在 `nexus_core.sandbox`（工具包只依赖 core），`nexus_sandbox.contracts` 提供 `CommandExecutorPort`、`FileStorePort` 并再导出。
- [x] 3.2 `paths`：虚拟路径映射与越界拒绝（含符号链接）；单元测试覆盖穿越样例。
  - `paths`：按真实路径拒绝符号链接越界；`tests/test_sandbox.py`。
- [x] 3.3 `backends/docker`：容器生命周期、卷、`exec`、资源限制、超时与取消杀进程组、输出上限、环境从零构造。
  - `backends/docker`、`backends/local`（开发替身）、`backends/output`；用记录型 `docker` 替身脚本测试参数与流程。**未在真实守护进程上运行**：当前开发机的用户无权访问 Docker 套接字。取消时按命令标记杀进程组的脚本只能在真实容器里验证，已列入验收的 `cancellation` 项。
- [x] 3.4 `lease`：Run 持有、空闲回收、崩溃后遗留容器回收。
  - `manager`：目录、容器名、空闲与孤儿回收（`reap`）。后台定期调用 `reap` 尚未接入 worker 循环。
- [x] 3.5 `[sandbox]` 部署配置读取与校验（`deployment.py`），配置错误不泄露细节；`configs/README.md` 与示例同步。
  - `[sandbox]` 读取与校验、`configs/nexus.example.toml`、`configs/README.md`、`.gitignore`。
- [ ] 3.8 `bwrap` 后端（追加，用户确认）：`backends/bwrap`、`backend = "bwrap"`、管理器与验收接入、`exec_async` 明确拒绝。
  - 代码与参数测试已写，未在真实 bwrap 上验证（待用户验证）；进程数限制缺失，验收的进程数探测预计不通过。
- [ ] 3.6 `acceptance` 全部探测项与迁移 `sandbox_acceptance`；worker 启动自检与 `sandbox-check` 命令；验收报告输出到文件。
  - 部分完成：验收模块 12 项探测与按指纹失效的报告已实现；`--sandbox-check` 命令已加入 worker（调整：用参数而非子命令）。调整：报告保存在 `workspace_root/acceptance.json`，不建 `sandbox_acceptance` 表——工作区里有未提交的知识库迁移，新迁移无法稳定接在链上；迁移链稳定后再改表。
- [ ] 3.7 在真实 Docker 上跑通验收并保存报告；无 Docker 的环境相关测试跳过并说明。
  - 未做：需要有 Docker 权限的环境运行 `--sandbox-check`。

## 4. 沙箱工具组（阶段 B）

- [x] 4.1 `sandbox_list_files`、`sandbox_read_file`、`sandbox_search_files`（`read`，`parallel`）。
- [x] 4.2 `sandbox_write_file`、`sandbox_edit_file`（`write`，按路径 `serial`；原子写入；写后递增全局写入计数，读缓存失效）。
  - `sandbox_write_file` / `sandbox_edit_file` 按路径串行、原子写入。读缓存失效计数（`mutation_epoch`）已在文件存储里维护，目前没有读缓存使用它。
- [x] 4.3 `sandbox_exec`（风险随网络配置；`exclusive`）；`public_result` 不含宿主路径。
  - 风险随 `[sandbox].network`；`public_result` 不含宿主路径（测试断言）。
- [x] 4.4 守卫规则：`dangerous_shell_commands.json` 的 `tools` 增加沙箱命令工具；新增路径越界与敏感位置规则及测试。
  - `dangerous_shell_commands.json` 的 shell 类规则加入 `sandbox_exec`。路径越界与敏感位置的专门规则未加：路径越界已由 `paths` 拒绝。
- [x] 4.5 `sandbox` 组 `availability`（部署启用且验收通过）与默认关闭；编辑器的沙箱分区、不可用原因展示。
  - 部分完成：`sandbox` 组 `availability`（部署启用且验收通过；`local` 需 `allow_local` 与开发认证模式）与默认关闭已完成；编辑器：沙箱档位选择与不可用原因已有（`sandboxProfile`），沙箱组的开关与不可用原因随 1.6 的「工具分组」块完成。
- [x] 4.6 `/outputs` 产物登记（新表）、下载授权检查、审计（设计见 design.md 2.6）。
  - [x] 4.6.1 `artifacts` 表、模型与迁移（空库 / 升降级）。
  - [x] 4.6.2 `HostFileStore.output_files()` 与 `nexus_platform/artifacts/service.py`：登记（复制、哈希、上限、去重、事件与审计）、列表、详情、下载、删除与授权。
  - [x] 4.6.3 worker 收尾接入登记。
  - [x] 4.6.4 REST `/artifacts` 与测试。
  - [x] 4.6.5 文档同步。
  - [x] 4.6.6 前端产物库（2026-11-11，用户要求）：接口增加名称与扩展名筛选、总数、`latest` 与 `version_count`、会话标题、`all_versions` 删除；`api/nexusArtifactAdapter.ts`（纯函数，单测 4 项）与 `api/artifacts.ts` 改调 `/artifacts`；`ArtifactLibrary.vue` 按产物 id 定位，预览先取字节再交给预览组件并忽略过期响应；路由 `artifacts` 指向该页；交互测试 5 项。`file_type` 取文件扩展名而不是 MIME，否则预览会把所有文件判成不支持。**未在浏览器里验证**，也未跑 `vue-tsc` / `pnpm build`；对适配器与 `artifacts.ts` 做了 `tsc --strict` 检查并用故意出错探针确认有效，模板编译无错。聊天页里按 `artifacts.registered` 事件展示产物卡片未做。
  - 实施说明（2026-11-11）：表 `artifacts` 与迁移 `c2d3e4f5a6b7`；`HostFileStore.output_files()`；`nexus_platform/artifacts/service.py`；`nexus_worker/artifacts.py` 接入 `native.py` 收尾；`apps/api/.../http/artifacts.py`。测试 `tests/test_artifacts.py`（9 项）、`tests/test_artifacts_api.py`（4 项）；相关 232 项后端测试通过。判断顺序上「单文件过大」先于数量与配额，以便如实报告。**未做**：前端界面、保留期自动清理、会话删除时清理副本文件（行随会话级联删除，副本留在磁盘，需要单独的清理任务）。顺带修正 `tests/test_run_transactions.py` 的表数量断言（`knowledge_base_shares` 之后一直是 102，现为 103）。
- [x] 4.7 `sandbox_exec_async`、`sandbox_job_wait`、`sandbox_job_cancel`；Run 终态回收作业；与路线图 3.24 的关系写入文档。
  - 状态放在 `/workspace/.jobs/<id>/`（`out`、`rc`、`pid`、`started`），任何 worker 都能读；作业在独立会话里运行，看门狗负责超时（rc 124），取消与结束都杀整个进程组；每会话最多 4 个；Run 结束时 `close_jobs` 取消仍在跑的作业。后台命令只能在 `/workspace` 下。没有做跨 Run 的结果回投（路线图 3.24 单独评估）。
  - 未做，与路线图 3.24 一并设计。
- [ ] 4.8 `run_skill_script` 在沙箱可用时改走沙箱后端（决定 5）；不可用时保持现有门禁；原有技能脚本测试保持通过。
  - 未做：技能脚本通过 stdin 传 JSON 参数，沙箱执行器目前不支持 stdin；`run_skill_script` 的开关（`scripts_available`）也要重新设计，改动面大，单独做。
  - 未做。
- [ ] 4.9 端到端：开启沙箱组的智能体能写文件、运行脚本、读回产物；关闭组或 `read_only` 时工具不可见；`strict` 下写与命令进入审批。
  - 部分完成：`tests/test_sandbox_tools.py` 用本地后端经真实网关走通写、读、编辑、搜索、命令、访问级别与批次调度；真实 Docker 与 worker 端到端待验收后进行。

## 5. Schema 清洗与 `tool_search`（阶段 D）

- [x] 5.1 `nexus_tools.schema.sanitize` 与测试（属性名、顶层联合、缺 `properties`、`default` 与 `$ref`、布尔 `required`、名称还原）；模型客户端接入。
  - `nexus_core.schema`（放在 core，因为 runtimes 不依赖 tools）；`openai_compatible` 与文本工具协议发送前清洗，网关对参数 `restore`；`tests/test_schema_sanitize.py`。
- [x] 5.2 `tool_search` / `tool_describe` / `tool_call` 与目录构建；阈值与目录预算；`tool_call` 经完整网关；Run 内工具块不变的测试。
  - `nexus_tools/bridge.py` 与网关集成；阈值改为 `tool_search_min_tokens`（调整：绝对 token 数，不用上下文比例，网关不知道上下文窗口）；目录写进 `tool_search` 描述；`tests/test_tool_search.py`。当前没有内置工具声明 `deferrable`，等 MCP 接入生效。
- [x] 5.3 未绑定或组开关关闭的工具经桥接调用被拒绝的测试。

## 6. Web 工具组（阶段 E）

- [x] 6.1 出站地址校验抽到 `nexus_core.net`，模型连接改用它，既有测试保持通过。
  - 调整：没有改动模型连接的校验。它按 `[model_network]` 允许私有地址，语义与「永不允许私有地址」的 `web_fetch` 相反，合并会让两边都更难读；`web_fetch` 的校验独立实现在 `web/fetch.py`，不共用 `nexus_core.net`。
- [x] 6.2 `web_fetch`：逐跳校验、大小与超时上限、正文抽取、外部内容前缀、注入扫描。
  - `web/fetch.py`：逐跳校验、固定到已校验地址并保留 SNI、手动重定向、字节上限、HTML 抽取。
- [x] 6.3 搜索后端注册表与首批后端（决定 7 确认后）；凭据引用；`web` 组 `availability`。
  - 调整：后端为 tavily、brave、searxng，密钥直接写 `[web].search_api_key`（部署文件），不走租户凭据引用；请求形状未对真实服务验证。组可用性改为 `[web].enabled`（搜索后端缺失时 `web_search` 返回 `web_search_backend_missing`，不隐藏工具）。
- [x] 6.4 测试：内网与重定向到内网被拒；超大响应截断；后端未配置时组不可见。
  - `tests/test_web_tools.py`。

## 7. Wiki 组门控（阶段 F）

- [x] 7.1 `wiki` 组与子组、风险映射、`availability`、编辑器占位。
  - `wiki` 组已在 `tool_groups` 中声明，可用性 `wiki_base_not_bound`，编辑器目录显示「待实现」；风险映射写在提案，随 K6.1 工具一起落地。
- [x] 7.2 九个工具的实现登记到知识库提案 K6.1，在其任务中引用本变更的分组与风险约定。
  - 登记到知识库提案：K6.1 的 Wiki 工具须注册到 `wiki` 组，读类 `read`，写、替换、改名 `write`，删除 `destructive`，以页面路径为 `serial` key。

## 8. 协作、定时与视觉（阶段 G，每项开始前补设计并再确认）

- [x] 8.1 `delegate_task`：补设计、确认、实现、测试（子集权限、不可递归、审批冒泡、预算扣减）。
  - `apps/worker/src/nexus_worker/subagent.py` + `builtins/collab.py`。调整：子智能体是进程内嵌套 Run，消息只在内存，不建 `parent_run_id` 的子 Run 记录；工具调用记在父 Run 上，另写 `subagent.started` / `subagent.finished` 两个事件。审批不冒泡：子智能体内需审批的操作直接被拒绝（`tool_approval_unavailable`），由父级决定。预算：token 取父级剩余的一份（至少 1000，否则 `budget_exhausted`），用掉的计入父级。`tests/test_subagent.py`。
- [x] 8.2 `cronjob`：补设计、确认、实现、测试（无人值守约束、提示扫描、配额）。
  - `nexus_platform/schedule/`（规则、服务）、`CronJobRecord` + 迁移 `f9a0b1c2d3e4`、`cronjob_list` / `cronjob_manage`、worker 的 `ScheduleBridge` 与 `schedule_tick`。调整：一个任务一个会话，每次触发往同一会话加消息，便于用会话识别无人值守；规则只支持 interval（≥15 分钟）/ daily / weekly，不支持 cron 表达式；无人值守的 Run 不提供 `ask_user` 与 `cronjob_manage`，需审批的操作被拒绝；创建上限每人 10 个活动任务；提示入库前做注入扫描；任务绑定创建时的智能体版本，版本不再是已发布版本、或用户/空间不可用时任务被挂起（`suspended`）。`tests/test_schedule.py`。**代码已在工作区完成并通过测试，但尚未提交**：迁移接在 `e8f9a0b1c2d3`（记忆文档亲和度，另一项未提交的工作）之后，先提交会让远端迁移链缺父；`tests/test_run_transactions.py` 的表数量断言也要随两边一起变成 91。待那项工作提交后一并提交。任务的 REST 接口与界面未做。
- [x] 8.3 `vision_analyze`（可选）：补设计、确认、实现。
  - `builtins/media.py`、`nexus_worker/vision.py`、`NativePolicy.vision_model_profile_version_id`；沙箱端口新增 `read_image`。调整：图片只能来自沙箱工作区，所以 `media` 组可用性要求沙箱可用（`sandbox_required`）。未对真实视觉模型验证。`tests/test_vision_tool.py`。

## 10. cron 的 REST 与界面（8.2 追加；设计见 design.md 8.2a，用户 2026-11-11 确认 C1–C6）

- [x] 10.1 服务层：`get_job`、`update_job`、`run_now`、`list_runs`、`preview`、`all` 范围与管理员暂停，审计动作，单元测试。
- [x] 10.2 REST：`/api/v1/tenants/{tenant_id}/schedules` 全部接口、错误码映射、权限与越权测试。
- [x] 10.3 前端数据层：`nexusAutomationAdapter.ts`（含单测）与 `api/automation.ts` 接 Nexus；授权、通知调用短路为待实现。
- [x] 10.4 前端页面：路由 `automations` 指向 `AutomationList.vue`；编辑器的智能体选择、触发器类型限制与待实现标记；列表的我的 / 全部切换；详情运行记录；六种语言文案；交互测试。
  - 实施说明（2026-11-11）：数据层 `api/nexusAutomationAdapter.ts`（纯函数，单测 6 项）；`api/automation.ts` 改调 `/schedules`，授权与通知返回空并标待实现；`utils/automationSchedule.ts` 增加 `interval` 类型与 `isSupportedKind`；编辑器用智能体选择器替换模型选择器、不支持的调度类型与执行控件禁用并标「待实现」、每周只能选一天；列表页管理员的「我的 / 全部成员」切换，他人任务只能暂停；详情页只读模式；路由 `automations` 指向 `AutomationList.vue`；六种语言文案；原有交互测试补上 `@/stores/auth`、`@/api/nexus-agents` 依赖并改写模型覆盖与审批超时两条，新增管理员视图 2 条。**未在浏览器里验证**，也未跑 `vue-tsc` / `pnpm build`（本机内存不足）；对适配器与相关 TS 文件做了 `tsc --strict` 检查并用故意出错探针确认有效，三个 Vue 模板编译无错。
- [x] 10.5 文档：`docs/architecture.md` 定时部分、`docs/roadmap.md` 3.27、`packages/platform` 文档、`apps/web` 说明。

## 9. 收尾

- [ ] 9.1 同步 `docs/architecture.md`、`docs/roadmap.md`、各包 `docs/design.md` 与 README，只记录当前结果与明确标注的计划。
- [ ] 9.2 后端全量 pytest、迁移升降级、前端单测与构建通过（前端构建需在内存充足的环境执行）。
- [ ] 9.3 把规格同步到 `openspec/specs/tool-expansion/` 并归档本变更。
