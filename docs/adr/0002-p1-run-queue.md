# ADR-0002：P1 Run 持久队列

- 状态：P1 初始实现采纳；PostgreSQL 并发/故障演练待目标环境验证
- 日期：2026-10-24
- 范围：Run 投递、worker 领取与租约恢复

## 决策

P1 以 PostgreSQL Outbox 表作为持久 Run 队列，不增加 Redis、RabbitMQ 等独立 broker。Outbox 记录与 Run、初始状态及 `run.queued` 事件在同一事务提交。Worker 用 `SELECT ... FOR UPDATE SKIP LOCKED` 领取可处理记录，并写入有过期时间的 lease。队列语义为至少一次；Run 状态和幂等约束负责阻止重复执行。

Worker 丢失 lease 后，新 worker 可以重新领取记录。若持久 Run 状态表明外部执行可能已开始但结果不明，必须转为 `interrupted`，不自动重放副作用。P1 未接入 Runtime，因此新 Run 被 worker 明确标记为 `failed/runtime_not_configured`；不把队列消费描述成模型执行。

## 候选比较

| 候选 | 优点 | 成本与风险 | P1 结论 |
|---|---|---|---|
| PostgreSQL Outbox/队列表 | 与 Run 状态同事务；无需第二套服务；`SKIP LOCKED` 可支持多个消费者领取不同记录 | 与业务库争用资源；需监控积压、清理完成记录和数据库负载；适合当前平台规模，不能据此承诺高吞吐 | 采用 |
| Redis Streams | Consumer group 提供 pending entries；`XAUTOCLAIM` 可把闲置消息交给其他消费者；适合横向消费 | Run 事务仍需 PostgreSQL Outbox 和 relay；额外运行 Redis；Redis 确认与数据库状态不在同一事务，需接受重复投递并持续对账 | 暂不采用；规模/隔离需求出现时复评 |
| RabbitMQ 等独立 broker | 更完整的 broker 路由、确认和运维能力 | 仍需 transactional outbox；增加服务、客户端和部署/监控成本 | P1 不增加 |

PostgreSQL 文档说明 `SKIP LOCKED` 会返回不一致视图，因此不适合普通查询，但适用于多个消费者访问 queue-like table 以避免锁竞争。[PostgreSQL SELECT 锁定文档](https://www.postgresql.org/docs/current/sql-select.html)。Redis Streams 使用 pending entries 跟踪未确认消息，并支持用 `XAUTOCLAIM` 转移 idle 消息所有权。[Redis Streams 官方文档](https://redis.io/docs/latest/develop/data-types/streams/)；[XAUTOCLAIM 命令](https://redis.io/docs/latest/commands/xautoclaim/)。

## 验证状态

- 已实现 Postgres 方言的 row-lock/skip-locked claim、lease 到期重领、幂等 Outbox 消息、持久 Run 状态检查、终态事件和显式 worker 关闭。
- SQLite 单元/API 测试覆盖 Run 提交、事件续读和 worker 消费；SQLite 不执行 PostgreSQL 行锁语义。
- 当前容器未提供 PostgreSQL 服务且 Docker daemon 不可访问。生产并发领取、崩溃、取消和优雅关闭验收须运行 `NEXUS_TEST_POSTGRES_URL` 集成测试后完成；在此之前本 ADR 的 PostgreSQL 运行验证状态保持待办。

## 复评条件

出现队列延迟/积压、数据库连接池争用、Outbox 表维护成本或需要多类型消息路由时，用目标部署配置比较 PostgreSQL 队列与 Redis Streams/RabbitMQ，先补测重复投递、崩溃恢复、取消、关闭和观测，再以新 ADR 切换。
