# 设计

沿用 WeKnora frontend/src/views/settings/MemorySettings.vue 的设置行、记忆列表、新增表单和归档确认，使用 TDesign Tab 与对话框。新增 POST native/memory 接收标题、类型、正文、重要度；身份来自认证上下文。手动来源无 Run，草稿 scope 使用 user:<owner UUID>，origin=manual，版本来源 Run 可空；通过现有筛查、去重、预算及 review 规则在一个事务中完成用户明确发布。既有 Run 来源保持不变，无虚构 Run。历史保留，不提供永久删除和归档列表恢复。
