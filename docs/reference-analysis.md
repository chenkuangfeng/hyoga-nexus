# 参考项目与取舍

静态阅读日期：2026-10-24。未安装运行参考项目，不把 README 演示和性能说法视为本项目验收结果。

| 项目 | 本地版本 | 主要参考价值 |
|---|---|---|
| Tencent/WeKnora | e1f9a6166 / v0.8.3 | 知识库生命周期、混合检索与引用、多资源绑定、会话/事件、IM 适配、权限和沙箱 |
| lsdefine/GenericAgent | a9a36b4 | Python 轻量循环、工具分发、分层记忆、SOP、生成器输出与多前端入口 |

## GenericAgent 实际组织

- agent_loop.py：agent_runner_loop 循环调用 client.chat，解析 tool_calls，再通过 BaseHandler.dispatch 分发 do_<tool>；StepOutcome 表达结果、下一步提示与退出。
- agentmain.py：GenericAgent 用任务与输出 Queue、后台线程、模型客户端和历史状态组织任务，支持 abort；不是单纯一个无状态请求函数。
- ga.py：9 类基础工具包括代码执行、文件读/写/补丁、网页扫描/JS、工作检查点、询问用户和长期记忆更新。
- llmcore.py：多模型请求、工具协议与历史处理；NativeClaudeSession 是模型会话实现，不等于 Claude Code Agent SDK。
- memory/：分层索引、事实、SOP/脚本与原始会话；“自进化”主要通过模型按指令更新记忆和程序实现，不是自动训练模型权重。
- plugins/hooks.py：提供 agent/turn/LLM/tool 生命周期回调，部分调用传 locals()，接口耦合较紧。
- frontends/：包含 Streamlit、终端、FastAPI conductor、桌面桥，以及企业微信/微信/QQ 等入口。
- frontends/genericagent_acp_bridge.py：ACP 初始化声明 HTTP/SSE MCP 能力为 false；不能因为有 ACP 桥就假设已有完整 MCP 或知识库资源体系。

## 适合迁移的能力

紧凑而可替换的执行循环、统一工具结果、运行生命周期钩子、短期工作检查点、摘要/索引/详细资料分层、完成后沉淀 SOP 草稿、多入口复用任务执行。

## 需要重新设计

当前 code_run 主要通过宿主机 subprocess 执行，inline_eval 还可以在当前进程执行并改变 cwd；工作目录规范化不等于文件系统隔离。服务化需要独立沙箱、运行级权限与资源限制。

存在源码目录下 memory/temp、模块级配置与工具 Schema，以及前端/执行逻辑间的共享状态。不能直接把一个共享 GenericAgent 实例交给所有用户。需按平台 Session/Run 隔离，并将持久化、模型配置和事件协议移到平台边界。

原子工具的能力很广；Nexus 优先提供确定性领域工具，受控 shell 按授权启用。SOP/经验更新经过草稿、验证、版本发布，不直接改写生产技能。知识库多租户检索、文档版本和权限体系另行用 Python 建立。

## 组合建议

平台组织与智能体可靠性逻辑对照 WeKnora，Native 执行/工作记忆/SOP 主干对照 GenericAgent。用户已明确要求按锁定源码复制或等价翻译迁移全部适用逻辑与细节，并参照模块结构；日常配置优先通过前端管理，允许保持兼容的易用性扩展。自有 Python 知识库形成公共资源；Codex/Claude Code/其他运行时并列接入同一资源体系。当前尚未迁移完整源码；后续逐文件核对许可证、保留来源与归属，不提交整个第三方源码仓库。

## P1 实现映射

- WeKnora 以 Tenant ID 作为资源数据范围，并由请求上下文携带 tenant/user 身份；Nexus 将该边界表达为 Workspace，并在服务层将 Principal 映射为 User，再验证 Membership。关键 AgentVersion、Session、Run 和模型配置关系增加 Workspace 复合外键，读取和写入都按 Workspace 过滤。
- WeKnora 对共享 Agent/知识库分别检查来源租户和共享范围；Nexus 的 ResourceGrant 只表示 Workspace 间显式共享，ResourceBinding 只记录 Agent 版本想使用的资源。发布、Run 创建和真实资源访问分别复核资源登记、版本与当前 Grant，Agent 配置不会自行授予权限。
- WeKnora 的 AgentGrant 是另一类授权：按 session/automation scope 绑定用户、grant key、配置 hash、风险级别、撤销/过期时间和 automation 空闲期。它不能与 ResourceGrant 混为一谈。P1 尚无 Runtime 工具调用和审批执行；在实现工具审批/记忆授权前，后续 OpenSpec 必须逐字段保留并扩展这些可观察语义，不得用 Workspace 角色或资源共享替代。
- GenericAgent 的任务 Queue、输出 Queue、Abort 与 StepOutcome 属于执行生命周期。P1 只实现持久化 Run/事件和数据库 worker 投递；P2 Native Runtime 必须在统一事件契约下保留流式输出、工具结果、停止控制、生命周期钩子及运行级隔离。

## 核查入口

- https://github.com/lsdefine/GenericAgent/blob/a9a36b4/agent_loop.py
- https://github.com/lsdefine/GenericAgent/blob/a9a36b4/ga.py
- https://github.com/Tencent/WeKnora/tree/e1f9a6166/internal/agent
- https://github.com/Tencent/WeKnora/tree/e1f9a6166/internal/im

## P2 行为保持

已按相同固定版本核对 GenericAgent loop/StepOutcome/dispatch、hooks、abort、history、checkpoint、memory/SOP，以及 WeKnora 事件、会话 busy gate/测试、AgentGrant 测试和流式聊天组件。Native 的行为映射与本地测试证据见 [P2 验收矩阵](../openspec/changes/p2-native-agent/verification.md)。没有复制两个项目的源码。

多用户服务采用持久 Run/Input/Outbox 代替进程内回调和共享历史；Typed hooks 代替 locals()；Memory/SOP 写入只产生可归属的草稿；任意宿主执行在缺少隔离后端时明确 unavailable。这些是隔离、审计和权限方面的增强，不把高风险动作审批或 AgentGrant 语义混同为 Workspace 共享授权。高风险工具审批/自动化尚未开放。

## 源码差距审计与后续迁移

WeKnora 的 `internal/agent` 包含实际执行循环、完成判断、压缩、steer、审批与恢复，应一并迁移，而不只参考资源组织。

当前 P2 本地验证不等于 GenericAgent 完整功能兼容。no_tool 判断、done hooks、回合收尾、完整工作记忆/长期 SOP、上下文变换 hooks、多模型协议/故障转移等尚未完整实现；六项代码/文件/浏览器工具按用户此前确认继续暂缓。未审查、未实现、暂缓和部署未验收分别登记，不再以“接口预留”或“已参考”代替功能迁移完成。

后续设计见 [智能体框架重构方案](pending/agent-framework-redesign.md)。
