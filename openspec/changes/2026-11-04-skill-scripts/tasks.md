# 任务：技能加载与脚本执行

> 状态：已确认，实施中。第 7 节（脚本执行）与 1.3 受阻，见下方“阻塞”；其余已实施并通过测试。

## 1. 确认与前置

- [x] 1.1 用户确认 proposal.md 第 6 节与第 7 节的各项（未回复的按推荐值）。
- [x] 1.2 核实 `ResourceBindingRecord` 可用于 `kind='skill'`。结果：绑定外键指向 `platform_resources`，发布时登记版本行即可满足；`runtime_capability_unavailable` 检查原先拒绝所有非 `tool` 绑定，已改为同时放行 `skill`。
- [x] 1.3 决定（用户选 b）：不经过执行端口，脚本由 `nexus_skills.runner` 直接用子进程运行。原核实结果：`packages/sandbox` 全部为占位模块，没有 `CommandExecutorPort` 与 `local` 后端。结果：`packages/sandbox` 全部为占位模块，没有 `CommandExecutorPort`，也没有 `local` 后端。脚本执行无法按提案经该端口运行，需要用户决定（见下方“阻塞”）。原文：核实 `CommandExecutorPort` 的 `local` 后端接口，确认能设置工作目录、环境变量白名单、超时与输出上限；不满足则在本变更内补充端口参数，并记录。
- [ ] 1.4 部分完成：认证模式与 `[skills].allow_local_scripts` 可在配置层读取（`skill_scripts_gate`）。API 绑定地址是进程参数而非配置，无法在进程内核实，需要用户决定检查位置。

## 2. 技能定义与解析（`packages/skills/loader`）

- [x] 2.1 `SKILL.md` frontmatter 解析：`name`、`description`、`scripts`、`tools`；正文作为 Level 2。
- [x] 2.2 名称校验（单段，`[\p{L}\p{N}_-]+`）、长度上限（名称 64、简介 1024）、保留词。
- [x] 2.3 简介截断到 1024 字符，按词边界截断。
- [x] 2.4 资源路径规范化，越界路径拒绝。
- [x] 2.5 测试：合法与非法 frontmatter、名称与长度、保留词、越界路径、截断。

## 3. 不可变版本与持久化

- [x] 3.1 `skills`、`skill_versions`、`skill_version_files` 模型与 Alembic 迁移（需确认后执行）。
- [x] 3.2 版本生成：内容哈希稳定，发布生成新版本，已发布版本不可修改。
- [x] 3.3 单文件与总大小上限。
- [x] 3.4 内置技能导入：`import_builtin(db, principal, tenant, root)` 以 `builtin` 来源发布目录下的技能；已存在且内容相同的报告为 `unchanged`；同名的已安装技能拒绝替换（`skill_source_conflict`）。未提供命令行入口，需要管理员身份的调用方。
- [x] 3.5 测试：哈希稳定、不可修改、迁移往返（SQLite）。

## 4. 智能体配置与绑定

- [x] 4.1 偏差：配置放在智能体 Native 行为策略 `NativePolicy.skill_scripts`（缺省 `true`，布尔校验），而不是新的顶层字段。它随智能体版本的行为配置一起进入内容哈希，并出现在设置页。
- [x] 4.2 绑定展开（`bound_versions`，复用 `kind='skill'`，只返回仍有效的版本）。：智能体版本 → 技能版本集合（`kind='skill'`）。
- [x] 4.3 发布校验：绑定技能的依赖工具须已由智能体绑定；缺失则拒绝并说明原因。
- [x] 4.4 测试：配置变更生成新版本；缺失依赖拒绝发布并给出原因。

## 5. 门禁与工具注册

- [x] 5.1 配置项 `[skills] allow_local_scripts`，默认 `false`。
- [~] 5.2 门禁函数 `skill_scripts_gate` 已实现，覆盖配置、认证模式、执行后端三项；API 绑定地址待 1.4 决定。：配置开启 + 认证模式 `development` + API 绑定 `127.0.0.1` + 执行后端 `local`。
- [x] 5.3 `load_skill`、`read_skill_file` 注册：仅在智能体绑定了技能时出现；未绑定时返回"不可用"，不泄露技能是否存在。
- [x] 5.4 `run_skill_script` 注册：工具仅在门禁与智能体设置同时有效时出现在 Run 的工具列表中（`preparation.py`）；调用时再次检查门禁。：仅在门禁与智能体配置同时有效时出现。
- [~] 5.5 门禁测试已完成；界面“当前环境不可用”提示未实现。：三个门禁条件各自缺失时工具均不出现；`enabled=false` 时不出现；界面状态显示"当前环境不可用"。

## 6. 内联加载（渐进披露）

- [x] 6.1 系统提示索引：已绑定技能的名称与简介，每个会话冻结一次（与记忆快照相同的做法）。
- [x] 6.2 `load_skill(name)` 返回正文，作为工具结果进入上下文。
- [x] 6.3 `read_skill_file(name, path)` 只读取该技能版本内的文件。
- [x] 6.4 发出 `skill.loaded` 事件（仅正文加载；资源读取只写审计）。
- [x] 6.5 测试：未绑定拒绝；越界拒绝；索引冻结后刷新前不变。

## 7. 脚本执行（`packages/skills/runner`）

- [x] 7.1 脚本声明校验：解释器在白名单内；脚本位于 `scripts/`；参数 Schema 合法。
- [x] 7.2 运行前复制不可变版本到临时副本，校验内容哈希；哈希不一致则拒绝运行。
- [x] 7.3 工作目录限定在副本；环境变量白名单，不注入凭据。
- [x] 7.4 超时（默认 60 秒，上限 300 秒）终止进程组；标准输出与标准错误各限 64 KB。
- [x] 7.5 审批：每次调用写入审批请求，包含脚本哈希、参数摘要与配置哈希；拒绝则不运行。
- [x] 7.6 配置哈希变化后挂起的审批失效。
- [x] 7.7 审计：记录为一次工具调用，含技能版本、脚本名、脚本哈希、参数摘要、退出码、耗时、超时与截断标记。
- [x] 7.8 发出 `skill.script.started`、`skill.script.completed` 事件。
- [x] 7.9 测试：超时、输出截断、环境变量白名单、哈希不一致、审批拒绝、审批失效、单次运行调用次数上限（10）。

## 8. 发布与静态提示

- [x] 8.1 发布时检查解释器白名单、脚本存在性、哈希可计算。
- [x] 8.2 静态提示扫描（可疑网络请求、凭据读取、写入目标）：结果记录在发布记录中，仅作提示，不阻止发布。
- [x] 8.3 测试：非白名单解释器拒绝发布；扫描结果被记录但不阻止。

## 阻塞

- 无（脚本执行按用户决定 (b) 实施）。风险说明：`nexus_skills.runner` 不是隔离边界，脚本以服务进程用户身份运行；仅在开发门禁下可用。
- **HTTP 接口**：已实现 `POST/GET /api/v1/tenants/{tenant_id}/skills` 与版本元数据接口（`apps/api/src/nexus_api/http/skills.py`）。
- **发布权限**：发布沿用现有 `tools:manage` 权限，没有新增 `skills:manage`。

## 9. 示例与文档

- [x] 9.1 两个示例技能：`skills/general/weekly-report`（纯内联）与 `skills/general/text-stats`（内联 + 资源 + 脚本 `count`）。内容为占位示例，发布与运行由 `tests/test_skill_examples.py` 验证；正式内容仍需用户确认。
- [x] 9.2 端到端测试已覆盖（`tests/test_skill_script_run.py`）：门禁开启时运行并产生事件；门禁关闭或智能体设置关闭时工具不出现；参数错误拒绝。使用示例技能的验证待 9.1。
- [x] 9.3 更新 `packages/skills/README.md`（模块当前结果）；`docs/architecture.md` 2.6 节未改动，待 7.1 完成后统一更新。
- [ ] 9.4 更新路线图 7.1 的对应子项（仅勾选已完成部分；草稿审核与 MCP 保持未完成）。

## 10. 验证与归档

- [ ] 10.1 运行相关测试与全量后端测试；`tests/test_native_engine_golden.py` 基线保持一致。
- [ ] 10.2 提交并推送到 `origin/main`，只包含本变更相关文件。
- [ ] 10.3 全部已确认项完成且验证通过后，归档到 `openspec/changes/archive/`。
