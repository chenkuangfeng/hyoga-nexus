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
| `acceptance` | 隔离验收：12 项真实探测，报告按后端、镜像与限制的指纹失效 |

## 后台命令

`SandboxSession.exec_async` 把命令交给一个独立会话里的 shell（`setsid`），状态写在 `/workspace/.jobs/<id>/`：`out`（输出）、`rc`（退出码，124 表示超时）、`pid`、`started`、`cancelled`。读状态直接读宿主目录里的这些文件，不需要再进容器。shell 自己是进程组组长，里面的看门狗到点写 124 并杀整组，命令结束时 shell 写退出码后也杀整组，所以命令留下的后台进程不会比作业活得更久；`job_cancel` 对 `pid` 所在进程组发 SIGKILL。每个会话最多同时 4 个，Run 结束时 `close_jobs` 取消仍在跑的作业。

## 容器参数

非 root（服务进程为 root 时用 65534），`--cap-drop ALL`，`no-new-privileges`，只读根文件系统，`/tmp` 为 tmpfs，默认 `--network none`，`--cpus`、`--memory` 与同值 `--memory-swap`、`--pids-limit`，`--pull never`，只挂载本会话的两个目录，不传服务进程环境变量。

## bwrap 后端

`--unshare-all --cap-drop ALL --die-with-parent --new-session --remount-ro /`，环境用 `--clearenv` 重建，网络仅在 `network = "bridge"` 时 `--share-net`；服务进程为 root 时以 65534 运行。资源限制用外层 shell 的 `ulimit`（`-v` 地址空间按 `memory_mb`、`-f` 单文件按配额、`-c 0`、`-n 1024`）。与 docker 后端的差异：没有进程数限制（`RLIMIT_NPROC` 按宿主用户统计，不可用，需要 cgroup）、没有 CPU 配额、`image`/`cpus`/`pids` 不生效、不支持后台命令（隔离环境随启动它的 shell 结束，`exec_async` 返回 `sandbox_background_unsupported`）、解释器与库就是宿主的。验收的进程数探测预计不通过，是否放行由运维验证后决定。

## 档位

`[sandbox.profiles.<名字>]` 定义命名档位，类型为 `local`、`docker`、`bwrap`；`default_profile` 缺省为 `local`；档位只能由运维在部署配置里定义，智能体设置 `sandbox_profile` 只能选名字，已发布的智能体版本固定其档位。每个档位解析为一个 `SandboxSettings`，后端、管理器和验收都按档位工作：每个档位有自己的 `SandboxManager`，docker 容器名在非 `default` 档位时带档位名，容器带 `nexus.sandbox.profile` 标签，空闲与孤儿回收只处理本档位；验收报告为 `acceptance.json`（旧的 `default` 档位）或 `acceptance-<档位>.json`，指纹含档位的类型、镜像与限制。`--sandbox-check` 默认检查全部 docker 与 bwrap 档位，`--profile` 只检查一个。

不适用于某类型的键直接报错（例如 bwrap 档位里的 `pids`），避免静默无效；`docker run` 的加固（非 root、只读根、`cap-drop ALL`、`no-new-privileges`）不可配置，也不支持透传任意 `docker run` 参数；`env_passthrough` 显式转发宿主变量，名字像凭据（含 `KEY`、`TOKEN`、`SECRET`、`PASSW`、`AUTH` 等）、沙箱自己设置的名字（`PATH`、`HOME`……）和 `NEXUS_` 前缀的名字被拒绝。`local` 档位仅当 `allow_local = true` 且认证为开发模式时可用，否则可用性为 `sandbox_local_not_allowed`，沙箱工具组不出现，不会因此启动失败。旧的扁平键等同一个名为 `default` 的档位；没有任何沙箱配置时只有隐式的 `local` 档位。可用性原因码：`sandbox_disabled`、`sandbox_not_accepted`、`sandbox_local_not_allowed`、`sandbox_profile_unknown`。

## 技能与标准输入

技能脚本由 `exec_skill` 运行（见 `packages/skills`）。沙箱侧提供三样东西：**投射**（`nexus_sandbox/skills.py`）把技能文件按 `<技能>@<内容哈希前 12 位>` 写进会话的 `skills` 目录——先写到暂存目录再原子改名，同一哈希不会被覆盖，最多 1000 个文件、32 MB——docker 与 bwrap 把该目录只读挂载为 `/skills`，`local` 档位的命令看到宿主路径，所以直接用宿主上的目录；**命令环境**，调用方（不是模型参数）可以给一次命令追加环境变量，名字须是大写字母、数字与下划线，`exec_skill` 用它设置 `NEXUS_SKILL_DIR` 与 `NEXUS_SKILL_OUTPUT_DIR`；**标准输入**，`sandbox_exec` 与 `exec_skill` 可传最多 65536 字节的文本，三个执行器都支持（docker 用 `exec -i`），不传时仍然关闭。技能的超时有单独上限：`exec_skill` 用档位的 `skill_timeout_seconds`（默认 120）与 `skill_timeout_max_seconds`（600），不受 `exec_timeout_max_seconds` 限制。已存在的 docker 容器（改动前创建）没有 `/skills` 挂载，空闲回收后重建即带上。

## 验收项

connectivity、user、network、time_limit、output_limit、memory_limit、process_limit、tenant_isolation、path_escape、environment、cancellation、cleanup_and_residue。`local` 后端在任何探测运行前被拒绝，因为内存与进程数探测本身带有破坏性。

## 已知限制

- 路径检查与打开之间存在符号链接替换的竞态；边界由容器提供，不由路径检查提供。
- 验收报告保存在 `workspace_root/acceptance.json`，多机部署时各机各自验收。迁移到数据库表需要等仓库中迁移链稳定后进行。
- 配额以目录总大小估算，每次写入遍历一次工作区。

## 依赖环境构建（技能安装）

带 `requirements.txt` 或 `package.json` 的技能在安装时构建依赖环境（`nexus_sandbox/build.py`），运行脚本时只读使用。构建是唯一需要联网的步骤，所以在所选档位的**临时构建环境**里进行，与运行时环境分开：

- `docker`：一次性容器（标签 `nexus.sandbox.build`，`--rm`、非 root、`--cap-drop ALL`、只读根文件系统），网络取档位的 `install_network`（默认 `bridge`），只挂载清单（只读）与空的 `env` 目录（可写）；
- `bwrap`：与运行时相同的 jail，开放网络，`env` 可写；
- `local`：宿主子进程，仅开发。

产物是 `env/venv` 与 `env/node/node_modules`，另有构建结束时 `pip list` 的 `installed.json`（供验证关核对清单包，核对后删除）。构建有墙钟上限（`build_timeout_seconds`，默认 600）、日志只留末尾 60 行、目录大小上限（`env_max_mb`，默认 512）。环境放在 `<workspace_root>/_skill_envs/<档位>/<内容哈希前 16 位>-<环境指纹>/`，环境指纹是 docker 的镜像标识或宿主 Python 版本的摘要，所以同一版本在不同档位各有一份。

运行时 docker 与 bwrap 把 `_skill_envs/<档位>` 只读挂载为 `/skill_envs`（容器创建时挂载，旧容器空闲回收后重建即带上），`local` 用宿主路径；`exec_skill` 在命令前加 `PATH=<环境>/venv/bin:…:"$PATH"`，并设 `NODE_PATH`，`python3` 因而解析到环境里的解释器（`pyvenv.cfg` 在解释器旁边，目录改名后仍可用；入口脚本的 shebang 不可靠，所以不依赖它们）。本档位没有对应环境时脚本不运行，返回 `skill_env_missing` 并提示管理员对该档位重建。同一档位的所有会话能看到该档位全部环境目录（名字是哈希，内容是公开软件包）。

命令行由纯函数生成并有单元测试；docker 与 bwrap 上的真实构建**尚未验证**，本机只验证了 `local` 档位（真实 venv + 本地 wheel，含目录改名后的可用性）。
