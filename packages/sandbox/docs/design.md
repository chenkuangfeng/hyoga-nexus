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

`--unshare-all --cap-drop ALL --die-with-parent --new-session --remount-ro /`，环境只含显式 `--setenv` 的变量（启动 bwrap 时父进程环境已只剩 `PATH`；不用 `--clearenv`，bwrap 0.4.0 不认识它），网络仅在 `network = "bridge"` 时 `--share-net`；服务进程为 root 时以 65534 运行。资源限制用外层 shell 的 `ulimit`（`-v` 地址空间按 `memory_mb`、`-f` 单文件按配额、`-c 0`、`-n 1024`）。与 docker 后端的差异：没有进程数限制（`RLIMIT_NPROC` 按宿主用户统计，不可用，需要 cgroup）、没有 CPU 配额、`image`/`cpus`/`pids` 不生效、不支持后台命令（隔离环境随启动它的 shell 结束，`exec_async` 返回 `sandbox_background_unsupported`）、解释器与库就是宿主的。进程回收验收只验证命令结束后的清理。

## 档位

`[sandbox.profiles.<名字>]` 定义命名档位，类型为 `local`、`docker`、`bwrap`、`ssh`、`managed`；`default_profile` 缺省为 `local`；档位只能由运维在部署配置里定义，智能体设置 `sandbox_profile` 只能选名字，已发布的智能体版本固定其档位。每个档位解析为一个 `SandboxSettings`，后端、管理器和验收都按档位工作：每个档位有自己的 `SandboxManager`，docker 容器名在非 `default` 档位时带档位名，容器带 `nexus.sandbox.profile` 标签，空闲与孤儿回收只处理本档位；验收报告为 `acceptance.json`（旧的 `default` 档位）或 `acceptance-<档位>.json`，指纹含档位的类型、镜像与限制。`--sandbox-check` 默认检查全部隔离档位，`--profile` 只检查一个。

不适用于某类型的键直接报错（例如 bwrap 档位里的 `pids`），避免静默无效；`docker run` 的加固（非 root、只读根、`cap-drop ALL`、`no-new-privileges`）不可配置，也不支持透传任意 `docker run` 参数；`env_passthrough` 显式转发宿主变量，名字像凭据（含 `KEY`、`TOKEN`、`SECRET`、`PASSW`、`AUTH` 等）、沙箱自己设置的名字（`PATH`、`HOME`……）和 `NEXUS_` 前缀的名字被拒绝。`local` 档位仅当 `allow_local = true` 且认证为开发模式时可用，否则可用性为 `sandbox_local_not_allowed`，沙箱工具组不出现，不会因此启动失败。旧的扁平键等同一个名为 `default` 的档位；没有任何沙箱配置时只有隐式的 `local` 档位。可用性原因码：`sandbox_disabled`、`sandbox_not_accepted`、`sandbox_local_not_allowed`、`sandbox_profile_unknown`。

## 技能与标准输入

技能脚本由 `exec_skill` 运行（见 `packages/skills`）。沙箱侧提供三样东西：**投射**（`nexus_sandbox/skills.py`）把技能文件按 `<技能>@<内容哈希前 12 位>` 写进会话的 `skills` 目录——先写到暂存目录再原子改名，同一哈希不会被覆盖，最多 1000 个文件、32 MB——docker 与 bwrap 把该目录只读挂载为 `/skills`，`local` 档位的命令看到宿主路径，所以直接用宿主上的目录；**命令环境**，调用方（不是模型参数）可以给一次命令追加环境变量，名字须是大写字母、数字与下划线，`exec_skill` 用它设置 `NEXUS_SKILL_DIR` 与 `NEXUS_SKILL_OUTPUT_DIR`；**标准输入**，`sandbox_exec` 与 `exec_skill` 可传最多 65536 字节的文本，三个执行器都支持（docker 用 `exec -i`），不传时仍然关闭。技能的超时有单独上限：`exec_skill` 用档位的 `skill_timeout_seconds`（默认 120）与 `skill_timeout_max_seconds`（600），不受 `exec_timeout_max_seconds` 限制。已存在的 docker 容器（改动前创建）没有 `/skills` 挂载，空闲回收后重建即带上。

## 验收项

connectivity、user、network、time_limit、output_limit、memory_limit、process_limit、tenant_isolation、path_escape、environment、cancellation、cleanup_and_residue。`local` 后端在任何探测运行前被拒绝，因为内存与进程数探测本身带有破坏性。

**bwrap 档位的验收差异**：没有长驻容器，且每条命令是独立的 PID 命名空间，所以 `process_limit`、`cancellation`、`cleanup_and_residue` 三项改为从宿主进程表按标记进程（`sleep <本次随机秒数>`）检查。`process_limit` 不再要求“被限制在 pids 以内”（bwrap 没有进程数限制，真正的限制需要 cgroup），而是验证 fork 出 `pids × 2` 个进程后，它们随 jail 一起结束；取消与后台进程同理。这是有意放宽的准入条件，进程数仍只靠命令超时和 jail 销毁兜底。

## 已知限制

- 路径检查与打开之间存在符号链接替换的竞态；边界由容器提供，不由路径检查提供。
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

SSH 和 HTTPS 托管档位复用现有会话文件、技能只读投射和产物登记。API、worker 和执行节点挂载同一份工作区卷。各节点可用不同的本地挂载点，必须对同一个租户与会话解析到同一份文件数据。节点需要相容的 UID/GID 和文件权限。环境依赖放入远端运行环境，远程档位当前不构建技能依赖，也不提供后台作业。

- **SSH** 使用部署指定的私钥和固定的 known_hosts，调用远端 Python 模块 `nexus_sandbox.remote_runner`。远端选一个启用的断网 bwrap 档位。SSH 档位仅供信任租户与脚本的部署启用，需设置 `trusted_ssh = true` 并通过连通性及隔离检查。其报告不声明 CPU、PID 和远端取消验收。
- **HTTPS** 使用运维配置的可信 HTTPS 端点与 bearer 凭据文件。Nexus 兼容网关按请求启动并回收独立 Docker 容器，限制每次任务的 CPU、内存、PID、时间与输出。取消等待容器清理，容器保留额外的存活期限以处理网关异常退出。
- **管理端** 参考 WeKnora 沙箱卡片与抽屉。企业 owner/admin 可查看配置和验收，平台管理员可暂停档位或调整命令及技能超时。轻量策略原子保存于共享卷的 `_profile_policies`，不得挂入沙箱。API 需要写权限，worker 需要读权限，同一套部署使用相容的运行账号。暂停拦截新 Run，已启动 Run 的工作区仍可完成产物登记。
- **验收** 在实际 worker 节点执行 `--sandbox-check --profile NAME`。远程档位验证共享卷的读写、租户文件隔离、网络和超时。托管档位还验证 CPU、PID 和取消响应。报告继续采用档位指纹与数据库门禁，运维变更远端镜像或执行策略后应从目标 worker 重新验收。

### 托管网关协议 v1

运维可单独运行 `uv run uvicorn nexus_api.sandbox_gateway:app --workers 1`，前方使用 HTTPS。网关读取 `[sandbox_gateway]` 的凭据文件和允许的 Docker 档位。访问凭据只发给可信 worker，工作区根及连接配置不接受来自智能体的输入。每个网关进程服务一个明确的执行节点，取消请求必须送到接收原执行请求的进程。

- `POST /v1/executions`，bearer 鉴权，JSON 请求上限 1 MiB。字段为 `id`（32 位小写十六进制）、`profile`、`tenant_id`、`session_id`、`command`、`cwd`、`timeout_seconds`、`output_limit`、`env`、`stdin`、`network` 和 `limits`。`network` 固定为 `none`，`limits` 包含 `cpus`、`memory_mb` 与 `pids`，需要与节点真实策略匹配。
- 成功返回 `ExecResult` JSON，包含独立标准输出/错误、退出码、超时和截断状态。脚本非零退出是命令结果。连接、鉴权和策略不匹配返回 HTTP 错误。
- `DELETE /v1/executions/{id}`，使用同一 bearer 凭据。返回 204 时正在运行的任务已终止，或请求已结束。未收到原请求时短期记录取消，防止交错到达后开始执行。

第三方网关可实现相同协议及共享卷语义。CubeSandbox/E2B 的原生 API 需要单独的协议适配和文件传输层。
