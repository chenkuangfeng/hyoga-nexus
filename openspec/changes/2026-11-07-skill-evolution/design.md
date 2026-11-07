# 设计：技能演进（第六版）

状态：待确认。以下为推荐方案下的设计，决定变更后同步修改。

## 1. 现状与扩展点

已有（不推翻）：`skills`（租户内唯一名、`source`、`current_version_id`）、`skill_versions`（不可变，含 `content_hash`、`scan_hints`）、`skill_version_files`（文本）、`session_skill_snapshots`、`platform_resources`（技能版本登记为平台资源，`active` 是生效开关）、`agent_resource_bindings`（带 `source_tenant_id`，外键指向已登记资源）、`resource_grants`、`nexus_platform.skills.service`、工具 `load_skill` / `read_skill_file` / `run_skill_script`；沙箱包 `nexus_sandbox`（`docker` / `bwrap` / `local` 三个执行器、`SandboxManager`、验收、`[sandbox]` 部署配置）。

原则：复制 WeKnora 的运行语义，数据与授权复用本仓库已有机制，只新增作用域、草稿、提交、构建状态、系统租户与沙箱档位。

## 2. 作用域

```text
                 skills.tenant_id   skills.owner_user_id   登记为平台资源   进入智能体的方式
内置技能与工具   系统租户            NULL                   是               绑定（source_tenant_id = 系统租户）
空间技能库       普通租户            NULL                   是               绑定
私有技能         普通租户            用户                   否               Run 按当前用户并入索引
```

- 唯一性：`(tenant_id, name) WHERE owner_user_id IS NULL` 与 `(tenant_id, owner_user_id, name) WHERE owner_user_id IS NOT NULL` 两个部分唯一索引，替换 `uq_skills_tenant_name`。
- 私有技能不登记为平台资源：不可绑定、不可授权，授权规则是「所有者等于当前主体」。共享到库是**复制**，两者此后互不影响。
- 名字解析：库 → 内置；私有只在本人范围内查找，创建时不能与库或内置同名；库后来发布同名则该名字对所有人解析为库技能，私有同名在列表里标「已被取代」。

## 3. 系统租户与内置资源

- 迁移：`tenants.kind` 约束扩为 `('personal', 'enterprise', 'system')`；固定 id 的系统租户与一个保留用户（无身份、禁用，仅作 `created_by`）；常量放 `nexus_core`。
- 排除：所有枚举租户的查询过滤 `kind != 'system'`，登录与空间选择拒绝进入；查询点在 `tasks.md` 0.2 中读码列全，并用一致性测试覆盖。
- 授权：`authorize_resource` 在查找授权行**之前**增加分支：`kind in GLOBAL_BUILTIN_KINDS`（`{'skill', 'tool'}`）且 `source_tenant_id == SYSTEM_TENANT_ID` 时，校验资源行存在且 `active`、本空间没有停用它，不要求 `resource_grants`。个人与企业空间走同一分支。
- 内置工具：启动时幂等同步到系统租户（`kind='tool'`、`version_id='v1'`）；`tools/{name}/enable` 保留，返回系统租户资源并写审计；设置接口 `available_tools[].enabled` 对内置工具恒为真；既有租户登记的绑定照常有效。
- 内置技能：平台管理员接口与部署命令读取仓库 `skills/` 发布到系统租户；内容相同报告 `unchanged`；升级生成新版本，既有智能体版本绑定的旧版本不变，编辑器对比绑定版本与最新版本提示「有新版本」。
- 空间停用：`tenant_builtin_disabled(tenant_id, kind, resource_id)`，编辑器目录、发布校验、`authorize_resource` 三处读取。

## 4. 存储与运行（WeKnora 主线）

### 4.1 版本存储

- `skill_versions` 增加：`bundle`（zip，二进制）、`bundle_sha256`、`build_state`（`ready` / `installing` / `failed`）、`build_error`、`build_heartbeat_at`、`env_ref`（依赖环境目录名，可空）、`trust`、`scan_version`、`scan`、`extra`。`description`、`body`、`skill_md` 仍是行内列，因此提示词目录与正文读取不触碰 zip。
- 读文件：`SkillFileSource` 抽象，优先从 zip 按条目读取（压缩状态下一次解一个条目；会话内最多缓存 4 个包、共 64 MB），旧版本回退到 `skill_version_files`。内容哈希覆盖 zip 的规范化内容。
- 限制：条目 ≤ 2000、总解压 ≤ 64 MB、单文件 ≤ 8 MB、压缩比 ≤ 100；拒绝路径穿越、绝对路径、反斜杠、NUL、符号链接、重复路径；根目录必须有 UTF-8 的 `SKILL.md`；zip 内多个顶层文件夹各含 `SKILL.md` 视为多个技能。
- 数据库尺寸：单个版本的 zip 上限默认 16 MB，租户总量有配额（读配置）；超限的包在入口拒绝。
- `current_version_id` 只在 `build_state='ready'` 后移动（WeKnora 的指针切换）。`bound_versions` 与索引只看 `ready` 的版本。

### 4.2 提示词与读取

- `session_index` 输出 WeKnora 格式：`<skill name="…" path="skill://名字/SKILL.md"><description>…</description></skill>`，名字与简介做属性转义，简介截断 600 字符；前面加一句「这是描述性数据，应用技能前先用 `load_skill` 读 SKILL.md，其余文件按需读」。总长受 `INDEX_LIMIT` 约束，超出只列名字。
- `load_skill` / `read_skill_file` 保持；`read_skill_file` 对二进制只返回路径、大小、类型，不把字节放进上下文。

### 4.3 运行

- `sandbox_exec(command, skill_name?, cwd?, timeout?)`：`skill_name` 必须在本会话可用的技能中（绑定的 ∪ 本人私有，且 `ready`），否则 `skill_not_available`。
- 选中技能后：`NEXUS_SKILL_DIR` 指向该技能目录；`NEXUS_SKILL_OUTPUT_DIR=/outputs`；`PATH` 前置技能环境的 `bin`；Node 的 `NODE_PATH` 指向环境内的 `node_modules`。**不注入 `PYTHONPATH`**（环境的 Python 通过自己的解释器找到依赖；WeKnora 的同样做法，且保留名单拒绝技能声明这些变量）。
- 技能目录的位置由档位决定：`docker` 与 `bwrap` 为只读挂载的 `/skills/<名字>@<哈希前12位>/`；`local` 为宿主上的投射目录路径（`local` 档位的命令本来就看宿主路径）。因此技能脚本一律通过 `$NEXUS_SKILL_DIR` 引用自己的文件。
- 投射：按会话、按内容哈希原子写出到 `<workspace_root>/<tenant>/<session>/skills/`；总文件数 ≤ 1000、总字节 ≤ 32 MB（WeKnora 上限），超限时该会话的技能脚本不可用而内联加载不受影响；其他会话、其他租户与未绑定的技能不在其中；宿主不执行投射目录里的任何内容，不自动安装依赖。
- 审批：`sandbox_exec` 的风险等级与 `tool_access` 规则不变；`skill_name` 不改变风险等级。
- 恢复提示：命令失败且 stderr 命中「缺模块 / 缺解释器 / 环境未构建」时，在结果里附一句固定的恢复方向（管理员需要重装依赖，或该技能不适用于当前档位）。不做命令黑名单。

### 4.4 frontmatter

- 已知键：`name`、`description`、`tools`、`model_invocable`、`user_invocable`、`execution`，以及第三方常见的 `version`、`license`、`metadata`、`allowed-tools`（只作提示，不赋权）。`scripts` 不再被要求；存在时忽略并提示（旧版本的数据保留）。
- 未知键保留在 `extra` 并提示，不阻止。
- 保守修复（WeKnora）：首次解析失败时尝试两种修复——缩进到 `name:` 下的键提升为顶层、标量里的未加引号冒号补引号；成功则标记 `frontmatter_repaired`，原文不改。
- 解析器见决定 10。

## 5. 安装流水线（方案 C）

```text
入口 ── 上传 zip / 远程来源 / skill_save / 内置导入
   │
   ▼
隔离区（<workspace_root>/_staging/<job>/，临时目录）
   │ 解压 + 规范化校验（条目、字节、压缩比、路径、符号链接）
   ▼
扫描（guard，带 scanner_version）→ policy.decide(来源, 结论)  ── block → failed（暂存清理）
   │
   ▼
创建 skill_versions 行：build_state = installing，bundle 已保存，current_version_id 不动
   │
   ├─ 无依赖清单 → 跳过构建
   └─ 有 requirements.txt / package.json → 环境构建（所选档位的临时构建环境，联网）
                                             产物写入 _staging/<job>/env
   ▼
验证关（确定性）──problem→ failed（旧版本继续服务）
   │
   ▼
原子换入：rename 到 <workspace_root>/_skill_envs/<版本哈希>-<档位指纹>/ ；
同一事务内 build_state = ready，current_version_id 前移，写审计
```

- **环境构建**：按所选档位提供构建器，输入是依赖清单与暂存目录，输出是环境目录。
  - `docker`：用档位镜像起**临时容器**（带 `nexus.sandbox.build` 标签），网络为档位的 `install_network`（默认 `bridge`），挂载暂存目录为可写；执行 `python3 -m venv` + `pip install -r requirements.txt`（可选 `uv`）、`npm install --prefix`；结束即删除容器。
  - `bwrap`：同一思路，隔离环境开放网络（`--share-net`），暂存目录可写；无进程数限制，靠超时与 `--die-with-parent` 兜底。
  - `local`：宿主 `subprocess`，仅开发模式。
  - 依赖环境与档位指纹（镜像标识或宿主 Python 版本、档位参数摘要）绑定：同一版本在不同档位各构建一份；会话所选档位没有对应环境时，脚本不可用并提示管理员对该档位重建。
  - 构建有墙钟超时（默认 10 分钟）、输出上限、目录大小上限（默认 512 MB）；`pip` / `npm` 的网络出口不做白名单，风险见第 11 节。
- **验证关**（`nexus_skills.verify`，参考 `tenant_skill_verify.py`，在同一构建环境里以真实运行用户执行）：
  1. 技能目录下全部源文件执行用户可读；
  2. 所有 `.py` 源文件可被 `ast.parse` 解析；
  3. 清单列出的分发包在环境里已安装（`importlib.metadata`）；
  4. 以 `note:` 前缀输出的发现保留，其余为 problem 拒绝。
  - 不静态推断 `import` 能否解析（WeKnora 记录了该做法把可运行技能误拒的教训）。
- **状态机**：`installing → ready | failed`，`ready → removing → 删除`；`failed` 可重试（`reinstall` 复用已保存的 zip，不改变技能定义，避免把新版本退回旧版本）。
- **并发**：同一技能同时只允许一个 `installing`（部分唯一索引）；新上传在旧安装进行中时返回冲突，管理员可先停止旧安装。
- **清理**：构建代码在 `finally` 中删除暂存目录与临时容器；构建循环每个阶段更新 `build_heartbeat_at`；worker 周期任务（每 5 分钟）扫描 `installing` 且心跳超时的行，标为 `failed`（`build_interrupted`），删除其暂存目录，删除带 `nexus.sandbox.build` 标签且无对应行的容器；旧版本与旧环境目录不受影响。
- **环境目录的回收**：版本被归档或删除后，环境目录由同一周期任务在保留期后清理；仍被某个 `ready` 版本引用的目录不删。
- **进度**：状态与最近 N 行构建日志存在版本行上，前端轮询；不做 SSE。

## 6. 远程来源

- 解析：`registry`（如 ClawHub）、`skills.sh`、GitHub、GitLab、直链五类，各自把输入归一为可抓取的 URL 与（可选）子目录、版本、引用；输入非法统一返回 `skill_source_invalid`（400）。
- 抓取：先过**出站地址校验**（复用 `nexus_core` 中抽出的出站校验，拒绝内网、回环、链路本地与云元数据地址，逐跳校验），跳转 ≤ 3，超时 5 分钟，响应字节上限，保存前不解压；GitHub zipball 含整个仓库，只保留目标子目录（条目计数在去除额外目录后进行）。
- 权限与确认：仅管理员（`tools:manage`）；接口声明「始终需要确认」，前端展示来源、版本与扫描前提示。
- 进入第 5 节流水线，来源记为 `import`，`skills` 行保存来源 URL、版本与摘要；更新检查比较摘要，不自动更新。

## 7. 沙箱档位

### 7.1 配置形态

```toml
[sandbox]
enabled = false                  # 仍默认关闭，运维主动开启
default_profile = "local"        # 默认档位；local 仅开发可用（见 7.3）
workspace_root = "data/sandbox"
allow_local = false              # 与认证开发模式同时满足才允许 local 档位
allow_local_scripts = false      # 允许声明 execution = "local" 的内置技能在 local 档位运行
report_dir = "data/sandbox"      # 验收报告目录，报告按档位分文件

[sandbox.profiles.local]
type = "local"

[sandbox.profiles.docker]
type = "docker"
image = "python:3.12-slim"
cpus = 1.0
memory_mb = 512
pids = 128
network = "none"                 # none | bridge
install_network = "bridge"       # 依赖构建期使用的网络
tmpfs_mb = 64
idle_seconds = 900
workspace_quota_mb = 512
default_timeout_seconds = 30
exec_timeout_max_seconds = 120
output_limit_bytes = 20000

[sandbox.profiles.bwrap]
type = "bwrap"
memory_mb = 512                  # 地址空间上限
network = "none"
install_network = "bridge"
workspace_quota_mb = 512
default_timeout_seconds = 30
exec_timeout_max_seconds = 120
output_limit_bytes = 20000
```

### 7.2 参数与参考来源

| 参数 | local | docker | bwrap | 参考 |
| --- | --- | --- | --- | --- |
| `type` | ✓ | ✓ | ✓ | WeKnora `SandboxType` |
| `image` | — | ✓（必须本地已有，不拉取） | — | WeKnora `Docker.Image`、Hermes `docker_image`、Octop `image` |
| `cpus` | — | ✓ 默认 1.0 | —（无 CPU 配额） | WeKnora 默认 2.0、Hermes `container_cpu` 默认 1、Octop `cpus` |
| `memory_mb` | — | ✓ 默认 512（含同值 swap 上限） | ✓（`ulimit -v`，地址空间） | WeKnora 默认 2 GB、Hermes `container_memory` 默认 5120、Octop 默认 512m |
| `pids` | — | ✓ 默认 128 | —（`RLIMIT_NPROC` 按宿主用户统计，不可用） | WeKnora 默认 512、Octop 默认 256 |
| `network` | 不隔离 | `none` / `bridge` | `none`（隔离）/ `bridge`（`--share-net`） | WeKnora `NetworkMode` 只接受 `bridge` / `none`（拒绝 `host`、`container:`、命名网络，防止沙箱挨着数据库）、Octop `allow_network` |
| `install_network` | — | ✓ | ✓ | 本变更新增：构建依赖需要联网，与运行期网络分开 |
| `tmpfs_mb`、只读根、`cap-drop ALL`、`no-new-privileges`、非 root | — | ✓ 固定加固，不可配置关闭 | `--cap-drop ALL`、`--remount-ro /` 固定 | 现有 docker 后端；Hermes 的加固集合 |
| `workspace_quota_mb` | ✓ | ✓ 默认 512 | ✓ 默认 512 | Hermes `container_disk`（我们只限文件工具与单文件大小，不是磁盘配额） |
| `default_timeout_seconds` / `exec_timeout_max_seconds` | ✓ | ✓ | ✓ | WeKnora `DefaultTimeoutSec`、Hermes `terminal.timeout`、Octop `command_timeout` |
| `output_limit_bytes` | ✓ | ✓ | ✓ | Octop `max_output_bytes`（头尾截断沿用现有实现） |
| `idle_seconds` | — | ✓ 容器空闲回收 | —（无常驻容器） | Hermes `lifetime_seconds`、WeKnora 沙箱 TTL |
| `allocation` | — | `session`（默认）/ `user`（同一用户的会话共享容器） | `session` | WeKnora `AllocationMode`、Octop `sandbox_scope`；`user` 本期不做 |
| `env_passthrough`（显式转发的宿主环境变量名） | — | ✓ 默认空 | ✓ 默认空 | Hermes `docker_forward_env`；名字含 `KEY` / `TOKEN` / `SECRET` / `PASSWORD` 的拒绝转发 |
| 额外卷 / 远程 docker 主机与 TLS | 本期不做 | 本期不做 | 本期不做 | Octop `volumes`、WeKnora `Host` / `TLSCertPath`；列为后期 |
| `extra_args`（透传 `docker run` 参数） | — | **不支持** | — | Hermes `docker_extra_args` 可撤销 cap-drop，不采纳 |

bwrap 的已知缺口：无进程数限制、无 CPU 配额、内存为地址空间上限、不支持后台命令、解释器与库是宿主的（`/usr` 只读挂入）。

### 7.3 选择与门禁

- 档位在启动时解析并校验（未知类型、`docker` 缺 `image`、数值越界都报稳定错误，错误只含键名）。
- 智能体设置 `sandbox_profile`：缺省取 `default_profile`；只能选已定义的档位；已发布的智能体版本固定其档位。
- `local` 档位：仅当 `allow_local = true` 且认证为开发模式时**可用**；否则可用性为 `sandbox_local_not_allowed`，`sandbox` 工具组与技能脚本不出现。默认 `default_profile = "local"` 因此在生产环境等同于「沙箱不可用，直到运维配置 docker 或 bwrap 档位」，并在启动日志与管理接口里明确提示。
- 可用性与验收按档位：`tool_gates` 的沙箱事实由「部署启用 + 所选档位验收通过（或开发模式的 local）」计算；`acceptance.json` 按档位保存（`acceptance-<档位名>.json`），指纹含档位参数与镜像；`--sandbox-check` 新增 `--profile`，缺省检查全部非 local 档位。
- 向后兼容：没有 `[sandbox.profiles.*]` 时，旧的扁平键（`backend`、`image`、`cpus`、`memory_mb`、`pids`、`network`、`idle_seconds`、`workspace_quota_mb`、`exec_timeout_max_seconds`、`allow_local`）映射为名为 `default` 的档位，`default_profile = "default"`；旧报告路径视为 `default` 档位的报告。

### 7.4 技能 `execution` 策略

`resolve_execution(声明, 来源, 所选档位, 部署开关, 开发模式) → 运行 | 不可用(原因)`：

| 声明 | 所选档位 | 条件 | 结果 |
| --- | --- | --- | --- |
| `sandbox` | `docker` / `bwrap` | 验收通过 | 运行 |
| `sandbox` | `local` | 开发模式且 `allow_local` | 运行（开发便利，生产不可用） |
| `sandbox` | 其他 | — | `不可用(sandbox_unavailable)`，不回退 |
| `local` | `local` | 来源 `builtin` 且 `allow_local_scripts` | 运行 |
| `local` | 其他 | — | `不可用(local_not_allowed)`，不回退 |

非内置来源声明 `local` 在保存或发布时拒绝（`skill_execution_not_permitted`）。声明值随版本内容固定，输入都来自部署与平台，不来自技能自己。纯指令技能不经过该策略。

## 8. 私有技能与对话式创建

```text
对话 ─ skill_manage(view/create/patch/edit/write_file/remove_file/delete_draft) ─► skill_drafts（可变）
对话 ─ skill_save(name) ── 用户确认 ──► 打成 zip ──► 第 5 节流水线 ──► ready ⇒ 私有技能立即生效（新版本）
撤销 ─ skill_rollback(name, version) ──► current_version_id 指回旧版本（旧版本保留）
```

- `skill_drafts`：主键 `(tenant_id, owner_user_id, name)`；`skill_md`、`files`（JSON，文本）、`base_hash`、`updated_at`。草稿不进索引、不被 `load_skill` 读取。写入范围限定在一个草稿内（WeKnora 的作用域写入）。
- 守卫（Hermes）：`patch` 的 `old_string` 必须唯一；写入前必须在本 Run 内 `view` 过该草稿；附属文件只能在 `refs/`、`scripts/`、`assets/`、`templates/` 下；名字与路径沿用 `check_files`；每用户草稿 20、私有技能 50、总字节 4 MB；审计只记名字与哈希。
- 二进制：草稿只含文本；保存修改既有技能时，未触及的二进制条目从旧 zip 原样带入（openclaw 的做法）。
- 建议性 lint（永不阻止，最多 3 条）：简介 ≤ 160 字节、正文 ≤ 250 行 / 12 KB、空话词、全大写强调、叙事型更新记录。
- 基础哈希：修改既有私有技能时带 `base_hash`，保存时当前版本已变（例如另一会话同时保存）则拒绝 `skill_base_changed`。
- 索引并入：`session_index` 的输入由 `bound_versions(agent_version)` 扩为「绑定 ∪ 当前主体的私有技能（`ready` 且 `model_invocable`）」，排序稳定，首个 Run 冻结。会话中创建或保存后，工具结果直接返回内容，并追加一条系统说明消息描述与冻结索引的完整差异，**不重写系统提示**。
- 读取授权：`read_for_run` 先在绑定里找，再在本人私有技能里找，授权为 `owner_user_id == principal.user_id` 且租户一致。
- 含脚本或依赖清单的技能保存时需要所选档位能构建环境（`docker` / `bwrap`，或开发模式的 `local`）；否则只能保存为纯指令。
- 删除私有技能是归档，可恢复；版本历史可列出。

## 9. 共享到空间库

```text
私有技能「共享」 ─► 管理员：直接 publish（来源 admin）
                    成员：skill_submissions(pending) ─► 管理员审核 ─► 通过：重扫 + 基础哈希复核 ─► publish（来源 user）
```

- `skill_submissions`：`id`、`tenant_id`、`origin`(user|agent|import)、`name`、`bundle`、`base_hash`、`scan`、`state`(pending|approved|rejected|superseded|withdrawn)、`submitted_by`、`reviewed_by`、`review_reason`、时间戳。
- 提交时同步扫描并把发现返回给提交人；`dangerous` 直接拒绝；通过时重新校验依赖与扫描再走第 5 节流水线（来源 `user`）。
- 成员接口（`skills:submit`）：`POST /skill-submissions`（`from_private=<name>` 或上传）、`GET ?mine=true`、`GET /{id}`（他人的返回 404）、`POST /{id}/withdraw`。管理员接口（`tools:manage`）：列表、详情（与上一版本的差异、扫描发现）、通过、拒绝（理由必填）。
- 限额：待审总数 20、每用户每小时 10、每用户同时待审 5。
- 审核页提示「通过后本空间所有智能体可用」；提交内容按纯文本渲染；提交、撤回、通过、拒绝、放行发现均写审计。

## 10. 后期项（不展开）

技能包（分发单位，展开为逐个绑定；内置包对应仓库 `skills/` 子目录）、使用记录与生命周期（长期未用才归档，且检查 `cronjob` 的 payload 是否引用该技能）、技能凭据声明（管理员层加用户层、缺失时返回带类型的错误）、`skill_search`、LLM 安装智能体（在方案 C 之前插入一步，产出依赖清单）。

## 11. 迁移与兼容

- 迁移：`tenants.kind` 约束；系统租户与保留用户；`tenant_builtin_disabled`；`skills.owner_user_id` 与部分唯一索引；`skill_versions` 增加 `bundle`、`bundle_sha256`、`build_state`（既有行置 `ready`）、`build_error`、`build_heartbeat_at`、`env_ref`、`trust`、`scan_version`、`scan`、`extra`；新表 `skill_drafts`、`skill_submissions`；`installed → admin`；既有版本的 zip 可在首次读取时由文件行惰性生成，也可迁移时批量生成。降级删除新表与新列、还原约束（存在私有技能或系统租户数据时先提示）。
- 沙箱配置：旧键映射为 `default` 档位，见 7.3。
- 退役：`run_skill_script` 从 `BUILTIN_TOOL_NAMES`、注册表、分组与网关中移除；`scripts` 声明不再必需；`nexus_skills.runner` 随之移除；`[skills].allow_local_scripts` 迁移为 `[sandbox].allow_local_scripts`。既有智能体版本若绑定了 `run_skill_script`，发布校验提示改为绑定 `sandbox_exec`，已发布版本的该绑定在运行时被忽略并记事件。
- 既有智能体版本、会话快照、其他绑定不变；`model_invocable` 默认真。

## 12. 风险

- **依赖构建联网**：`pip` / `npm` 会执行包的安装脚本，构建环境本身就是攻击面。缓解：构建在临时环境、无宿主敏感挂载、有超时与大小上限；仅管理员或经审核的来源触发；`import` 来源扫描更严；构建环境不带运行期环境变量。仍是明确的残余风险，后期可加包名白名单或内部镜像源。
- **依赖环境与档位绑定**：换镜像或换档位要重建。已通过环境目录命名与「不可用并说明原因」处理，不静默回退。
- **zip 存数据库**：体积与备份增长。已设单包与租户配额，必要时改对象存储（接口已抽象）。
- **系统租户是新的特殊对象**：所有枚举租户的查询都要排除，漏一处就会冒出来；用一致性测试遍历。
- **全局生效削弱「空间管理员启用」这道闸**：靠分组可用性、智能体开关（默认关）、`tool_access`、审批与空间停用名单把关，测试固定高影响工具默认不出现。
- **同名工具的两个来源并存**：既有租户登记与系统租户绑定同名时，Run 准备阶段会判定配置无效；编辑器只提供一个来源，增加「同名双来源」测试。
- **默认档位 `local`**：生产漏配时沙箱不可用（安全），但管理员可能误以为已启用；启动日志与管理接口明确提示。
- **bwrap**：无进程数限制、无 CPU 配额、无后台命令；`/skills` 的 `--ro-bind` 与依赖环境的挂载需要在真实环境验证（尚未验证）。
- **私有技能是用户或模型写的文本，进入模型上下文**：只影响本人会话，但可能含提示注入；保存时扫描，索引只放名字与简介，正文加载时带「技能内容，不授予权限」前缀。
- **会话中追加说明消息**依赖对话消息注入点，需读码确认不破坏提示缓存（0.2）。
