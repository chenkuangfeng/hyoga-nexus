# 设计：技能演进

状态：待确认（第三版）。以下为推荐方案下的设计，决定变更后同步修改。

## 1. 现状与扩展点

已有（不推翻）：`skills`（租户内唯一名、`source`、`current_version_id`）、`skill_versions`（不可变，含 `content_hash`、`scan_hints`）、`skill_version_files`（文本）、`session_skill_snapshots`（会话首个 Run 冻结索引，保护提示缓存）、`platform_resources`（技能版本登记为平台资源，`active` 是生效开关）、`agent_resource_bindings`（智能体版本绑定技能版本，带 `source_tenant_id`，外键指向已登记资源）、`resource_grants`（源租户到目标租户的授权）、`nexus_platform.skills.service`（`publish`、`bound_versions`、`session_index`、`read_for_run`、`prepare_script`、`import_builtin`）、工具 `load_skill` / `read_skill_file` / `run_skill_script`。

本设计的原则：**尽量复用资源登记、绑定与授权机制**，新增的只有作用域、草稿、提交、包、系统租户这几块。

## 2. 作用域模型

```text
                  skills.tenant_id        skills.owner_user_id      登记为平台资源   进入智能体的方式
内置技能与工具    系统租户                 NULL                      是               绑定（source_tenant_id = 系统租户）
租户技能库        普通租户                 NULL                      是               绑定
私有技能          普通租户                 用户                      否               Run 按当前用户自动并入索引
```

- 唯一性：`(tenant_id, name) WHERE owner_user_id IS NULL`（库与内置）与 `(tenant_id, owner_user_id, name) WHERE owner_user_id IS NOT NULL`（私有）两个部分唯一索引，替换现有的 `uq_skills_tenant_name`。
- 私有技能**不登记为平台资源**：它不可绑定、不可授权，授权规则就是「所有者等于当前主体」，从而不会出现「别人绑定了我的私有技能」的情形。共享到库是**复制**出一个新的库技能，两者此后互不影响。
- 名字解析顺序（读取、`load_skill`）：技能库 → 内置；私有仅在「本人」范围内查找，并且创建时不能与库或内置同名（决定 7）。技能库后来发布同名技能时，该名字对所有人解析为库技能，私有同名在列表里标「已被取代」。

## 3. 系统租户与内置技能、内置工具

- 迁移：`tenants.kind` 约束扩为 `('personal', 'enterprise', 'system')`；插入固定 id 的系统租户和一个保留用户（无身份、`status` 禁用，仅作 `created_by`）。常量放在 `nexus_core`，两处引用同一 id。
- 排除：所有「列出租户 / 成员 / 组织 / 平台汇总 / 注册 / 空间切换」的查询过滤 `kind != 'system'`；登录与空间选择拒绝进入系统租户。这些查询点在 `tasks.md` 0.2 中读码列全，并用测试覆盖。
- 授权：`authorize_resource` 在查找授权行**之前**增加分支：`kind in GLOBAL_BUILTIN_KINDS`（本变更为 `{'skill', 'tool'}`）且 `source_tenant_id == SYSTEM_TENANT_ID` 时，校验资源行存在且 `active`、本空间没有停用它，不要求 `resource_grants`。其他资源种类不受影响。个人空间与企业空间走同一分支，不区分 `kind`。
- 内置工具：启动时（API 与 worker 共用的幂等同步函数）把 `BUILTIN_TOOL_NAMES` 逐个登记到系统租户（`kind='tool'`、`version_id='v1'`）；新增工具随发版自动出现，已有行不变。绑定内置工具时 `source_tenant_id` 为系统租户。
- 兼容：既有的租户登记工具与绑定照常有效；`POST /tenants/{id}/tools/{name}/enable` 保留，返回系统租户的资源并写审计，不再写租户登记；设置接口 `available_tools[].enabled` 对内置工具恒为真，`can_enable_tools` 对内置工具不再有意义（前端据此隐藏启用按钮）。
- 空间停用：`tenant_builtin_disabled(tenant_id, kind, resource_id)`，主键三列。编辑器目录、发布智能体版本时的绑定校验、`authorize_resource` 的系统租户分支三处读取它；停用不改变已发布的智能体版本，只让之后的调用被授权拒绝，并在目录中标「本空间已停用」。
- 空间自有资源：租户技能库与空间自有工具仍是 `source_tenant_id == 本租户` 的登记，`authorize_resource` 的既有分支不变；其他空间的智能体既不能绑定（外键与目录过滤），也读不到。
- 绑定：智能体编辑器列出「本租户技能 + 内置技能」「本租户工具 + 内置工具」；绑定内置技能写 `source_tenant_id = 系统租户`。`bound_versions` 现有的校验（版本的租户等于绑定的源租户、资源生效）对内置技能同样成立。
- 导入与升级：平台管理员接口 `POST /platform/skills/import-builtin` 与部署命令，读取仓库 `skills/` 逐个发布到系统租户；内容相同报告 `unchanged`；升级生成新版本。既有智能体版本绑定的旧版本不变（不可变语义）；编辑器对比绑定版本与最新内置版本，提示「有新版本」。
- 撤销：平台管理员可把某个内置版本的资源置为不生效，所有绑定它的智能体下一次 Run 即看不到它（沿用 `_live`）。

## 4. 来源、信任与扫描

```text
内容 ──► 解析与名字校验（loader）──► 规则扫描（guard，带 scanner_version）
                                         │ 结论 safe / caution / dangerous
        来源（builtin/admin/import/agent/user/私有）┤
                                         ▼
                      policy.decide(source, verdict, acknowledged) → allow | need_ack | pending_review | block
```

- `nexus_skills.guard`：纯函数 `scan(parsed, files) -> ScanResult(version, verdict, findings)`；每项发现含 `rule`、`severity`、`category`、`path`、`line`、`excerpt`（截断）。规则表短而可审，每条带测试样例。扫描只是门禁之一，运行时授权与沙箱仍然有效。
- 建议性检查（linter）单独成函数，结果只提示（Hermes）：如描述过长、正文用文字指示模型调用已有原生工具的 shell 命令等。
- `nexus_skills.policy.decide`：矩阵是一张常量表，测试逐格覆盖。
- 持久化：`skill_versions` 增加 `trust`、`scan_version`、`scan`（JSON）；`scan_hints` 保留。`skills.source` 迁移 `installed → admin`，新增 `user` / `agent` / `import`。
- 重扫：扫描器版本变化后，列表接口把低于当前版本的行标为 `rescan_needed`；重扫结果追加到版本的 `scan`，不修改内容，也不让已绑定版本自动失效。
- 私有技能保存时同步扫描：`dangerous` 拒绝，`caution` 放行并把发现展示给本人。

## 5. 私有技能与对话式创建

```text
对话 ──► skill_manage(create/patch/edit/write_file/remove_file/view) ──► skill_drafts（可变）
                                                                         │
对话 ──► skill_save(name)  ── 用户确认 ──► 扫描 ──► publish_private ──► skill_versions（不可变，owner_user_id = 当前用户）
```

- `skill_drafts`：主键 `(tenant_id, owner_user_id, name)`；`skill_md`、`files`（JSON，受大小上限）、`base_hash`（修改既有私有技能时记录）、`updated_at`。草稿不进索引，不被 `load_skill` 读取，只有 `skill_manage view` 看得到。
- `skill_manage` 的守卫（Hermes）：`patch` 要求 `old_string` 在目标内唯一；写入前必须在本 Run 内 `view` 过该草稿（先读后写）；名字与路径校验沿用 `check_files`；附属文件只允许 `refs/`、`scripts/` 等固定子目录；每用户草稿数、私有技能数、总字节有上限（默认 20 / 50 / 4 MB）。所有动作写审计，内容不入审计，只记名字与哈希。
- `skill_save`：把草稿校验（`parse_skill`、依赖工具名存在）、扫描、保存为私有版本；每次调用需用户确认。保存纯指令技能不需要沙箱；含脚本的草稿在沙箱投射可用之前拒绝保存（`skill_scripts_need_sandbox`）。
- 索引并入：`session_index` 的输入由 `bound_versions(agent_version)` 扩为「绑定 ∪ 当前主体的私有技能（`model_invocable` 为真）」，排序稳定；首个 Run 冻结。会话中创建或保存后：工具结果直接返回技能内容；同时追加一条系统说明消息「本会话可用的技能有变化：…」，说明与冻结索引相比的完整差异，**不重写系统提示**（Hermes `skills_index_delta`）。
- 读取：`read_for_run` 先按名字在绑定里找，再在当前主体的私有技能里找；后者的授权是 `owner_user_id == principal.user_id` 且租户一致。
- 数量与规模：私有技能的索引行与库技能一起受 `INDEX_LIMIT` 约束，超出时只列名字。

## 6. 共享、提交与审核

```text
私有技能 / 上传的包 / 模型提交 ──► skill_submissions(pending)
                                       │ 管理员直接发布则跳过
                                       ▼
                         管理员审核：差异 + 扫描发现 + 「通过后租户内所有智能体可用」提示
                                       │ 通过：重校验依赖 + 重扫 + 基础哈希 → publish（技能库，登记为平台资源）
                                       └ 拒绝：理由必填
```

- `skill_submissions`：`id`、`tenant_id`、`origin`(user|agent|import)、`name`、`skill_md`、`files`（JSON）、`base_hash`（新建为空）、`scan`、`state`、`submitted_by`、`run_id?`、`reviewed_by`、`review_reason`、时间戳。
- 并发保护：通过时在事务内读取库技能当前 `content_hash`；与 `base_hash` 不同则置 `superseded`。新建时同名库技能已存在同样 `superseded`。
- 成员接口（租户下，需 `skills:submit`）：`POST /skill-submissions`（带 `base_hash`；或 `from_private=<name>` 直接以私有技能为内容）、`GET /skill-submissions?mine=true`、`GET /skill-submissions/{id}`（成员只读自己的，他人的返回 404）、`POST /skill-submissions/{id}/withdraw`。
- 管理员接口（`tools:manage`）：列表、详情（差异、扫描）、通过、拒绝。管理员「共享」自己的私有技能时服务端直接走 `publish`，来源记 `admin`。
- 限额：待审总数 20、每用户每小时 10、每用户同时待审 5（读配置）。
- 提交时同步扫描并把发现返回给提交人；`dangerous` 直接拒绝，不入库。
- 通过后版本 `trust` 记提交来源；`skill_submissions` 保留提交人，版本详情接口返回提交人，模型可见内容中不出现。
- 审计：提交、撤回、通过、拒绝、放行发现、重扫。

## 7. 导入、导出与技能包

### 7.1 统一流水线（Octop）

```text
zip / 目录 ──► resolve → ResolvedSkillPackage(slug, files[(path, bytes)], source) ──► normalize ──► 目标
目标（协议）：PrivateDraftTarget（写草稿） | LibrarySubmissionTarget（产生提交 / 管理员直接发布） | SystemTarget（平台管理员发布内置）
```

- `normalize`：条目数 ≤ 2000、总解压字节 ≤ 64 MB、单文件上限、压缩比 ≤ 100、拒绝路径穿越与绝对路径、反斜杠、NUL、符号链接、重复路径；必须有根目录 `SKILL.md` 且为 UTF-8；多个顶层文件夹各含 `SKILL.md` 视为多个技能。
- 目标是协议，`导入` 逻辑只写一遍；以后接入新来源只需新增 `resolve`。
- 浏览器端可先解压并展示文件清单作为体验优化，服务端仍完整校验。

### 7.2 frontmatter 兼容

- 已知键：`name`、`description`、`tools`、`scripts`、`model_invocable`、`user_invocable`，以及第三方常见的 `version`、`license`、`metadata`、`allowed-tools`（映射为 `tools` 的提示，不自动赋权）。
- 未知键保留在版本元数据 `extra` 中，导入时给出提示，不阻止。
- 保守修复（WeKnora）：首次解析失败时尝试两种修复——缩进到 `name:` 下的键提升为顶层、标量里的未加引号冒号补引号；成功则标记 `frontmatter_repaired`。
- 解析方式见决定 4。

### 7.3 二进制资源

- `skill_version_files` 增加 `content_bytes`（可空二进制）与 `is_binary`；文本仍用 `content`。每技能总量上限默认 8 MB，文件数上限不变。
- `read_skill_file` 对二进制只返回路径、大小、类型，不把字节放进上下文；下载与沙箱投射时按字节写出。内容哈希覆盖字节。

### 7.4 技能包

- `skill_packs(id, tenant_id, owner_user_id?, name, description)` 与 `skill_pack_items(pack_id, skill_name, version)`。系统租户下的包对应仓库 `skills/` 的子目录（`general`、`guanlan`），由内置导入同时创建。
- 「应用到智能体」展开为逐个技能的绑定（固定版本），生成新的智能体版本；包本身不进入运行时。
- 导出：包导出为含多个技能文件夹的 zip，附一个清单（包名、成员、版本）；导入清单存在时还原为包。
- 私有包只有所有者可见与导出；库包按读权限。

## 8. 投射到沙箱与脚本执行

```text
会话沙箱目录：<workspace_root>/<tenant>/<session>/{workspace, outputs, skills}
                                                           │ 只读挂载为 /skills
skills/<name>@<hash12>/{SKILL.md, refs/, scripts/}   ← 本会话可用（绑定 + 本人私有）且启用的技能，按 content_hash 命名
```

- 投射在会话第一次沙箱使用前完成，文件由数据库内容原子写出；总文件数 ≤ 1000、总字节 ≤ 32 MB（WeKnora 上限）；超限则该会话技能脚本不可用而内联加载不受影响。
- 虚拟根新增只读的 `/skills`：`paths.VIRTUAL_ROOTS` 增加，`HostFileStore` 对其写入一律拒绝；docker 后端加 `-v <dir>:/skills:ro`，bwrap 后端加 `--ro-bind`（bwrap 每条命令一个隔离环境，需要在真实环境验证）。容器是长期的，所以投射目录在容器创建时挂载，技能集合在会话内不变；会话中新保存的私有技能的脚本在下一个会话生效。
- 其他会话、其他租户与未授权的技能不在该目录中。
- `run_skill_script`：命令为 `cd /workspace && <解释器> /skills/<name>@<hash>/scripts/<file>`，参数经 stdin；解释器白名单沿用 `guard`；输出转义沿用 `runner`。依赖由镜像提供，不在运行时安装；失败时附 WeKnora 式的恢复提示。
- 沙箱不可用：生产环境不提供脚本工具；开发模式的门禁只对 `builtin` 来源开放。
- 开放网络的沙箱执行任何技能脚本，每次调用强制审批（风险等级已是 `destructive`）。
- 私有技能的脚本：投射可用后允许保存与运行，运行同样只在沙箱。

## 9. 使用记录

- `skill_usage(tenant_id, owner_user_id?, skill_name)`；`load_skill` 成功时递增（同一 Run 同一技能只计一次），与加载同事务，失败不影响加载。
- 生命周期：worker 空闲时每日评估，超过阈值（默认 90 天）未用且未 `pinned` 的 `active` 置 `stale`；`stale` 再过阈值由所有者或管理员决定归档。不自动归档，不自动删除。
- 归档的技能不进新会话的索引，绑定显示「已归档」；历史版本与已有会话快照不变，可恢复。

## 10. 兼容与迁移

- 迁移：`tenants.kind` 约束；系统租户与保留用户；`tenant_builtin_disabled`；内置工具同步到系统租户；`skills` 增加 `owner_user_id` 并替换唯一约束；`skill_versions` 增加 `trust`、`scan_version`、`scan`、`extra`；`skill_version_files` 增加二进制列；新表 `skill_drafts`、`skill_submissions`、`skill_packs`、`skill_pack_items`、`skill_usage`；`installed → admin`。降级删除新表与新列、还原约束（有私有技能或系统租户数据时，降级前先给出明确提示）。
- 既有智能体版本、会话快照、绑定不变；`model_invocable` 默认真，因此行为不变。
- 公开 API 只增不改；旧发布接口在 `admin` 来源下行为一致，只多返回扫描结论。

## 11. 风险

- **同名工具的两个来源并存**：既有租户登记的工具绑定与新的系统租户绑定都存在时，Run 准备阶段按名字去重会判定 `tool_configuration_invalid`。编辑器只提供一个来源（优先系统租户），迁移不改写既有绑定，并增加测试覆盖「同名双来源」。
- **全局生效削弱了「空间管理员启用」这道闸**：靠分组可用性、智能体开关（默认关）、`tool_access` 与审批把关，并提供空间停用名单；高影响工具（沙箱、Web、委派、定时）的默认关闭状态要有测试固定。

- **系统租户是新的特殊对象**：所有枚举租户的查询都要排除它，漏一处就会在界面里冒出来。用一致性测试遍历租户相关查询，并在 0.2 中列全。
- 私有技能是用户或模型写的任意文本，进入模型上下文：它只影响本人会话，但可能含提示注入。保存时扫描，索引里只放名字和简介，正文在加载时带「技能内容，不授予权限」前缀（沿用现有 `read_for_run`）。
- 规则扫描的覆盖有限：`import` 与共享来源一律从严；用已知恶意样例与大量正常技能验证误报率。
- 会话中差异说明依赖对话消息注入点，需读码确认不会破坏提示缓存（0.2）。
- bwrap 后端的 `--ro-bind /skills` 需要真实验证；bwrap 无进程数限制，脚本类能力的放行由验收结果决定。
- 投射按会话复制，技能很多时磁盘占用上升；上限已设，必要时改为按哈希共享后硬链接。
