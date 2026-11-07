# 技能演进：以 WeKnora 技能实现为主线，叠加 Hermes 对话式创建；沙箱档位（local / docker / bwrap）；内置技能与工具对所有空间可分配

## 状态

待确认（2026-11-07，第六版，取代前五版）。主线改为复制 WeKnora 的技能实现并按本仓库架构改写；安装采用「确定性安装」方案（决定 8）。下文「待确认的决定」逐项给出推荐，确认前不编码。

## 原因

技能的基础已经实现（归档提案 `2026-11-04-skill-scripts`）：`SKILL.md` 解析、不可变版本、绑定与发布前依赖校验、内联加载、会话技能索引快照、脚本子进程运行、管理员发布。缺口：

1. 只有管理员能发布，没有上传 zip 与远程来源安装；`import_builtin` 只是服务层函数。
2. 用户不能通过对话沉淀自己的技能，也没有「只给自己用」的范围。
3. 内置技能进不了库，也不能对所有空间生效；内置工具要每个空间的管理员逐个 `enable` 才能绑定，个人空间也一样。
4. 技能脚本在宿主上以子进程运行（`runner`），不是隔离边界；每个脚本都要声明解释器、超时、风险等级。
5. 技能依赖（Python 包、Node 包）没有任何处理；资源只能是文本。
6. 沙箱只有一份全局配置，无法按智能体选择 local / docker / bwrap。
7. 没有来源与信任体系（静态提示「仅记录、不阻止」），没有使用记录。

## 参考源码

本地副本 `/project/opensource/agents/`。下表列已读到的部分；`tasks.md` 第 0 节要求实施前补读其余。

| 项目 | 文件 | 采用什么 |
| --- | --- | --- |
| **WeKnora（主线）** | `internal/types/tenant_skill.go`、`agent/skills/{manager,tenant_source,skill,skill_frontmatter,shell_staging,env_resolver}.go` | 技能目录与安装行、状态机（`installing → ready / failed / removing`）、行内保存简介与正文、资源按条目读取并缓存、提示词目录格式与 `skill://` 路径、`shell_exec(skill_name)` 统一运行、暂存、frontmatter 保守修复、名字规则 |
| | `agent/tools/{skill_file,skill_runtime_guard}.go`、`prompts.go` | 限定单个技能目录的写入工具；失败恢复提示；描述性数据声明 |
| | `application/service/tenant_skill_{install,source,verify,reaper,steer}.go`、`tenant_skill_verify.py` | 安装流水线结构、验证关（确定性部分）、远程来源解析（registry / skills.sh / GitHub / GitLab / 直链）、卡死安装的清理思路；**安装智能体与快照镜像不抄**（决定 8） |
| | `types/tenant.go`（`TenantSandboxConfig`） | 沙箱参数：超时、网络模式只允许 `bridge` / `none`、CPU / 内存 / 进程数、分配模式（会话或用户）、环境变量 |
| **Hermes（创建）** | `tools/skill_manager_tool.py`、`skill_manager_guards.py`、`skill_manager_batch.py` | 对话式创建：创建、补丁、编辑、写附属文件、删除；先读后写、固定保护、路径与名字校验、`created_by: agent` |
| | `tools/skills_hub_install.py`、`skills_guard.py` | 隔离区暂存、校验、扫描、原子换入；锁文件与审计；来源 × 扫描结论放行矩阵 |
| | `agent/skills_index_delta.py`、`tools/skill_linter.py` | 会话中变化追加差异说明，不重写系统提示；建议性 lint |
| | `cli-config.yaml.example`（`terminal.*`） | 沙箱参数：后端选择、容器 CPU / 内存 / 磁盘、显式转发环境变量 |
| openclaw | `src/gateway/server-methods/skills-retired.ts`、`src/skills/workshop/*`、`src/skills/library/*` | **废弃提案审核与 curator，改为立即生效、可撤销**，每次变更存版本、有变更流；建议性 lint（简介 ≤160 字节、正文 ≤250 行 / 12KB）；长期未用才归档且检查定时任务引用；模型只改文本、未触及的二进制资源保持原字节；`assertCurrent` 在提交点复核 |
| DeerFlow | `skills/mutations/`、`skills/projection.py`、`authz/skill_filter.py` | 修改带基础版本哈希、不符即拒绝；只读投射进沙箱；可见性加激活时二次检查 |
| Octop | `infra/skills/{install,skill_packages,skillhub_common}.py`、`infra/backend/docker_spec.py` | 统一解析为规范包再提交；压缩包 2000 条、64MB、**压缩比 100 倍**上限；沙箱参数（`allow_network`、内存、CPU、进程数、作用域 agent / user / fixed、卷、环境文件） |
| RAGFlow | `internal/entity/skill_space.go`、`skill_search.go` | 技能多时按名字 / 标签 / 简介 / 内容加权检索（后期；只读了实体定义） |
| deepseek-harness | `snapshots/session/skill-load/...` | `disable-model-invocation`、`user-invocable` |

## 主线：复制什么、改什么、不抄什么

| WeKnora 的做法 | 本仓库 |
| --- | --- |
| 租户目录 + 安装行 + 沙箱配置 + 智能体选择 | 目录 = `skills` + 不可变 `skill_versions`；「安装」收敛为版本的构建状态；沙箱配置 = 部署级**档位**（见 D）；智能体选择 = 现有资源绑定 |
| 行内存简介与正文，资源存 zip，按条目读取 | 版本保存 zip 包与行内简介正文；**顺带解决二进制资源**；条目 / 字节上限收紧到数据库可承受 |
| 提示词目录、`skill://` 路径、「描述性数据」声明 | 照搬格式；读取仍用 `load_skill` / `read_skill_file` |
| `shell_exec(skill_name=…)`，无脚本声明，解释器按路径推断 | 采用：`sandbox_exec` 增加 `skill_name`；取消 frontmatter 的 `scripts` 声明与 `run_skill_script`（决定 6） |
| 安装智能体 + 验证关 + 快照镜像 + 回收器 + 补偿清理 | **改为确定性安装**（决定 8）：清单驱动的依赖构建 + 确定性验证关 + 隔离区暂存与原子换入 + 轻量清理；不做 LLM 安装智能体、不做快照镜像链 |
| 远程来源安装（registry、skills.sh、GitHub、GitLab、直链） | **保留**，管理员专用、始终确认、出站校验、按 `import` 来源扫描 |
| 技能环境变量与凭据（管理员层 + 用户层） | 后期 |
| 无内容扫描、无私有技能、无创建、无全局内置 | 叠加：Hermes 的信任矩阵与对话式创建；私有范围；系统租户 |

## 总体模型

技能按**租户（空间）**组织；**内置技能与内置工具不属于任何普通空间，对所有空间有效，含个人空间**。「有效」指**可分配**：出现在空间的目录里，可被绑定到智能体，**不等于启用**；智能体用不用取决于是否绑定，高影响工具还受分组开关控制。空间自有的技能与工具只在本空间可用。

| 层 | 归属 | 谁能用 | 怎么产生 | 审核 |
| --- | --- | --- | --- | --- |
| 内置技能与内置工具 | 系统租户（平台保留，不可登录，不出现在任何列表） | 所有空间的智能体可分配；空间管理员可停用 | 技能由平台管理员或部署从仓库 `skills/` 导入；工具随发版登记 | 可信 |
| 空间技能库 | 租户 | 本空间的智能体 | 管理员上传或远程安装；成员共享（审核） | 成员提交与远程安装按矩阵 |
| 私有技能 | 租户内某个用户 | 仅本人的会话，自动并入索引，不需要绑定 | 对话创建或上传 | 不审核，立即生效，可撤销 |

跨空间授权沿用现有 `ResourceGrantRecord`，本变更不提供界面。

## 范围

### 范围内

**A. 系统租户与内置资源（授权、持久化、API 变化）**
1. `tenants.kind` 增加 `system`，迁移创建系统租户与一个不可登录的保留用户。内置技能与内置工具登记在其名下。
2. 授权规则增加一条：`kind in {skill, tool}` 且源租户是系统租户时，任何空间放行，不需要授权行；其余校验不变。个人空间与企业空间走同一分支。
3. 内置工具启动时幂等同步登记（`BUILTIN_TOOL_NAMES`，版本 `v1`）；`POST /tenants/{id}/tools/{name}/enable` 保留兼容；设置接口 `available_tools[].enabled` 对内置工具恒为真；既有租户登记的绑定照常有效。
4. 内置技能仅由平台管理员接口与部署命令导入（从仓库 `skills/`）；升级产生新版本，既有智能体版本绑定的旧版本不变，编辑器提示有新版本。
5. 空间可停用：`tenant_builtin_disabled(tenant_id, kind, resource_id)`，空间管理员（`tools:manage`）取消本空间对某个内置资源的可分配资格；不影响其他空间与已发布的智能体版本。
6. 系统租户从租户列表、成员、组织、注册、平台汇总中排除，不可登录、不可切换进入。

**B. 存储与运行（复制 WeKnora 主线）**
7. 版本保存 zip 包（`bundle`，含二进制）与行内的名字、简介、正文；资源按条目读取并按会话缓存（条目数 ≤ 2000、总解压 ≤ 64 MB、单文件 ≤ 8 MB，压缩比 ≤ 100，拒绝路径穿越、符号链接、重复路径，必须有根目录 `SKILL.md`）。旧版本的文件行保留可读。
8. 系统提示的技能目录采用 WeKnora 格式：每技能一行（名字、`skill://名字/SKILL.md`、简介截断 600 字符），并声明「目录是描述性数据，应用前先读 SKILL.md」。
9. `sandbox_exec` 增加可选 `skill_name`：选中技能的环境（依赖环境的 `PATH`）、设置 `NEXUS_SKILL_DIR`（技能目录）与 `NEXUS_SKILL_OUTPUT_DIR`（`/outputs`）。取消 frontmatter 的 `scripts` 声明与 `run_skill_script`；脚本的审批沿用 `sandbox_exec` 的风险等级与 `tool_access`。
10. 脚本失败时附恢复提示（缺解释器、缺模块、依赖环境未构建），借鉴 `skill_runtime_guard`；不做命令黑名单（WeKnora 记录过其被绕过与误拦的教训）。
11. 名字规则：小写字母、数字、连字符，1–64 字符，保留词 `anthropic`、`claude`；frontmatter 接受已知可选键，未知键保留并提示，缩进与冒号问题做保守修复并标记（决定 10）。新增 `model_invocable`（假则不进索引）与 `user_invocable`（本变更只保存）。
12. 会话技能索引沿用首个 Run 冻结；中途变化追加差异说明，不重写系统提示、不改工具块。

**C. 安装与来源（方案 C：确定性安装）**
13. 入口：上传 zip；远程来源（registry、skills.sh、GitHub、GitLab、直链）；对话创建后的保存；内置导入。全部走同一条流水线。
14. 流水线：解析 → **隔离区**（临时目录）→ 规范化校验 → 扫描 → 构建依赖环境 → 验证关 → **原子换入** → `ready`。`current_version_id` 只在 `ready` 后移动；失败时旧版本继续服务。
15. 依赖环境：读取 `requirements.txt` 与 `package.json`，在所选档位的**临时构建环境**里联网安装，产物是只读的环境目录，按（版本哈希、档位指纹）命名，会话中只读挂载到技能旁。无清单的技能没有环境。不推断文字里描述的依赖。
16. 验证关（确定性，参考 `tenant_skill_verify.py`）：执行用户能读全部源文件、Python 源文件可解析、清单列出的包已装；结果分 `note`（保留）与 `problem`（拒绝）；**不静态推断 `import` 能否解析**。不做 LLM 修复轮次。
17. 清理：构建在 `finally` 中清理暂存目录与临时容器；构建带心跳；周期任务把超时的 `installing` 标为 `failed`，清理残留暂存目录与带标签的临时容器；`installing` 超过阈值可被管理员停止或重试。
18. 远程来源约束：仅管理员；每次需确认；抓取前做出站地址校验（复用工具扩展提案的 `web_fetch` 校验）；跳转 ≤ 3；抓取超时 5 分钟；大小上限；记录来源 URL 与版本；包按 `import` 来源过扫描矩阵。
19. 来源与信任：`skills.source` 取 `builtin` / `admin` / `import` / `agent` / `user`（旧值 `installed` → `admin`）；版本记 `trust`、`scan_version`、`scan`。规则扫描器（网络请求、凭据读取、敏感路径写入、混淆、提示注入）输出 `safe` / `caution` / `dangerous`；放行矩阵：`builtin` 放行；`admin` 遇 `dangerous` 须显式确认并审计；`import` 遇 `caution` / `dangerous` 阻止，管理员可留理由放行；`agent` 与 `user` 进入共享流程（F）；私有技能遇 `dangerous` 拒绝保存。扫描器带版本号，升级后旧版本标为需重扫。

**D. 沙箱档位（配置、Runtime、持久化变化）**
20. 部署配置 `[sandbox]` 支持多个命名**档位**，类型为 `local`、`docker`、`bwrap`；`default_profile` 默认为 `local`；档位由运维在部署配置里定义，租户与智能体不能自行创建或修改参数（Hermes 的 `docker_extra_args` 这类可撤销加固的透传不支持）。
21. 智能体设置新增 `sandbox_profile`（档位名，缺省取 `default_profile`），只能选运维定义的档位。
22. **`local` 不是隔离边界**：只有 `allow_local = true` 且认证为开发模式时可用；否则该档位不可用并给出原因 `sandbox_local_not_allowed`，不报错退出。生产环境须显式把 `default_profile` 或智能体选择改为 `docker` / `bwrap`。
23. 各档位参数、默认值与参考来源见 `design.md` 第 7 节。公共参数：默认超时、最大超时、输出上限、空闲回收、工作区配额、网络（`none` / `bridge`）、构建期网络；docker 另有镜像、CPU、内存、进程数、只读根、tmpfs、运行用户；bwrap 另有内存（地址空间）；明确列出 bwrap 没有进程数限制与 CPU 配额、不支持后台命令。
24. 隔离验收、`sandbox` 工具组的可用性、技能脚本的可用性都**按智能体所选档位**判定；验收报告按档位保存，指纹含档位参数。
25. 技能 `execution` 属性（`sandbox` 默认 / `local`）：声明 `sandbox` 要求所选档位为 `docker` 或 `bwrap`，开发模式下 `local` 档位也视为满足；声明 `local` 仅限内置来源、所选档位为 `local` 且部署开关 `allow_local_scripts` 开启；不满足时脚本不可用并说明原因，**不回退**。其他来源声明 `local` 在保存或发布时拒绝。
26. 向后兼容：旧的扁平 `[sandbox]` 键（`backend`、`image`、`cpus`……）在没有 `profiles` 时映射为名为 `default` 的档位。

**E. 私有技能与对话式创建（Hermes + openclaw）**
27. 私有技能：`skills.owner_user_id` 非空；不登记为平台资源、不可绑定；Run 的技能索引 = 绑定的技能 ∪ 当前用户启用的私有技能；名字在「本人私有 + 本空间库 + 内置」范围内唯一，库后来发布同名技能则解析为库技能，私有同名标记已被取代。
28. 草稿：`skill_drafts`（租户、用户、名字为主键），可变；工具 `skill_manage`（`view`、`create`、`patch`、`edit`、`write_file`、`remove_file`、`delete_draft`），写入限定在**一个技能的草稿目录**（WeKnora 的作用域写入）；守卫取 Hermes：先读后写、`patch` 匹配唯一、固定子目录、名字路径校验、数量与大小上限。
29. 工具 `skill_save`：把草稿打成 zip，走与上传**同一条流水线**（扫描、构建环境、验证关），私有技能**立即生效**；每次需用户确认；`dangerous` 拒绝。
30. 可撤销（openclaw）：每次保存是一个新版本；`skill_rollback` / 接口把当前版本指回任一旧版本；删除私有技能是归档，可恢复。不设提案审核队列。
31. 建议性 lint 随 `skill_manage` 返回（简介长度、正文长度、空话、全大写强调等，永不阻止）；模型编辑文本时未触及的二进制资源保持原字节；修改既有技能带基础版本哈希，提交时当前版本已变则拒绝（`skill_base_changed`）。
32. 含脚本或依赖清单的私有技能，在所选档位可构建环境之前不能保存为可用（仍可保存为纯指令）；限额：每用户草稿 20、私有技能 50、总字节 4 MB。

**F. 共享到空间库（审核仅此一处）**
33. 私有技能「共享到空间库」＝复制为库技能；管理员直接发布；成员需 API 权限 `skills:submit`（owner 拥有，admin 基线包含，其他成员经角色授予），提交进 `skill_submissions` 由管理员审核；审核与发布沿用 `tools:manage`。
34. 提交带基础哈希，通过时哈希不符或同名已存在则置 `superseded`；待审总数 20、每用户每小时 10、每用户同时待审 5；成员只能看、撤回自己的提交，他人的提交对其返回不存在；拒绝须填理由；审核页提示「通过后本空间所有智能体可用」，内容按纯文本渲染；通过后版本记录提交人。`agent` / `user` 来源遇 `dangerous` 在提交时拒绝。

**G. 后期（不阻塞前面各期）**
35. 技能包：包是分发单位（应用到智能体展开为逐个绑定）；内置包对应仓库 `skills/` 子目录；导出为 zip。
36. 使用记录与生命周期：`active → stale → archived`，长期未用才归档且**检查定时任务引用**（openclaw），只归档不删除。
37. 技能凭据声明（WeKnora / Hermes）、`skill_search`（RAGFlow）、LLM 安装智能体（WeKnora 的完整形态）。

### 范围外

- 安装时由 LLM 推断文字里描述的依赖、快照镜像链、快照回收器（决定 8；后期可加）。
- 跨空间共享的界面与流程；模型扫描；规则自动审核；自动瘦身（openclaw `skill-diet`）；自动把任务经验沉淀为技能（GenericAgent，必须经用户确认的版本另议）。
- MCP；外部 Runtime 的技能转换；观澜技能内容本身；内置资源中技能与工具以外的种类。

## 待确认的决定

1. **内置技能与工具放系统租户**
   - 推荐：新增保留的系统租户，授权放行一处，复用资源登记与绑定。
   - 备选：每个租户复制一份并按来源哈希同步。
2. **私有技能不进智能体绑定**，Run 自动并入索引。备选：必须绑定（每次创建都要新智能体版本）。
3. **私有技能立即生效、可撤销，不设审核队列；共享到空间库才审核**（依据 openclaw 废弃审核队列）。备选：私有也需审核。
4. **沙箱档位由运维在部署配置里定义，智能体只选名字；默认档位 `default_profile = "local"`，但 `local` 在非开发模式下不可用**（决定 22）。备选：档位可由空间管理员创建（WeKnora 做法，但会让租户能选择无隔离的后端）；或默认档位仍为 `docker`。
5. **技能 `execution` 属性保留**（规则见 25）。备选：取消，运行位置完全由所选档位决定。
6. **取消 `scripts` 声明与 `run_skill_script`，统一 `sandbox_exec(skill_name)`**（WeKnora 做法）。备选：保留声明与独立脚本工具。
7. **存储改为 zip 包 + 行内简介正文**，旧文件行保留可读。备选：保持文件表，二进制资源不支持。
8. **安装采用方案 C**：确定性依赖构建 + 确定性验证关 + 隔离区暂存与原子换入 + 轻量清理，不做 LLM 安装智能体与快照镜像；文字里才有的依赖暂不支持，验证关报出。备选：A 完整复制；B 完全不做安装，依赖由运维预置镜像。
9. **远程来源安装保留**：仅管理员、每次确认、出站校验、按 `import` 过扫描矩阵。
10. **frontmatter 解析**：推荐引入 PyYAML `safe_load`（后端规范允许实际使用时加入并锁定版本；当前项目刻意避开 YAML 额外依赖，需你确认放宽），保留保守修复。备选：扩充受限读取器以覆盖多行列表与嵌套映射的子集。
11. **共享权限**：新增 `skills:submit`；私有创建不需要该权限，由智能体是否绑定 `skills` 组的创建工具决定。备选：所有活跃成员默认可共享。
12. **跨空间共享**：本变更不做界面。备选：同期提供。
13. **空间停用名单**：增加。备选：不增加。
14. **阶段**：S1 → S6 分阶段（见 `tasks.md`）；技能包、使用记录、凭据、`skill_search` 在 S6 之后按需。

## 对其他提案的影响（确认后同步修改，不在本次改动）

- 工具扩展提案 `2026-11-07-tool-expansion`：3.5 的 `[sandbox]` 配置形态扩为档位并兼容旧键；3.6 / 3.7 的验收按档位；4.5 的可用性按智能体所选档位；**4.8（`run_skill_script` 改走沙箱）被本变更第 9 条取代**。默认后端由 `docker` 改为 `local` 会改动 `tests/test_sandbox.py` 里「默认配置是禁用的 docker」的断言（沙箱仍默认 `enabled = false`）。
- 归档提案 `2026-11-04-skill-scripts` 的 `runner`、`scripts` 声明、`run_skill_script` 随第 9 条退役。

## 验收

- 内置技能与工具在企业空间和个人空间无需启用步骤即可绑定；高影响工具在分组不可用或智能体开关关闭时仍不出现；空间停用后目录不列出、发布拒绝、调用拒绝；系统租户不出现在任何列表。
- 上传 zip 与远程来源安装的技能都经过隔离区、扫描、环境构建、验证关，通过后原子换入；任一步失败时旧版本继续服务，暂存目录与临时容器被清理；卡死的安装被周期任务标为失败。
- 带二进制资源的技能往返导出导入内容一致；压缩比异常、路径穿越、符号链接的包被拒绝；远程来源的内网地址被拒绝。
- `sandbox_exec(skill_name=…)` 在所选档位下运行技能脚本，能找到 `NEXUS_SKILL_DIR`，使用技能的依赖环境；失败时有恢复提示；沙箱内不能修改技能目录，也看不到其他租户或未绑定的技能。
- 智能体选择 `local` / `docker` / `bwrap` 档位后，工具可用性与验收结果按所选档位判定；生产模式下 `local` 档位不可用且给出原因；旧的扁平 `[sandbox]` 配置继续有效。
- 在对话里让智能体创建技能，用户确认保存后立即可用（同会话经差异说明），可撤销回旧版本；其他用户与空间不可见；共享到空间库时，管理员直接发布，成员经审核。
- 既有技能、绑定、会话快照行为不变；全量测试通过，迁移可升可降。
