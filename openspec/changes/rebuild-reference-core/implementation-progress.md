# 已批准实现的实际进度

本变更已获用户明确确认。此记录区分实际实现与后续迁移；B2–B4 仍未完成，不将已有 P0–P2 或本次结构拆分描述为完整对齐两个参考项目。

## B1：契约、实体、运行职责和事务首批

- `core/runtime.py`、`native.py` 改为同名 package，按模型、工具、事件、预算、存储、取消、策略和 hook 数据组织；类字段、默认值、方法和原入口继续保留。
- `persistence/base.py` 是唯一 Base；34 张表按身份、空间、配置、会话、运行、事件、调用、队列、记忆、审批和审计分布。原 `persistence.models` 导入仍指向相同定义。
- Run 原 `service.py`、`execution.py` 成为兼容入口，提交、查询、事件、取消、领取、执行准备、执行上下文、持久适配、输入回答与结束处理分别组织。原实现中的配置快照、幂等保存点、状态分支及授权条件保留。
- 实际使用 SqlAlchemyUnitOfWork，借用的会话不关闭，工厂创建的会话总是关闭；成功提交、异常回滚，拒绝隐式嵌套。查询、事件和领取使用实际仓储；授权与查询在同一事务，不额外开启 Session。
- 故障注入发现并修正 sqlite3 legacy 保存点未纳入外层物理事务的问题：UnitOfWork 对当前没有物理事务的 pysqlite 连接先发 BEGIN，已开启事务时保持原驱动控制。测试验证审计失败后 Run/消息/事件/Outbox 一起回滚，幂等键能重试；领取回滚不遗留 lease 或 attempts。

## 来源、适配与边界

本批以第一方实现的职责移动、仓储抽取与事务修复为主，没有复制上游代码片段，因此没有新增上游版权声明。不能将这一批计为 GA 循环、模型协议、WeKnora 全部 Session 或授权行为的迁移。

WeKnora 锁定版本 `e1f9a6166a593a4804a2f99f1d942919c9cc8ea7` 本批再次阅读：

| 源文件/指纹（SHA-256） | 核对的行为 | 本批目标与明确边界 |
| --- | --- | --- |
| `internal/application/repository/session.go` / `b6566a13e75ed77857d2142e5d8f9e90976b7bc98649ea99f5de223e3fb2a8e5` | Get tenant+user scope、Create/Fork 事务、QueryPaged 来源/分页、更新受影响行数与 fork snapshot 生命周期 | `runs/repository.py` 显式 workspace+user；UnitOfWork 同事务。保留 Nexus 既有可见性，不引入空 user 的 tenant-wide 回退。来源列表、pin、fork sandbox snapshot 等未在此批迁移。 |
| `internal/types/interfaces/session.go` / `c3e40404c7ddd31643178d58329b089ab84a57c92731f6b7023494ecd0b9ee9b` | Service/Repository 分离；GetSession 读取与 GetOwnedSession 修改权限不同；事务内 fork | `runs/ports.py` 表达查询边界；Nexus 既有读可见性、写所有者权限不变。不存在无授权公开的 GetByID。其余接口未宣称实现。 |

事务修复的驱动依据：[SQLAlchemy SQLite legacy transaction control](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html#legacy-transaction-mode-with-the-sqlite3-driver)，保存点早于 BEGIN 时无法被外围 ROLLBACK 撤销。此修复不改变表结构、API 或 PostgreSQL 事务协议。

## 本批验证

- `uv run --locked pytest -q -rs`：244 passed，1 skipped；跳过 `tests/test_platform_postgres.py`，环境没有 `NEXUS_TEST_POSTGRES_URL`。另有既存 Starlette/httpx 弃用警告。
- 相关平台与 Native 行为回归覆盖空间隔离、撤权、不可变版本、Session 固定、幂等、领取/过期、事件重放、取消与输入恢复。
- 新增 `test_run_transactions.py` 四项：提交后续失败完整回滚、领取回滚、会话归属/重入/事务拒绝与关闭、旧入口类型身份/唯一 metadata/外键解析。
- SQLite 空库正式升级、降级再升级与旧 P1 数据保留回归通过；正式迁移与拆分后 metadata 的 Alembic compare_metadata 差异为空。
- 拆分前后逐项比较 SQLite、PostgreSQL 的全部表与索引 DDL，列表完全一致。34 张表；SHA-256（按表名/索引名排序，SQL 用换行连接）：SQLite `b6c489579e1ee3e5397a56577f051d3078b4d8e3b8fc42de5ae861ab99fe1263`，PostgreSQL `9ec667e2d61eaa8e881cf6dee8f69c657879e03f12fe403617770c1e768d2530`。这不是 PostgreSQL 实库验收，不生成结构未变化的迁移。
- core、platform 的 sdist/wheel 构建通过；本地文档链接、`git diff --check`、OpenSpec 严格校验通过。
- 未修改前端，本批不涉及聊天交互与配置界面变更，未重新运行前端构建/浏览器用例。

## 未完成

B1 的提交、取消和输入恢复已完成下述写入隔离；执行资源授权、执行准备和持久适配仍需继续分离 ORM。B0 的其余模块深读门禁仍保留；B2 模型私有历史/文本协议/上下文压缩、B3 循环/hooks/工具并发、B4 快照/ActionGrant/长期记忆整理未完成。真实供应商、上游 Go 测试和 PostgreSQL 实库尚未验收；不归档提案，不勾选这些任务。


## B1 后续：写入应用边界

- RunSubmissionService、RunCancellationService、RunInputService 只操作领域对象和 RunCommandUnitOfWork 端口；直接导入这些类不会加载 SQLAlchemy。领域 Run 与 JSON 是独立副本，显式 save 后才写入跟踪行。
- 配置读取、当前权限、Run 幂等插入、消息、事件、队列、输入消费和审计分别绑定同一 Session。保留当前授权先于重放、Session 固定版本、原配置快照键、保存点回退、取消事件顺序、输入 key 原值和已消费回答优先重放等规则。
- compatibility.py 维护旧函数签名及 RunRecord 返回身份；直接使用仓储已跟踪的行，不追加提交后的查询。先前职责模块中的旧函数导入也继续可用。
- 新增 test_run_write_boundaries.py 14 项真实仓储/事务和架构边界用例；测试保存点碰撞与外层继续写入、无显式保存不落库、旧实体身份/事务状态、三种 idle 取消、active 取消去重、跨主体/空间写入拒绝、取消/输入后续失败回滚、回答 key 原值/终态重放、禁用主体不能用幂等绕过权限。没有删除旧用例，原事务故障探针改为在审计适配边界注入。
- 对应编码前来源/分支/目标/断言映射见 [写入迁移关卡](persistence-boundary-analysis.md)。本批以第一方持久化隔离为主，没有复制上游片段，不宣称循环、协议或全部 Session 功能已迁移。

- 同批完成旧 P1 RunLeaseService.process 的队列/Run/事件/审计端口隔离，保留 missing/completed/foreign owner 早退、取消优先、未知执行 interrupted、无 Runtime started/failed 和 terminal 早退租约字段语义。新增 test_run_lease_boundaries.py 的 8 项真实数据库用例；领域导入隔离测试一并覆盖租约服务。

- 本批最终全量回归：`uv run --locked pytest -q -rs` 为 266 passed、1 skipped，仍只跳过缺少 `NEXUS_TEST_POSTGRES_URL` 的 PostgreSQL 专项，既有 Starlette/httpx 弃用警告保留。platform 的 sdist/wheel 构建通过；SQLite/PostgreSQL 34 张表与索引 DDL 再次逐项比较不变，SQLite 正式迁移/metadata 一致性随全量测试通过。未生成伪迁移，未修改前端。
