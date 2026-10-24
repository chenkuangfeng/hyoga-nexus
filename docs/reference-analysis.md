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

## 适合借鉴

紧凑而可替换的执行循环、统一工具结果、运行生命周期钩子、短期工作检查点、摘要/索引/详细资料分层、完成后沉淀 SOP 草稿、多入口复用任务执行。

## 需要重新设计

当前 code_run 主要通过宿主机 subprocess 执行，inline_eval 还可以在当前进程执行并改变 cwd；工作目录规范化不等于文件系统隔离。服务化需要独立沙箱、运行级权限与资源限制。

存在源码目录下 memory/temp、模块级配置与工具 Schema，以及前端/执行逻辑间的共享状态。不能直接把一个共享 GenericAgent 实例交给所有用户。需按平台 Session/Run 隔离，并将持久化、模型配置和事件协议移到平台边界。

原子工具的能力很广；Nexus 优先提供确定性领域工具，受控 shell 按授权启用。SOP/经验更新经过草稿、验证、版本发布，不直接改写生产技能。知识库多租户检索、文档版本和权限体系另行用 Python 建立。

## 组合建议

平台组织参考 WeKnora，Native 内核参考 GenericAgent，自有 Python 知识库形成公共资源；Codex/Claude Code/其他运行时并列接入同一资源体系。研究和复用机制优先，尚未引入参考项目源码或依赖；如后续复用实际代码，再按该文件和第三方组件的许可保留归属信息。

## 核查入口

- https://github.com/lsdefine/GenericAgent/blob/a9a36b4/agent_loop.py
- https://github.com/lsdefine/GenericAgent/blob/a9a36b4/ga.py
- https://github.com/Tencent/WeKnora/tree/e1f9a6166/internal/agent
- https://github.com/Tencent/WeKnora/tree/e1f9a6166/internal/im
