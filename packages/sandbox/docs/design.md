# 沙箱设计

模型只看到两个虚拟根：`/workspace`（可读写）和 `/outputs`（交付物）。宿主路径由后端映射，不出现在任何工具结果里。

| 模块 | 职责 |
| --- | --- |
| `settings` | 读取 `[sandbox]`；非法值只报键名，不回显值 |
| `paths` | 虚拟路径解析：拒绝 `..`、NUL、其他根；按真实路径判断符号链接是否越界 |
| `files` | `HostFileStore`：宿主目录上的文件读、分页读、原子写、唯一匹配编辑、搜索、配额、产物收集（`output_files()` 给出 `/outputs` 下普通文件的宿主路径，供平台在 Run 结束时登记，符号链接不收） |
| `backends/docker` | 每个（租户，会话）一个容器；`docker exec` 执行；`timeout` 带进程组；取消时按命令标记杀进程组 |
| `backends/bwrap` | 每条命令一个 bubblewrap 隔离环境：宿主 `/usr` 等只读、仅 `/workspace` 与 `/outputs` 可写、独立 user/pid/ipc/uts/cgroup/net 命名空间；不依赖守护进程与镜像 |
| `backends/local` | 开发替身，不隔离 |
| `backends/output` | 输出按头 70% 加尾 30% 保留 |
| `session` | `SandboxSession`：把文件存储与执行器合成工具使用的 `SandboxSessionPort`（契约在 `nexus_core.sandbox`） |
| `manager` | 租约：目录、容器名、空闲与孤儿回收 |
| `acceptance` | 隔离验收：按后端执行真实探测，报告按后端、镜像与限制的指纹失效 |

## 后台命令

`SandboxSession.exec_async` 把命令交给一个独立会话里的 shell（`setsid`），状态写在 `/workspace/.jobs/<id>/`：`out`（输出）、`rc`（退出码，124 表示超时）、`pid`、`started`、`cancelled`。读状态直接读宿主目录里的这些文件，不需要再进容器。shell 自己是进程组组长，里面的看门狗到点写 124 并杀整组，命令结束时 shell 写退出码后也杀整组，所以命令留下的后台进程不会比作业活得更久；`job_cancel` 对 `pid` 所在进程组发 SIGKILL。每个会话最多同时 4 个，Run 结束时 `close_jobs` 取消仍在跑的作业。

## 容器参数

非 root（服务进程为 root 时用 65534），`--cap-drop ALL`，`no-new-privileges`，只读根文件系统，`/tmp` 为 tmpfs，默认 `--network none`，`--cpus`、`--memory` 与同值 `--memory-swap`、`--pids-limit`，`--pull never`，只挂载本会话的两个目录，不传服务进程环境变量。

## bwrap 后端

`--unshare-all --cap-drop ALL --die-with-parent --new-session --remount-ro /`，环境只含显式 `--setenv` 的变量（启动 bwrap 时父进程环境已只剩 `PATH`；不用 `--clearenv`，bwrap 0.4.0 不认识它），网络仅在 `network = "bridge"` 时 `--share-net`；服务进程为 root 时以 65534 运行。资源限制用外层 shell 的 `ulimit`（`-v` 地址空间按 `memory_mb`、`-f` 单文件按配额、`-c 0`、`-n 1024`）。与 docker 后端的差异：默认没有进程数与 CPU 配额；配置 `cgroup_root` 后启用整棵命令树的 CPU、PID 和内存硬限额、`image`/`cpus`/`pids` 不生效、不支持后台命令（隔离环境随启动它的 shell 结束，`exec_async` 返回 `sandbox_background_unsupported`）、解释器与库就是宿主的。进程回收验收只验证命令结束后的清理。

## 档位

`[sandbox.profiles.<名字>]` 定义命名档位，类型为 `local`、`docker`、`bwrap`、`ssh`、`managed`；`default_profile` 在未声明档位时缺省为 `docker`；档位只能由运维在部署配置里定义，智能体设置 `sandbox_profile` 只能选名字，已发布的智能体版本固定其档位。每个档位解析为一个 `SandboxSettings`，后端、管理器和验收都按档位工作：每个档位有自己的 `SandboxManager`，docker 容器名在非 `default` 档位时带档位名，容器带 `nexus.sandbox.profile` 标签，空闲与孤儿回收只处理本档位；验收报告为 `acceptance.json`（旧的 `default` 档位）或 `acceptance-<档位>.json`，指纹含档位的类型、镜像与限制。`--sandbox-check` 默认检查全部隔离档位，`--profile` 只检查一个。

不适用于某类型的键直接报错（bwrap 的 `pids` 和 `cpus` 需要同时配置 `cgroup_root`），避免静默无效；`docker run` 的加固（非 root、只读根、`cap-drop ALL`、`no-new-privileges`）不可配置，也不支持透传任意 `docker run` 参数；`env_passthrough` 显式转发宿主变量，名字像凭据（含 `KEY`、`TOKEN`、`SECRET`、`PASSW`、`AUTH` 等）、沙箱自己设置的名字（`PATH`、`HOME`……）和 `NEXUS_` 前缀的名字被拒绝。`local` 档位仅当 `allow_local = true` 且认证为开发模式时可用，否则可用性为 `sandbox_local_not_allowed`，沙箱工具组不出现，不会因此启动失败。旧的扁平键等同一个名为 `default` 的档位；没有任何沙箱配置时默认启用 `docker` 与 `local` 两个档位，总开关与 `allow_local` 缺省为 `true`；Docker 仍需验收，Local 仍需开发认证。显式自定义档位不补入缺省档位。可用性原因码：`sandbox_disabled`、`sandbox_not_accepted`、`sandbox_local_not_allowed`、`sandbox_profile_unknown`。

## 技能与标准输入

技能脚本由 `exec_skill` 运行（见 `packages/skills`）。沙箱侧提供三样东西：**投射**（`nexus_sandbox/skills.py`）把技能文件按 `<技能>@<内容哈希前 12 位>` 写进会话的 `skills` 目录——先写到暂存目录再原子改名，同一哈希不会被覆盖，最多 1000 个文件、32 MB——docker 与 bwrap 把该目录只读挂载为 `/skills`，`local` 档位的命令看到宿主路径，所以直接用宿主上的目录；**命令环境**，调用方（不是模型参数）可以给一次命令追加环境变量，名字须是大写字母、数字与下划线，`exec_skill` 用它设置 `NEXUS_SKILL_DIR` 与 `NEXUS_SKILL_OUTPUT_DIR`；**标准输入**，`sandbox_exec` 与 `exec_skill` 可传最多 65536 字节的文本，三个执行器都支持（docker 用 `exec -i`），不传时仍然关闭。技能的超时有单独上限：`exec_skill` 用档位的 `skill_timeout_seconds`（默认 120）与 `skill_timeout_max_seconds`（600），不受 `exec_timeout_max_seconds` 限制。已存在的 docker 容器（改动前创建）没有 `/skills` 挂载，空闲回收后重建即带上。

## 验收项

connectivity、user、network、time_limit、output_limit、memory_limit、process_limit、tenant_isolation、path_escape、environment、cancellation、cleanup_and_residue。`local` 后端在任何探测运行前被拒绝，因为内存与进程数探测本身带有破坏性。

**bwrap 档位的验收差异**：没有长驻容器，且每条命令是独立的 PID 命名空间，所以 `process_limit`、`cancellation`、`cleanup_and_residue` 三项改为从宿主进程表按标记进程（`sleep <本次随机秒数>`）检查。`process_limit` 不再要求“被限制在 pids 以内”（bwrap 没有进程数限制，真正的限制需要 cgroup），而是验证 fork 出 `pids × 2` 个进程后，它们随 jail 一起结束；取消与后台进程同理。这是有意放宽的准入条件，进程数仍只靠命令超时和 jail 销毁兜底。

## 已知限制

- Linux 文件内容读取和写入通过目录描述符锚定路径，拒绝链接竞态与特殊文件。
- 验收报告按档位保存在平台数据库表 `sandbox_acceptance`（每档位一行，重新验收时覆盖），API 与各 worker 共读，所以分机部署也一致；有效条件是行的 `fingerprint`（后端、镜像、限制的哈希）等于当前配置。`nexus_sandbox` 只依赖存储端口 `ReportStore`，数据库实现在平台包（`nexus_platform/runs/sandbox_acceptance.py`）。每次验收仍在 `workspace_root` 下写一份 `acceptance[-<档位>].json` 副本供运维查看；表里没有该档位的行时（升级前做过的验收）退回读这份文件，有行则以行为准。数据库读取失败按未验收处理。
- 配额以目录总大小估算，每次写入遍历一次工作区。

## 依赖环境构建（技能安装）

带 `requirements.txt` 或 `package.json` 的技能在安装时构建依赖环境（`nexus_sandbox/build.py`），运行脚本时只读使用。构建是唯一需要联网的步骤，所以在所选档位的**临时构建环境**里进行，与运行时环境分开：

- `docker`：一次性容器（标签 `nexus.sandbox.build`，`--rm`、非 root、`--cap-drop ALL`、只读根文件系统），网络取档位的 `install_network`（默认 `bridge`），只挂载清单（只读）与空的 `env` 目录（可写）；
- `bwrap`：与运行时相同的 jail，开放网络，`env` 可写；
- `local`：宿主子进程，仅开发。

产物是 `env/venv` 与 `env/node/node_modules`，另有构建结束时 `pip list` 的 `installed.json`（供验证关核对清单包，核对后删除）。构建有墙钟上限（`build_timeout_seconds`，默认 600）、日志只留末尾 60 行、目录大小上限（`env_max_mb`，默认 512）。环境放在 `<workspace_root>/_skill_envs/<档位>/<内容哈希前 16 位>-<环境指纹>/`，环境指纹是 docker 的镜像标识或宿主 Python 版本的摘要，所以同一版本在不同档位各有一份。

运行时 docker 与 bwrap 把 `_skill_envs/<档位>` 只读挂载为 `/skill_envs`（容器创建时挂载，旧容器空闲回收后重建即带上），`local` 用宿主路径；`exec_skill` 在命令前加 `PATH=<环境>/venv/bin:…:"$PATH"`，并设 `NODE_PATH`，`python3` 因而解析到环境里的解释器（`pyvenv.cfg` 在解释器旁边，目录改名后仍可用；入口脚本的 shebang 不可靠，所以不依赖它们）。本档位没有对应环境时脚本不运行，返回 `skill_env_missing` 并提示管理员对该档位重建。同一档位的所有会话能看到该档位全部环境目录（名字是哈希，内容是公开软件包）。

命令行由纯函数生成并有单元测试；docker 与 bwrap 上的真实构建**尚未验证**，本机只验证了 `local` 档位（真实 venv + 本地 wheel，含目录改名后的可用性）。

## 远程工作区与管理端

SSH 和 HTTPS 档位复用文件工具、技能投射与产物登记。SSH 节点通过共享卷访问当前会话；HTTPS 网关与 worker 共用会话目录，供应商实例通过文件 API 同步当前会话的有界快照。Linux 文件与产物复制通过逐级目录句柄和不跟随链接的打开方式约束访问范围，文件内容从同一描述符读取。

- **SSH** 使用部署指定私钥和固定 known_hosts，调用远端 `nexus_sandbox.remote_runner`。远端使用已启用的断网 bwrap 档位。部署需显式设置 `trusted_ssh`，SSH 验收不声明远端 CPU、PID 和取消能力。
- **HTTPS** 按请求使用独立 Docker 容器或 E2B 兼容 VM。供应商模板执行前验证实际 CPU/内存分配，文件根独立，技能只读。供应商后台任务和技能依赖构建尚未提供。
- **持久生命周期** 网关私有目录保存请求 ID、实例 ID、状态、创建时间与策略摘要。命令和文件内容不进入日志。已登记请求不能重复执行，实例创建结果未知时按元数据发现并回收。回收任务抵御重复取消，失败记录保留到下一次重试。
- **文件传输** `transfer.py` 的归档只允许普通文件和目录，限制文件数、深度、单文件和总字节数。实例仅接收当前会话与技能，不接收宿主目录结构。快照完整校验后替换工作区，发布失败回滚。同步期间对同一会话的文件工具写入与其他同步串行。
- **输出采集** `provider_runner.py` 与本地执行器共用 `Sink`，在实例内读取时保留头尾。SDK 命令结果只包含控制输出，返回文件经带访问令牌请求头的文件 API 流式获取。
- **界面** 参考 WeKnora 的 `SandboxSettings.vue` 与 `SandboxConfigEditorDrawer.vue`。企业 owner/admin 查看档位和验收，并维护运行策略、供应商模板和加密凭据、验证连接及重试实例回收。
- **配置边界** 执行节点地址、SSH 主机身份、共享卷、cgroup 委派和 XFS 挂载由部署运维提供。供应商配置可在界面编辑，密钥加密保存在网关控制目录。网关凭据与加密主密钥不得挂入沙箱。
- **验收绑定** managed 档位先连接网关并保存节点/模板/代码/资源策略摘要，再在 worker 节点验收。执行时必须匹配当前摘要。Docker 网关将实际镜像 ID 纳入摘要；供应商使用模板 ID 和运维声明的不可变版本。修改模板构建时必须更新版本。

### 托管网关协议 v1

运维运行 `uv run uvicorn nexus_api.sandbox_gateway:app --workers 1` 并配置 HTTPS。网关读取 `[sandbox_gateway]` 的凭据和允许档位。每个状态目录由一个进程独占，重启恢复使用原目录。API 与网关通过部署配置的受信连接通信，不接受模型提供的端点。

- `GET /v1/profiles/{name}/capabilities` 返回策略摘要、供应商、文件传输方式与执行能力。
- `POST /v1/executions` 接受最多 1 MiB 的 JSON，包含请求 ID、远端档位、租户/会话标识、命令、虚拟工作目录、超时、输出上限、环境与标准输入、断网策略、资源限制和 `policy_digest`。摘要不匹配返回 409，重复 ID 返回 409。命令结果使用 `ExecResult`。
- `DELETE /v1/executions/{id}` 取消并等待实例回收。回收不能确认时返回错误。
- `GET /v1/executions/{id}` 返回生命周期状态。
- `GET /v1/profiles/{name}/executions` 列出未完成实例。`POST /v1/profiles/{name}/executions/{id}/cleanup` 重试已退出活动注册表的实例回收。
- `GET/PUT /v1/profiles/{name}/provider` 查询和更新供应商配置。响应只包含凭据存在标志；配置变更要求所有实例已回收。文件以部署 Fernet 密钥加密并绑定档位名。

上述网关接口均需 bearer 身份验证。平台 API 再按企业成员身份与 owner/admin 角色限制管理操作。真实服务验收、cgroup v2 及 XFS quota 验收需要具备相应凭据和权限的目标节点。

### 控制台配置注册

企业管理端的“沙箱引擎”沿用 WeKnora 的类型筛选、搜索卡片和分区编辑器，支持新增、编辑、删除 Local、SSH、Bubblewrap、Docker 和 HTTPS 托管档位。稳定标识与展示名称分离，智能体仍绑定稳定标识。当前企业 owner/admin 均可修改共享档位，无须额外的平台管理员身份。部署总开关、本地执行许可仍由 `nexus.toml` 管理。

API 在共享 `workspace_root/_sandbox_profiles.json` 保存配置覆盖和删除标记，使用跨进程文件锁、原子替换和全局修订号拒绝过期提交。部署档位可以编辑，默认档位和被任意企业草稿或已发布版本引用的档位禁止删除。API 与 worker 必须共享控制卷。配置统一复用部署参数验证器，不接受任意配置键。SSH 私钥、known_hosts 和网关令牌只保存节点文件引用，供应商 API Key 仍经现有网关接口加密保存。

部署的 `default_profile` 可引用控制台创建的稳定档位标识；默认档位在合并共享配置后校验。不存在或已删除的默认档位会使配置加载失败，不自动改选其他执行环境。

worker 以部署文件和注册文件的修改标识刷新配置。运行参数哈希作为配置版本，Docker 容器名称与验收指纹纳入版本。修改运行参数后旧策略与连接证明失效，暂停标记保留，需重新验证托管连接并执行隔离验收。名称或描述修改不改变运行版本。在途调用继续使用原管理器，新调用使用新配置。

管理 API 为 `GET/POST /tenants/{tenant}/admin/sandboxes`、`PUT /{name}/configuration` 与 `DELETE /{name}?revision=...`，写入携带读取时的 `revision`。保存后进入详情，可继续连接验证、供应商管理和实例回收。
