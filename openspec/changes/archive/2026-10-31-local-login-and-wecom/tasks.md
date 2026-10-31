# 实施任务

- [x] 用户确认本提案（事后补写，于 2026-10-31 确认）。
- [x] 实现密码哈希、账号创建、密码登录、失败锁定与修改密码。
- [x] 实现服务端会话表、摘要存储、过期与吊销。
- [x] 实现企业微信登录与绑定，含一次性 state 与用途区分。
- [x] 实现管理员创建账号接口与 `create-owner` 引导命令。
- [x] 增加登录页、我的账号页、角色页“添加账号”表单及登录态检查。
- [x] 增加三张表的迁移 `c4e8a2f6d1b9`。
- [x] 增加后端测试 `tests/test_auth.py`（12 项）与 Web 浏览器测试 `tests/web/auth.mjs`。
- [ ] 在 PostgreSQL 上执行迁移与登录流程验证。（已跳过：用户决定当前使用 SQLite，暂不做 PostgreSQL 验证。）
- [x] 在部署文档中写明 `create-owner` 调用方式（`apps/api/README.md`；暂不注册为 pyproject 脚本入口）。
- [x] 更新 `apps/api` 与 `packages/platform` 的 README，说明登录配置、环境变量与认证模块位置。
- [x] 运行 Web 浏览器测试 `auth.mjs`，并补跑 `conversation`、`model-settings`、`roles` 共四项，全部通过。
- [x] 同步规格到 `openspec/specs/local-login/spec.md`，归档本变更。
