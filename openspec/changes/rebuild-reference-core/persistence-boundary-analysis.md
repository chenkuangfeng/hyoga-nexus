# B1 写入应用服务的迁移关卡

本批在已批准范围内继续分离 Run 应用规则与 SQLAlchemy，不改变 API、表结构、权限或执行行为。不将此项记为 GA/WK 全量核心迁移。

## 参考来源与本批边界

WeKnora 固定 `e1f9a6166a593a4804a2f99f1d942919c9cc8ea7`：定点核对 `internal/application/service/session.go` 的 GetSession/GetOwnedSession/GetSessionByID（270–340 行）、`internal/application/repository/session.go` 的 Get/Create/Fork 事务，以及 `session_user_scope_test.go` 的 TestGetSessionIsScopedToCurrentUser（57–89 行）、repository/session_test.go 的 Get/Update/Delete 用户作用域测试（57–131 行）。本批仅使用已核对的读/写边界与事务职责，不宣称其余功能已迁移。源文件完整指纹沿用 implementation-progress.md，新增完整文件指纹（只对上述定点范围声称已读）：

- `internal/application/service/session.go`：`a160cd43545528c3a885a62f41640a9a5f7556107481a9e933a351842c907aed`。
- `internal/application/service/session_user_scope_test.go`：`3d73ffa1a09b221cf55ab303f7183a712a8d813dfa6a1b5ac600e336209ab538`。
- `internal/application/repository/session_test.go`：`24d6852ae30153153c0ef3bbbe09be837b05daeaf410a16bce9fd7834b1aa3bb`。

原行为：读路径与 owner 写路径不同；scope 是仓储必需输入；权限失败不会退化为未限定用户的写操作；多个关联写入同一事务。上游 legacy 空 user 的 tenant-wide 行为及 Admin+ API-key 读取回退不适用于 Nexus 已确认的主体/空间模型，本批保持原 Nexus 边界。没有复制上游片段，不新增未经核实的版权声明。

## 编码前分支映射

| 原 Nexus 分支 | 目标职责 | 必须保留的断言 |
| --- | --- | --- |
| submission.submit：trim/长度→主体/空间/成员→锁自己 Session→状态/版本/资源/模型授权→幂等→active Run→保存点→消息/事件/Outbox/审计 | submission.py 应用编排；configuration.py 值对象；configuration_repository.py 配置读取；submission_access.py 当前权限适配；repository.py Run 保存点；message/queue/audit 仓储 | 未授权幂等请求不成功；相同 key 不同 payload 冲突；保存点后的异常全回滚；Session 固定已发布版本 |
| cancellation.cancel：锁 workspace+principal Run；terminal 不写；queued/waiting 直接取消并完成 pending；running 只申请并确保 cancel task；先 cancelled 后 cancel_requested | domain.py Run 状态；cancellation.py 规则；repository/queue/audit 适配 | 他人/跨空间不能取消；终态不增事件；运行中不提前设 cancelled；事件顺序与队列状态兼容 |
| inputs.respond：不 trim 实际 key；锁自己的 Run；先检查已消费同 key+response，后 waiting/cancel 状态；一次写消息/event/重新入队/审计 | inputs.py 规则；input_repository.py 读写；message/queue/audit 适配 | 已消费相同回答可重放；不相同返回 Conflict；失败不消费输入、不增消息、不重新入队 |
| 旧函数返回 RunRecord，调用后借用 Session 无额外事务 | compatibility.py：单独维护 ORM 返回转换；应用服务返回独立 Run 对象 | 原入口保留 mapped identity；转换不追加 SELECT、不新开事务；纯领域更改只有显式 save 后持久化 |

仓储返回真正的领域数据副本，不用改名的 ORM 行充当领域对象。旧入口从本次 UoW 仓储已经跟踪的行取回兼容实体，不再打开另一事务。事件 flush 不 commit；原 Session/Run 锁、保存点与数据库约束保持。

执行准备/持久 store 继续作为后续分离项，不在本批勾选完整 Repository 门禁。

同批继续隔离旧 P1 `leasing.py::process`：原顺序为锁投递→校验已完成/owner→锁 Run→丢失/终态仅完成投递→取消优先→有执行记录则 interrupted→无 Runtime 首次 started/failed→完成并清理 lease。目标仍为 RunLeaseService，锁与完成更新移至 queue_repository，Run 状态用已有领域对象。验证错误 worker/重复投递无副作用，未知副作用不重放，started/failed 事件顺序及失败后的 Run/事件/投递回滚。此路径是原 P1 无 Runtime 兼容入口，不代替 Native ExecutionPreparer。
