# Nexus Worker

worker 领取平台 Outbox，装配 Native Engine，并通过短事务保存消息、工具状态与事件。运行：

```bash
uv run python -m nexus_worker
```

API 与 worker 使用同一 `NEXUS_DATABASE_URL`，启动前运行 `uv run alembic upgrade head`。SQLite 用于本轮隔离测试；PostgreSQL 部署验收仍待目标环境执行。

模型配置通过平台 `/docs` 创建：

1. 创建 `environment` 类型凭据引用，handle 为 `env://NEXUS_MODEL_API_KEY`。引用不包含秘密值。
2. 在 worker 的本地环境设置该变量，并设置 `NEXUS_MODEL_CREDENTIAL_ALLOWLIST=NEXUS_MODEL_API_KEY`。不将变量值写进仓库或聊天。
3. 模型配置 `provider` 按供应商命名，`model_name` 填账号实际可用的模型，`options` 设置 `{"protocol":"openai_chat_completions","base_url":"https://api.openai.com/v1"}`，并关联凭据引用。兼容供应商须验证支持流式工具调用、usage 和 `max_completion_tokens`。
4. 创建并发布 Native Agent，选择该模型版本，配置预算；前端选择已发布智能体新建会话。

安全内置工具为 `ask_user`、`update_working_checkpoint`、`propose_memory_draft`。先由管理员调用 `POST /api/v1/workspaces/{workspace_id}/tools/{name}/enable` 登记，再在 Agent 中以 `kind=tool`、`resource_id=工具名`、`resource_version_id=v1` 显式绑定并发布。登记本身不授予调用权限，执行前继续复核 Workspace、主体、Run、绑定和 grant。

自定义 Python 工具在应用组合入口通过 `ToolRegistry` 注册；处理器接收可信 `ToolContext` 和取消信号，显式声明副作用、deadline 和公开输出投影。不得注册阻塞宿主命令或把普通 Python 函数称作沙箱。

缺少协议/Runtime 时以 `runtime_not_configured` 失败；凭据不可用时为 `model_credential_unavailable`。收到进程停止信号会取消当前受控执行；可能发生但结果未知的副作用标记 interrupted，不自动重试。外部 Runtime、隔离 Sandbox、文件产物和生产凭据后端仍未接入。
