# 实施任务

状态：待确认（第六版，2026-11-07）。已完成的任务才勾选。

## 0. 准备

- [ ] 0.1 补读 WeKnora：`tenant_skill_install.go` 的 `installParsedSkill` / `runInstall` 全流程、`tenant_skill_source.go` 的解析与抓取、`tenant_skill_bundle.go`、`tenant_skill_files.go`、`skill_runtime_guard.go`、`env_resolver.go`；Hermes：`skill_manager_tool.py` 各动作与 `skill_manager_guards.py`、`skills_guard.py` 规则表、`skills_index_delta.py`；openclaw：`workshop/library.ts`、`skill-versions.ts`、`skill-lint.ts`、`review-undo.ts`；DeerFlow：`mutations/service.py`；Octop：`skill_packages.py`。
- [ ] 0.2 读码确认：
  - 所有枚举租户的查询点（列表、成员、组织、平台汇总、注册、空间切换、登录），列出需要排除 `system` 的位置；
  - `users` 表对保留用户的约束；
  - Run 的主体与租户字段在 `read_for_run`、`session_index` 调用处是否可得；
  - 会话中追加说明消息的注入点，确认不破坏提示缓存与冻结的工具块；
  - 智能体绑定里「逐个关闭技能」的字段位置；
  - 内置工具的调用期授权路径（网关如何带 `source_tenant_id` 调用 `authorize_resource`）、编辑器的工具目录与 `available_tools`、`enable_builtin` 的全部调用方、`runs/settings.py` 对租户登记工具的读取点；
  - `run_skill_script` 的全部引用（注册表、分组、网关、编辑器、测试）；
  - `tool_gates.deployment_gate_facts` 与 `SandboxManager` 的全部调用点（档位化需要改的位置）；
  - 审批机制可用的风险等级与「每次需确认」的表达方式；
  - `.codex/rules/backend.md` 依赖条款与 PyYAML 的锁定方式（决定 10）。
- [ ] 0.3 确认后先更新文档：`docs/architecture.md` 2.6 与 2.9、`docs/roadmap.md` 7.1、`packages/skills/docs/design.md` 与 README、`packages/sandbox/docs/design.md` 与 README、`configs/nexus.example.toml` 与 `configs/README.md`、`skills/general/README.md`。
- [ ] 0.4 与工具扩展提案对齐：确认后在其 `tasks.md` 标注 3.5 / 3.6 / 3.7 / 4.5 的档位化、4.8 被本变更取代，并更新其中「默认后端」相关测试说明。

## 1. S1 系统租户、内置资源与来源信任

- [ ] 1.1 迁移：`tenants.kind` 加 `system`；系统租户与保留用户；`tenant_builtin_disabled`；`skills.source` 迁移 `installed → admin`；`skill_versions` 增加 `trust`、`scan_version`、`scan`、`extra`；升降级测试。
- [ ] 1.2 排除系统租户：按 0.2 的清单逐处过滤；一致性测试断言系统租户不出现、不可登录、不可切换进入。
- [ ] 1.3 `authorize_resource` 增加系统租户分支（`GLOBAL_BUILTIN_KINDS = {'skill', 'tool'}`）；测试：企业与个人空间的智能体无需启用即可绑定并调用，普通空间不能向系统租户发布或撤销，其他资源种类不受影响。
- [ ] 1.4 内置工具同步：启动时幂等登记；`tools/{name}/enable` 兼容；`available_tools[].enabled` 恒为真；同名双来源测试；高影响工具组默认不出现的测试（个人与企业空间各一组）。
- [ ] 1.5 空间停用：管理接口（`tools:manage`）；编辑器目录、发布校验、调用授权三处读取；测试。
- [ ] 1.6 平台管理员接口与部署命令：从仓库 `skills/` 导入内置技能到系统租户；`unchanged` 报告；升级后编辑器提示有新版本。
- [ ] 1.7 规则扫描器 `nexus_skills.guard` 与 `ScanResult`（规则表带样例，扫描器版本号，建议性 lint 独立）；`policy.decide` 放行矩阵逐格测试；`publish` 接入；`acknowledge_findings`；审计；需重扫标记。
- [ ] 1.8 名字规则与保留词；frontmatter 已知键、未知键保留与提示、保守修复；`model_invocable` / `user_invocable` 解析；索引与 `read_for_run` 的过滤；编辑器可绑定内置技能与工具并标「内置」；前端隐藏对内置工具的启用按钮。
- [ ] 1.9 测试：既有技能、绑定、会话快照、脚本相关测试保持通过。

## 2. S2 沙箱档位与技能运行

- [ ] 2.1 `[sandbox]` 档位配置：解析与校验（未知类型、缺 `image`、越界值，错误只含键名）；旧扁平键映射为 `default` 档位；`configs/nexus.example.toml` 与 `configs/README.md` 同步。
- [ ] 2.2 档位参数落到各后端：`docker`（`install_network`、`tmpfs_mb`、`env_passthrough` 名单与敏感名拒绝）、`bwrap`（`install_network`、`memory_mb`）、`local`；`extra_args` 明确不支持并有测试。
- [ ] 2.3 智能体设置 `sandbox_profile`；已发布版本固定；缺省取 `default_profile`；`SandboxManager` 按档位构造。
- [ ] 2.4 `local` 档位门禁：非开发模式或 `allow_local` 关闭时可用性为 `sandbox_local_not_allowed`；启动日志与管理接口提示；默认 `default_profile = "local"` 对应的测试说明（沙箱仍默认关闭）。
- [ ] 2.5 可用性与验收按档位：`tool_gates` 按智能体档位计算；`acceptance-<档位>.json`；指纹含档位参数；`--sandbox-check --profile`；迁移 `sandbox_acceptance`（若采用表存储）带档位列。
- [ ] 2.6 技能投射：`docker` / `bwrap` 只读挂载 `/skills`，`local` 宿主路径；`NEXUS_SKILL_DIR`、`NEXUS_SKILL_OUTPUT_DIR`；文件数与字节上限；其他会话 / 租户 / 未绑定技能不可见。
- [ ] 2.7 `sandbox_exec` 增加 `skill_name`：可用性检查、环境变量、`PATH` 前置、恢复提示；退役 `run_skill_script`、`scripts` 声明与 `nexus_skills.runner`；`allow_local_scripts` 迁移；已发布版本中既有绑定的运行时忽略与事件。
- [ ] 2.8 `execution` 属性与 `resolve_execution`：解析与校验、保存或发布时拒绝非内置的 `local`、运行时按策略、不回退、编辑器与详情展示声明值与有效位置；表驱动测试（声明 × 档位 × 来源 × 开关 × 开发模式）。
- [ ] 2.9 测试：沙箱内无法修改技能目录；看不到其他租户技能；开放网络强制审批；三种档位下的参数断言（docker 参数列表、bwrap 参数列表）。
- [ ] 2.10 在真实 Docker 与 bwrap 上验证挂载与执行（环境相关测试无环境时跳过并说明）。

## 3. S3 存储与安装流水线（方案 C）

- [ ] 3.1 迁移：`skill_versions` 增加 `bundle`、`bundle_sha256`、`build_state`（既有行 `ready`）、`build_error`、`build_heartbeat_at`、`env_ref`；`installing` 的部分唯一索引；既有版本 zip 的生成策略（惰性或批量）。
- [ ] 3.2 `SkillFileSource`：zip 按条目读取与会话内缓存；回退到文件行；`read_skill_file` 对二进制只返回元信息。
- [ ] 3.3 规范化与校验：条目、总字节、单文件、压缩比、路径穿越、符号链接、重复路径、根目录 `SKILL.md`；恶意样例测试（穿越、炸弹、符号链接、重复路径）。
- [ ] 3.4 隔离区与原子换入：暂存目录、规范化、扫描、构建、验证、`rename` 换入、同事务移动 `current_version_id`；失败路径逐点测试（每一步失败旧版本仍服务、暂存清理）。
- [ ] 3.5 环境构建器：docker 临时容器（标签、联网、可写暂存）、bwrap、local；超时、输出与目录大小上限；档位指纹命名；无对应环境时脚本不可用并提示。
- [ ] 3.6 验证关 `nexus_skills.verify`：可读、`ast` 可解析、清单包已装；`note` 与 `problem` 分档；不推断 `import`。
- [ ] 3.7 状态机与清理：`installing → ready | failed`、`reinstall` 复用已存 zip、停止；心跳；周期任务清理超时 `installing`、残留暂存目录与带标签容器、过期环境目录。
- [ ] 3.8 上传入口：管理员上传 zip 接口（大小限制）；构建状态与日志查询；前端上传、状态轮询、失败原因展示。
- [ ] 3.9 远程来源：五类来源解析与归一；出站校验抽到 `nexus_core` 并复用；跳转、超时、字节上限；GitHub 子目录裁剪；仅管理员与始终确认；来源 URL 与摘要记录；更新检查；测试覆盖内网地址、重定向到内网、超大响应、非法输入。
- [ ] 3.10 导出：单个技能 zip 下载（权限：库按读权限，内置所有人，私有仅所有者）。

## 4. S4 私有技能与对话式创建

- [ ] 4.1 迁移：`skills.owner_user_id` 与部分唯一索引；`skill_drafts`。
- [ ] 4.2 草稿服务：创建、补丁、覆盖、写附属文件、删除附属文件、删除草稿；先读后写；数量与大小上限；名字撤重与「已被取代」标记。
- [ ] 4.3 工具 `skill_manage`、`skill_save`、`skill_rollback`（`skills` 组）；注册、分组一致性、`BUILTIN_TOOL_NAMES` 同步；`skill_save` 与删除每次需用户确认；工具说明含写技能规范。
- [ ] 4.4 保存走第 3 节流水线；`dangerous` 拒绝；含脚本或依赖清单需所选档位可构建；基础哈希冲突 `skill_base_changed`。
- [ ] 4.5 `session_index` 并入本人私有技能；`read_for_run` 读取私有技能；授权测试（他人、他租户不可读）。
- [ ] 4.6 会话中差异说明消息；测试：不改系统提示、不改工具块、提示缓存前缀不变。
- [ ] 4.7 建议性 lint 随工具结果返回；未触及的二进制资源保持原字节。
- [ ] 4.8 撤销与归档：回退当前版本、归档、恢复、版本列表。
- [ ] 4.9 前端：「我的技能」页（列表、查看、启停、回退、删除、扫描发现）；对话中保存确认的展示。
- [ ] 4.10 测试：对话创建 → 保存 → 加载的端到端；会话中途创建后同会话可用；其他用户与空间不可见；限额。

## 5. S5 共享到空间库

- [ ] 5.1 迁移：`skill_submissions`。
- [ ] 5.2 权限 `skills:submit`：权限目录、admin 基线、角色授予界面、五种语言文案；测试 owner / admin / 授予角色的成员 / 未授予成员。
- [ ] 5.3 提交服务与成员接口（提交、查看自己的、撤回，他人的返回 404）；限额；基础哈希与 `superseded`。
- [ ] 5.4 管理员审核接口（列表、详情含差异与扫描、通过、拒绝需理由）；通过时重扫并走第 3 节流水线；管理员共享直接发布；审计。
- [ ] 5.5 前端：成员的「我的提交」页；管理员审核页（纯文本渲染、差异、提示通过后空间内所有智能体可用）；私有技能的「共享到空间库」按钮。
- [ ] 5.6 测试：成员提交不改已发布版本；`agent` / `user` + `dangerous` 提交时拒绝；`user` 的 `safe` 仍进审核；限额；通过后版本可追溯提交人。

## 6. S6 之后（按需，各自开始前补设计并再确认）

- [ ] 6.1 技能包（分发单位、内置包、导出）。
- [ ] 6.2 使用记录与生命周期（长期未用才归档，检查 `cronjob` 引用）。
- [ ] 6.3 技能凭据声明与两层取值。
- [ ] 6.4 `skill_search`。
- [ ] 6.5 LLM 安装智能体（输出依赖清单，接在第 3 节流水线之前）。
- [ ] 6.6 额外卷、远程 docker 主机与 TLS、`allocation = user`。
- [ ] 6.7 审核辅助数据：确定性包分析器（资源引用图、内容摘要），审核页展示。
- [ ] 6.8 上传前浏览器端解压并预览文件清单（服务端校验不变）。

## 7. 收尾

- [ ] 7.1 同步 `docs/architecture.md`、`docs/roadmap.md`、`packages/skills`、`packages/sandbox` 与平台文档、`skills/general/README.md`、`configs/*`，只记录当前结果与明确标注的计划。
- [ ] 7.2 后端全量 pytest、迁移升降级、前端单测与构建通过。
- [ ] 7.3 规格同步到 `openspec/specs/skill-evolution/` 并归档本变更。
