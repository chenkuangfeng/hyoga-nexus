# Nexus Worker

worker 领取平台 Outbox，装配 Native Engine，并通过短事务保存消息、工具状态与事件。运行：

```bash
uv run python -m nexus_worker
```

在仓库根目录运行上述命令，配置步骤见[项目入口](../../README.md#本地开发)。API 与 worker 自动读取同一个 `configs/nexus.toml` 中的 `[database].url`，启动前运行 `uv run alembic -c alembic.ini upgrade head`。SQLite 用于本轮隔离测试；PostgreSQL 部署验收仍待目标环境执行。

推荐通过前端「用户设置 → 模型供应商」创建供应商、填写 API 地址与 Key，添加账号可用模型，并设置个人/空间默认模型。管理员先在 API 与 worker 共用的 `configs/nexus.toml` 的 `[security]` 中配置相同的 `credential_encryption_key`（Fernet 格式），随后重启服务；主密钥不进入仓库。可以在本地安全终端生成后保存到部署秘密管理中：

```bash
uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
```

完成 `uv run alembic -c alembic.ini upgrade head` 后可保存设置。不要反复生成并覆盖已有主密钥，否则现有密文无法解析。设置页提供测试连接和创建/发布 Native 智能体；测试可能产生少量费用。更换模型地址需要新 Key，旧版本保留旧地址和凭据；同地址替换 Key 会应用于已有引用的后续调用。

既有环境凭据方式仍可通过平台 `/docs` 创建：

1. 创建 `environment` 类型凭据引用，handle 为 `env://NEXUS_MODEL_API_KEY`。引用不包含秘密值。
2. 在 `configs/nexus.toml` 的 `[model_credentials]` 中添加 `NEXUS_MODEL_API_KEY = "..."`。表中的名称即白名单，未列出的名称无法解析；不将真实值写进仓库或聊天。
3. 模型配置 `provider` 按供应商命名，`model_name` 填账号实际可用的模型，`options` 设置 `{"protocol":"openai_chat_completions","base_url":"https://api.openai.com/v1"}`，并关联凭据引用。兼容供应商须验证支持流式工具调用、usage 和 `max_completion_tokens`。
4. 创建并发布 Native Agent，选择该模型版本，配置预算；前端选择已发布智能体新建会话。

安全内置工具为 `ask_user`、`update_working_checkpoint`、`propose_memory_draft`。先由管理员调用 `POST /api/v1/tenants/{tenant_id}/tools/{name}/enable` 登记，再在 Agent 中以 `kind=tool`、`resource_id=工具名`、`resource_version_id=v1` 显式绑定并发布。登记本身不授予调用权限，执行前继续复核 Tenant、主体、Run、绑定和 grant。

自定义 Python 工具在应用组合入口通过 `ToolRegistry` 注册；处理器接收可信 `ToolContext` 和取消信号，显式声明副作用、deadline 和公开输出投影。不得注册阻塞宿主命令或把普通 Python 函数称作沙箱。

缺少协议/Runtime 时以 `runtime_not_configured` 失败；凭据不可用时为 `model_credential_unavailable`。收到进程停止信号会取消当前受控执行；可能发生但结果未知的副作用标记 interrupted，不自动重试。外部 Runtime、隔离 Sandbox、文件产物和外部凭据保险库仍未接入。模型请求默认只允许公网 HTTPS；可信私有模型需部署端在 `configs/nexus.toml` 的 `[model_network].private_host_allowlist` 中显式配置，API 与 worker 使用相同文件。沙箱仅保留接口。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)
