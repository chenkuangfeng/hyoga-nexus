# 验证结果

验证时间：2026-10-31，提交 `cc8a573` 之前的工作区。

- `uv run --locked pytest`：309 passed，1 skipped。
- `uv run --locked pytest tests/test_auth.py`：12 passed，覆盖密码登录与 Cookie、统一失败与锁定、摘要存储、修改密码吊销会话、管理员建号、企业微信登录与绑定、state 重用、企业微信身份不可绑定到两个账号、会话过期、owner 引导重复用户名、短密码拒绝、哈希往返。
- `apps/web`：`npm run build`（含 `vue-tsc --noEmit`）通过，退出码 0。
- 浏览器测试（2026-10-31 补充，Vite 开发服务 `127.0.0.1:5173`，Playwright Chromium）：`auth.mjs`、`conversation.mjs`、`model-settings.mjs`、`roles.mjs` 均通过。
- 未验证：PostgreSQL 上的迁移与并发。用户决定当前版本使用 SQLite，跳过该项验证（本机无 PostgreSQL 服务，`.env` 指向 SQLite）。
- 未验证：真实企业微信回调；`create-owner` 的端到端调用（仅有测试覆盖）。
