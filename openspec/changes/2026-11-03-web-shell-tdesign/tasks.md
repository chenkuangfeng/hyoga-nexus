# 实施任务

状态：提案待确认（2026-11-03）。确认前不编码。确认时请先回答 `proposal.md` 中"需要你确认的项"的 6 个问题，再按下列任务实施。

## 准备

- [ ] 确认 `proposal.md` 第 1–6 项，并把结论写回本文件与 `design.md`。
- [ ] 复核 WeKnora 的 `menu.vue`、`Settings.vue`、`SettingsModalShell` 与 `views/settings/*` 的布局数值（侧栏宽度、设置导航宽度、弹窗尺寸），结论写入 `design.md` 第 3 节。
- [ ] 复核 WeKnora 的 `config/integrations.ts` 与 `stores/menu.ts`，确认集成子项与顶层菜单的权限条件。

## 依赖与基础

- [ ] 安装 `tdesign-vue-next`（^1.19.2）与 `tdesign-icons-vue-next`（0.4.4），锁定 `pnpm-lock.yaml`。
- [ ] 在 `main.ts` 中注册 TDesign（按需引入），接入 `vue-i18n` 的语言包。
- [ ] 把 `tokens.css` 的语义 token 映射到 TDesign 的 CSS 变量（根节点）；不在组件内写死颜色。

## 外壳与菜单

- [ ] `layouts/AppLayout.vue`：TDesign 布局，侧栏 + 内容区；展开、折叠、拖拽调宽（如确认），宽度存入 localStorage。
- [ ] `layouts/AppSidebar.vue`：品牌区、"新建会话"、最近会话列表、"更多功能"折叠区（知识库、制品库、智能体、自动化、工具箱、组织）、底部用户名称与弹出菜单（设置、退出）；按 `design.md` 第 2 节。
- [ ] 底部用户菜单的"设置"路由到 `/settings`，不弹窗；空间切换位置按 `proposal.md` 待探讨项确定。
- [ ] 新建对话的会话子列表：按时间分组，结构与入口；会话操作沿用 `session-management` 提案。
- [ ] 响应式：≥ 1024 展开；768–1023 图标列；< 768 抽屉（Esc 关闭）。
- [ ] 可访问性：`nav`、`aria-current`、`aria-expanded`、焦点环、图标按钮的可访问名称。
- [ ] `router/navigation.ts`：替换为平铺的顶层菜单结构；权限与能力条件按第 2.1 节。
- [ ] `router/index.ts`：新增 `/knowledge-bases`、`/artifacts`、`/agents`、`/automations`、`/toolbox`、`/organizations`、`/settings/:section`；无效分区重定向到默认可见分区。
- [ ] 旧路径重定向（`design.md` 第 2.2 节），`legacyHashRoutes` 同步更新。

## 设置

- [ ] 设置导航：七个分组，23 个分区 + 集成下的子项（按确认结果决定原排除项是否显示）。
- [ ] 按角色过滤分区；角色不足显示"无权限"。
- [ ] 设置为独立页面：一级 `/settings`，二级 `/settings/:section` 整页切换；一级与二级有返回按钮（优先 `router.back()`，无历史时回上一级）。
- [ ] 三级（编辑、新建、详情）使用抽屉或对话框，不新建页面。
- [ ] 占位页组件：标题、说明、"规划中"与路线图步骤、返回入口（`design.md` 第 6 节）。
- [ ] 迁入页面：`ModelSettingsView`、`RoleManagementView`、`SpaceOrganizationView`（组织绑定部分）、`AccountView`、`OrganizationManagementView`（顶层菜单）。
- [ ] 扩展分区（按确认结果）：`NativeSettingsView`（Native 运行）、`AdminSessionsView`（会话查询）、`OverviewView`（版本信息）。
- [ ] 其余分区全部使用占位页。

## 页面迁移（Element Plus → TDesign）

- [ ] 迁移 `views/auth/*`（登录与账号）。
- [ ] 迁移 `views/chat/*` 与 `components/*`（对话页、模型分支、运行控件、记忆快照控件）。
- [ ] 迁移上述已迁入的设置页与弹窗（`ModelEditorDrawer`、`SettingsDialog` 等）。
- [ ] 删除 `element-plus` 依赖与 `element-theme.css` 中的相关覆盖；确认 `grep -r "el-\|element-plus"` 无结果（若第 4 项选择迁移）。

## 测试与文案

- [ ] 更新 `tests/web/*.mjs` 中依赖 Element Plus 选择器与旧导航地址的用例。
- [ ] 新增导航用例：顶层菜单可达、设置分区可深链与刷新、无效分区重定向、角色不足的提示、旧地址重定向。
- [ ] 新增占位页用例：每个占位分区显示状态与路线图步骤。
- [ ] 宽度 375、768、1024、1440 下无横向滚动；侧栏键盘操作。
- [ ] 中英文文案齐全，切换语言后无遗漏的硬编码文案。

## 验证

- [ ] `pnpm build`（含 `vue-tsc`）通过。
- [ ] `pnpm test:browser` 全部通过。
- [ ] `uv run --locked pytest` 全部通过（后端不改动，应不受影响）。
- [ ] 截图与 WeKnora 逐页比对，差异记入 `design.md`。

## 不做

- 不实现占位分区的业务功能，不新增后端 API。
- 不做全局命令面板。
- 不做深色主题切换入口（由 `dark-theme` 提案负责）。
