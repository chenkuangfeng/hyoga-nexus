# 实施任务

状态：草案，待确认（2026-11-11）。确认 `proposal.md` 中“需要你确认的项”之前不开始编码。各阶段开始前在 `design.md` 补齐细节并经确认，实施中发现的追加工作写入本文件。

## E0 知识库维护开放给智能体管理员

- [ ] E0.1 `knowledge/access.py` 新增 `can_maintain_content`（`design.md` 第 2 节），文档、分块、问答的写接口改用它；库设置、删除、共享仍用 `can_write`。
- [ ] E0.2 接口返回 `can_maintain` 字段；通过这条路径的写入在审计中记录 `via_agent_id`。
- [ ] E0.3 前端：知识库列表与详情按 `can_maintain` 显示维护入口。
- [ ] E0.4 测试：有 `manage` 可维护；只有 `edit` 不可维护；解绑或撤权后立即失去权限；不能删除库、修改设置或共享；共享来的库仍然只读。
- [ ] E0.5 文档：`docs/architecture.md` 2.10 与 `packages/knowledge` 的模块文档。

## E1 SaaS 企业底座

- [ ] E1.1 迁移：`tenants.status` 增加 `pending`、`suspended`；新表 `enterprise_policies`、`enterprise_limits`、`platform_audit_records`；`tenant_roles.builtin`。
- [ ] E1.2 企业生命周期：`[platform].enterprise_signup`；准入检查（`require_membership` 与派发领取）；平台接口 `/api/v1/platform/enterprises` 与平台审计。
- [ ] E1.3 企业策略：读取与修改接口（`policy:manage`）；在创建智能体、模型选择与 Run 准备、共享到共享空间三处检查。
- [ ] E1.4 个人空间边界：在资源授权、共享、分叉、技能复制入口校验，并补跨空间测试矩阵。
- [ ] E1.5 企业级管理角色：`policy:manage`、`audit:read_content`；企业创建时写入 `security_admin` 与 `auditor` 内置角色，旧企业由迁移补齐。
- [ ] E1.6 前端：平台运营的企业管理页；企业设置中的“企业策略”分区；等待开通页。
- [ ] E1.7 PostgreSQL 门禁：完成路线图 2.9，并覆盖本阶段新增的表。
- [ ] E1.8 文档：`docs/architecture.md` 2.11、`docs/roadmap.md`（新增企业化步骤，2.9 改为前置门禁）、`configs/README.md`。

## E2 企业微信

- [ ] E2.0 核对企微官方文档：代开发与自建两种模式下，登录、部门、成员、直属上级、回调、应用消息、模板卡片各接口的可用字段与限制，结果记录在 `design.md` 第 4 节。
- [ ] E2.1 `tenant_wecom_apps` 与配置界面（加密保存密钥）；回调验签与解密。
- [ ] E2.2 扫码与企微内免登；已同步成员首次进入时自动开户。
- [ ] E2.3 通讯录全量同步与回调增量；`user_managers`。
- [ ] E2.4 离职处理：撤销成员身份、ActionGrant、MCP 令牌与定时任务；资产移交；审计。
- [ ] E2.5 企微消息渠道（承接路线图 9.1）。

## E3 组织驱动授权与审批

- [ ] E3.1 `agent_principal_grants` 与资源授权的部门、成员接收方；部门子树展开。
- [ ] E3.2 审批人路由（`self`、`manager`、`resource_owner`、`role`）、审批超时、Web 待办。
- [ ] E3.3 企微审批卡片。

## E4 成本与配额

- [ ] E4.1 `usage_ledger` 累加与用量报表（企业、部门、个人、智能体、模型）。
- [ ] E4.2 三级月度上限的准入检查。

## E5 数据治理

- [ ] E5.1 留存清理与法务保全。
- [ ] E5.2 审计导出与哈希链。
- [ ] E5.3 离职成员的记忆处理。

## 收尾

- [ ] 同步 OpenSpec 规格、路线图与模块文档后归档。
