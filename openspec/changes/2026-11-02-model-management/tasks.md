# 实施任务：模型管理

状态：已确认（2026-11-02），已实施；PostgreSQL 迁移未验证（见第 4 节）。

## 0. 确认

- [x] 确认 proposal.md 的四项决定（均采用建议选项 A）。
- [x] 按确认结果修订 design.md。

## 1. 持久化

- [x] 迁移：`model_profiles.model_type` 增加，已有行回填 `chat`（`migrations/platform/versions/0a7c3e9d1b5f_model_types.py`）。
- [x] 迁移：`model_defaults` 重建并把 `model_type` 加入主键，已有行归为 `chat`；降级只保留对话默认值。
- [x] 持久化模型与迁移测试（`tests/test_model_types_migration.py`，SQLite 往返升降级通过）。

## 2. 后端

- [x] `validate_model_options` 与 `model_type` 校验；类型创建后不可变，编辑时更改返回 409。
- [x] 默认模型按类型读写（`set_default`、`list_settings`）；版本类型与槽位不一致返回 409。
- [x] `POST .../model-settings/test`：未保存配置的连接测试，含限频、超时、错误码与审计。（草稿限频在进程内按用户计，见 design.md）
- [x] 保存接口接受 `model_type`，非法值返回 422（Pydantic 校验）。

## 3. 前端

- [x] `ModelSettingsView.vue`：类型标签页与计数，卡片网格，添加卡片。
- [x] `ModelEditorDrawer.vue`：类型切换、服务商（含内联新建）、模型预设、连接、高级选项、实际调用方式。来源切换未做（本阶段固定 API）。
- [x] `data/modelPresets.ts`：静态预设（只填充名称，不写入后端）。
- [x] 默认设置区块按类型显示（类型 × 作用域表格），每次选择即时保存。
- [x] 中英文文案（`i18n/locales/zh-CN.ts`、`en-US.ts`）与 key 一致性检查（`vue-tsc` 通过）。

## 4. 验证

- [x] `uv run --locked pytest`：553 通过，1 跳过（`test_platform_postgres.py` 需要 `NEXUS_TEST_POSTGRES_URL`，本环境未提供）。
- [x] `npm run build` 通过（含 `vue-tsc`）。
- [x] `tests/web/model-settings.mjs` 按新界面更新并通过；其余 7 个浏览器套件也通过。
- [x] 模型页在 375px 下无横向溢出（浏览器测试）；外壳的 375 / 768 / 1024 / 1440 px 由 `layout.mjs` 覆盖。
- [x] 迁移前后的对话默认模型保持不变（迁移往返测试核对）。

## 4. 未验证项

- PostgreSQL 迁移：迁移使用重建表的方式（重命名旧表、创建新表、复制数据、删除旧表），SQLite 已验证；PostgreSQL 需在 `NEXUS_TEST_POSTGRES_URL` 指向的库上执行 `alembic upgrade head` 并复核。本环境无法访问 Docker，因此未运行。
- 草稿连接测试的限频（同一用户 10 秒一次）保存在进程内存中。多进程部署时实际上限会放宽，需要时改为数据库或共享存储。

## 5. 收尾

- [ ] 更新 `docs/roadmap.md` 中阶段 2 的相关条目（待你确认是否由本变更更新）。
- [ ] 按 OpenSpec 工作流同步规格并归档。
