# 任务

已确认并实施。已完成的任务才勾选。

实施中追加（决定 6 允许）：`GET /skills` 为每个技能增加 `verdict`、`trust`、`rescan_needed`（技能库表的徽标需要）；没有新增接口。

- [x] 1. `config/toolbox.ts`：标签增加 `available` 标记（技能、工具为真，MCP、浏览器连接为假）；`canAccessToolboxSection` 与新标签 `tools` 的角色门禁；单测。
  - `TOOLBOX_ITEMS` 为技能、工具、MCP、浏览器连接，后两者 `available: false`；`isToolboxSectionAvailable`；`canAccessToolboxSection` 改为所有活跃成员可见（写操作由服务端按权限判断）；`config/toolbox.test.ts` 改写。
- [x] 2. `NexusToolbox.vue`：标签栏、选中与回退逻辑（沿用 `Toolbox.vue` 结构）、计划中的标签禁用且不发请求；路由 `toolbox/:section?` 改指向它。
  - `NexusToolbox.vue` 沿用 `Toolbox.vue` 的布局与样式；计划中的标签禁用、显示「计划中」、不发请求，地址栏直接输入也回退到第一个可用标签；路由 `toolbox/:section?` 已指向它。WeKnora 的 `Toolbox.vue` 与 `SkillSettings` / `McpSettings` / `BrowserConnectionSettings` 保留文件但不再被路由使用，MCP 与浏览器连接做后端时再接。
- [x] 2a. 把安装、我的技能、审核三个对话框的内容抽成面板（`NexusSkillInstallPanel` / `NexusMySkillsPanel` / `NexusSkillReviewPanel`），对话框只剩外壳，编辑器行为不变。
  - 三个 `*Panel.vue` 抽出，`*Dialog.vue` 只剩 `t-dialog` 外壳且面板仅在打开时挂载（每次打开重新开始，行为同前）。
- [x] 3. `NexusToolboxSkills.vue`：子页切换（技能库 / 我的技能 / 审核提交 / 安装技能，后两者仅管理员）；技能库表（含使用记录、扫描结论、脚本可运行性）、版本历史、导出、重扫、内置停用/恢复；其余子页嵌入上述面板。
  - `NexusToolboxSkills.vue`：技能库 / 我的技能 / 审核提交 / 安装技能四个子页（后两者仅 `tools:manage`）；技能库表含版本、使用、默认档位下脚本能否运行及原因、徽标、版本历史（来源、扫描、构建状态）、导出 zip（当前或指定版本）、重扫、内置停用/恢复。
- [x] 4. `NexusToolboxTools.vue`：内置工具目录按分组显示，风险与审批说明，管理员停用/恢复。
  - `NexusToolboxTools.vue`：按分组列出内置工具，风险、需审批、只读、内置、本空间状态；管理员停用/恢复内置工具、启用未启用的工具。
- [x] 5. 六种语言文案与键一致性审计；纯逻辑单测（表格行的徽标、排序、权限按钮显示）。
  - 六种语言文案（键一致性审计通过）；`toolbox.test.ts` 覆盖徽标、脚本状态与原因、排序、工具状态与操作、分组。
- [x] 6. 文档：路线图与 `apps/web` 说明；模板编译检查；浏览器实测留给有环境时。
  - 路线图已记录；新 `.vue` 的模板编译无错；`toolboxSkills.ts` / `toolboxTools.ts` 用 `tsc --strict` 检查通过（请求层打桩）。**未在浏览器里验证**，`vue-tsc` 未跑。
