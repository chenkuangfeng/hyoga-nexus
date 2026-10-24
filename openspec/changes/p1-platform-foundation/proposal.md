# Proposal: P1 平台底座

## 1. 问题陈述

P1 需要为智能体平台建立可追溯、可授权的最小持久化底座。当前架构、资源模型和 Runtime 契约定义了对象边界，但尚未明确租户隔离规则、配置发布与快照语义、运行事件恢复语义、任务投递一致性及迁移管理约束。若直接开始 CRUD 或运行代码，各模块容易对身份、权限和状态作出不兼容假设。

## 2. 提议变更

- 定义 Workspace、Membership、Agent/AgentVersion、资源绑定、ModelProfile/CredentialRef、Session、Run、RunEvent、ToolInvocation 和 RuntimeSessionBinding 的 P1 逻辑模型及关系。
- 定义最小角色授权、空间边界、资源授权校验点、凭据引用边界和撤权生效时机。
- 定义 Agent 草稿/发布版本、会话固定版本、运行配置快照和资源版本引用语义。
- 定义 Run 状态迁移、事件顺序/游标、持久化后投递、幂等请求和 worker 崩溃恢复策略。
- 按已记录 ADR 采用 PostgreSQL、SQLAlchemy 2/psycopg 3/Alembic，并以 PostgreSQL Outbox 作为 P1 持久队列；目标 PostgreSQL 环境下的并发和故障恢复验收仍待完成。
- 按可独立验收的批次实施 P1：技术决策与迁移基线、Core/持久化契约、Workspace 与授权、Agent 配置版本、Session/Run/Event 与 worker、API 验收。
- 用户已确认本提案并授权开始编码；所有实现依据此变更记录。技术选型通过 ADR 显式记录，尚未接入的生产适配器不视为已实现。

## 3. 影响与范围

- **影响模块**：`core` 公共标识与事件契约、`platform` 身份/空间/配置/会话/运行/持久化、API/worker 组合入口、`migrations/`。平台关系库已按用户确认选用 PostgreSQL。
- **不在范围**：Native 执行循环、模型调用、知识库处理、技能/MCP 实现、渠道、观澜业务、前端管理页、外部 Runtime 接入、生产部署及选定具体队列产品。
- **验收结果**：能在 Workspace 授权边界内创建并发布 Native 配置型 Agent、创建固定版本 Session、幂等提交持久化 Run；事件可按游标续读，worker 的重复投递与异常中断可恢复或明确标记。P1 不执行模型推理。

## 4. 实施批次

1. **决策与存储基线**：已记录 PostgreSQL 迁移工具与 Outbox 队列 ADR；SQLite 迁移往返已验证，PostgreSQL 队列并发、崩溃恢复、取消和优雅关闭待目标环境验收。
2. **公共契约与持久化**：在 `core` 定义稳定平台 DTO/状态/事件契约；在 `platform` 建立仓储与事务端口；创建 PostgreSQL 初始迁移、审计、幂等、Outbox 和 worker lease 结构。
3. **身份、空间与 Agent 配置**：落地主体注入边界、Workspace/Membership 策略、Agent 草稿和不可变发布版本、模型配置及 CredentialRef、多资源绑定校验。
4. **Session、Run 与 worker**：落地 Session、幂等 Run、运行快照、授权复核、状态迁移、持久化事件、worker 领取/恢复、事件查询与 SSE 游标。
5. **验收与文档**：覆盖跨空间拒绝、撤权、版本不可变、幂等冲突、重复投递、崩溃恢复、事件续读和秘密保护；同步架构及资源契约文档。

身份提供方和凭据秘密后端尚未确定，因此本阶段通过可替换端口隔离，不绑定具体供应商；在缺少外部配置时不宣称提供生产认证或凭据保险库。
