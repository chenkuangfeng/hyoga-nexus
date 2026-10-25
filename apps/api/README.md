# Nexus API

FastAPI 应用入口，提供平台资源、会话/运行与 SSE、用户模型设置 API。`http/` 处理协议，`schemas/` 定义接口，`dependencies/` 注入认证与数据库；业务服务位于 platform。仓库根目录执行 `uv run --env-file .env uvicorn nexus_api.main:app --reload --host 127.0.0.1`，启动前配置数据库/认证并执行 Alembic，见 [项目入口](../../README.md)。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)
