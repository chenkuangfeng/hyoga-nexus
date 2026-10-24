# Specification Delta: 平台底座

## Status
- **Change ID**: `p1-platform-foundation`
- **Status**: Draft

## Requirements

### ADDED Requirements

- **REQ-01 空间隔离**：平台管理对象必须归属一个明确的 Workspace，或明确标记为平台级共享对象。每个请求必须由已认证主体及其 Workspace Membership 建立执行上下文；读取和写入均须在该上下文中限定范围。
- **REQ-02 最小角色**：P1 至少区分 Workspace owner、admin、member。角色只表达管理动作范围；资源访问还必须检查对象归属、显式绑定及调用场景，不得仅凭“在同一空间”授予 Agent 运行资源。
- **REQ-03 权限校验时点**：创建/发布 Agent、创建 Session、提交 Run、实际执行工具、检索或读取文档时必须验证权限。Run 启动时记录授权资源快照；每次工具或文档操作仍须对当前权限做校验，撤权在下一次操作生效。
- **REQ-04 凭据引用**：ModelProfile、MCPConnection 等配置只能保存 CredentialRef 与非敏感配置。明文凭据不得写入 AgentVersion、Run 快照、事件、日志或提示词；凭据解析必须在执行边界按需完成并限制到单次运行。
- **REQ-05 版本不可变**：已发布 AgentVersion 及其内容不得原位修改。更改 Agent 指令、模型配置、预算或资源绑定时创建新版本；草稿可以编辑。版本引用应稳定且可审计。
- **REQ-06 Session 固定配置**：Session 创建时固定 AgentVersion 和 RuntimeType。后续新版本不得静默改变既有 Session；换 Runtime 通过新 Session 或显式分支表达。
- **REQ-07 Run 快照**：Run 启动时保存不可变的配置快照，包括 AgentVersion、RuntimeType、模型配置版本、资源绑定及所引用资源版本、预算、触发主体和授权决策时间。快照不包含凭据值。执行仍依据最新权限校验结果约束能力。
- **REQ-08 Run 状态**：Run 状态至少支持 `queued`、`running`、`waiting_input`、`waiting_approval`、`completed`、`failed`、`cancelled`、`interrupted`。终态不得因普通重试回退；只有显式完成事件可令状态为 `completed`。Worker 意外退出或连接中断应在恢复流程中判定为可恢复或 `interrupted`，不得推断成功。
- **REQ-09 持久化事件**：RunEvent 按 Run 使用从 1 开始、单调递增且唯一的 sequence；写入持久化成功后才可向 SSE/其他订阅者投递。事件至少含 event_id、run_id、sequence、occurred_at、type、schema_version 和结构化 payload。重连使用 Run 范围内的 sequence 游标，只重放已存事件，不触发执行。
- **REQ-10 消息与调用关联**：平台消息、Run、工具调用、产物和引用必须通过稳定 ID 关联；ToolInvocation 保存调用状态及受控输入/输出摘要，不记录凭据或不受限的敏感正文。事件和调用记录需能从 Run 追溯。
- **REQ-11 幂等提交**：创建 Run 的客户端请求支持由调用方提供或平台生成的幂等键，并在 Workspace/调用主体范围内唯一。重复提交返回既有 Run，不重复排队。队列消息可重复投递，worker 必须以持久化 Run 状态和领取/租约机制避免并发执行同一 Run。
- **REQ-12 副作用重试**：执行结果未知的有副作用操作不得自动重放。运行器或工具需要通过 operation/invocation ID 查询已知结果，或明确进入 `interrupted` 并交由受控恢复/人工处理。
- **REQ-13 外部 Runtime 会话映射**：RuntimeSessionBinding 将平台 Session 与外部 Runtime 类型、运行时实例/配置范围及厂商会话 ID 关联；厂商 ID 不得跨 Workspace 暴露。外部会话恢复能力需单独标注，不能与事件重放混为一谈。
- **REQ-14 数据库迁移**：平台主关系存储使用 PostgreSQL。持久化结构必须通过有序、可审计的迁移演进；迁移具备版本记录和失败处理约定。迁移工具须在实施前经验证并记录 ADR。
- **REQ-15 队列验证**：P1 以 PostgreSQL Outbox/lease polling 为初始实现，决策及候选方案比较记录在 ADR。必须以 API/worker 分离形态验证持久投递、重复投递、worker 崩溃恢复、排队取消、优雅关闭、可观测性和本地开发体验；目标 PostgreSQL 验收完成前，不得宣称这些运行语义已通过验证。
- **REQ-16 审计最小记录**：空间成员角色变化、Agent 发布、权限/绑定变化、Run 创建与终态、审批决定和凭据引用变更必须有操作者、目标对象、时间及结果记录；审计内容不包含凭据值或完整秘密。

### MODIFIED Requirements

无。

### REMOVED Requirements

无。
