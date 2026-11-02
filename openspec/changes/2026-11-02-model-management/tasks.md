# 实施任务：模型管理

状态：提案草稿，待确认。确认前不编码；以下任务均未开始。

## 0. 确认

- [ ] 确认 proposal.md 的四项决定（非对话类型、未保存测试、默认按类型拆分、前端静态预设）。
- [ ] 按确认结果修订 design.md。

## 1. 持久化

- [ ] 迁移：`model_profiles.model_type` 增加，已有行回填 `chat`。
- [ ] 迁移：`model_defaults` 主键加入 `model_type`，已有行归为 `chat`。
- [ ] 持久化模型与迁移测试。

## 2. 后端

- [ ] `validate_model_options` 与 `model_type` 校验。
- [ ] 默认模型按类型读写（`set_default`、`list_settings`）。
- [ ] `POST .../model-settings/test`：未保存配置的连接测试，含限频、超时、错误码与审计。
- [ ] 保存接口接受 `model_type`，非法值返回 400。

## 3. 前端

- [ ] `ModelSettingsView.vue`：类型标签页与计数，卡片网格，添加卡片。
- [ ] `ModelEditorDrawer.vue`：类型与来源切换、服务商、模型预设、连接、高级选项、实际调用方式。
- [ ] `data/modelPresets.ts`：静态预设。
- [ ] 默认设置区块按类型显示，每次选择即时保存。
- [ ] 中英文文案（`i18n/locales/zh-CN.ts`、`en-US.ts`）与 key 一致性检查。

## 4. 验证

- [ ] `uv run --locked pytest` 全部通过（含迁移与接口测试）。
- [ ] `npm run build` 通过（含 `vue-tsc`）。
- [ ] `tests/web` 模型页浏览器测试按新界面更新并通过。
- [ ] 375 / 768 / 1024 / 1440 px 无横向溢出。
- [ ] 迁移前后的对话默认模型保持不变（手工或脚本核对）。

## 5. 收尾

- [ ] 更新 `docs/roadmap.md` 中阶段 2 的相关条目（确认后）。
- [ ] 按 OpenSpec 工作流同步规格并归档。
