# Nexus API

FastAPI 应用入口，提供平台资源、会话/运行与 SSE、用户模型设置 API。`http/` 处理协议，`schemas/` 定义接口，`dependencies/` 注入认证与数据库；业务服务位于 platform。仓库根目录执行 `uv run uvicorn nexus_api.main:app --reload --host 127.0.0.1`，启动前配置数据库/认证并执行 Alembic，见 [项目入口](../../README.md)。

## 登录与首个账号

- 会话 Cookie 默认带 `Secure` 标记；仅在本地 HTTP 调试时设置 `NEXUS_COOKIE_SECURE=0`。
- 企业微信扫码登录需要 `NEXUS_WECOM_CORP_ID`、`NEXUS_WECOM_AGENT_ID`、`NEXUS_WECOM_SECRET`、`NEXUS_WECOM_REDIRECT_URI`；未配置时只影响企业微信入口，密码登录不受影响。
- 首个 owner 账号通过运维命令创建，密码以隐藏输入方式读取，不接受命令行参数或环境变量：

  ```bash
  uv run python -m nexus_api.cli create-owner --tenant "公司名" --username alice --display-name "Alice"
  ```

  该命令当前未注册为 pyproject 脚本入口，需通过 `python -m` 调用。之后的成员账号由管理员在“角色与权限”页面创建。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)
