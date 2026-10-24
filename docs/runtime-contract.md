# Runtime 适配契约

状态：目标契约草案。当前 contracts.py 仅有最小 stream 协议，本文件不表示接口已实现。

## 职责

Runtime 执行智能体任务；平台负责资源授权、身份、记录、调度和消息投递。Native 自己实现循环，Codex/Claude Code 等适配器驱动原有执行器，不再用 Native 循环嵌套外部循环。

目标操作：describe_capabilities、start、stream、cancel、resume、respond_to_approval；steer 为可选能力。恢复进程执行、恢复对话以及重放历史事件是三个不同概念，分别声明。

## 能力描述

按安装版本和当前配置验证 text_stream、tool_bridge、mcp、skills、attachments、artifacts、approvals、cancel、conversation_resume、execution_resume、steer。状态区分 supported、unsupported、unverified；支持的平台功能不代表所有 Runtime 都支持。

若某种资源仅能转成上下文摘要，必须明确与原生技能加载不同。没有授权桥接或不能限制原生工具的运行时，不允许绑定它无法执行授权策略的配置。

## 统一输入输出

输入包括 run_id、session_id、agent_version、user_message、附件引用、模型配置引用、授权资源清单、预算、工作区和凭据句柄。每个适配器只得到本次所需授权。

事件包括 run.started、message.delta、progress、tool.started、tool.completed、approval.requested、artifact.created、usage.updated、run.completed、run.failed、run.cancelled。Run 状态为 queued/running/waiting_input/waiting_approval/completed/failed/cancelled/interrupted；只有明确 completed 才算成功，不把进程退出或网络断开直接视为完成。

事件持久化先于对外投递，每个运行使用有序 sequence。工具调用记录关联 invocation_id。重试按操作设置幂等键；执行结果未知的有副作用操作先核实，不自动重放。

## 工具、Skill 与知识库桥接

平台工具通过直接回调或受控 MCP 服务提供给运行时。MCP 桥必须携带短时、按运行授权的身份上下文；MCP 服务仍负责每次调用的权限校验，不能信任模型传入的 workspace/user 标识。

平台维护技能版本、正文与资源。适配器可以加载受支持的技能目录，或明确转换成指令和授权工具；缺失依赖阻止配置发布。知识库统一通过 search/read/list 等工具接入，不依赖厂商各自的文件存储形成多份事实源。

## 原生工具与沙箱

平台网关只控制经过它的调用，不能自动约束 SDK 自带的 shell/文件/网络工具。因此适配器还需配置运行时权限和隔离工作区、凭据及网络范围，记录可观察的原生工具事件。不支持约束时声明限制，不假装已受控。

## Codex 路径核对

2026-10-24 核对官方文档：Codex 有 Python SDK，控制本地 app-server；自定义客户端也可通过 app-server 协议接入。先验证 Python SDK 是否覆盖本项目需要的事件、工具、审批与恢复，再决定是否补充直接协议适配；不把“Python 后端”误写成“必须嵌入 TypeScript SDK”。

来源：[Codex SDK](https://learn.chatgpt.com/docs/codex-sdk)、[App Server](https://learn.chatgpt.com/docs/app-server)。正式接入时锁定版本并重新核对，账号和模型权限单独验证。

Claude Code、DeepSeek Harness 在各自阶段核对官方文档和真实项目；本阶段只保留边界，不宣称与 Codex 功能对等。
