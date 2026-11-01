# 实施任务

状态：提案已确认（2026-11-02），已实施；浏览器测试与构建通过。

## 准备

- [x] 阅读 WeKnora 的 `frontend/src/components/menu.vue` 与 `views/platform/index.vue`，结论写入 design.md。
- [x] 确认 proposal.md 中的决定 1–4。

## 外壳

- [x] `layouts/AppLayout.vue`：侧栏 + 主内容区，展开状态记入 localStorage。
- [x] `layouts/AppSidebar.vue`：Logo、空间选择器、分组导航、会话列表、用户区。全局搜索入口未做。
- [x] 断点：≥1024 展开，768–1023 图标列，<768 抽屉（Esc 关闭）。
- [x] 导航表（`router/navigation.ts`）；平台管理分组与路由仅对管理员显示，非管理员访问被重定向。

## 页面迁移

- [x] 去掉各页面的重复空间下拉，统一读取侧栏的当前空间（管理员会话查询的筛选与组织绑定目标保留）。
- [x] 对话页会话列表移入侧栏。
- [x] 删除 `App.vue` 中的顶部平铺按钮；后端 WeCom/OIDC 重定向改为路径。

## 验证

- [x] `npm run build` 通过（含 `vue-tsc`）。
- [x] `tests/web/*.mjs` 更新导航地址与会话列表的模拟响应，五个脚本全部通过。
- [x] 375/768/1024/1440 宽度检查：无横向滚动；<768 抽屉关闭时侧栏隐藏。（截图中的中文因沙箱缺少 CJK 字体显示为方块，属于环境问题。）
- [~] 键盘可打开、关闭、切换侧栏，焦点可见：按钮可聚焦并有 focus-visible 样式，Esc 关闭抽屉；未做完整的键盘脚本测试。
- [x] `uv run --locked pytest` 全部通过（`tests/test_auth.py` 已按新重定向更新）。

## 未实施

- 全局搜索入口（侧栏顶部的搜索按钮）：当前没有可搜索的统一入口，未实现。
- 部署的 history 模式回退：需要在部署层配置，代码不包含。
