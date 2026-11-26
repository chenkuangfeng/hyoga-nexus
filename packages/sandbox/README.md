# nexus_sandbox

沙箱后端、租约与隔离验收，供 `sandbox` 工具组使用。提案：`openspec/changes/2026-11-07-tool-expansion`。

## 使用

1. 缺省启用沙箱并预置 `docker` / `local`，默认选 Docker。可在 `configs/nexus.toml` 的 `[sandbox]` 覆盖（见 `configs/nexus.example.toml`）；显式 `enabled = false` 仍关闭，显式档位列表不自动补入默认项。
2. 确保镜像已在本机（沙箱从不自动拉取），且包含 `sh`、`timeout`、`python3`。
3. 运行 `uv run python -m nexus_worker --sandbox-check`，全部通过后写入验收报告（平台数据库的 `sandbox_acceptance` 表，并在 `workspace_root` 下留一份 JSON 副本；未配置数据库时只写文件）。 worker 启动时会对未通过验收的档位打警告（只读，不自动验收）。
4. 在智能体编辑器里打开「沙箱」工具组并勾选需要的工具。部署、验收、智能体开关三者缺一，工具都不会出现。

`local` 后端不隔离，只用于开发，需要 `allow_local = true` 和开发认证模式，且不能运行验收。

## 模块

见 [设计](docs/design.md)。

## 远程节点

- **SSH**：远端安装同一版本的 `hyoga-nexus-sandbox` 和 bwrap。将共享工作区挂载到远端，并给执行账号配置启用的断网 bwrap 档位。SSH 账号登录时需能运行 `python3 -m nexus_sandbox.remote_runner`，且以节点配置目录为工作目录（例如在账号家目录下放置 `configs/nexus.toml`）。建议用该账号的 SSH 强制命令绑定这一入口。worker 的档位使用部署已核验的 known_hosts 与专用私钥。
- **托管网关**：在独立的 Docker 执行节点部署应用依赖，挂载共享工作区，配置允许的断网 Docker 档位和 `[sandbox_gateway]`。启动 `uv run uvicorn nexus_api.sandbox_gateway:app --workers 1` 并通过 HTTPS 提供服务。worker 用 `managed` 档位配置端点、凭据文件和远端档位名称。
- **管理端**：企业设置中的「沙箱引擎」显示运行策略、支持的能力和最近验收。企业 owner/admin 与平台管理员可在详情中暂停档位或设置超时。首次启用或更换远端配置后，在实际 worker 节点执行 `uv run python -m nexus_worker --sandbox-check --profile NAME`。

参见 [部署样例](../../configs/nexus.example.toml) 与 [网关协议](docs/design.md#托管网关协议-v1)。

## E2B 与 CubeSandbox 适配器

企业 owner/admin 与平台管理员可在「沙箱引擎 → 配置详情 → 供应商与实例管理」选择 E2B 或 CubeSandbox，填写模板、域名、环境版本和 API Key。密钥使用部署凭据加密主密钥加密保存到网关状态目录；网关需配置与平台相容的主密钥。界面仅返回已配置状态。运行中或待回收实例存在时拒绝更换配置。

也可在独立网关的部署文件中定义初始供应商配置：

```toml
[sandbox_gateway.providers.node-docker]
type = "e2b" # 或 cubesandbox
template = "your-template-id"
domain = "e2b.app"
revision = "immutable-template-build-version"
api_key_file = "/run/secrets/provider_key"
```

域名需支持 SDK 的 `https://api.<domain>` 和数据面路由。模板需提供 Python 3.11+、Shell、root 文件准备能力和无 sudo/提权权限的 `user` 账号。CPU 与内存必须匹配资源档位，实例创建后还会查询供应商实际分配值。PID 由实例内核的 UID 进程数限制控制，每个请求使用独立 VM。环境版本应对应供应商的不可变模板构建，更新模板时同步更新版本并重新验收。

实例通过供应商文件 API 接收当前会话及技能，工作目录为 `/workspace`，交付目录为 `/outputs`。技能文件由 root 持有且对执行账号只读。每个快照最多 4096 个条目，单文件 50 MiB，总计不超过档位配额和 200 MiB 中的较小值。链接、特殊文件与扩展归档头被拒绝。会话快照下载后经过完整校验才提交，包含文件删除。实例无需挂载 worker 的共享卷；worker 与网关继续共享会话文件目录。

## 连接、验收与恢复

1. 在管理端点击「验证连接」，绑定网关节点、镜像或供应商模板版本、资源策略及适配器代码摘要。
2. 在实际 worker 节点运行 `uv run python -m nexus_worker --sandbox-check --profile NAME`。连接验证本身不开放执行工具。
3. 网关会拒绝策略摘要不匹配的请求。更换节点、模板版本、资源限制或适配器代码后，重新验证连接并验收。
4. 网关状态目录默认为 `<workspace_root>/_gateway_state`，也可用 `[sandbox_gateway].state_root` 指定。保留该目录才能进行重启恢复；同一目录只允许一个网关进程。
5. 网关启动和每 30 秒重试回收未结束实例。创建响应未知时通过请求元数据查找实例，保留记录直到实例硬 TTL 过去。原命令不会重放。管理端可查看待回收状态并重试回收。

实例内 runner 在读流时保留输出头尾，SDK 只接收控制结果。有界文件下载使用携带访问令牌请求头的流式 HTTP，避免 SDK 的文件读取缓冲。命令超时会结束进程组并保存已生成的文件；取消时尽量导出部分文件，然后销毁实例。

## Linux 资源限额

bwrap 可配置 `cgroup_root`，指向已由运维委派并启用 `cpu memory pids` 控制器的 cgroup v2 子树，同时配置 `cpus`、`memory_mb` 和 `pids`。Nexus 为每条命令创建子 cgroup，设置 CPU、内存、swap 和 PID 限额，结束后杀净进程并回收子组。未配置时保留已有的地址空间限制与进程回收语义；配置失效时执行被拒绝。

Docker 和 bwrap 可配置 `quota_mount`、`quota_project_start` 和 `quota_inodes` 启用 XFS project quota。目录需位于已启用项目配额的 XFS 挂载下；运维需为本部署预留从 `quota_project_start` 开始的 100000 个项目 ID，并提供执行 `xfs_quota` 的权限。字节硬限额沿用 `workspace_quota_mb`。这会约束 Shell 直接写入和 inode 消耗。配额配置错误时执行被拒绝；未配置时仅有文件工具与快照配额。原子文件更新和快照发布需要额外临时空间。

Docker 命令、文件工具写入和供应商同步使用共享卷上的跨进程锁。回收器获取独占锁并检查空闲时间后才删除容器。分布式部署的文件系统必须提供可靠的 POSIX 锁语义。

参见 [部署样例](../../configs/nexus.example.toml) 与 [网关协议](docs/design.md#托管网关协议-v1)。

企业 owner/admin 与平台管理员可在企业管理端“沙箱引擎”新增或编辑五种执行档位，配置写入 API 与 worker 共享控制卷并自动加载。全局启用与本地执行许可仍由部署配置控制。SSH 与网关凭据填写执行节点上的文件路径。托管配置保存后在详情验证连接，并在 worker 完成隔离验收。默认档位及被智能体引用的档位不能删除，详见 [配置注册设计](docs/design.md#控制台配置注册)。

## 控制台保存位置与反馈

控制台新增、编辑、删除写入 `<workspace_root>/_sandbox_profiles.json`，默认路径为 `data/sandbox/_sandbox_profiles.json`，不修改 `configs/nexus.toml`。API 与 worker 必须读取同一共享目录。保存成功会重新读取目录并显示配置；保存配置不等于通过执行验收。编辑器固定底部显示未满足的保存条件及保存错误，输入不会因失败丢失；发生修订冲突时关闭编辑器并刷新列表后再提交。

配置保存支持 Windows API 宿主，使用 Windows 文件锁并在临时文件关闭后替换共享注册文件；无需安装 `fcntl`。配置使用 UTF-8，支持中文名称。执行节点仍须满足各后端的运行条件，配置保存兼容不等于 Windows 原生隔离验收通过。
