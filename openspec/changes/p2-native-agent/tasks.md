# Tasks: P2 自研 Native 智能体闭环

用户于 2026-10-25 明确要求继续 P2 代码实现，已进入实施与本地验收。以下勾选表示实现和对应本地验证已完成，不代表 PostgreSQL、真实供应商或隔离后端的部署验收。验收证据与边界见 [verification.md](verification.md)。

- [x] 1. 参考行为与公共契约
  - [x] 1.1 按 `docs/architecture.md` 第 2 节 对照 GenericAgent 固定版本的 loop、handler、StepOutcome、工具、hooks、abort、history、checkpoint、memory/SOP 建立行为验收矩阵
  - [x] 1.2 设计并评审兼容的 `ChatModelPort`、ModelChunk/ToolCall、ToolResult/ToolDisposition、CancellationToken、RuntimeLifecycleHook 契约；core 不引入厂商类型
  - [x] 1.3 对照 P1 Runtime/Run/Event/ToolInvocation schema，确定事件向后兼容和助手/工具消息存储迁移
- [x] 2. Provider 与 Native Engine
  - [x] 2.1 验证首个 OpenAI-compatible 异步 SDK 的流式文本、工具参数分片、异常、超时和关闭行为，锁定依赖并记录 ADR/依赖归属
  - [x] 2.2 实现隔离的模型 Provider adapter、CredentialResolver 注入与秘密日志测试
  - [x] 2.3 实现 Native 多轮 Engine、上下文编排、token/轮次/耗时预算、流式文本与最终结果映射
  - [x] 2.4 实现多个工具调用的顺序处理、schema/JSON 校验、坏调用恢复、StepOutcome 三态和边界/重复回合保护
  - [x] 2.5 实现 typed lifecycle hooks：agent/turn/model/tool before/after，Hook 异常隔离和 Run 级注销/清理
- [x] 3. 工具、状态和安全
  - [x] 3.1 建立版本化 ToolDefinition/registry 与授权执行网关，检查当前 membership、resource grant、binding、run 和 capability
  - [x] 3.2 实现已登记的 Python 工具调用、ToolInvocation 状态、截断摘要、错误码与审计
  - [x] 3.3 设计 SandboxPort 与 capability gate；只有隔离 backend 验收通过才注册任意代码执行工具
  - [x] 3.4 实现运行级取消信号、模型流关闭、工具/Sandbox deadline、未知副作用 `interrupted` 和重复投递保护
  - [x] 3.5 实现 Session assistant/tool message、工作检查点、waiting_input 响应及记忆/SOP 待审核草稿扩展端口
- [x] 4. Platform/Worker/API 流程
  - [x] 4.1 在 worker Runtime Router 装配 Native Engine；保留未配置 Runtime 明确失败语义
  - [x] 4.2 实现事件先持久化后推送、Run SSE/Last-Event-ID 续读和游标回放测试
  - [x] 4.3 增加 waiting_input 提交与继续流程，避免 worker 长时间阻塞等待
  - [x] 4.4 验证同 Session 并发 Run 的顺序/互斥与幂等消息创建
- [x] 5. Web 会话工作台
  - [x] 5.1 对照 WeKnora/GenericAgent 界面核对会话连续性、模型/Agent 选择、流式内容、工具结果、进度和 Stop 行为
  - [x] 5.2 增加类型化 API/SSE 客户端、去重/断线重连 composable 和状态联合类型
  - [x] 5.3 实现 Native Session 对话页面、运行/工具状态、输入等待、取消/失败/重连和安全内容展示
  - [x] 5.4 验收桌面/窄屏、键盘/读屏、加载/空态/无权/错误/重复事件与停止反馈
- [x] 6. 验收与文档
  - [x] 6.1 FakeChatModel 覆盖文本流、多调用、坏参数、Provider 故障/超时/预算和取消
  - [x] 6.2 FakeTool/平台集成覆盖授权撤销、Session 隔离、重入/幂等、waiting_input、事件续读与未知副作用
  - [x] 6.3 使用明确隔离 backend 验收 Sandbox/文件产物；未提供 backend 时验证任意代码工具不注册
  - [x] 6.4 更新 Runtime 契约、资源模型、架构、目录和路线图，清楚区分 P2 已实现与保留扩展项

## 后续环境验收（不以模拟测试替代）

- PostgreSQL 专项按用户安排放到最后，在后续环境执行，继续跟踪 P1 未完成项。
- 使用账号实际可用的模型与凭据完成供应商在线验收；本轮没有发送真实模型请求。
- 按用户确认，沙箱仅保留现有接口，本轮不实现执行后端；已验证危险执行不注册且调用被拒绝，不宣称支持沙箱或文件产物。
- 未使用真实读屏软件；已验证语义标签、单一状态播报区、键盘焦点和桌面/窄屏。
- Memory/SOP 已实现草稿与扩展端口，审核发布/长期记忆检索仍待治理阶段，不自动生效。

当前保留变更目录供验收，尚未归档。
