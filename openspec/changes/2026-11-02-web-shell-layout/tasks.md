# 实施任务

状态：待确认提案（见 proposal.md 的"需要你决定的项"）。

## 准备

- [x] 阅读 WeKnora 的 `frontend/src/components/menu.vue` 与 `views/platform/index.vue`，结论写入 design.md。
- [ ] 确认 proposal.md 中的决定 1–4。

## 外壳

- [ ] `AppShell.vue`：侧栏 + 主内容区，展开状态记入 localStorage。
- [ ] `AppSidebar.vue`：Logo、搜索入口、空间选择器、分组导航、用户区。
- [ ] 断点：≥1024 展开，768–1023 图标列，<768 抽屉。
- [ ] 导航表与 `visible(user)`；平台管理员入口仅对管理员显示。

## 页面迁移

- [ ] 去掉各页面的重复空间下拉，统一读取侧栏的当前空间。
- [ ] 对话页会话列表移入侧栏（若决定 3 采纳）。
- [ ] 删除 `App.vue` 中的顶部平铺按钮。

## 验证

- [ ] `npm run build` 通过。
- [ ] `tests/web/*.mjs` 按新选择器更新并全部通过。
- [ ] 375/768/1024/1440 宽度截图检查，无横向滚动。
- [ ] 键盘可打开、关闭、切换侧栏，焦点可见。
- [ ] `uv run --locked pytest` 全部通过。
