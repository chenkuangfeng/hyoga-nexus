# 实施任务

状态：实施中（2026-11-07，决定 1–8 已确认，默认并发 32）。已完成的任务才勾选。

## 0. 准备
- [x] 0.1 用户确认决定 1–8（决定 1 默认 32）。
- [ ] 0.2 补读 deer-flow `runtime/runs/worker.py` 的任务生命周期与取消、`app/gateway/app.py` 并发上限接入；Octop `infra/bridge/transport.py` 的 `_spawn`；WeKnora `qa.go` 的取消上下文。
- [ ] 0.3 共享状态审计（沙箱会话、工具注册表、嵌入器单例、`contextvars`、`OutputSpill`、模型连接池配置、`_worker_loop`），结果记入本节。
- [ ] 0.4 扫描 `async def` 内直接调用同步数据库的位置，列出清单。
- [ ] 0.5 先更新文档：`docs/architecture.md` 2.12、`docs/roadmap.md`、`apps/worker`、`apps/api`、`packages/platform` 的 README 与 design，`configs/nexus.example.toml`。

## 1. 配置
- [ ] 1.1 `[worker]`：`max_concurrent_runs`、`db_threads`、`stop_timeout_seconds`；启动校验；`embedded_workers` 弃用警告。
- [ ] 1.2 启动时校验线程池与连接池容量。

## 2. 并发执行
- [ ] 2.1 `db_call` 与专用线程池；热点调用迁移；新增静态扫描测试。
- [ ] 2.2 `ControlChannel.wait_async` 三后端实现；监视协程改用它。
- [ ] 2.3 `run_async`：领取协程、信号量、Run 任务；`once`、`stopped` 语义保持。
- [ ] 2.4 后台作业放线程并限制并发。
- [ ] 2.5 停止流程与总超时。
- [ ] 2.6 事件循环滞后看门狗。
- [ ] 2.7 嵌入模式改单线程单循环。

## 3. unknown 恢复
- [ ] 3.1 `resolve_unknown_admin` 与列表查询；权限；审计。
- [ ] 3.2 接口 `GET .../admissions/unknown`、`POST .../runs/{id}/resolve-unknown`；命令行 `list-unknown`、`resolve-unknown`。
- [ ] 3.3 `settle_recovered_unattended` 接入启动恢复。
- [ ] 3.4 安全判定与 `[platform].auto_resolve_safe_unknown`（默认关闭）。
- [ ] 3.5 会话视图 `blocked` 字段；前端提示条与解除按钮。

## 4. 验证
- [ ] 4.1 并发 N 个 Run、取消隔离、停止、慢数据库、崩溃恢复、权限、自动解除、嵌入模式连接复用等测试。
- [ ] 4.2 全量 `pytest`；默认配置下事件序列基线不变。
- [ ] 4.3 前端单元测试；`pnpm build` 与浏览器测试（本机内存不足时在有条件的环境执行）。
