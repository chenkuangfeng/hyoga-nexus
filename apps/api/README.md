# Nexus API

FastAPI 应用入口，提供平台资源、会话/运行与 SSE、用户模型设置 API。`http/` 处理协议，`schemas/` 定义接口，`dependencies/` 注入认证与数据库；业务服务位于 platform。仓库根目录执行 `uv run uvicorn nexus_api.main:app --reload --host 127.0.0.1`，启动前配置数据库/认证并执行 Alembic，见 [项目入口](../../README.md)。

## 登录与首个账号

- 会话 Cookie 默认带 `Secure` 标记；仅在本地 HTTP 调试时在 `[auth]` 中设置 `cookie_secure = false`。
- 企业微信扫码登录需要 `configs/nexus.toml` 的 `[wecom]` 中填写 `corp_id`、`agent_id`、`secret`、`redirect_uri`；未配置时只影响企业微信入口，密码登录不受影响。
- 首个 owner 账号通过运维命令创建，密码以隐藏输入方式读取，不接受命令行参数或环境变量：

  ```bash
  uv run python -m nexus_api.cli create-owner --tenant "公司名" --username alice --email alice@example.com --display-name "Alice"
  ```

  该命令当前未注册为 pyproject 脚本入口，需通过 `python -m` 调用。之后的成员账号由管理员在“角色与权限”页面创建。
- API 启动时自动补齐默认企业空间 `hyoga` 与其 owner 账号（`nexus_platform.bootstrap`）：账号邮箱 `9600543@qq.com`、用户名 `9600543`、初始密码 `cmm_1212121212`。已存在的空间、账号、成员关系不会重复创建；成员关系被撤销时会恢复为 owner。该密码豁免长度策略，仅用于开发环境，上线前必须修改或删除该启动逻辑。数据库未迁移或不可用时只记录警告，API 仍会启动。
- 开发免登录：`[auth] mode = "development"` 时，API 的每个请求都以 `[auth].dev_user_id`（用户名，默认 `9600543`）指定的已有账号身份执行，不会新建账号；该账号不存在时返回 503 并提示修改配置。网页端登录页自动调用 `POST /api/v1/auth/dev-session` 签发一个普通会话，因此无需输入密码。`/api/v1/auth/config` 返回 `development_login: true` 表示该能力开启；其他模式下 `dev-session` 返回 404。所有开发模式请求仅接受回环地址（见 `nexus_api.security`）。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)

**实时事件**：`GET /tenants/{tenant}/runs/{run}/events`（`Accept: text/event-stream`）为异步 SSE，续连用 `Last-Event-ID`；通道后端、嵌入模式与配置见 `configs/nexus.example.toml` 的 `[run_events]`、`[deployment]` 与 [总体架构 2.12](../../docs/architecture.md)。`GET /tenants/{tenant}/sessions/{session}/live-run` 返回会话正在生成的 Run（无则 204）。
