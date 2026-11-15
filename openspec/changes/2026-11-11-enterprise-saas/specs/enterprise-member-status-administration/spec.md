## ADDED Requirements

### Requirement: 企业成员可逆停用与恢复
管理应用 SHALL 允许具有 `members:manage` 的成员把活跃企业成员临时停用并恢复。成员状态 SHALL 区分 `active`、`suspended` 与现有永久移除状态 `revoked`；停用 SHALL 保留原角色、部门关系、资源、审计和运行历史，恢复 SHALL 复用这些关系。停用后该成员 SHALL 不能取得当前企业身份或访问企业资源，也不能发起新的 Run；已开始的 Run SHALL 不自动取消，其后续操作仍经服务端现有授权检查。

- **WHEN** 管理员停用活跃成员
- **THEN** 服务端在事务中写入 `suspended` 和停用时间、记录操作者/目标/状态变化审计，后续企业授权请求被拒绝
- **WHEN** 管理员恢复已停用成员
- **THEN** 服务端写入 `active` 并记录状态变化；原角色与部门关系继续生效
- **WHEN** 请求把成员状态重复设置为当前状态
- **THEN** 操作幂等，不新增重复状态变化审计

### Requirement: 成员状态变更权限与 owner 安全
成员状态写入 SHALL 通过 `/api/v1/tenants/{tenant_id}/admin/members/{member_id}/status` 并要求 `members:manage`。非 owner SHALL 不能变更 owner 状态；事务 SHALL 保证至少一名 owner 保持 active。永久移除 SHALL 继续使用既有撤销接口，不得以停用替代。已停用账号 SHALL 不能由邀请或手工添加流程隐式恢复，必须使用显式恢复操作。

- **WHEN** 操作者无 `members:manage`，或非 owner 尝试变更 owner
- **THEN** 服务端拒绝且不写入部分状态
- **WHEN** 操作会停用企业最后一名 active owner
- **THEN** 服务端返回冲突且成员保持原状态
- **WHEN** 活跃 owner 被成员列表中的用户临时停用
- **THEN** 其余 active owner 可显式恢复，且恢复后不重置角色或部门关系

### Requirement: 人工停用优先于企微同步
企微同步 SHALL 保留管理员设置的 `suspended` 状态，不得因为通讯录成员仍处于在职状态而自动恢复；企微确认成员离职或离开同步范围时仍 SHALL 撤销成员关系并记录审计。成员列表 SHALL 返回 active 与 suspended 成员及其状态时间，隐藏 revoked 成员，并为停用和恢复提供作用域安全的确认、反馈与刷新。
