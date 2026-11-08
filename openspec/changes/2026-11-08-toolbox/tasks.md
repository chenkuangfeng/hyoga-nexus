# 任务

确认前不编码。已完成的任务才勾选。

- [ ] 1. `config/toolbox.ts`：标签增加 `available` 标记（技能、工具为真，MCP、浏览器连接为假）；`canAccessToolboxSection` 与新标签 `tools` 的角色门禁；单测。
- [ ] 2. `NexusToolbox.vue`：标签栏、选中与回退逻辑（沿用 `Toolbox.vue` 结构）、计划中的标签禁用且不发请求；路由 `toolbox/:section?` 改指向它。
- [ ] 3. `NexusToolboxSkills.vue`：技能表（含使用记录、扫描结论、脚本可运行性）、版本历史、导出、重扫、内置停用/恢复；页头按钮复用安装、我的技能、审核三个对话框。
- [ ] 4. `NexusToolboxTools.vue`：内置工具目录按分组显示，风险与审批说明，管理员停用/恢复。
- [ ] 5. 六种语言文案与键一致性审计；纯逻辑单测（表格行的徽标、排序、权限按钮显示）。
- [ ] 6. 文档：路线图与 `apps/web` 说明；模板编译检查；浏览器实测留给有环境时。
