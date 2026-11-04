# 任务：Native 运行工作台

> 状态：已确认，实施中。`[x]` 表示已完成，`[ ]` 表示未完成，括号内注明原因。

## 1. 前置

- [x] 1.1 确认 proposal.md 中的四项决定。
- [x] 1.2 核对平台接口的请求与响应结构（Run 视图、事件 payload、`queue_position`、`attention_required`），确定前端类型。

## 2. 接口封装

- [x] 2.1 `api/native-runs.ts`：会话列表与创建、智能体列表、提交 Run（幂等键）、读取 Run、订阅事件（SSE，`Last-Event-ID`）、取消、等待输入回答、确认告警、追加指令。
- [x] 2.2 响应校验：对 Run 与事件的关键字段做运行时校验（`api/native-run-types.ts`，测试见 `native-run-types.test.ts`）。

## 3. 页面与组件

- [x] 3.1 路由与导航：`/platform/native`、`/platform/native/sessions/:sessionId`，导航项 `menu.native`（需要登录与空间）。
- [x] 3.2 会话页：智能体选择（仅已发布）、消息列表、输入框、排队位置提示。
- [x] 3.3 事件渲染：文本流、工具调用（开始、完成、失败）、终态与错误码；按 `sequence` 去重（`nativeRunState.ts`，测试覆盖）。
- [x] 3.4 告警条（`NativeWatchdogBanner.vue`）：`attention_required` 为 true 且 Run 未结束时显示，三个操作；操作后刷新 Run 视图。
- [x] 3.5 等待输入：显示问题与候选项，提交回答。
- [x] 3.6 状态与无障碍：加载、空结果、失败、断线提示；按钮有可读名称；告警条使用 `role="alert"`；窄屏布局（media query）。无权限的专门状态未单独设计，沿用服务端错误信息。

## 4. 测试与验证

- [ ] 4.1 测试：状态规则（去重、顺序、告警显隐、操作权限）已覆盖。**未完成**：组件测试（告警条交互、确认后刷新、续读不重复提交）尚未编写。
- [ ] 4.2 `pnpm build` 与类型检查：`vue-tsc` 检查 `views/native` 与新增模块通过；完整 `pnpm build` 与整个项目的类型检查因本机内存不足（OOM）未能完成。前端全量测试 2049 项中 2044 通过、5 跳过、0 失败（含样式守卫与 i18n 审计）。
- [ ] 4.3 浏览器用例：未编写，需要后端夹具与浏览器环境。

## 5. 文档与收尾

- [x] 5.1 更新 `apps/web/docs/design.md`：删除不存在的 Native 组件描述，补充新页面。
- [ ] 5.2 更新 `docs/roadmap.md` 第 3 步 3.23 的进度，以及 `openspec/changes/2026-11-04-run-watchdog/tasks.md` 中的 2.6、3.5、4.2。
- [ ] 5.3 OpenSpec 规格同步与归档，按工作流执行。
