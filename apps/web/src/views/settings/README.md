# 用户模型设置

已实现多个供应商/模型、个人与空间共享范围、一次性 Key 输入、连接测试、默认模型、最小 Native 智能体创建与发布。页面为 `ModelSettingsView.vue`，设置行为见 [总体架构](../../../../../docs/architecture.md) 第 5.13、5.15 节。

## 角色与权限

`RoleManagementView.vue` 管理空间自定义角色、成员角色分配与智能体级权限，逻辑在 `composables/useRoles.ts`，接口在 `api/roles.ts`。仅拥有 `roles:manage` 的成员可见管理内容；服务端检查是权限的唯一依据。成员显示目前为用户 ID 前缀，展示名称需等待身份资料接口。浏览器验收见 `tests/web/roles.mjs`。
