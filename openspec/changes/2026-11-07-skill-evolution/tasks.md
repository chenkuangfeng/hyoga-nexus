# 实施任务

状态：待确认（第三版，2026-11-07）。已完成的任务才勾选。

## 0. 准备

- [ ] 0.1 补读 Hermes：`skill_manager_tool.py` 各动作与 `skill_manager_guards.py`、`skills_guard.py` 规则表与放行逻辑、`skills_ast_audit.py`、`skills_index_delta.py`、`skill_usage.py`；Octop：`skill_packages.py`、`skill_package_store.py`、`skill_transfer.py`、`routers/skill_packages.py`；DeerFlow：`skills/mutations/service.py`、`projection.py`；WeKnora：`shell_staging.go`、`skill_frontmatter.go`。
- [ ] 0.2 读码确认：
  - 所有枚举租户的查询点（列表、成员、组织、平台汇总、注册、空间切换、登录），列出需要排除 `system` 的位置；
  - `users` 表对保留用户的约束（身份、状态、非空字段）；
  - Run 的主体与租户字段（`principal_id`、`tenant_id`）在 `read_for_run`、`session_index` 调用处是否可得；
  - 会话中追加说明消息的注入点，确认不破坏提示缓存与冻结的工具块；
  - 智能体绑定里「逐个关闭技能」的字段位置；
  - 内置工具的调用期授权路径（网关如何带 `source_tenant_id` 调用 `authorize_resource`）、编辑器的工具目录与 `available_tools`、`enable_builtin` 的全部调用方、`runs/settings.py` 对租户登记工具的读取点；
  - `paths.VIRTUAL_ROOTS` 与两个沙箱后端的挂载点；
  - 审批机制可用的风险等级与「每次需确认」的表达方式；
  - `.codex/rules/backend.md` 的依赖条款（决定 4）。
- [ ] 0.3 确认后先更新文档：`docs/architecture.md` 2.6、`docs/roadmap.md` 7.1、`packages/skills/docs/design.md` 与 README、`skills/general/README.md`。

## 1. S1 系统租户、内置技能与来源信任

- [ ] 1.1 迁移：`tenants.kind` 约束加 `system`；系统租户与保留用户；`skills.source` 迁移 `installed → admin`；`skill_versions` 增加 `trust`、`scan_version`、`scan`、`extra`；升降级测试。
- [ ] 1.2 排除系统租户：按 0.2 的清单逐处过滤；一致性测试遍历这些查询，断言系统租户不出现、不可登录、不可切换进入。
- [ ] 1.3 `authorize_resource` 增加系统租户技能分支；测试：任意租户的智能体可绑定并读取，普通租户不能向系统租户发布或撤销，其他资源种类不受影响。
- [ ] 1.3a 内置工具同步：启动时幂等把 `BUILTIN_TOOL_NAMES` 登记到系统租户；`GLOBAL_BUILTIN_KINDS = {'skill', 'tool'}`；授权分支对 `tool` 同样放行；测试：企业空间与个人空间的智能体无需启用即可绑定并调用；新增工具名随同步出现。
- [ ] 1.3b 兼容：`tools/{name}/enable` 保留并改返回系统租户资源；`available_tools[].enabled` 对内置工具恒为真；既有租户登记的绑定照常有效；同名双来源的测试。
- [ ] 1.3c 空间停用：迁移 `tenant_builtin_disabled`；管理接口（`tools:manage`）；编辑器目录、发布校验、调用授权三处读取；测试：停用后目录不列出、发布拒绝、调用拒绝，其他空间不受影响。
- [ ] 1.3d 门控不退化：测试固定「高影响工具组（沙箱、Web、委派、定时）在分组不可用或智能体开关关闭时仍不出现」；个人空间与企业空间各一组用例。
- [ ] 1.3e 前端：设置与编辑器按系统租户来源展示内置工具与技能（标「内置」），隐藏对内置工具的启用按钮，展示「本空间已停用」。
- [ ] 1.4 `nexus_skills.guard` 规则扫描器与 `ScanResult`；规则表带测试样例；扫描器版本号；建议性 linter。
- [ ] 1.5 `nexus_skills.policy.decide` 与放行矩阵；逐格测试。
- [ ] 1.6 名字规则与保留词；frontmatter `model_invocable` / `user_invocable` 解析与校验；索引与 `read_for_run` 的过滤。
- [ ] 1.7 `publish` 接入扫描与矩阵；`acknowledge_findings`；审计；被阻止时稳定错误码与发现列表。
- [ ] 1.8 平台管理员接口与部署命令：内置导入（发布到系统租户）；列表返回 `source` / `trust` / 扫描结论 / `rescan_needed`；重扫。
- [ ] 1.9 编辑器可绑定内置技能；「有新版本」提示；智能体逐个关闭技能（产生新智能体版本）。
- [ ] 1.10 测试：既有技能、绑定、会话快照、脚本相关测试保持通过。

## 2. S2 私有技能与对话式创建（先支持纯指令技能）

- [ ] 2.1 迁移：`skills.owner_user_id`，部分唯一索引替换 `uq_skills_tenant_name`；`skill_drafts`。
- [ ] 2.2 私有技能服务：创建草稿、补丁、覆盖、写附属文件、删除附属文件、保存、删除；先读后写；数量与大小上限；名字撤重与「已被取代」标记。
- [ ] 2.3 工具 `skill_manage`、`skill_save`（`skills` 组）；工具说明含写技能规范；`BUILTIN_TOOL_NAMES`、分组一致性测试同步；`skill_save` 与删除每次需用户确认。
- [ ] 2.4 `session_index` 并入本人私有技能；`read_for_run` 读取私有技能；授权测试：他人、他租户不可读。
- [ ] 2.5 会话中的差异说明消息；测试：不改系统提示、不改工具块、提示缓存前缀不变。
- [ ] 2.6 保存时扫描：`dangerous` 拒绝；含脚本的草稿拒绝保存（`skill_scripts_need_sandbox`）。
- [ ] 2.7 前端：「我的技能」页（列表、查看、启停、删除、扫描发现）；对话中的保存确认展示。
- [ ] 2.8 测试：对话创建到保存到加载的端到端；会话中途创建后同会话可用；其他用户不可见；限额。

## 3. S3 共享到技能库与审核

- [ ] 3.1 迁移：`skill_submissions`。
- [ ] 3.2 权限 `skills:submit`：权限目录、admin 基线、角色授予界面、五种语言文案；测试 owner / admin / 授予角色的成员 / 未授予成员。
- [ ] 3.3 提交服务：来源 `user` / `agent` / `import`，基础哈希，限额，扫描，`superseded` 判定；管理员共享直接 `publish`。
- [ ] 3.4 成员接口：提交（含 `from_private`）、查看自己的、撤回；他人的返回 404；提交时同步扫描并返回发现。
- [ ] 3.5 管理员审核接口：列表、详情（差异与发现）、通过、拒绝（理由必填）；通过时重校验依赖与重扫，再走 `publish`；审计。
- [ ] 3.6 前端：成员的「我的提交」页；管理员审核页（文本渲染、差异、提示通过后租户内所有智能体可用）；私有技能的「共享到技能库」按钮。
- [ ] 3.7 测试：成员提交不改已发布版本；基础哈希变化被拒；`agent` / `user` + `dangerous` 拒绝；`user` 的 `safe` 仍进人工审核；限额；通过后版本可追溯提交人。

## 4. S4 上传下载与技能包

- [ ] 4.1 迁移：`skill_version_files` 二进制列；`skill_packs`、`skill_pack_items`。
- [ ] 4.2 统一导入流水线：`resolve` → `ResolvedSkillPackage` → `normalize` → 目标协议；三个目标实现。
- [ ] 4.3 压缩包检查：条目数、总字节、单文件、压缩比、路径穿越、符号链接、重复路径；恶意样例测试（穿越、炸弹、符号链接）。
- [ ] 4.4 frontmatter 兼容：已知可选键、未知键保留与提示、保守修复；按决定 4 引入解析；第三方样例测试。
- [ ] 4.5 二进制资源：存储、哈希、`read_skill_file` 只返回元信息、下载与往返一致。
- [ ] 4.6 导出：单技能与技能包 zip；权限（私有仅所有者、库按读权限、内置所有人）。
- [ ] 4.7 技能包：创建与编辑、应用到智能体（展开为逐个绑定）、导入清单还原、内置包随内置导入创建。
- [ ] 4.8 前端：上传、下载、技能包管理、导入预览。
- [ ] 4.9 测试：往返、越权、超限、内置包启用。

## 5. S5 沙箱投射与脚本（工具扩展 4.8 完成后开始）

- [ ] 5.1 投射器：按会话、按内容哈希原子写出，文件数与字节上限；失败降级为仅内联。
- [ ] 5.2 虚拟根 `/skills`（只读）：`paths`、`HostFileStore` 拒绝写入；docker `:ro` 挂载；bwrap `--ro-bind`。
- [ ] 5.3 `run_skill_script` 改用投射路径；失败恢复提示；原有脚本测试保持通过。
- [ ] 5.4 脚本工具的可用性：沙箱不可用时生产不提供，开发门禁只对 `builtin` 来源开放；私有技能的脚本在此后允许保存。
- [ ] 5.5 测试：沙箱内无法修改 `/skills`；看不到其他租户与未授权技能；开放网络强制审批。
- [ ] 5.6 在真实 Docker 与 bwrap 上验证挂载与执行（环境相关测试无环境时跳过并说明）。

## 6. S6 使用记录与生命周期

- [ ] 6.1 迁移：`skill_usage`。
- [ ] 6.2 `load_skill` 计数；worker 空闲评估 `stale`；归档、恢复、`pinned` 接口。
- [ ] 6.3 索引排除已归档技能；绑定显示状态。

## 7. 收尾

- [ ] 7.1 同步 `docs/architecture.md`、`docs/roadmap.md`、`packages/skills` 与平台文档、`skills/general/README.md`，只记录当前结果与明确标注的计划。
- [ ] 7.2 后端全量 pytest、迁移升降级、前端单测与构建通过。
- [ ] 7.3 规格同步到 `openspec/specs/skill-evolution/` 并归档本变更。
