# 实施任务

状态：待确认（2026-11-07）。已完成的任务才勾选。

## 0. 准备
- [ ] 0.1 用户确认决定 1–8。
- [ ] 0.2 补读 deer-flow `stream_bridge/redis.py` 的 `subscribe`、围栏与清理，`runs/worker.py` 的发布与租约接入；WeKnora `redis_manager.go` 的 live-run 与 steer 部分。
- [ ] 0.3 核对：助手消息是否在持久事件中携带完整文本（决定 2 的前提）；`message.delta` 的所有消费方；前端事件归并逻辑。
- [ ] 0.4 先更新文档：`docs/architecture.md`、`docs/roadmap.md`、`apps/api`、`apps/worker`、`packages/core`、`packages/platform` 的 design 与 README。

## 1. 契约与配置
- [ ] 1.1 `nexus_core.run_events`：端口、`BusEvent`、`StreamGap`、哨兵；契约无外部依赖。
- [ ] 1.2 `[run_events]` 配置与启动校验；`configs/nexus.example.toml`；`redis` extra。

## 2. 后端
- [ ] 2.1 `memory` 后端与分进程部署的启动检查。
- [ ] 2.2 `database` 后端：共享轮询器、自适应间隔、定期复核授权。
- [ ] 2.3 `redis` 后端：发布、订阅、断档、围栏租约、清理、`ping`、瞬时错误重试。
- [ ] 2.4 `ControlChannel`、`LiveRunMarker` 三后端实现。
- [ ] 2.5 契约测试：三后端同一套用例（`fakeredis`）。

## 3. 写入路径
- [ ] 3.1 `store.py`：持久事件提交后发布；临时事件走通道；失败吞掉并计数。
- [ ] 3.2 `heartbeat()` 接入控制通道、生产者租约、活动标记续期。
- [ ] 3.3 取消与审批接口双写控制信号。
- [ ] 3.4 终态收尾：`publish_end`、清标记、延迟清理；会话与 Run 删除清理键。

## 4. API
- [ ] 4.1 SSE 异步订阅与 `stream.resync`；流内短会话。
- [ ] 4.2 `GET /sessions/{id}/live-run`；`/health/ready` 报告。
- [ ] 4.3 指标。

## 5. 前端
- [ ] 5.1 无 `id` 事件、`stream.resync`、`live-run` 接入；单元测试。

## 6. 验证
- [ ] 6.1 压测脚本与三后端对比数据记入 `docs`。
- [ ] 6.2 故障注入：Redis、worker、客户端。
- [ ] 6.3 全量 `pytest`、`pnpm build` 与浏览器测试。
