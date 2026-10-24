# Tasks: P1 平台底座

本清单描述后续实施工作；当前 OpenSpec 变更仅完成设计草案，所有任务保持未完成。

- [ ] 1. 定稿领域契约
  - [ ] 1.1 审阅 Workspace/Membership/AgentVersion/Binding/Session/Run/Event/Invocation 逻辑模型与跨空间约束
  - [ ] 1.2 定稿角色矩阵、共享资源授权和撤权并发语义
  - [ ] 1.3 定稿 Agent 发布、Session 固定版本及 Run 快照字段
  - [ ] 1.4 定稿 Run 状态机、事件 schema/游标和幂等作用域
- [ ] 2. 技术验证与 ADR
  - [ ] 2.1 验证 PostgreSQL 迁移工具、事务隔离、JSON 快照和事件序号方案并记录 ADR
  - [ ] 2.2 比较 Redis Streams、数据库任务队列和独立 broker，验证重复投递、worker 崩溃恢复、取消与优雅关闭并记录 ADR
  - [ ] 2.3 定义身份认证和 CredentialRef 后端适配边界；部署提供方明确后记录决策
  - [ ] 2.4 定义 ID 生成、事件保留及审计保留策略并记录决策
- [ ] 3. Core 与持久化底层
  - [ ] 3.1 在 core 定义稳定 ID、角色、版本、Run 状态和平台事件契约
  - [ ] 3.2 在 platform 定义 Repository、事务和授权端口，保持 core 无 ORM/厂商依赖
  - [ ] 3.3 建立平台迁移基线及 Workspace 一致性约束
  - [ ] 3.4 建立审计、幂等记录、Outbox 和 worker lease 持久化
- [ ] 4. 身份、空间与智能体配置
  - [ ] 4.1 实现认证主体到 User/Workspace Membership 的解析与最小角色策略
  - [ ] 4.2 实现 Agent 草稿、依赖校验、不可变发布版本和并发冲突处理
  - [ ] 4.3 实现模型配置版本与 CredentialRef，避免秘密出现在普通持久化/日志中
  - [ ] 4.4 实现多资源绑定、空间/grant 校验和 Runtime capability 校验端口
- [ ] 5. Session、Run 与事件
  - [ ] 5.1 实现固定 AgentVersion/RuntimeType 的 Session 创建与消息关联
  - [ ] 5.2 实现幂等 Run 提交、授权快照及事务 Outbox
  - [ ] 5.3 实现 worker 领取租约、状态迁移、取消请求和未知结果保护
  - [ ] 5.4 实现有序持久事件、Run 事件查询/SSE 游标和 RuntimeSessionBinding
  - [ ] 5.5 实现实际工具/资源访问时的二次权限检查端口及审计记录
- [ ] 6. 应用接口与验收
  - [ ] 6.1 接入 API 与 worker 组合入口，不在 core/platform 引入特定 Runtime SDK 或 guanlan
  - [ ] 6.2 验收空间隔离、撤权、不可变版本、幂等提交、重复投递、崩溃恢复、事件续读及秘密不落日志
  - [ ] 6.3 更新 architecture/resource-model/runtime-contract/roadmap 以反映经批准的设计及已实现状态
