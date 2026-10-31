# Hyoga Nexus · 织枢

Python 多类型智能体平台，已实现自研 Native，规划接入 Codex、Claude Code 和更多运行时。每个智能体可绑定多个技能、工具、MCP 工具及知识库；新建会话时选择已配置的智能体。**观澜 Guanlan** 是首个股票研究应用。

## 技术与状态

Python 3.11+ / FastAPI / 多包 uv workspace；Vue 3 / TypeScript / Element Plus / Vite，Node.js 22.12+。模块化单体部署，API 与后台 worker 分开启动。

当前已实现健康/就绪检查、规划能力目录，以及 P1 平台 API：Tenant 成员与最小角色、模型配置版本、Agent 草稿/发布、Session、Run 幂等提交和事件游标。平台数据使用 PostgreSQL 与 Alembic；worker 通过 PostgreSQL Outbox/租约领取任务。P2 已实现 Native 多轮流式执行、授权 Python 工具、取消/等待输入、SSE 续读与对话工作台，并完成 SQLite/模拟模型验证。用户设置已支持多个模型供应商、多个模型、加密 Key、个人/空间默认模型和连接测试。尚未接入真实身份提供方、凭据保险库、外部 Runtime、知识库、技能/MCP、隔离沙箱、文件产物或股票分析。

## 目录入口

- apps/：API、worker、Element Plus 前端。
- packages/：[core](packages/core/README.md)、[platform](packages/platform/README.md)、runtimes、skills、tools、mcp、knowledge、sandbox、connectors、guanlan。
- skills/：通用与股票领域技能内容，当前只有草稿。
- [configs/](configs/README.md)：部署数据库配置；migrations/、infra/：数据迁移和部署。
- tests/：软件测试；evals/：Agent、检索、技能与股票分析质量评估预留。

完整目录及边界见 [总体架构](docs/architecture.md) 第 4 节。

## 开发计划

[总体架构](docs/architecture.md) · [实施路线图](docs/roadmap.md)

顺序：平台底座 → 自研智能体 → Python 知识库与技能/MCP → Codex/Claude Code → 股票数据与研究技能 → 多渠道；企业微信可以在基础执行稳定后提前。

## 本地开发

推荐安装 uv 后执行：

```bash
uv sync --locked --extra dev
# 首次配置；已有文件时不要覆盖。
cp configs/nexus.example.toml configs/nexus.toml
# 编辑 configs/nexus.toml，填写实际的数据库连接串后执行：
export NEXUS_AUTH_MODE=development
export NEXUS_DEV_USER_ID=local-developer
uv run alembic -c alembic.ini upgrade head
uv run uvicorn nexus_api.main:app --reload --host 127.0.0.1
```

API、worker 和 Alembic 自动读取当前工作目录下的 `configs/nexus.toml`，无需加载 `.env`。请从仓库根目录启动；安装后部署在部署工作目录提供相同路径的文件。模板见 [configs/nexus.example.toml](configs/nexus.example.toml)，配置规则见 [configs 说明](configs/README.md)。真实配置文件已被 Git 忽略；不要提交数据库密码。PostgreSQL 连接串中用户名或密码的特殊字符需进行 URL 编码。

Windows PowerShell 首次配置：

```powershell
Copy-Item configs/nexus.example.toml configs/nexus.toml
notepad configs/nexus.toml
$env:NEXUS_AUTH_MODE = "development"
$env:NEXUS_DEV_USER_ID = "local-developer"
uv run alembic -c alembic.ini upgrade head
uv run uvicorn nexus_api.main:app --reload --host 127.0.0.1
```

配置优先级为显式传入的数据库连接串 > TOML 文件中的 `[database].url` > 已设置的 `NEXUS_DATABASE_URL`。文件缺失或没有数据库字段时才回退环境变量；格式错误、空值或错误类型会明确报错。认证与模型加密等其他部署配置仍使用原有环境变量，不从 `.env` 自动读取。开发认证使用固定的单一主体，不信任请求头中的用户 ID；只用于本机开发，服务应绑定 `127.0.0.1`，不能作为生产登录方案。生产环境接入外部身份提供方后设置 `NEXUS_AUTH_MODE=external` 并在 API 组合入口注册 provider。

或者使用 Python 3.11+ 环境：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
export NEXUS_AUTH_MODE=development
export NEXUS_DEV_USER_ID=local-developer
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

参考项目独立保留在 `/project`，不嵌入本仓库。

在另一个终端中，自动读取同一个 `configs/nexus.toml` 配置文件运行 worker：

```bash
uv run python -m nexus_worker
```

P2 worker 按已发布 Native Agent 配置执行。可通过用户设置配置供应商/模型与 Key（API/worker 需同一部署加密主密钥），也可继续使用凭据引用与允许解析的环境变量；未配置时仍明确失败，不声称已调用模型。配置步骤见 [worker 使用说明](apps/worker/README.md)，对话与浏览器验证见 [Web 使用说明](apps/web/README.md)。平台 API 文档位于 `http://127.0.0.1:8000/docs`，数据库连通检查为 `http://127.0.0.1:8000/api/v1/ready`。
