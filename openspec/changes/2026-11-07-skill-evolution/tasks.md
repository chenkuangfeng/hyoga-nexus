# 实施任务

状态：已确认（第六版，2026-11-07，决定 1–14 全部采用推荐方案），实施中：S1 后端与编辑器前端已完成；S2 已完成 2.1–2.9（档位、投射、`exec_skill`、`run_skill_script` 退役、`execution` 策略）及编辑器里的档位选择；2.10（真实 Docker 与 bwrap 上验证）未做，需要你在有环境时验证。已完成的任务才勾选。

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

- [x] 1.1 迁移：`tenants.kind` 加 `system`；`tenant_builtin_disabled`；`skills.source` 迁移 `installed → admin`；`skill_versions` 增加 `trust`、`scan_version`、`scan`、`extra`、`model_invocable`、`user_invocable`、`execution`；升降级测试。
  - 迁移 `c1d2e3f4a5b6` 与 `d2e3f4a5b6c7`（`tests/test_system_space_migration.py`）。调整：系统租户与保留用户不在迁移里创建，而在 API 与 worker 启动时幂等创建（`nexus_platform.system.ensure_system_resources`），这样测试用 `create_all` 建库与迁移建库行为一致。同时把 `CronJobRecord` 纳入 `persistence/models/__init__.py`，表数断言不再依赖导入顺序（92 张）。
- [x] 1.2 排除系统租户：按 0.2 的清单逐处过滤；一致性测试断言系统租户不出现、不可登录、不可切换进入。
  - 读码结论：系统租户没有成员、编码和企业微信信息，因此空间列表、登录与切换（都经成员关系）天然不包含它；只有平台管理员的全部空间列表和汇总计数需要显式排除（`kind != 'system'`）。测试：`tests/test_system_space.py::test_the_system_space_is_never_listed`。
- [x] 1.3 `authorize_resource` 增加系统租户分支（`GLOBAL_BUILTIN_KINDS = {'skill', 'tool'}`）；测试：企业与个人空间的智能体无需启用即可绑定并调用，普通空间不能向系统租户发布或撤销，其他资源种类不受影响。
  - 调整：除显式来源为系统租户外，未指明来源或来源为本空间且本空间没有自己登记时回落到系统租户；智能体草稿绑定在本空间没有登记时把来源归一为系统租户（外键要求），本空间自己的登记优先。`read_for_run` 与 `prepare_script` 改用版本所属租户作授权来源。个人空间的用例用「改 `kind`」模拟（授权路径不看空间类型）。
- [x] 1.4 内置工具同步：启动时幂等登记；`tools/{name}/enable` 兼容；`available_tools[].enabled` 恒为真；同名双来源测试；高影响工具组默认不出现的测试（个人与企业空间各一组）。
  - 已做：API 与 worker 启动同步；`enable` 保留（只解除本空间的停用并返回系统租户登记）；设置接口 `available_tools` 与编辑器 `/agent-tools` 增加 `builtin`、`disabled`，`enabled_in_tenant` 对内置恒为真（语义为可分配）；本空间自有登记优先。高影响工具组的默认关闭由既有分组门控保证（未改动），未新增专门用例。
- [x] 1.5 空间停用：管理接口（`tools:manage`）；编辑器目录、发布校验、调用授权三处读取；测试。
  - `GET/PUT/DELETE /tenants/{id}/builtin-disabled`；已停用的资源在目录里仍列出并标 `disabled`（管理员可恢复），发布智能体版本与调用被拒绝，其他空间不受影响。
- [x] 1.6 平台管理员接口与部署命令：从仓库 `skills/` 导入内置技能到系统租户；`unchanged` 报告；升级后编辑器提示有新版本。
  - `POST /api/v1/platform/skills/import-builtin`（平台管理员）与 `python -m nexus_api.cli import-builtin-skills`；目录取 `[skills].builtin_dir`。目录接口 `list_skills` 在每个空间列出内置技能（`scope = 'builtin'`）。「有新版本」提示依赖编辑器前端，未做。
- [x] 1.7 规则扫描器 `nexus_skills.guard` 与 `ScanResult`（规则表带样例，扫描器版本号，建议性 lint 独立）；`policy.decide` 放行矩阵逐格测试；`publish` 接入；`acknowledge_findings`；审计；需重扫标记。
  - `guard/scan.py`（19 条规则，每条有样例）、`policy.py`（逐格测试）、`publish` 接入、错误带发现列表、`rescan` 与接口、版本列表返回 `verdict`、`findings`、`rescan_needed`。调整：建议性 lint 随创建流程（S4）实现，本期未做；`agent` / `user` 来源在 S5 的审核流程之前只会得到 `skill_review_required` 或 `skill_scan_refused`。
- [ ] 1.8 名字规则与保留词；frontmatter 已知键、未知键保留与提示、保守修复；`model_invocable` / `user_invocable` 解析；索引与 `read_for_run` 的过滤；编辑器可绑定内置技能与工具并标「内置」；前端隐藏对内置工具的启用按钮。
  - 后端已完成：PyYAML 6.0.3（`packages/skills`，锁文件已更新）、`safe_load` 加重复键拒绝、两种保守修复、`extra` 与 `notes`、名字规则、`model_invocable` / `user_invocable` / `execution` 解析与存储、索引与读取过滤、非内置来源声明 `local` 被拒绝。前端（`apps/web` 智能体编辑器，已做）：内置工具标「内置」；本空间停用 / 恢复（管理员，带确认说明停用只影响本空间、已发布版本不变）；`enable` 按钮只在非内置且未启用的旧情形出现；新增「技能」分区，列出内置技能与本空间技能，选择技能时一并绑定读取技能所需的工具、缺工具时点名提示，已停用的内置技能不能新增绑定，绑定旧版本时显示「有新版本」并可更新；技能列表接口增加 `version_id`、`tools`、`execution`、`model_invocable`。**未做**：用浏览器实际点过这些界面，以及完整 `vue-tsc --build` 与 `pnpm build`（见下）。
- [x] 1.9 测试：既有技能、绑定、会话快照、脚本相关测试保持通过。
  - 全量 `pytest`：1285 通过、1 跳过。新增 `tests/test_system_space.py`、`test_system_space_migration.py`、`test_skills_scan.py`、`test_skills_release.py`，改写 `test_skills_builtin_import.py`，并更新 `test_skills_rules.py`、`test_agent_editor.py`、`test_run_transactions.py`。

## 2. S2 沙箱档位与技能运行

- [x] 2.1 `[sandbox]` 档位配置：解析与校验（未知类型、缺 `image`、越界值，错误只含键名）；旧扁平键映射为 `default` 档位；`configs/nexus.example.toml` 与 `configs/README.md` 同步。
  - `nexus_sandbox/settings.py`：`SandboxConfig` / `SandboxSettings`、`load_config`、`load_settings(profile=)`。不适用于某类型的键报错（例如 bwrap 的 `pids`）；没有任何沙箱配置时只有隐式的 `local` 档位。调整：默认超时与输出上限仍是智能体设置（`sandbox_exec_timeout_seconds`、`sandbox_output_limit`），不放进档位。
- [x] 2.2 档位参数落到各后端：`docker`（`install_network`、`tmpfs_mb`、`env_passthrough` 名单与敏感名拒绝）、`bwrap`（`install_network`、`memory_mb`）、`local`；`extra_args` 明确不支持并有测试。
  - `tmpfs_mb`、`env_passthrough` 已落到 docker / bwrap / local；`install_network` 已解析校验，要到 S3 的依赖构建才使用。docker 容器名在非 `default` 档位带档位名，容器带 `nexus.sandbox.profile` 标签，回收只处理本档位。
- [x] 2.3 智能体设置 `sandbox_profile`；已发布版本固定；缺省取 `default_profile`；`SandboxManager` 按档位构造。
  - `NativePolicy.sandbox_profile`（名字校验）、worker 按档位取管理器与会话、编辑器 `/agent-tools` 返回 `sandbox_profiles`（名字、类型、是否默认、是否可用、原因）。前端已做：工具分区里的「沙箱档位」选择（默认档位 + 运维定义的档位，标出类型与是否可用，不可用时说明原因并提示沙箱工具与技能脚本不会出现）。
- [x] 2.4 `local` 档位门禁：非开发模式或 `allow_local` 关闭时可用性为 `sandbox_local_not_allowed`；启动日志与管理接口提示；默认 `default_profile = "local"` 对应的测试说明（沙箱仍默认关闭）。
  - 管理接口的提示以 `/agent-tools` 的 `sandbox_profiles[].reason` 提供；启动日志的提示未单独加。
- [x] 2.5 可用性与验收按档位：`tool_gates` 按智能体档位计算；`acceptance-<档位>.json`；指纹含档位参数；`--sandbox-check --profile`；迁移 `sandbox_acceptance`（若采用表存储）带档位列。
  - 报告是文件（`acceptance.json` 给旧的 `default` 档位，`acceptance-<档位>.json` 给其他档位），没有表，因此无需迁移。`--sandbox-check` 默认检查全部 docker 与 bwrap 档位。同时修正 `sandbox_exec` 的风险等级与网关超时：改为按全部档位计算（任一 docker / bwrap 档位开放网络即 `destructive`），否则档位化后会误读顶层键而降级风险。
- [x] 2.6 技能投射：`docker` / `bwrap` 只读挂载 `/skills`，`local` 宿主路径；`NEXUS_SKILL_DIR`、`NEXUS_SKILL_OUTPUT_DIR`；文件数与字节上限；其他会话 / 租户 / 未绑定技能不可见。
  - `nexus_sandbox/skills.py`：内容哈希命名、暂存后原子改名、同哈希不覆盖、路径与大小校验（1000 个文件、32 MB）、支持二进制；`SandboxSession.project_skill` / `skill_environment`；docker `-v …:/skills:ro`、bwrap `--ro-bind`。只投射本次 Run 要运行的那个技能，不预投射；已存在的旧容器没有该挂载，空闲回收后重建即带上。
- [x] 2.7 执行器端口新增可选 `env` 与 `stdin`（docker `exec -i`，bwrap 与 local 写标准输入，默认仍 `DEVNULL`）；`sandbox_exec` 新增可选 `stdin`（≤ 65536 字节）。
  - 三个执行器与会话端口已支持，限制在会话层校验（字节数、变量名与值）；`sandbox_exec` 工具已暴露 `stdin`（≤ 65536 字节，超出由参数模式拒绝）。`sandbox_exec_async` 不带 `stdin`（后台命令没有可写的输入端）。
- [x] 2.7a `exec_skill`：纯逻辑 `nexus_skills/exec.py`（脚本路径规范化、解释器选择、环境变量与 `PATH` 构造、argv 组装）；工具定义放 `nexus_tools/builtins/skills.py`（`skills` 组）；`RunStore.exec_skill`（取内容、授权、哈希校验、审计、恢复提示）；可用性按所选档位沙箱可用；`skill_timeout_seconds` / `skill_timeout_max_seconds`；`load_skill` 的 `${NEXUS_SKILL_DIR}` 替换。
  - 已做：`exec.py`、工具与 `RunStore.exec_skill`（参数经 `shlex` 引用，不经 shell 解释）、可用性（智能体 `skill_scripts` 开关加所选档位可用）、worker 在 `sandbox` 组关闭但绑定了 `exec_skill` 时仍创建会话、技能超时、审计记录脚本路径与哈希、恢复提示（缺模块指向管理员而不是 `pip install`）。`load_skill` 与 `read_skill_file` 把 `${NEXUS_SKILL_DIR}` 替换为技能在沙箱里的真实目录（先投射，使路径真实存在；没有沙箱或投射失败时原样返回，读取技能不会因沙箱而失败）。**未做**：`PATH` 前置依赖环境（要等 S3 的依赖构建）。审批方面，`exec_skill` 在 `strict` 下与其他写类工具一样可以「本会话允许」（提案 2026-11-06-tool-call-hardening E 的会话授权，`destructive` 不可记住），多脚本技能不需要为此另做机制。
- [x] 2.7b 退役 `run_skill_script`、`scripts` 声明与 `nexus_skills.runner`：注册表、分组、`BUILTIN_TOOL_NAMES`、网关与测试同步；`allow_local_scripts` 迁移；已发布版本中既有绑定的运行时忽略与事件；发布校验提示改绑 `exec_skill`。
  - `RETIRED_TOOL_NAMES = {'run_skill_script'}`：保存的设置与已发布版本里的旧名字被接受，准备 Run 时忽略（未记事件）。`nexus_skills.runner`、`skill_scripts_allowed` / `skill_scripts_gate`、`[skills].allow_local_scripts` 已删除，开关移到 `[sandbox].allow_local_scripts`。`scripts` 声明仍可解析（旧技能不报错），但不再驱动任何行为。删除的旧测试：`test_skill_runner`、`test_skill_script_run`、`test_skill_config_gate`、`test_skill_approval_flow`，由 `test_exec_skill`、`test_skill_exec` 覆盖。**发布校验提示改绑未做**。
- [x] 2.8 `execution` 属性与 `resolve_execution`：解析与校验、保存或发布时拒绝非内置的 `local`、运行时按策略、不回退、编辑器与详情展示声明值与有效位置；表驱动测试（声明 × 档位 × 来源 × 开关 × 开发模式）。
  - `nexus_skills/policy.py::resolve_execution` 表驱动测试 12 格；运行时由 `RunStore.exec_skill` 查策略，不满足返回 `refused` 并写审计，集成测试覆盖「要宿主的内置技能：开关关闭被拒、打开后运行」。版本列表与技能列表返回 `execution`；编辑器在技能旁标「需在宿主运行」，技能列表接口带 `sandbox_profile` 参数时，为带脚本的技能返回 `run:{ok,reason}`（与 `exec_skill` 同一套判定），编辑器随档位选择在每个技能下显示「可在所选档位运行脚本」或不能运行的原因；独立详情页未做。
- [x] 2.9 测试：`exec_skill` 拒绝越界路径、不存在的脚本与白名单外的解释器，argv 不经 shell（含空格与元字符的参数原样到达），`stdin` 到达脚本，审计记录脚本哈希，多个脚本依次运行并通过 `/workspace` 交接；沙箱内无法修改技能目录；看不到其他租户技能；开放网络强制审批；三种档位下的参数断言（docker 参数列表、bwrap 参数列表）。
- [ ] 2.10 在真实 Docker 与 bwrap 上验证挂载与执行（环境相关测试无环境时跳过并说明）。

## 3. S3 存储与安装流水线（方案 C）

- [x] 3.1 迁移：`skill_versions` 增加 `bundle`、`bundle_sha256`、`build_state`（既有行 `ready`）、`build_error`、`build_heartbeat_at`、`env_ref`；`installing` 的部分唯一索引；既有版本 zip 的生成策略（惰性或批量）。
  - `skill_versions` 增加 `bundle`、`bundle_sha256`、`build_state`、`build_error`、`build_log`、`build_heartbeat_at`、`env_ref` 与 `installing` 部分唯一索引（迁移 `e3f4a5b6c7d8`，往返测试）；既有版本不批量生成 zip，导出时由文件行惰性重建；新发布的版本都写入规范 zip。状态机与心跳的使用见 3.4、3.7。
- [ ] 3.2 （已完成：二进制文件只存于 zip，运行时与文本文件一起投射进沙箱，脚本解析只看文本文件，内容哈希覆盖二进制；**未做**：按条目读取与会话内缓存，`read_skill_file` 对二进制返回元信息。）`SkillFileSource`：zip 按条目读取与会话内缓存；回退到文件行；`read_skill_file` 对二进制只返回元信息。
- [x] 3.3 规范化与校验：条目、总字节、单文件、压缩比、路径穿越、符号链接、重复路径、根目录 `SKILL.md`；恶意样例测试（穿越、炸弹、符号链接、重复路径）。
  - `nexus_skills.bundle`：先查条目表再按上限读取，拒绝穿越、符号链接/设备文件、重复路径、加密、条目过多、压缩比异常、超限；根目录或单一外层目录下的 `SKILL.md`；丢弃 `__MACOSX`、`.DS_Store` 与点文件；`pack` 输出规范 zip（排序、固定时间与权限，同内容同字节）。13 项测试。
- [x] 3.4 隔离区与原子换入：暂存目录、规范化、扫描、构建、验证、`rename` 换入、同事务移动 `current_version_id`；失败路径逐点测试（每一步失败旧版本仍服务、暂存清理）。
  - 带依赖清单的版本以 `installing` 入库（指针与资源登记不动），worker `skill_install_tick` 认领（心跳置位，一行只有一个 worker 能赢）→ 暂存目录构建 → 清单包核对 → `rename` 换入环境根 → 同一事务 `ready`、移动指针、登记资源、写审计；每一步失败都标 `failed` 并清理暂存，旧版本继续服务；构建中途被停止则放弃（`cancelled`）。测试：成功、构建失败、清单包缺失、构建抛异常、并发安装冲突、停止、认领互斥。无依赖清单的版本仍同步发布。
- [x] 3.5 环境构建器：docker 临时容器（标签、联网、可写暂存）、bwrap、local；超时、输出与目录大小上限；档位指纹命名；无对应环境时脚本不可用并提示。
  - `nexus_sandbox.build`：docker 临时容器（标签、`install_network`、非 root、只读根）、bwrap 联网 jail、local 子进程；时间、日志、目录大小上限；环境名含内容哈希与环境指纹；运行时 docker/bwrap 只读挂载环境根、`exec_skill` 加 `PATH` 前缀与 `NODE_PATH`，缺环境返回 `skill_env_missing` 并提示。**真实验证只做了 local**（真实 venv + 本地 wheel，含改名后可用，以及经 `exec_skill` 的端到端）；docker 与 bwrap 只有命令行单元测试，待在有环境的机器上验证。
- [ ] 3.6 （已完成：`nexus_skills.verify` 的 `.py`/`.sh`/`.bash`/`.js` 语法检查、解释器缺失只给 `note`、`requirements.txt` 格式校验与 `missing_distributions`，并已接入发布与上传；清单包核对已在安装流水线里完成（构建结束时 `pip list` 的结果与 `requirements.txt` 比对）；`package.json` 的包不核对；`.js` 的 `node --check` 在无 node 的主机上只给 `note`。**仍未做**：在构建环境内做「文件可读」检查。）验证关 `nexus_skills.verify`：可读；`.py` 用 `ast` 解析，`.sh` 用 `sh -n`，`.js` 用 `node --check`（解释器不存在时只给 `note`）；清单包已装；`note` 与 `problem` 分档；不推断 `import`。
- [x] 3.7 状态机与清理：`installing → ready | failed`、`reinstall` 复用已存 zip、停止；心跳；周期任务清理超时 `installing`、残留暂存目录与带标签容器、过期环境目录。
  - `installing → ready | failed`；`reinstall` 复用已存 zip（也用于补建另一档位的环境）；`stop-install`；心跳；`reap` 每约 5 分钟：失去心跳超 10 分钟的构建标 `failed`（`build_interrupted`）、清理不属于任何安装中版本的暂存目录、清理无 `ready` 版本引用且超过 7 天的环境目录。**未做**：清理带 `nexus.sandbox.build` 标签且无对应行的 docker 容器（构建超时路径已 `docker rm -f`，崩溃遗留靠 `--rm`）。
- [x] 3.8 上传入口：管理员上传 zip 接口（大小限制）；构建状态与日志查询；前端上传、状态轮询、失败原因展示。
  - `POST /tenants/{id}/skills/upload`（原始 zip 请求体，流式限长 32 MB，管理员，走同一发布检查与发布策略，可带 `sandbox_profile` 指定构建档位）；`GET .../versions/{n}/install` 查状态与日志尾部；`reinstall`、`stop-install`。前端：智能体编辑器技能分区里（管理员）「安装技能」对话框，上传 zip 或远程来源（必须勾选确认）；扫描需确认时展示发现并要求明确确认后才可「仍要安装」；有依赖的技能每 3 秒轮询构建状态，可停止与重试；失败原因按分组给出多语言说明（6 种语言）。**前端未在浏览器里验证**，只有纯逻辑的单元测试与模板编译检查。
- [x] 3.9 远程来源：五类来源解析与归一；出站校验抽到 `nexus_core` 并复用；跳转、超时、字节上限；GitHub 子目录裁剪；仅管理员与始终确认；来源 URL 与摘要记录；更新检查；测试覆盖内网地址、重定向到内网、超大响应、非法输入。
  - `nexus_core.egress`（出站校验与逐跳下载，`web_fetch` 改为复用，原 45 项测试不变）；`nexus_skills.source` 五类来源解析；`bundle.subtree` 从仓库压缩包裁出目录（条目计数在裁剪后进行）；`nexus_platform.skills.remote`：`install-remote`（管理员、必须 `confirm`、权限检查先于任何联网）与 `check-update`（按内容哈希比较，不自动更新）；来源（类型、URL、引用、压缩包摘要）记在版本的 `extra.origin`，未新增列。测试覆盖内网地址、元数据地址、重定向到内网、重定向过多、超大响应、非法输入。**未联网验证** ClawHub 下载地址与 GitHub / GitLab 实际压缩包格式；前端入口随 3.8 的前端一起做。
- [x] 3.10 导出：单个技能 zip 下载（权限：库按读权限，内置所有人，私有仅所有者）。
  - `GET /tenants/{id}/skills/{name}/bundle?version=`：本空间技能或内置技能，空间成员可导出；私有技能的所有者限制随 S4 加入。

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
