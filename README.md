# Hyoga Nexus · 织枢

Python 多类型智能体平台，支持规划中的自研 Native、Codex、Claude Code 和未来运行时。每个智能体可绑定多个技能、工具、MCP 工具及知识库；新建会话时选择已配置的智能体。**观澜 Guanlan** 是首个股票研究应用。

## 技术与状态

Python 3.11+ / FastAPI / 多包 workspace；Vue 3 / TypeScript / Element Plus / Vite，Node.js 22.12+。模块化单体部署，API 与后台 worker 分开启动。

当前已实现健康检查、规划能力目录、读取目录的前端和基础协议。本轮已调整目录与开发计划；新增包仅是骨架，尚无真实 Agent 执行、知识库、权限管理、SDK、数据采集或股票分析。

## 目录入口

- apps/：API、worker、Element Plus 前端。
- packages/：core、platform、runtimes、skills、tools、mcp、knowledge、sandbox、connectors、guanlan。
- skills/：通用与股票领域技能内容，当前只有草稿。
- configs/、migrations/、infra/：配置、数据迁移和部署预留。
- tests/：软件测试；evals/：Agent、检索、技能与股票分析质量评估预留。

完整目录及边界见 [目录设计](docs/directory-layout.md)。

## 开发计划

[总体架构](docs/architecture.md) · [资源模型](docs/resource-model.md) · [Runtime 契约](docs/runtime-contract.md) · [实施计划](docs/roadmap.md) · [参考项目分析](docs/reference-analysis.md)

顺序：平台底座 → 自研智能体 → Python 知识库与技能/MCP → Codex/Claude Code → 股票数据与研究技能 → 多渠道；企业微信可以在基础执行稳定后提前。

## 本地开发

推荐安装 uv 后执行：

```bash
uv sync --locked --extra dev
uv run uvicorn nexus_api.main:app --reload
```

或者使用 Python 3.11+ 环境：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python scripts/install_dev.py
uvicorn nexus_api.main:app --reload
```

另一个终端，切换到 Node.js 22.12+ 后启动前端：

```bash
cd apps/web
npm ci
npm run dev
```

访问 Vite 输出地址。开发代理将 `/api` 转发到 `127.0.0.1:8000`；API 文档为 `http://127.0.0.1:8000/docs`。生产环境需配置同源 API 代理。

```bash
uv run --locked pytest
cd apps/web
npm run build
```

`uv run python -m nexus_worker` 仅打印 worker 骨架说明，尚无调度或消费逻辑。参考项目独立保留在 `/project`，不嵌入本仓库。
