# nexus_sandbox

沙箱后端、租约与隔离验收，供 `sandbox` 工具组使用。提案：`openspec/changes/2026-11-07-tool-expansion`。

## 使用

1. 在 `configs/nexus.toml` 写 `[sandbox]`（见 `configs/nexus.example.toml`），`enabled = true`。
2. 确保镜像已在本机（沙箱从不自动拉取），且包含 `sh`、`timeout`、`python3`。
3. 运行 `uv run python -m nexus_worker --sandbox-check`，全部通过后写入验收报告（平台数据库的 `sandbox_acceptance` 表，并在 `workspace_root` 下留一份 JSON 副本；未配置数据库时只写文件）。 worker 启动时会对未通过验收的档位打警告（只读，不自动验收）。
4. 在智能体编辑器里打开「沙箱」工具组并勾选需要的工具。部署、验收、智能体开关三者缺一，工具都不会出现。

`local` 后端不隔离，只用于开发，需要 `allow_local = true` 和开发认证模式，且不能运行验收。

## 模块

见 [设计](docs/design.md)。

## 远程节点

- **SSH**：远端安装同一版本的 `hyoga-nexus-sandbox` 和 bwrap。将共享工作区挂载到远端，并给执行账号配置启用的断网 bwrap 档位。SSH 账号登录时需能运行 `python3 -m nexus_sandbox.remote_runner`，且以节点配置目录为工作目录（例如在账号家目录下放置 `configs/nexus.toml`）。建议用该账号的 SSH 强制命令绑定这一入口。worker 的档位使用部署已核验的 known_hosts 与专用私钥。
- **托管网关**：在独立的 Docker 执行节点部署应用依赖，挂载共享工作区，配置允许的断网 Docker 档位和 `[sandbox_gateway]`。启动 `uv run uvicorn nexus_api.sandbox_gateway:app --workers 1` 并通过 HTTPS 提供服务。worker 用 `managed` 档位配置端点、凭据文件和远端档位名称。
- **管理端**：企业设置中的「沙箱引擎」显示运行策略、支持的能力和最近验收。平台管理员可在详情中暂停档位或设置超时。首次启用或更换远端配置后，在实际 worker 节点执行 `uv run python -m nexus_worker --sandbox-check --profile NAME`。

参见 [部署样例](../../configs/nexus.example.toml) 与 [网关协议](docs/design.md#托管网关协议-v1)。

## E2B 与 CubeSandbox 适配器

兼容网关支持 E2B 协议的供应商模板。网关配置增加以下表，名称与已有的网关 Docker 策略档位相同，策略字段用于匹配 worker 的资源要求。实际执行将交给供应商模板。

```toml
[sandbox_gateway.providers.node-docker]
type = "e2b" # 或 cubesandbox
template = "your-template"
domain = "e2b.app" # CubeSandbox 使用自己的域名
api_key_file = "/run/secrets/provider_key"
```

域名需支持 SDK 标准的控制面 `https://api.<domain>` 和数据面域名路由，自建 CubeSandbox 应配置对应 HTTPS 反向代理。模板需预设匹配的 CPU、内存与 PID 限制，提供 Python、Shell、mount 及无 sudo、无提权权限的非特权 user 账号，并将与 worker 相同的共享工作区挂到 `/nexus`。适配器通过随机文件验证挂载，映射当前会话的 `/workspace`、`/outputs` 和只读 `/skills`，命令完成后销毁实例。普通 E2B Cloud 模板没有该挂载，需要先准备可访问共享文件系统的自定义模板。真实供应商验收通过后才能开放给智能体。
