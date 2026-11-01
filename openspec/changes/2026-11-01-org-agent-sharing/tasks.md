# 实施任务

状态：待确认提案（方案 2）。确认前不编码。下列任务均未完成。

## 准备

- [ ] 确认提案"需要你确认"的 5 项。
- [ ] 阅读 WeKnora 的 AgentShare 与 receiver 视图源码，比较候选实现，结论写入 design.md。

## 数据与迁移

- [ ] `tenant_org_roles` 模型与外键（引用 `tenant_org_bindings` 与 `tenant_roles`）。
- [ ] `sessions.org_unit_id`（可空，按第 4 项确认结果决定是否加入）。
- [ ] 迁移（SQLite 升级与回退）。
- [ ] PostgreSQL 验证随路线图 2.9。

## 权限计算

- [ ] `effective_permissions` 与 `agent_permissions` 合并组织角色。
- [ ] 读取类接口改用"成员或组织角色"判断，成员管理保持 `require_membership`。
- [ ] 空间列表包含组织来源的空间，并返回来源标记。

## 服务与接口

- [ ] 授予与撤销组织角色（空间 owner 与 admin），写审计。
- [ ] 空间侧的组织角色视图。
- [ ] 会话创建时记录 `org_unit_id`（若确认）。
- [ ] 聊天记录与记忆的读取范围：普通用户、空间 owner/admin、平台管理员。
- [ ] 会话列表支持按智能体、组织、空间筛选（平台管理员）。

## 前端

- [ ] 空间设置中的组织角色区域（使用 `ui-ux-pro-max` 设计）。
- [ ] 空间列表的组织来源标记。
- [ ] "组织访问"标识（若确认）。
- [ ] 浏览器验收用例并入 `test:browser`。

## 测试

- [ ] 授予规则：只接受自定义角色，owner 与 admin 被拒绝，重复授予被拒绝。
- [ ] 权限合并与撤销即时生效。
- [ ] 授予前后成员表不变。
- [ ] 空间列表与来源标记。
- [ ] 聊天记录与记忆的三种可见性。
- [ ] 后端全量测试与前端构建。

## 文档

- [ ] `docs/architecture.md`、`docs/roadmap.md` 更新。
- [ ] `packages/platform/docs/` 更新。
- [ ] OpenSpec 规格与本文件按实施结果同步。

## 归档

- [ ] 全部完成并验证后，按 OpenSpec 工作流同步规格并归档。
