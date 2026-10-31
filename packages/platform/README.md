# Nexus Platform

管理身份/空间、模型与凭据、智能体版本、会话/运行、资源授权和审计。模型设置实现位于 `src/nexus_platform/models/provider_settings.py`，数据库定义位于 `persistence/models/`（按领域组织，共用 `persistence/base.py` 的 metadata）。由 API 和 worker 注入数据库会话与主体，不作为独立服务启动。本地账号、会话与企业微信绑定位于 `src/nexus_platform/auth/`（密码哈希、账号、会话、企业微信流程），对应表定义在 `persistence/models/auth.py`。数据库升级使用根目录 Alembic 命令，模型使用说明见 [worker](../../apps/worker/README.md)。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)

Run 写入规则位于 `runs/submission.py`、`cancellation.py`、`inputs.py`；领域值对象、事务端口和 SQLAlchemy 适配分别组织。原 `runs.service`、`runs.execution` 调用入口保持兼容，具体边界见 [平台设计](docs/design.md)。
