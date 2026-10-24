# Proposal: P1 平台底座

## 1. 问题陈述

P1 需要为智能体平台建立可追溯、可授权的最小持久化底座。当前架构、资源模型和 Runtime 契约定义了对象边界，但尚未明确租户隔离规则、配置发布与快照语义、运行事件恢复语义、任务投递一致性及迁移管理约束。若直接开始 CRUD 或运行代码，各模块容易对身份、权限和状态作出不兼容假设。

## 2. 提议变更

- 定义 Workspace、Membership、Agent/AgentVersion、资源绑定、ModelProfile/CredentialRef、Session、Run、RunEvent、ToolInvocation 和 RuntimeSessionBinding 的 P1 逻辑模型及关系。
- 定义最小角色授权、空间边界、资源授权校验点、凭据引用边界和撤权生效时机。
- 定义 Agent 草稿/发布版本、会话固定版本、运行配置快照和资源版本引用语义。
- 定义 Run 状态迁移、事件顺序/游标、持久化后投递、幂等请求和 worker 崩溃恢复策略。
- 评估 PostgreSQL 迁移基线及候选任务队列，形成可验收的技术验证与 ADR 任务；选择在验证后确定。
- 定义 P1 实施顺序和验收条件，暂不实现业务接口或运行功能。

## 3. 影响与范围

- **影响模块**：`core` 公共标识与事件契约、`platform` 身份/空间/配置/会话/运行/持久化、API/worker 组合入口、`migrations/`。
- **不在范围**：Native 执行循环、模型调用、知识库处理、技能/MCP 实现、渠道、观澜业务、前端管理页、外部 Runtime 接入、生产部署及选定具体队列产品。
- **用户可见变化**：本变更只产生 OpenSpec 设计工件，不新增可用功能。
