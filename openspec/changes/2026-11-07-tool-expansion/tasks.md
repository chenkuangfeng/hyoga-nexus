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

- [ ] 3.1 `nexus_sandbox.contracts`：`CommandExecutorPort`、`FileStorePort`、`VirtualPath`、`SandboxLease`。
- [ ] 3.2 `paths`：虚拟路径映射与越界拒绝（含符号链接）；单元测试覆盖穿越样例。
- [ ] 3.3 `backends/docker`：容器生命周期、卷、`exec`、资源限制、超时与取消杀进程组、输出上限、环境从零构造。
- [ ] 3.4 `lease`：Run 持有、空闲回收、崩溃后遗留容器回收。
- [ ] 3.5 `[sandbox]` 部署配置读取与校验（`deployment.py`），配置错误不泄露细节；`configs/README.md` 与示例同步。
- [ ] 3.6 `acceptance` 全部探测项与迁移 `sandbox_acceptance`；worker 启动自检与 `sandbox-check` 命令；验收报告输出到文件。
- [ ] 3.7 在真实 Docker 上跑通验收并保存报告；无 Docker 的环境相关测试跳过并说明。

## 4. 沙箱工具组（阶段 B）

- [ ] 4.1 `sandbox_list_files`、`sandbox_read_file`、`sandbox_search_files`（`read`，`parallel`）。
- [ ] 4.2 `sandbox_write_file`、`sandbox_edit_file`（`write`，按路径 `serial`；原子写入；写后递增全局写入计数，读缓存失效）。
- [ ] 4.3 `sandbox_exec`（风险随网络配置；`exclusive`）；`public_result` 不含宿主路径。
- [ ] 4.4 守卫规则：`dangerous_shell_commands.json` 的 `tools` 增加沙箱命令工具；新增路径越界与敏感位置规则及测试。
- [ ] 4.5 `sandbox` 组 `availability`（部署启用且验收通过）与默认关闭；编辑器的沙箱分区、不可用原因展示。
- [ ] 4.6 `/outputs` 产物登记（新表）、下载授权检查、审计。
- [ ] 4.7 `sandbox_exec_async`、`sandbox_job_wait`、`sandbox_job_cancel`；Run 终态回收作业；与路线图 3.24 的关系写入文档。
- [ ] 4.8 `run_skill_script` 在沙箱可用时改走沙箱后端（决定 5）；不可用时保持现有门禁；原有技能脚本测试保持通过。
- [ ] 4.9 端到端：开启沙箱组的智能体能写文件、运行脚本、读回产物；关闭组或 `read_only` 时工具不可见；`strict` 下写与命令进入审批。

## 5. Schema 清洗与 `tool_search`（阶段 D）

- [ ] 5.1 `nexus_tools.schema.sanitize` 与测试（属性名、顶层联合、缺 `properties`、`default` 与 `$ref`、布尔 `required`、名称还原）；模型客户端接入。
- [ ] 5.2 `tool_search` / `tool_describe` / `tool_call` 与目录构建；阈值与目录预算；`tool_call` 经完整网关；Run 内工具块不变的测试。
- [ ] 5.3 未绑定或组开关关闭的工具经桥接调用被拒绝的测试。

## 6. Web 工具组（阶段 E）

- [ ] 6.1 出站地址校验抽到 `nexus_core.net`，模型连接改用它，既有测试保持通过。
- [ ] 6.2 `web_fetch`：逐跳校验、大小与超时上限、正文抽取、外部内容前缀、注入扫描。
- [ ] 6.3 搜索后端注册表与首批后端（决定 7 确认后）；凭据引用；`web` 组 `availability`。
- [ ] 6.4 测试：内网与重定向到内网被拒；超大响应截断；后端未配置时组不可见。

## 7. Wiki 组门控（阶段 F）

- [ ] 7.1 `wiki` 组与子组、风险映射、`availability`、编辑器占位。
- [ ] 7.2 九个工具的实现登记到知识库提案 K6.1，在其任务中引用本变更的分组与风险约定。

## 8. 协作、定时与视觉（阶段 G，每项开始前补设计并再确认）

- [ ] 8.1 `delegate_task`：补设计、确认、实现、测试（子集权限、不可递归、审批冒泡、预算扣减）。
- [ ] 8.2 `cronjob`：补设计、确认、实现、测试（无人值守约束、提示扫描、配额）。
- [ ] 8.3 `vision_analyze`（可选）：补设计、确认、实现。

## 9. 收尾

- [ ] 9.1 同步 `docs/architecture.md`、`docs/roadmap.md`、各包 `docs/design.md` 与 README，只记录当前结果与明确标注的计划。
- [ ] 9.2 后端全量 pytest、迁移升降级、前端单测与构建通过（前端构建需在内存充足的环境执行）。
- [ ] 9.3 把规格同步到 `openspec/specs/tool-expansion/` 并归档本变更。
