# 智能体与资源配置模型

状态：P1 平台核心模型已实现 PostgreSQL 迁移与 API。技能、工具、MCP、知识库等业务资源由未来资源包登记到平台资源目录；当前没有实现这些资源自身的 CRUD 或内容存储。

## 核心对象

| 对象 | 主要内容 |
|---|---|
| Workspace / Membership | 用户与角色、资源所属空间 |
| RuntimeType / RuntimeCapability | native、codex、claude_code 等类型与经验证的能力 |
| ModelProfile / CredentialRef | 模型、连接配置、凭据引用；与运行时类型分离 |
| Agent / AgentVersion | 名称、类型、说明、系统指令、模型引用、预算、发布版本 |
| AgentResourceBinding | 技能版本、工具、MCP 工具、知识库的多对多绑定 |
| Skill / SkillVersion | SKILL.md、资源、依赖、草稿/发布状态、内容哈希 |
| ToolDefinition / ToolVersion | 参数/结果 Schema、实现定位、风险与权限要求 |
| MCPConnection / MCPToolBinding | 服务连接、凭据引用、发现工具、按工具启用 |
| KnowledgeBase / Document / DocumentVersion / Chunk | 资料范围、文档处理状态、来源与引用定位 |
| Session / Message | 会话所属用户、智能体版本、渠道、消息与附件 |
| Run / RunEvent / ToolInvocation | 单次执行、配置快照、事件、用量、工具输入输出摘要 |
| RuntimeSessionBinding | 平台会话与厂商原生 thread/session ID 的映射 |
| Approval / Artifact / Citation | 审批、文件产物与证据引用 |
| Channel / ChannelIdentity / ChannelSessionBinding | 渠道凭据引用、平台身份映射与会话路由 |
| DataSource / IngestionJob / DatasetVersion | 观澜数据源、采集任务与数据版本，属于领域模块 |

## 智能体配置示意

以下为逻辑示例，不是当前可加载配置；使用演示标识，不含真实凭据。

```yaml
name: 观澜研究助手
runtime_type: native
model_profile_id: research-model
instructions: 基于可核查来源形成研究报告
skills:
  - skill_id: stock-analysis
    version: 0.1.0
tools:
  - stock.basic_info
  - stock.daily_bars
mcp_tools:
  - connection_id: research-search
    allowed_tools: [search]
knowledge_bases:
  - announcements
  - research-notes
budgets:
  max_rounds: 20
  timeout_seconds: 300
```

一个 Agent 可以绑定多个同类资源；修改资源创建新版本，不静默改变历史运行快照。技能声明的工具需求必须由智能体绑定满足，否则发布/启动时提示缺失，不能自动扩大权限。

## 交互流程

1. 管理资源：配置模型、知识库、工具、技能和 MCP。
2. 新建智能体：选择类型与模型，填写指令，绑定多个资源。
3. 校验配置：检查资源权限、技能依赖和 Runtime 能力，保存草稿或发布版本。
4. 新建会话：选择已发布智能体。可按类型筛选，或从系统预置 Native/Codex/Claude Code 智能体快速创建。
5. 发起运行：组装授权快照，入队，创建/恢复相应 Runtime 会话。
6. 展示文本、公开进度、工具、引用、审批和文件；不要求公开模型内部推理。
7. 继续追问沿用当前运行时；换类型通过新会话或分支操作。

## 前端信息结构

智能体管理、会话工作台、技能/工具/MCP 资源、知识库、渠道、设置、观澜业务工作台。前端类型标签展示能力来源，资源绑定同时显示兼容状态与版本。

## API 资源草案

`/api/v1/agents`、`/sessions`、`/runs`、`/skills`、`/tools`、`/mcp-connections`、`/knowledge-bases`、`/channels`、`/model-profiles`、`/artifacts` 为后续资源入口。Run 提供事件流、取消与审批操作。观澜 API 使用 `/api/v1/guanlan/...`。路由在实现时定稿，当前只存在 health 和 capabilities。
