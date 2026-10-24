# 开发规范

本文件是 hyoga-nexus 的仓库级工作入口。后端、Runtime、连接器和领域逻辑使用 Python 3.11+；Web 使用 Vue 3、TypeScript 和 Element Plus。

## 项目导航与职责

| 目录 | 职责 |
| --- | --- |
| `apps/api`、`apps/worker` | HTTP 与后台任务入口、依赖装配 |
| `apps/web` | Vue Web 工作台 |
| `packages/core` | 跨包共享契约，不依赖其他本地包或厂商 SDK |
| `packages/platform` | 身份、空间、智能体、会话、资源、授权与审计 |
| `packages/runtimes` | Native 执行器及外部 Runtime 适配器 |
| `packages/tools`、`skills`、`mcp`、`knowledge`、`sandbox`、`connectors` | 各自独立的通用能力包，具体边界见目录设计 |
| `packages/guanlan` | 观澜股票领域扩展，由应用入口组合；通用包不得导入 `guanlan` |
| `skills/` | 技能指令和资源内容；技能实现代码在 `packages/skills` |
| `tests/`、`evals/` | 软件测试与质量评估样例；金融回测在 `packages/guanlan/src/guanlan/backtesting/` |

开始功能开发前，阅读 [架构](docs/architecture.md)、[目录设计](docs/directory-layout.md) 和 [路线图](docs/roadmap.md) 的相关阶段。目录占位与计划不代表功能已实现。

## 规则入口

按任务范围主动阅读以下规则；不能假设工具会自动加载 `.codex/rules/`。

| 规则 | 适用范围 |
| --- | --- |
| [后端规范](.codex/rules/backend.md) | Python、平台、Runtime、适配器、持久化、迁移、API 与后端依赖 |
| [前端规范](.codex/rules/frontend.md) | `apps/web` 的 Vue、TypeScript、样式、API 接入与前端依赖 |

同时涉及 API 和界面时，两份都要阅读。规则按职责补充本文件，避免重复维护同一约束。前端设计、实现、评审或优化时，优先使用可用的 `ui-ux-pro-max` 技能。

## 需求与 OpenSpec

- 新功能、功能调整、跨包重构和接口行为变更，先创建 OpenSpec 提案，写明范围、需求、设计和实施任务；等待用户明确确认后再编码。
- 范围或方案不清楚时先探索；确认后按任务实施、验证，并按 OpenSpec 工作流同步规格和归档，不提前将未完成任务标记完成。
- 小需求、纯文档和非功能性维护可以直接实施；用户明确要求跳过 OpenSpec 时也可直接修改。不得把跨包行为变化拆成多个“小修改”绕过确认。

## 核心边界与参考实现

- 修改平台底座或 Native Runtime 行为前，阅读 [参考分析](docs/reference-analysis.md)，检查其中固定版本的 WeKnora 和 GenericAgent 源码与测试。
- WeKnora 用于平台组织和能力设计；GenericAgent 用于 Native 执行循环、工具分发、生命周期、记忆和 SOP。保留相关行为与扩展点，不得简化、删除或缩减核心能力；改动只能新增能力并保持向后兼容。
- 技术栈或安全要求导致实现方式调整时，记录行为映射、兼容边界和验证证据。复用源码前核对许可证，记录锁定版本和归属信息。
- `platform` 管理资源和授权，`runtimes` 负责执行；不得在 SDK 自带执行循环外再套 Native 循环。厂商 SDK 类型留在 Runtime 适配器中，平台专属消息类型留在连接器中。
- Skill 指令不能授予额外权限；实际调用工具或访问文档必须校验资源授权并记录访问。
- 知识文档、用户或智能体记忆、结构化股票数据分别管理。只在代码实际使用时添加依赖，不为计划能力安装依赖。

## 文档管理

- 根 `docs/` 维护全局架构、目录、契约、路线图、参考分析和 `docs/adr/` 中的架构决策；[项目 README](README.md) 作为入口。
- 包或应用需要独立说明时，在其 `docs/` 维护需求与设计，README 提供用途、使用方式和文档链接；按实际复杂度建立，不批量创建空文档。
- 功能或接口变化同步更新相关说明和 OpenSpec 规格。文档简洁记录当前结果、约束及明确标注的计划；过程记录保留在变更提案和 Git 历史中。

## 验证与交付

- Python 按需在仓库根目录执行 `uv sync --locked --extra dev` 和 `uv run pytest`，按改动范围选择相关测试。
- 前端在 `apps/web` 执行 `npm ci`、`npm run build`；开发入口为 `npm run dev`。不要求运行项目尚未提供的 lint 等脚本。
- 仅修改文档时检查本地链接、内容一致性、差异和 `git diff --check`，无需运行完整程序测试。
- 完成任务后检查整个工作区和待提交内容，将所有待提交的非敏感变更提交，并推送当前分支到 GitHub，不遗漏其他待提交变更。既有的其他任务改动须检查并与本次改动分开提交，交付时说明范围。
- 凭据、数据转储和第三方源码仓库始终不得提交；不要通过忽略校验或覆盖远端历史绕过失败。提交或推送失败时，说明具体阻碍并保留改动。
- 交付说明包含实际变更、验证结果和未完成项；区分环境阻碍与实现失败，不把脚手架、模拟实现或未验证能力描述为已完成。
