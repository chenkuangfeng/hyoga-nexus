# 设计

## 包结构

- `packages/platform/src/nexus_platform/auth/`
  - `passwords.py`：scrypt 哈希与校验，密码长度校验。
  - `accounts.py`：账号创建、密码登录（含失败计数与锁定）、修改密码、owner 引导。
  - `sessions.py`：会话签发、解析、吊销；只保存摘要。
  - `wecom.py`：企业微信登录与绑定流程，依赖 `WeComDirectory` 协议，不直接调用企业微信 SDK。
- `packages/platform/src/nexus_platform/persistence/models/auth.py`：`LocalCredentialRecord`、`AuthSessionRecord`、`AuthStateRecord`。
- `migrations/platform/versions/c4e8a2f6d1b9_local_login_sessions.py`：创建上述三张表，接在 `b7d1e5c3a9f2` 之后。
- `apps/api/src/nexus_api/http/auth.py`：`/api/v1/auth/*` 路由；`wecom_directory.py` 从环境变量装配企业微信适配器；`cli.py` 提供 `create-owner`。

## 关键决策

1. **服务端会话，而非无状态令牌。** 吊销、修改密码后全部失效、过期检查都需要服务端状态，因此使用会话表。
2. **会话令牌只存摘要。** 数据库泄露时不能直接冒用会话。
3. **统一失败文案，锁定而非延迟。** 登录失败只返回“用户名或密码错误”，不区分用户名是否存在；无效用户名也走一次哈希，减少时序差异（`DUMMY_HASH`）。连续 5 次失败锁定 15 分钟。
4. **企业微信只登录已绑定账号。** 首次使用企业微信不会自动创建账号，避免外部身份直接获得空间权限；未绑定时提示先用密码登录，再在设置中绑定。
5. **OAuth 风格的一次性 state。** 登录与绑定共用一个回调，由服务端保存的 `purpose` 决定走哪条流程；state 10 分钟过期，用后即标记消费，重复使用失败。
6. **账号归属空间。** 管理员创建账号时同时写入空间成员关系与角色，权限仍由既有的角色与授权模型（`members:manage`）控制。

## 数据与接口影响

- 新增三张表，不修改已有表结构；`user_identities` 被会话表外键引用。
- 新增接口：`/api/v1/auth/login`、`/logout`、`/me`、`/password`、`/wecom/start`、`/wecom/bind/start`、`/wecom/callback`；`/api/v1/tenants/{tenant_id}/accounts`。
- Cookie 名称与 `NEXUS_COOKIE_SECURE`（默认开启，设为 `0` 仅用于本地 HTTP 调试）。
- 企业微信配置环境变量：`NEXUS_WECOM_CORP_ID`、`NEXUS_WECOM_AGENT_ID`、`NEXUS_WECOM_SECRET`、`NEXUS_WECOM_REDIRECT_URI`。未配置时企业微信入口不可用，密码登录不受影响。

## 已知边界

- 会话过期后不自动续期，固定 12 小时。
- 锁定只按账号计数，未做按 IP 限流。
- 企业微信回调依赖外部服务可达，本地测试使用假的 `WeComDirectory`。
- 迁移与登录流程在 SQLite 上的测试已通过；未在 PostgreSQL 上验证（见 `verification.md`）。
