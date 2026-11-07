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
- [ ] 1.6 目录接口返回 `availability` 与 `reason`（接口已完成：`/agent-tools` 的 `group_info`）；智能体编辑器按组显示整组开关、逐工具勾选、风险徽标与不可用原因。

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
- [ ] 4.5 `sandbox` 组 `availability`（部署启用且验收通过）与默认关闭；编辑器的沙箱分区、不可用原因展示。
  - 部分完成：`sandbox` 组 `availability`（部署启用且验收通过；`local` 需 `allow_local` 与开发认证模式）与默认关闭已完成；编辑器的沙箱分区待前端。
- [ ] 4.6 `/outputs` 产物登记（新表）、下载授权检查、审计。
  - 未做。
- [ ] 4.7 `sandbox_exec_async`、`sandbox_job_wait`、`sandbox_job_cancel`；Run 终态回收作业；与路线图 3.24 的关系写入文档。
  - 未做，与路线图 3.24 一并设计。
- [ ] 4.8 `run_skill_script` 在沙箱可用时改走沙箱后端（决定 5）；不可用时保持现有门禁；原有技能脚本测试保持通过。
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

- [ ] 8.1 `delegate_task`：补设计、确认、实现、测试（子集权限、不可递归、审批冒泡、预算扣减）。
- [ ] 8.2 `cronjob`：补设计、确认、实现、测试（无人值守约束、提示扫描、配额）。
- [ ] 8.3 `vision_analyze`（可选）：补设计、确认、实现。

## 9. 收尾

- [ ] 9.1 同步 `docs/architecture.md`、`docs/roadmap.md`、各包 `docs/design.md` 与 README，只记录当前结果与明确标注的计划。
- [ ] 9.2 后端全量 pytest、迁移升降级、前端单测与构建通过（前端构建需在内存充足的环境执行）。
- [ ] 9.3 把规格同步到 `openspec/specs/tool-expansion/` 并归档本变更。
