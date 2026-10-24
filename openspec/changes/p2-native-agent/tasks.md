# Tasks: P2 自研 Native 智能体闭环

本变更为设计草案，等待用户确认后才开始编码。所有代码任务初始未勾选。

- [ ] 1. 参考行为与公共契约
  - [ ] 1.1 按 `docs/reference-analysis.md` 对照 GenericAgent 固定版本的 loop、handler、StepOutcome、工具、hooks、abort、history、checkpoint、memory/SOP 建立行为验收矩阵
  - [ ] 1.2 设计并评审兼容的 `ChatModelPort`、ModelChunk/ToolCall、ToolResult/ToolDisposition、CancellationToken、RuntimeLifecycleHook 契约；core 不引入厂商类型
  - [ ] 1.3 对照 P1 Runtime/Run/Event/ToolInvocation schema，确定事件向后兼容和助手/工具消息存储迁移
- [ ] 2. Provider 与 Native Engine
  - [ ] 2.1 验证首个 OpenAI-compatible 异步 SDK 的流式文本、工具参数分片、异常、超时和关闭行为，锁定依赖并记录 ADR/依赖归属
  - [ ] 2.2 实现隔离的模型 Provider adapter、CredentialResolver 注入与秘密日志测试
  - [ ] 2.3 实现 Native 多轮 Engine、上下文编排、token/轮次/耗时预算、流式文本与最终结果映射
  - [ ] 2.4 实现多个工具调用的顺序处理、schema/JSON 校验、坏调用恢复、StepOutcome 三态和边界/重复回合保护
  - [ ] 2.5 实现 typed lifecycle hooks：agent/turn/model/tool before/after，Hook 异常隔离和 Run 级注销/清理
- [ ] 3. 工具、状态和安全
  - [ ] 3.1 建立版本化 ToolDefinition/registry 与授权执行网关，检查当前 membership、resource grant、binding、run 和 capability
  - [ ] 3.2 实现已登记的 Python 工具调用、ToolInvocation 状态、截断摘要、错误码与审计
  - [ ] 3.3 设计 SandboxPort 与 capability gate；只有隔离 backend 验收通过才注册任意代码执行工具
  - [ ] 3.4 实现运行级取消信号、模型流关闭、工具/Sandbox deadline、未知副作用 `interrupted` 和重复投递保护
  - [ ] 3.5 实现 Session assistant/tool message、工作检查点、waiting_input 响应及记忆/SOP 待审核草稿扩展端口
- [ ] 4. Platform/Worker/API 流程
  - [ ] 4.1 在 worker Runtime Router 装配 Native Engine；保留未配置 Runtime 明确失败语义
  - [ ] 4.2 实现事件先持久化后推送、Run SSE/Last-Event-ID 续读和游标回放测试
  - [ ] 4.3 增加 waiting_input 提交与继续流程，避免 worker 长时间阻塞等待
  - [ ] 4.4 验证同 Session 并发 Run 的顺序/互斥与幂等消息创建
- [ ] 5. Web 会话工作台
  - [ ] 5.1 对照 WeKnora/GenericAgent 界面核对会话连续性、模型/Agent 选择、流式内容、工具结果、进度和 Stop 行为
  - [ ] 5.2 增加类型化 API/SSE 客户端、去重/断线重连 composable 和状态联合类型
  - [ ] 5.3 实现 Native Session 对话页面、运行/工具状态、输入等待、取消/失败/重连和安全内容展示
  - [ ] 5.4 验收桌面/窄屏、键盘/读屏、加载/空态/无权/错误/重复事件与停止反馈
- [ ] 6. 验收与文档
  - [ ] 6.1 FakeChatModel 覆盖文本流、多调用、坏参数、Provider 故障/超时/预算和取消
  - [ ] 6.2 FakeTool/平台集成覆盖授权撤销、Session 隔离、重入/幂等、waiting_input、事件续读与未知副作用
  - [ ] 6.3 使用明确隔离 backend 验收 Sandbox/文件产物；未提供 backend 时验证任意代码工具不注册
  - [ ] 6.4 更新 Runtime 契约、资源模型、架构、目录和路线图，清楚区分 P2 已实现与保留扩展项
