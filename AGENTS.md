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

开始功能开发前，阅读 [总体架构](docs/architecture.md)（含目录与模块设计）和 [路线图](docs/roadmap.md) 的相关阶段。目录占位与计划不代表功能已实现。

## 构建命令

### 后端（Python / uv）

以下命令在仓库根目录执行：

- **安装开发依赖**：`uv sync --locked --extra dev`
- **构建根应用包**：`uv build`
- **构建指定包**：`uv build --package hyoga-nexus-core`（按需替换包名）
- **升级平台数据库**：`uv run alembic -c alembic.ini upgrade head`
- **启动 API**：`uv run uvicorn nexus_api.main:app --reload`
- **启动 worker**：`uv run python -m nexus_worker`
- **运行全部测试**：`uv run --locked pytest`
- **运行指定测试**：`uv run --locked pytest tests/test_api.py`（按需替换测试路径）

启动前按 [项目 README](README.md) 配置 PostgreSQL 连接和认证环境；Native 模型配置见 [worker 使用说明](apps/worker/README.md)。

### 前端（Vue 3 / TypeScript / npm）

使用 Node.js 22.12+，以下命令在 `apps/web/` 目录执行：

- **安装依赖**：`npm ci`
- **启动开发服务**：`npm run dev`
- **类型检查与生产构建**：`npm run build`
- **预览生产构建**：`npm run preview`
- **浏览器测试**：`npm run test:browser`（需先安装 Playwright Chromium 并启动 Vite，详见 [Web 使用说明](apps/web/README.md)）

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
- 纯文档、非功能性维护，以及不改变对外契约的局部缺陷修复、文案和样式微调，可以直接实施。涉及 API 契约、权限规则、持久化模型或 Runtime 行为变化时仍须先提案并确认，不因改动量小而豁免；用户明确要求跳过 OpenSpec 时可直接修改。不得把跨包行为变化拆成多个“小修改”绕过确认。

## 参考源码迁移与模块归属

- **以 GenericAgent 和 WeKnora 的实际源码为实现基础**：对应功能优先采用源码移植、跨语言翻译和必要适配的方式落地，而不是仅理解思路后自行重新实现。迁移时保留原实现的关键流程、行为语义、边界条件和异常处理，不擅自简化或替换。
- **按本项目职责归类代码**：迁移前先建立“参考源码 → 本项目模块”的对应关系，将代码归入平台、Runtime、工具、技能、知识库、连接器等相应模块。遵守本项目的包边界与依赖方向，不直接照搬参考项目的目录结构，也不把整套功能集中堆入单个文件。
- **只做必要的适配与重构**：允许为本项目的语言、接口、配置、持久化和依赖装配方式进行调整；拆分和重组代码时应保持原有功能语义。涉及功能删减、行为改变或核心算法替换，必须明确说明并获得用户确认；已在获批提案中明确的差异按提案执行，无须重复确认。
- **明确两个项目的取舍**：同一功能在两个参考项目中存在不同实现时，先确定以哪一个为主、另一个补充哪些能力，说明选择依据，避免未经分析直接拼接。
- **按职责拆分，避免机械碎片化**：接口、业务逻辑、数据访问、外部适配和工具实现应有清晰边界；相关代码集中维护，通过明确接口协作，不为满足“一类一文件”制造没有独立职责的模块。
- **保留迁移依据与验证**：在提案或设计文档中记录来源仓库、版本或 commit、源码位置、目标模块及适配差异；结合原项目测试和本项目测试验证行为一致性，遵守原项目许可证并保留必要声明。源码迁移涉及的功能和契约变更仍遵循上述 OpenSpec 提案与确认流程。

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

- 根 `docs/` 仅保留 `architecture.md`（架构、模块设计、参考分析与关键决策）和 `roadmap.md`（阶段计划与验收）；[项目 README](README.md) 作为入口并链接模块文档。
- 全局需求和分阶段验收范围由 `docs/roadmap.md` 与 OpenSpec 规格表达；总体设计由 `docs/architecture.md`、目录和契约文档表达。模块文档描述自身需求与设计，父模块汇总并链接子模块内容，避免复制全文。
- 代码必须有详细的说明：模块文档说明职责、结构、关键流程和使用方式；公共接口、核心类与函数通过 docstring/JSDoc 说明用途、输入输出、异常及重要约束，复杂逻辑通过注释解释设计意图和边界条件。说明须与代码同步，避免逐行复述代码。
- 功能或接口变化同步更新相关 doc 文档和 OpenSpec 规格。文档记录当前结果、约束及明确标注的计划，不记录中间变更的说明；过程记录保留在变更提案和 Git 历史中。

## 验证与交付

- Python 按需在仓库根目录执行 `uv sync --locked --extra dev` 和 `uv run --locked pytest`，按改动范围选择相关测试。
- 前端在 `apps/web` 执行 `npm ci`、`npm run build`；开发入口为 `npm run dev`。聊天交互变化时还须执行 `npm run test:browser`，必要时更新对应行为用例；前置条件见构建命令。不要求运行项目尚未提供的 lint 等脚本。
- 仅修改文档时检查本地链接、内容一致性、差异和 `git diff --check`，无需运行完整程序测试。
- 完成任务后检查整个工作区和待提交内容，将所有待提交的非敏感变更提交，并推送当前分支到 GitHub，不遗漏其他待提交变更。既有的其他任务改动须检查并与本次改动分开提交，交付时说明范围。
- 凭据、数据转储和第三方源码仓库始终不得提交；不要通过忽略校验或覆盖远端历史绕过失败。提交或推送失败时，说明具体阻碍并保留改动。
- 测试出现跳过时，说明跳过范围、原因和未验证能力；部分测试通过不代表数据库、真实模型供应商等集成能力已经验证。
- 交付说明包含实际变更、验证结果和未完成项；区分环境阻碍与实现失败，不把脚手架、模拟实现或未验证能力描述为已完成。
