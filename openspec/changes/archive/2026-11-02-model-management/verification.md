# 验证结果

验证时间：2026-11-02，提交 `f1a2d6c`。

- `uv run --locked pytest`：553 passed，1 skipped。跳过项为 `tests/test_platform_postgres.py`，需要 `NEXUS_TEST_POSTGRES_URL`，本环境未提供。
- `tests/test_model_settings.py`：10 passed，覆盖类型校验与固定、按类型的默认、未保存配置的连接测试（不落库、不向非对话类型发请求、限频）、新建供应商缺 Key 与权限不足。
- `tests/test_model_types_migration.py`：SQLite 上升级到 head、重复升级、降级往返通过；默认值归为 `chat`，降级只保留对话默认。
- `apps/web`：`npm run build`（含 `vue-tsc --noEmit`）通过。
- 浏览器测试（Vite 开发服务 `localhost:5173`，Playwright Chromium）：`model-settings.mjs` 通过；其余 7 个套件（auth、conversation、roles、organization、i18n、layout、keyboard）均通过。
- 未验证：PostgreSQL 上的迁移。迁移重建 `model_defaults`，SQLite 已验证；需在目标库执行 `alembic upgrade head` 与降级后复核。本环境无法访问 Docker。
- 未验证：真实供应商的连接测试；非对话类型的实际调用（随知识库阶段）。
