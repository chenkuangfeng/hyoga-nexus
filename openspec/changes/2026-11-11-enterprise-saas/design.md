# 设计

本文件写 E0–E2 的设计，以及 E3–E6 的要点。各阶段开始前补齐接口与表结构，并经用户确认。

## 1. 租户模型

```text
部署（共享数据库、共享表，按 tenant_id 隔离）
  ├─ 企业 A（tenants.kind = 'enterprise', plan = 'standard'）
  │    ├─ enterprise_policies、tenant_wecom_apps
  │    ├─ 组织树（org_units / user_org_units，source = manual | wecom）
  │    ├─ 成员（tenant_memberships，source 增加 wecom）与角色（含 security_admin、auditor）
  │    ├─ 企业共享资源：可见范围为 tenant（以及 E4 的部门）的智能体、知识库……
  │    └─ 每个成员的个人区：本人的会话、记忆、私有智能体、私有知识库、产物
  ├─ 企业 B（plan = 'trial'，单人试用企业）
  └─ 共享空间（跨企业协作，受各企业的 external_sharing 约束；试用企业不能加入）
```

- **多租户方式**：共享库、共享表，用行级的 `tenant_id` 隔离。所有业务表都带 `tenant_id`，并用复合外键保证引用不跨企业（沿用 `org_units`、`tenant_agent_grants` 的做法）。PostgreSQL 行级安全（RLS）作为纵深防御，暂不启用，见第 7 节。
- **只收紧**：平台守卫 ⊇ 企业策略 ⊇ 空间角色与资源授权。企业策略不能放宽平台已有的检查。
- **执行时复核**：策略、组织关系、成员状态、套餐在每次请求和每次工具调用时重新查询，不进入 Run 快照。

## 2. E0 知识库维护开放给智能体管理员

`packages/platform/src/nexus_platform/knowledge/access.py`：

```python
def can_maintain_content(db, kb, user_id) -> bool:
    """文档级维护：can_write 成立，或者调用者管理着一个绑定了该库的本企业智能体。"""
```

- 判断条件：`kb.status == 'active'`；调用者是 `kb.tenant_id` 的有效成员；存在 `agent`，满足 `agent.tenant_id == kb.tenant_id`、`agent_permissions(...)` 含 `manage`、草稿绑定或当前已发布版本的绑定中有 `kind = 'knowledge_base'` 且 `resource_id = kb.id`。
- 每次请求现查，不缓存。解除绑定或撤销 `manage` 后，下一次请求即失去权限。
- 接入点：文档上传、删除、重新解析，分块与问答的增删改走 `can_maintain_content`；库的设置、删除、共享、存储与解析器配置仍走 `can_write`。
- 可读性：E1 引入私有库之后，`can_read` 对满足上述条件的调用者同样放行，否则维护者看不到要维护的库。
- 审计：通过这条路径写入的操作，在审计 detail 中记录 `via_agent_id`。
- 接口返回 `can_maintain` 字段，前端据此显示维护入口，不自行推断。

## 3. E1 租户与个人区

### 3.1 套餐与试用企业

- 迁移：`tenants.plan`（`trial`、`standard`，非空；已有企业设为 `standard`）。`kind` 的取值按需要确认的项 2 处理。
- `auth/accounts.py` `register`：去掉 `space_kind` 参数，一律创建企业。没有提供企业名称时，生成“{显示名}的试用企业”和一个随机企业编码，`plan = 'trial'`。在注册页填写企业名称与编码的，仍然创建 `trial`。
- 试用限制集中在 `tenants/plan.py` 的 `require_plan_feature(tenant, feature)`，`feature` 取 `invite_members`、`wecom`、`shared_spaces`，违反时返回 403 `plan_restricted`。检查点：添加成员与邀请、邀请链接、加入申请审批、企微接入配置、加入或创建共享空间。
- 命令行 `upgrade-enterprise --tenant <id>`：把 `plan` 改为 `standard`，写入审计。
- 登录：默认进入 `last_active_tenant_id`，没有时进入最早加入的企业（不再“个人空间优先”）。`onboarding/workspace` 页面去掉“创建个人空间”。

### 3.2 私有知识库

- 迁移：`knowledge_bases.visibility`（`private`、`tenant`，非空；已有知识库设为 `tenant`）。
- `can_read`：`kb.tenant_id == tenant_id` 时，`tenant` 可见范围对全体成员放行；`private` 只对创建者、企业 owner 与 admin、满足 `can_maintain_content` 的人放行。共享到共享空间的路径不变，但只有 `tenant` 可见范围的库才能共享出去。
- 修改可见范围属于 `can_write`。从 `tenant` 改为 `private` 时，如果有其他人可用的智能体绑定了这个库，就拒绝修改（409 `kb_in_use`），并列出这些智能体。
- 智能体发布检查（`agents/service.py` 发布时的绑定校验）：智能体有除创建者以外的使用者（角色授权、E4 的部门或成员授权、共享空间共享）时，所绑定的知识库必须是 `tenant` 可见范围（E4 之后为“覆盖使用范围”），否则返回 422 `binding_scope_narrower`。

### 3.3 企业策略

`enterprise_policies(tenant_id PK, self_build_agents, self_build_org_unit_ids JSON, personal_models, external_sharing, retention_days, updated_by, updated_at)`；企业创建时写入默认行。

- 读取接口对所有成员开放（前端据此隐藏入口），修改需要 `policy:manage`。
- 检查点：
  - 创建智能体：检查 `self_build_agents`，`org_units` 模式按调用者当前所在部门（含祖先）匹配；企业 owner、admin 不受限制；
  - 模型选择、发布与 Run 准备：`personal_models = false` 时，个人模型（`owner_user_id` 非空）既不能选择，也不能执行；
  - 共享到共享空间：检查 `external_sharing`。共享空间里只要有其他企业的成员租户就算外部。

### 3.4 企业级管理角色

- `authz/catalog.py` 增加 `policy:manage`、`audit:read_content`，二者纳入 `GOVERNANCE_APIS`。
- `tenant_roles.builtin`（布尔）。企业创建时写入 `security_admin`（`policy:manage`、`tools:manage`、`audit:read`）和 `auditor`（`audit:read`）；已有企业由迁移补齐。内置角色不能删除、不能改名，可以分配给成员。
- 审计正文：只有 `audit:read_content` 才能看到对话正文与工具参数，每次查看本身也写入审计。

### 3.5 PostgreSQL 门禁

路线图 2.9 的全部项目，加上本提案新增的列与表，在 PostgreSQL 上完成迁移往返和并发测试后，E1 才算验收。

## 4. E2 前端两个入口

- **构建**：`apps/web` 保持一个工程，路由分为 `/workspace/*` 与 `/admin/*` 两棵，各有自己的布局组件。`/admin` 下的页面全部用动态 `import()` 引入，并在 Vite 中配置独立的 chunk 组，员工端首屏不加载管理页面的代码。现有 `/platform/*` 路由重定向到新位置，保留一个版本周期。
- **入口判断**：`/auth/me` 增加 `entries`：
  - `workspace`：当前企业的有效成员；
  - `admin`：当前企业中持有任一治理权限（`members:manage`、`roles:manage`、`org:manage`、`policy:manage`、`audit:read`、`models:manage`、`tools:manage`）；
  - `platform_admin`：`users.is_platform_admin`。
  路由守卫只读取 `entries`。
- **设置项归属**：`config/settingsAccess.ts` 改为一张表，每一项记录 `entry`（`workspace` 或 `admin`）与所需权限。仍然是前端唯一的依据：

| 现有设置项 | 新位置 |
|---|---|
| `general`、`userprofile`、改密、企微绑定、`assistant`（个人部分）、`mymemory`、`envvars` | 工作台 → 个人设置 |
| `models` | 工作台 → 个人设置（仅当 `personal_models` 开启时显示个人模型）；企业模型 → 管理后台 |
| `tenant`、`members`、`org-structure`、角色、企业策略、`audit` | 管理后台 |
| `mcp`、`skills`、`websearch`、`chathistory`、`memory`（企业级开关）、`assistant`（企业部分） | 管理后台 |
| `vectorstore`、`parser`、`storage`、`sandbox`、`system-global`、`model-catalog`、`runtime-queues`、`platform-api-keys`、`system-audit-log`、`system` | `/platform-admin`（不变） |

- **工作台导航**：“我的”与“企业共享”分组由接口字段区分（智能体与知识库的列表接口返回 `owned_by_me`、`visibility`），前端不自行推断。
- **管理接口前缀**：新写的管理接口放在 `/api/v1/tenants/{id}/admin/...`；已有的管理接口在 E2 中迁移并保留旧路径一个版本周期。

## 5. E3 企业微信（要点）

- `tenant_wecom_apps` 的 `secret` 与 `encoding_aes_key` 用现有 Fernet 主密钥加密，不进事件与审计。试用企业不能创建（`require_plan_feature('wecom')`）。
- 回调：每企业一个 URL `/api/v1/integrations/wecom/{tenant_id}/callback`，先验签解密，再分发到“通讯录变更”“消息”“卡片按钮”。
- `WeComDirectory` 协议扩展为：部门列表、部门成员详情、成员详情、发送应用消息、更新模板卡片。HTTP 实现放在 `connectors/wecom`，platform 只依赖协议。
- 同步顺序：部门 → 成员 → 主部门与上级 → 停用差集。上级保存在新表 `user_managers(tenant_id, user_id, manager_user_id, source)`。
- 自动开户：在 `auth/wecom.py` 的登录分支中，未绑定且 `(corp_id, userid)` 已同步的成员，创建 `users`、`user_identities` 与企业成员身份，不创建其他空间，也不写入 `local_credentials`。
- 企微 H5：工作台在企微内置浏览器中使用网页授权免登；手机宽度下的布局纳入 E2 的验收。
- 消息渠道：沿用路线图 9.1 与架构 2.14 的约定（`ChannelIdentity`、`ChannelSessionBinding`、去重、回复长度、只在明确拒绝时重试）。

## 6. E4–E6（要点）

- **E4**：`tenant_agent_grants` 当前只有 `role_id` 作为接收方。新增 `agent_principal_grants(tenant_id, agent_id, principal_kind, principal_id, permission, include_descendants)`，`principal_kind` 取 `org_unit` 或 `user`；`agent_permissions` 取原有角色授权与新授权的并集。知识库可见范围增加 `org_units`。部门展开用递归 CTE 求调用者所在部门的祖先集合，每个请求内缓存一次。审批：`ActionApprovalRecord` 增加 `approver_kind` 与 `approver_user_ids`（发起时解析并冻结，决定时再校验审批人仍然有效），`resolve` 的权限由“Run 所有者”改为“在 `approver_user_ids` 中”。超时由 worker 定时扫描，按拒绝结束（`approval.resolved`，`reason = 'timeout'`）。
- **E5**：`usage_ledger(tenant_id, user_id, org_unit_id, agent_id, model_version_id, day, input, output, cache_read, cache_creation)` 从 `usage.updated` 累加；准入时检查企业、部门、个人三级的月度上限，超出返回 429 `quota_exhausted`。
- **E6**：worker 每天按 `retention_days` 清理会话、运行事件与产物，有法务保全标记的除外；审计按日导出为 JSONL，并写入哈希链字段；离职成员的企业内记忆默认删除。

## 7. 多租户隔离的后续加固（不在本提案实施）

- PostgreSQL RLS：以 `app.tenant_id` 会话变量为条件，作为应用层隔离之外的第二道防线。
- 每个企业的并发与速率上限：现有的 `max_concurrent_sessions_per_tenant` 已经支持全局统一值，按企业单独设定的上限随平台运营另提。
