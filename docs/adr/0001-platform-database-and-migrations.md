# ADR-0001：平台主存储与迁移机制

- 状态：已采纳
- 日期：2026-10-24
- 范围：P1 平台持久化

## 决策

- 平台主关系库使用 PostgreSQL。此数据库选择已由用户确认。
- 使用 SQLAlchemy 2.x 定义持久化适配器与事务边界，使用 psycopg 3 连接 PostgreSQL。
- 使用 Alembic 管理有序迁移。迁移由发布/运维命令显式执行，不在每个 API 或 worker 实例启动时自动运行。
- 平台状态、Run 事件、幂等记录和 Outbox 都以 PostgreSQL 为事实源。平台暂不启用 ORM 自动建表。
- P1 API/worker 使用同步 SQLAlchemy Session，FastAPI 同步路由在其线程池中执行；共享 Core 契约不暴露 ORM 类型。

## 原因

已有部署决策确定 PostgreSQL。SQLAlchemy 为 Python 应用提供 PostgreSQL 方言和事务抽象，Alembic 以 SQLAlchemy 元数据和迁移脚本管理 schema 变化。数据模型优先用关系外键和唯一约束表达归属、版本和幂等；Run 配置/事件 payload 用 JSON 保存。

同步 Session 让短事务行为可见，API 与 worker 共用 Repository/Unit of Work 端口；Run 外部执行不会持有数据库事务。后续若引入异步 I/O，可在适配器层增加异步实现，不改变 Core DTO 和授权语义。

## 验证

- `uv.lock` 固定当前实际解析的 SQLAlchemy、Alembic、psycopg 版本。
- 已在临时 SQLite 兼容库上生成并执行初始 Alembic 迁移，且通过 downgrade/upgrade 往返。
- 运行环境没有 PostgreSQL 二进制，也没有可访问的 Docker daemon；因此 PostgreSQL 真实服务器上的迁移演练仍需部署环境复验，不将 SQLite 结果当成 PostgreSQL 验收。

## 后果

- PostgreSQL URL 通过 `NEXUS_DATABASE_URL` 提供；代码、迁移和示例不包含可用凭据。
- `NEXUS_AUTH_MODE=development` 使用固定本地开发主体，不代表生产认证；默认未配置身份提供方时平台资源 API 返回 503。
- 不提供 SQLite 应用后端模式；SQLite 仅供隔离单元测试和迁移脚本的方言兼容检查。

## 来源

- [Alembic 官方迁移教程](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [SQLAlchemy 官方文档](https://docs.sqlalchemy.org/en/20/)
