# 部署配置

在仓库根目录将 `nexus.example.toml` 复制为 `nexus.toml`，填写 `[database].url`。真实文件已被 Git 忽略，不提交凭据。API、worker 与 Alembic 启动时自动读取该路径，无需加载 `.env`，修改后重启服务生效。

```toml
[database]
url = "postgresql+psycopg://nexus:CHANGE_ME@127.0.0.1:5432/nexus"
```

从仓库根目录执行 `uv run python -m nexus_worker`、`uv run uvicorn nexus_api.main:app --reload` 或 `uv run alembic -c alembic.ini upgrade head`。PowerShell 和 Bash 共用相同 TOML 格式。部署工作目录决定配置位置，相对 SQLite 路径也相对于该目录；SQLite 仅用于隔离验证，不能代替 PostgreSQL 部署验收。

数据库配置优先级：调用者显式 URL > 文件 `[database].url` > 已设置的 `NEXUS_DATABASE_URL`。文件缺失或没有数据库字段允许环境变量兼容；非法 TOML、错误类型及空连接串会报配置错误，不静默切换数据库。Alembic 编程调用可通过 `Config.attributes["database_url"]` 显式注入测试连接串；不再使用 `alembic.ini` 的数据库默认值。错误不包含连接串或原始配置片段。

本次文件只管理部署数据库连接，不管理用户模型与智能体配置。认证、加密主密钥、日志和模型网络策略仍按现有部署环境变量配置，见[本地开发](../README.md#本地开发)与 [worker 说明](../apps/worker/README.md)。不自动加载 `.env`。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)
- [智能体配置预留](agents/README.md)
- [模型配置预留](models/README.md)
- [渠道配置预留](channels/README.md)
