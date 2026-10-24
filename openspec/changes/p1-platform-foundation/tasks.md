# Tasks: P1 平台底座

状态截至 2026-10-25。已完成项以代码和本地测试为准；依赖真实 PostgreSQL 的并发、故障恢复验收仍保持未完成。P1 变更不归档，直到所有验收项完成。

本轮验收安排（用户于 2026-10-25 确认）：先使用 SQLite 隔离测试，PostgreSQL 专项留到后续新环境执行。已运行 `uv sync --locked --extra dev` 和 `env -u NEXUS_TEST_POSTGRES_URL uv run --locked pytest -q -rs`，结果为 10 passed、1 skipped；跳过项为 PostgreSQL 专项。存在一条 FastAPI/Starlette TestClient 的 httpx 弃用警告，不影响本次测试结果。不将本次结果计入 PostgreSQL 验收，相关待办保持未勾选。

- [x] 1. 定稿领域契约
  - [x] 1.1 定义 Workspace/Membership/AgentVersion/Binding/Session/Run/Event/Invocation 逻辑模型及数据库空间一致性约束
  - [x] 1.2 定义角色矩阵、共享资源授权和工具执行时撤权复核语义
  - [x] 1.3 定义 Agent 发布、Session 固定版本及 Run 配置/权限快照字段
  - [x] 1.4 定义 Run 状态、事件序号/游标和幂等作用域
- [ ] 2. 技术验证与 ADR
  - [ ] 2.1 已选 SQLAlchemy 2、psycopg 3、Alembic 并完成 SQLite 迁移往返；待 PostgreSQL 目标版本迁移、并发事务/事件序号验证及 ADR 验收
  - [ ] 2.2 已比较 PostgreSQL Outbox、Redis Streams、RabbitMQ 并记录 ADR；待 PostgreSQL 重复投递、worker 崩溃恢复、取消、优雅关闭及观测验收
  - [x] 2.3 定义外部身份提供方注入端口和 CredentialRef/凭据解析端口；具体身份/密钥后端留待部署决策
  - [ ] 2.4 UUIDv7 已实现；事件与审计保留/归档策略尚未确定
- [ ] 3. Core 与持久化底层
  - [x] 3.1 在 core 定义 UUIDv7、角色、版本、Run 状态、事件和授权端口契约
  - [ ] 3.2 授权和凭据解析端口已定义；Repository/Unit of Work 端口及服务层 ORM 隔离未完成
  - [x] 3.3 建立 Alembic 平台迁移基线及 Workspace 一致性约束（SQLite 往返通过；PostgreSQL 验收待做）
  - [x] 3.4 建立审计、幂等约束、事务 Outbox 和 worker lease 持久化
- [ ] 4. 身份、空间与智能体配置
  - [x] 4.1 实现主体注入、User/Workspace Membership 解析与最小角色策略（仅本地开发身份；生产 IdP 未接入）
  - [x] 4.2 实现 Agent 草稿、多资源依赖校验和不可变发布版本
  - [x] 4.3 实现模型配置版本和不返回秘密句柄的 CredentialRef；真实凭据解析后端未接入
  - [ ] 4.4 实现多资源绑定、空间/grant 检查；Runtime capability 端口/真实 Runtime 校验尚待实现
- [ ] 5. Session、Run 与事件
  - [x] 5.1 实现固定 AgentVersion/RuntimeType 的 Session 创建和消息关联
  - [x] 5.2 实现幂等 Run 提交、权限/配置快照和事务 Outbox
  - [ ] 5.3 实现 worker lease、状态迁移和排队取消；真实 Runtime 中断/未知副作用恢复待实现与验收
  - [ ] 5.4 实现有序持久事件和分页游标；SSE 与 RuntimeSessionBinding 生命周期服务未实现
  - [x] 5.5 实现资源调用授权复核端口和关键平台操作审计；实际工具执行待 Runtime 阶段
- [ ] 6. 应用接口与验收
  - [x] 6.1 接入 API 与 worker 组合入口，core/platform 未依赖 Runtime SDK 或 guanlan
  - [ ] 6.2 SQLite/API 测试覆盖空间隔离、撤权、版本、幂等、分页和秘密保护；PostgreSQL 并发、重复投递/崩溃恢复与目标运行环境验收待做
  - [x] 6.3 更新 architecture/resource-model/runtime-contract/roadmap/reference-analysis 以反映已批准设计与当前边界
