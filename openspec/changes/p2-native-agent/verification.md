# P2 本地验收与参考行为映射

本记录仅证明已选基础闭环的本地验证，不代表 GenericAgent / WeKnora 全功能迁移完成。后续设计讨论见 [总体架构](../../../docs/architecture.md)。

用户于 2026-10-25 确认开始实现。本轮以 SQLite 隔离数据库、真实锁定 SDK + 模拟 HTTP 流、FakeChatModel/FakeTool 和 Chromium API/SSE 夹具进行验证，不发送真实模型请求。PostgreSQL 专项按用户安排留到新环境执行。

## 参考行为与兼容证据

只读核对 GenericAgent `a9a36b4`（MIT）与 WeKnora `e1f9a6166`（MIT 及其第三方许可说明），没有复制其源码。

| 参考行为/状态/错误与扩展点 | P2 实现与兼容边界 | 本地证据 |
| --- | --- | --- |
| GenericAgent `agent_runner_loop` 多轮模型/工具循环与输出 | Native Engine 独占循环；文本增量先持久化，完成后保存 assistant；模型异常映射稳定代码 | 多工具、超时、不完整流、预算测试 |
| `StepOutcome(data,next_prompt,should_exit)` | 显式 continue/complete/wait_input/exit；保留数据、续接提示与完成/失败理由，不以空提示推断成功 | exit、continuation 协议测试 |
| `BaseHandler.dispatch` 多工具和坏 JSON 恢复 | 按声明顺序处理、JSON Schema 校验、独立 invocation；错误反馈模型并消耗预算 | 坏 JSON、错误类型、多调用顺序、工具超时测试 |
| agent/turn/llm/tool before/after hooks | 稳定元数据 DTO、异常隔离、超时与运行级清理，不暴露 locals/SDK/凭据 | hooks 失败隔离及模型关闭测试 |
| Queue、abort 和多前端输出 | 平台 Outbox/Run/Event、取消 monitor、模型流/工具取消；有副作用结果未知为 interrupted | 模型取消、工具两类取消、失租约恢复测试 |
| history/history_info、working checkpoint | Session 消息与检查点持久化、历史来源授权、完整最近工具交换、有界旧摘录；不删除源消息 | 会话隔离、检查点恢复、上下文压缩测试 |
| ask_user 进程内等待 | InputRequest + 同一 Run 幂等回答 + execute Outbox，等待不占 worker；预算跨恢复累计 | 等待/回答/重复回答、等待取消测试 |
| 长期 memory/SOP 更新 | 来源 Run、Session scope、diff、pending_review 草稿与读取 API；不注入正式记忆 | 草稿持久化与 system prompt 不含草稿测试 |
| code_run/宿主文件/web | 保留 SandboxPort；未接入已验收后端时不暴露，声明 sandbox capability 的工具也被网关拒绝 | 能力接口与未验证 Sandbox 拒绝测试 |
| WeKnora 会话 busy gate/测试 | 服务检查 + 数据库活跃 Run 部分唯一索引，避免同会话历史交错；新 Session 不受影响 | 活跃会话冲突、Run 幂等、P1 回归 |
| WeKnora 事件/权限与共享范围 | 持久序号、SSE 分页/游标续读；每次工具访问复核主体/空间/绑定/当前 grant 并审计 | SSE cursor/越权、工具间撤权和撤权后上下文拒绝测试 |
| WeKnora AgentGrant 高风险审批、自动化 | 不用 Workspace grant 冒充动作审批；本轮不启用任意宿主执行/自动化，高风险治理仍待后续实现 | capability unavailable，不宣称支持审批执行 |
| 两项目 UI 会话连续性、模型选择、工具进度和 Stop | 已发布 Agent/模型版本固定、Session 历史、工具卡片、等待、停止、游标重连；安全文本渲染 | 浏览器发送/回答/停止/重连/重复事件/安全显示/无权清理测试 |

## 验证命令

```bash
uv sync --locked --extra dev
env -u NEXUS_TEST_POSTGRES_URL uv run --locked pytest -q -rs
cd apps/web
npm ci
npm run build
# 保持 npm run dev 运行，且已安装 Chromium
npm run test:browser
```

- Python：31 passed、1 skipped；跳过项为 PostgreSQL 专项。SQLite 测试启用外键检查。
- 迁移：空库升级/降级/重升；保留 P1 已有用户数据、重复 upgrade、P2 表与消息元数据列检查。
- Provider：锁定 `openai==2.29.0` 的文本/参数分片合并、usage、流终止、超时、限流、上下文错误与错误秘密不外泄。
- Web：TypeScript 与 Vite 构建通过；Chromium 验证发送、等待/回答、工具状态、事件去重、游标重连不重发请求、停止、安全文本、无权清理、键盘焦点、1440px/375px 布局。
- 现存非失败警告：FastAPI/Starlette TestClient 的 httpx 弃用提醒；Element Plus 全量引入导致 Vite 大 chunk 提醒。未为绕过警告修改阈值或引入未验证依赖。

## 验收边界

- PostgreSQL 迁移/并发/真实进程故障和生产部署未验收；P1 保持其待办，不因 P2 本地通过而归档。
- 没有实际供应商账号在线验收；需使用目标环境实际模型、兼容协议和凭据再次核对。
- 按用户确认，沙箱仅保留现有接口，本轮不实现隔离 backend；任意代码执行与文件产物不可用，不声称普通 Python 函数具备沙箱隔离。
- 浏览器使用 API/SSE 夹具，后端集成使用真实 SQLite；不是完整部署环境的端到端验收。
- 未运行真实读屏软件；已有可访问名称、单一 polite 状态区、键盘焦点与响应式检查。
- Memory/SOP 审核发布、长期检索，消息/事件 retention 治理和外部 Runtime 仍为后续能力。P2 变更目录保留供部署验收，不提前归档。
