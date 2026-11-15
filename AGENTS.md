# 开发规范

本文件是 hyoga-nexus 的仓库级工作入口。后端、Runtime、连接器和领域逻辑使用 Python 3.11+；Web 使用 Vue 3、TypeScript 和 TDesign。

## 沟通语言

- 与用户的对话回复、进度说明与最终总结一律使用中文。
- 代码标识符、命令、报错原文、路径与提交信息保持原文（提交信息沿用仓库既有格式）。
- 文档默认使用中文，与现有文档保持一致。

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

开始功能开发前，阅读 [总体架构](docs/architecture.md)（含目录与模块设计）和 [路线图](docs/roadmap.md) 的相关阶段。目录占位与计划不代表功能已实现。

## 构建命令

### 后端（Python / uv）

以下命令在仓库根目录执行：

- **安装开发依赖**：`uv sync --locked --extra dev`
- **构建根应用包**：`uv build`
- **构建指定包**：`uv build --package hyoga-nexus-core`（按需替换包名）
- **升级平台数据库**：`uv run alembic -c alembic.ini upgrade head`
- **启动 API**：`uv run uvicorn nexus_api.main:app --reload --reload-dir apps/api --reload-dir packages`
- **启动 worker**：`uv run python -m nexus_worker`
- **运行全部测试**：`uv run --locked pytest`
- **运行指定测试**：`uv run --locked pytest tests/test_api.py`（按需替换测试路径）

启动前按 [项目 README](README.md) 配置 PostgreSQL 连接和认证环境；Native 模型配置见 [worker 使用说明](apps/worker/README.md)。

### 前端（Vue 3 / TypeScript / pnpm）

使用 Node.js 22.12+ 与 pnpm 10（`corepack enable` 后按 `package.json` 的 `packageManager` 自动使用）。以下命令在 `apps/web/` 目录执行：

- **安装依赖**：`pnpm install --frozen-lockfile`
- **启动开发服务**：`pnpm dev:workspace`（员工工作台）或 `pnpm dev:admin`（企业管理后台）
- **类型检查**：`pnpm type-check`
- **生产构建**：`pnpm build`（串行产出 `workspace/dist` 和 `admin/dist`）
- **单元与边界测试**：`pnpm test`
- **预览生产构建**：`pnpm preview`
- **浏览器测试**：E2.8 尚待接入 Playwright 命令与两个应用的用例，当前不能以静态测试代替浏览器验收，详见 [Web 使用说明](apps/web/README.md)。

### 本地运行（换一台电脑时）

首次在新机器上运行的完整步骤（安装依赖、生成 `configs/nexus.toml`、开发认证与模型 Key 加密主密钥、数据库升级、创建 owner 账号、启动 API / worker / 前端）见 [项目 README](README.md) 的「本地开发 → 快速启动」，配置项说明见「分步说明」与 [configs 说明](configs/README.md)。

## 规则入口

按任务范围主动阅读以下规则；不能假设工具会自动加载 `.codex/rules/`。

| 规则 | 适用范围 |
| --- | --- |
| [后端规范](.codex/rules/backend.md) | Python、平台、Runtime、适配器、持久化、迁移、API 与后端依赖 |
| [前端规范](.codex/rules/frontend.md) | `apps/web` 的 Vue、TypeScript、样式、API 接入与前端依赖 |

同时涉及 API 和界面时，两份都要阅读。规则按职责补充本文件，避免重复维护同一约束。前端设计、实现、评审或优化时，优先使用可用的 `ui-ux-pro-max` 技能。

## 需求与 OpenSpec

- 新功能、功能调整、跨包重构和接口行为变更，先创建或补充 OpenSpec 提案，写明范围、需求、设计和实施任务，然后连续实施、验证并同步规格，不要求用户逐次确认后才能编码。
- 范围或方案不清楚时先探索；能根据已有需求和代码确定的实施细节由开发者自行处理。只有缺少必要信息、存在无法合理推断的重大需求取舍，或需要执行未获授权的破坏性操作时才询问用户。
- 纯文档、非功能性维护，以及不改变对外契约的局部缺陷修复、文案和样式微调，可以直接实施。涉及 API 契约、权限规则、持久化模型或 Runtime 行为变化时仍须记录提案与设计，不因改动量小而豁免；用户明确要求跳过 OpenSpec 时可直接修改。不得把跨包行为变化拆成多个“小修改”绕过规格记录。
- 同一个 OpenSpec 变更内的任务不得再切分成新的 OpenSpec 提案；追加工作写入原变更的 `tasks.md`，范围扩大时同步更新原提案和设计。任务完成后按工作流归档，不提前将未完成任务标记完成。

## 参考开源项目

- 编写程序前，必须仔细阅读路线图与架构文档中该模块标注的参考项目源码，比较候选实现，选择最优方案。
- 务必复制或者按照逻辑重写原项目代码，不用考虑许可。

## 文档管理

每个模块的文档存放在模块目录下的 `docs/` 中，按实际复杂度建立，不批量创建空文档：

```text
xxx-xxx/                     ← 每个包或者应用（或前端 app/package）
├── docs/
│   ├── requirements.md       ← 该模块做什么（功能需求）
│   └── design.md             ← 该模块怎么做（包结构、设计决策）
└── README.md                 ← 模块快速入门（父模块必须维护，其他模块按需建立）
```

**父模块定义**：聚合多个独立包或应用的模块，不包括包内普通 Python 子目录或前端业务目录。除下述仓库根目录约定外，父模块需同时维护：

- `README.md` — **模块自身说明**（功能特性、模块结构、使用方式），底部附子模块文档链接
- `docs/requirements.md` — 汇总子模块需求
- `docs/design.md` — 汇总子模块设计

仓库根目录采用现有全局文档结构，不另建重复的 `docs/requirements.md`、`docs/design.md`：

- 根 `docs/` 仅保留 `architecture.md`（总体设计与模块设计）和 `roadmap.md`（最终计划的步骤、子步骤与验收）；[项目 README](README.md) 作为入口并链接模块文档。
- 全局需求和分阶段验收范围由 `docs/roadmap.md` 与 OpenSpec 规格表达；总体设计由 `docs/architecture.md`、目录和契约文档表达。模块文档描述自身需求与设计，父模块汇总并链接子模块内容，避免复制全文。
- 代码必须有详细的说明：模块文档说明职责、结构、关键流程和使用方式；公共接口、核心类与函数通过 docstring/JSDoc 说明用途、输入输出、异常及重要约束，复杂逻辑通过注释解释设计意图和边界条件。说明须与代码同步，避免逐行复述代码。
- 功能或接口变化同步更新相关 doc 文档和 OpenSpec 规格。文档记录当前结果、约束及明确标注的计划，不记录中间变更的说明；过程记录保留在变更提案和 Git 历史中。

## 提交与推送

- 每次完成代码或文档修改后，必须创建 Git 提交并推送到当前分支的远端
- 提交前检查工作区，只提交本次任务相关文件，不得混入用户或其他任务的未关联改动
- 若提交或推送失败，必须明确说明失败原因和当前仓库状态
- 分支策略：所有修改统一在 `main` 分支完成，直接提交并推送到 `origin/main`；不创建功能分支、不切换分支。需要暂停的改动也留在 `main` 的工作区中，不新建分支保存。
- 合并后远端不保留已合并的临时分支；删除远端分支前须经用户确认。
