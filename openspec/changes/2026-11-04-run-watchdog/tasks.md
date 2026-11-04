# 任务：运行监督 Watchdog

> 状态：后端与 API 已实施并通过测试；工作台提示与操作待办。`[x]` 表示已完成并验证，`[ ]` 表示未完成。

## 1. 前置

- [x] 1.1 确认 proposal.md 中的决定（按推荐方案，见 proposal.md 第 6 条）。
- [x] 1.2 回合数规则依赖 3.15，本次不实现；只实现"空闲"与"重复调用"两条规则。
- [x] 1.3 等待状态通过 Run 状态判断：只检查 `running`，等待输入与等待审批自动排除。

## 2. 实施

- [x] 2.1 规则为纯函数，位于 `packages/platform/src/nexus_platform/runs/watchdog.py`，不依赖数据库与模型。
- [x] 2.2 执行监控协程按间隔调用 `DurableRuntimeStore.watch`（`apps/worker/src/nexus_worker/native.py`）；检测异常只记日志。
- [x] 2.3 不新增持久化字段。`attention_required` 由事件派生（最新告警晚于所有非 Watchdog 事件与确认事件），因此无迁移。（原任务为"持久化字段并迁移"，已在实施中调整。）
- [x] 2.4 API：Run 视图增加 `attention_required`；新增 `POST .../runs/{run_id}/watchdog/acknowledge`。
- [x] 2.5 配置：`[watchdog]` 读取与校验（`watchdog_settings`），worker 启动时读取，无效值直接拒绝启动；`configs/nexus.example.toml` 与 `configs/README.md` 已同步。
- [ ] 2.6 Web 工作台：展示告警，提供"继续等待 / 取消 / 发送提示"。**未实施**：需要在前端接入 `attention_required` 与确认接口，并通过 `pnpm build` 验证（本机构建因内存不足被终止，需在有足够内存的环境验证）。

## 3. 测试

- [x] 3.1 规则单元测试：空闲超时、非运行状态不触发、重复调用需连续相同、签名只取决于工具名与参数、配置校验（`tests/test_run_watchdog.py`）。
- [x] 3.2 存储层测试：同一规则在一次停滞期内只告警一次；规则恢复后再次停滞会重新告警；告警不改变 Run 状态。
- [x] 3.2a 监控协程的检测异常不中断 Run（测试：`test_watchdog_check_failure_does_not_fail_the_run`）。
- [x] 3.3 SQLite 验证（无迁移）。PostgreSQL 验证随路线图 2.9。
- [x] 3.4 API 测试：`attention_required` 在告警后为 true，确认后为 false。
- [ ] 3.5 前端：告警展示与三个操作的可见状态；窄屏布局。（随 2.6）

## 4. 文档与收尾

- [x] 4.1 `docs/architecture.md` 2.2 与 2.12 已更新；`configs/README.md` 已更新。
- [ ] 4.2 路线图 3.23 勾选：尚未勾选，因为 2.6 工作台未完成。
- [ ] 4.3 OpenSpec 规格同步与归档：待工作台完成后执行。
