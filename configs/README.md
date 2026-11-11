# 部署配置

在仓库根目录将 `nexus.example.toml` 复制为 `nexus.toml`，填写 `[database].url` 及其他需要的段落。真实文件已被 Git 忽略，不提交凭据。API、worker 与 Alembic 启动时自动读取该路径；所有部署配置只来自此文件，环境变量与 `.env` 不再生效。修改后重启服务生效。

```toml
[database]
url = "postgresql+psycopg://nexus:CHANGE_ME@127.0.0.1:5432/nexus"
```

从仓库根目录执行 `uv run python -m nexus_worker`、`uv run uvicorn nexus_api.main:app --reload` 或 `uv run alembic -c alembic.ini upgrade head`。PowerShell 和 Bash 共用相同 TOML 格式。部署工作目录决定配置位置，相对 SQLite 路径也相对于该目录；SQLite 仅用于隔离验证，不能代替 PostgreSQL 部署验收。

数据库配置优先级：调用者显式 URL > 文件 `[database].url`。文件缺失或没有数据库字段会报配置错误，不回退其他来源；非法 TOML、错误类型及空连接串同样报错。Alembic 编程调用可通过 `Config.attributes["database_url"]` 显式注入测试连接串；不再使用 `alembic.ini` 的数据库默认值。错误不包含连接串或原始配置片段。

文件分段：`[database]` 数据库，`[auth]` 认证与 Cookie，`[logging]` 日志级别，`[security]` 凭据加密主密钥，`[model_credentials]` 模型供应商密钥（同时作为白名单），`[model_network]` 私有地址白名单，`[wecom]` 企业微信登录，`[platform]` 与 `[model_connection_pool]` 运行限制，`[watchdog]` Run 停滞检测（只报告，不取消），`[knowledge]` 知识库内置存储目录（原文件与内置 SQLite 向量库）、单次上传上限与索引并发数，以及 `allow_tenant_local_stores`（默认 `false`：企业不能自建以服务器路径为存储的 `sqlite` 向量库与 `local` 原文件存储，只适合单企业部署时打开；企业配置的外部向量库、存储与图存储地址须为公网地址，私有地址须列入 `[model_network].private_host_allowlist`），`[sandbox]` 沙箱（默认关闭；运维用 `[sandbox.profiles.<名字>]` 定义 `local` / `docker` / `bwrap` 档位，`default_profile` 缺省为 `local`，智能体按名字选择档位；`local` 不是隔离，仅在 `allow_local = true` 且开发认证模式下可用；启用后须运行 `uv run python -m nexus_worker --sandbox-check [--profile 名字]` 并通过隔离验收，沙箱工具组才会出现，且仍需在智能体里打开；旧的扁平键仍有效，等同一个名为 `default` 的档位），`[web]` 联网工具组（默认关闭；`web_search` 的后端与密钥、`web_fetch` 的大小与超时限制），`[skills]` 技能（`allow_local_scripts` 本地脚本门禁，仅开发模式；`builtin_dir` 内置技能目录，缺省 `skills`）。用户模型与智能体配置仍保存在数据库中，不在此文件管理。

## 按规模选择的示例

`profiles/` 下有三份可直接复制为 `nexus.toml` 的起步配置，数值是按架构估算的，上线前请压测后调整：

| 文件 | 场景 | 部署 | 数据库 | 事件通道 |
| --- | --- | --- | --- | --- |
| [`profiles/dev.example.toml`](profiles/dev.example.toml) | 开发、个人 | `embedded`，一个 API 进程 | SQLite | `memory` |
| [`profiles/team.example.toml`](profiles/team.example.toml) | 几十人的团队，单机 | `embedded`（或 `split` 加一个 worker） | PostgreSQL | `memory`（`split` 时 `database`） |
| [`profiles/production.example.toml`](profiles/production.example.toml) | 32 核 128GB 的生产服务器 | `split`，4 个 API 进程加 8 个 worker 进程 | PostgreSQL | `redis` |

几条要记住的关系：`embedded` 只能配一个 API 进程（`memory` 通道在进程内）；多个 API 或 worker 进程必须用 `redis` 或 `database` 通道；`max_concurrent_sessions` 不应小于 worker 进程数乘以每进程的 `max_concurrent_runs`，否则会话上限先到；数据库连接池为线程数加 4，PostgreSQL 的 `max_connections` 要大于所有进程的连接池之和；SQLite 只有单写者，并发固定为 4。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)
- [智能体配置预留](agents/README.md)
- [模型配置预留](models/README.md)
- [渠道配置预留](channels/README.md)
