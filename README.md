# Hyoga Nexus · 织枢

Python 多类型智能体平台，已实现自研 Native，规划接入 Codex、Claude Code 和更多运行时。每个智能体可绑定多个技能、工具、MCP 工具及知识库；新建会话时选择已配置的智能体。**观澜 Guanlan** 是首个股票研究应用。

## 技术与状态

Python 3.11+ / FastAPI / 多包 uv workspace；Vue 3 / TypeScript / Element Plus / Vite，Node.js 22.12+。模块化单体部署，API 与后台 worker 分开启动。

当前已实现健康/就绪检查、规划能力目录，以及平台 API（路线图第 2 步）：Tenant 成员与最小角色、模型配置版本、Agent 草稿/发布、Session、Run 幂等提交和事件游标。平台数据使用 PostgreSQL 与 Alembic；worker 通过 PostgreSQL Outbox/租约领取任务。Native 基础闭环（路线图第 3 步）已实现多轮流式执行、授权 Python 工具、取消/等待输入、SSE 续读与对话工作台，并完成 SQLite/模拟模型验证。用户设置已支持多个模型供应商、多个模型、加密 Key、个人/空间默认模型和连接测试。尚未接入真实身份提供方、凭据保险库、外部 Runtime、知识库、技能/MCP、隔离沙箱、文件产物或股票分析。

## 目录入口

- apps/：API、worker、Element Plus 前端。
- packages/：[core](packages/core/README.md)、[platform](packages/platform/README.md)、runtimes、skills、tools、mcp、knowledge、sandbox、connectors、guanlan。
- skills/：通用与股票领域技能内容，当前只有草稿。
- [configs/](configs/README.md)：部署数据库配置；migrations/、infra/：数据迁移和部署。
- tests/：软件测试；evals/：Agent、检索、技能与股票分析质量评估预留。

完整目录及边界见 [总体架构](docs/architecture.md) 第 1.4 节。

## 开发计划

[总体架构](docs/architecture.md) · [实施路线图](docs/roadmap.md)

顺序：平台底座 → 自研智能体 → Python 知识库与技能/MCP → Codex/Claude Code → 股票数据与研究技能 → 多渠道；企业微信可以在基础执行稳定后提前。

## 本地开发

### 快速启动（前后端）

首次在一台机器上运行，按顺序执行（均在仓库根目录，除非注明）：

1. 安装后端依赖：`uv sync --locked --extra dev`
2. 生成本地配置（已有 `configs/nexus.toml` 时不要覆盖）：`cp configs/nexus.example.toml configs/nexus.toml`（Windows PowerShell：`Copy-Item configs/nexus.example.toml configs/nexus.toml`），再编辑 `[database].url` 为实际连接串。真实配置已被 Git 忽略，不要提交。
3. 在同一个 `configs/nexus.toml` 中确认开发认证与模型 Key 加密主密钥（无需每个终端单独设置）：
   - `[auth]` 中设置 `mode = "development"`（仅用于本机，API 绑定 `127.0.0.1`）。
   - `[security].credential_encryption_key`：保存模型 Key 时需要，API 与 worker 必须使用同一个值（Fernet 格式）。从示例复制的配置已带开发用值；共享或生产环境须自行生成，见下文「分步说明」。
4. 升级数据库：`uv run alembic -c alembic.ini upgrade head`（每次拉取到新迁移后都要执行）。
5. 创建首个 owner 账号（只需一次）：`uv run python -m nexus_api.cli create-owner --tenant "公司名" --username alice --email alice@example.com --display-name "Alice"`，密码以隐藏输入方式输入。
6. 安装前端依赖：`corepack enable`（一次性），然后 `cd apps/web`、`pnpm install --frozen-lockfile`。

之后日常启动需要三个终端：

```bash
# 终端 1：API（仓库根目录）
uv run uvicorn nexus_api.main:app --reload --host 127.0.0.1

# 终端 2：worker（仓库根目录，需与 API 使用同一份 configs/nexus.toml）
uv run python -m nexus_worker

# 终端 3：前端
cd apps/web
pnpm dev
```

启动后访问 Vite 输出的地址（通常为 `http://localhost:5173`）。API 文档为 `http://127.0.0.1:8000/docs`，数据库连通检查为 `http://127.0.0.1:8000/api/v1/ready`。

本地 HTTP 调试登录时需在 `[auth]` 中设置 `cookie_secure = false`。更多细节见 [API 说明](apps/api/README.md)、[worker 说明](apps/worker/README.md)、[Web 说明](apps/web/README.md)。

### 分步说明

推荐安装 uv 后执行：

```bash
uv sync --locked --extra dev
# 首次配置；已有文件时不要覆盖。
cp configs/nexus.example.toml configs/nexus.toml
# 编辑 configs/nexus.toml，填写实际的数据库连接串，并在 `[auth]` 中取消注释 `mode = "development"`（仅本机）后执行：
uv run alembic -c alembic.ini upgrade head
uv run uvicorn nexus_api.main:app --reload --host 127.0.0.1
```

API、worker 和 Alembic 自动读取当前工作目录下的 `configs/nexus.toml`，它是全部部署配置的唯一来源（数据库、认证、日志、加密主密钥、模型凭据与网络白名单等）；不读取环境变量和 `.env`。请从仓库根目录启动；安装后部署在部署工作目录提供相同路径的文件。模板见 [configs/nexus.example.toml](configs/nexus.example.toml)，配置规则见 [configs 说明](configs/README.md)。真实配置文件已被 Git 忽略；不要提交数据库密码。PostgreSQL 连接串中用户名或密码的特殊字符需进行 URL 编码。

Windows PowerShell 首次配置：

```powershell
Copy-Item configs/nexus.example.toml configs/nexus.toml
notepad configs/nexus.toml
# 在 configs/nexus.toml 的 [auth] 中设置 mode = "development"
uv run alembic -c alembic.ini upgrade head
uv run uvicorn nexus_api.main:app --reload --host 127.0.0.1
```

显式传入的数据库连接串优先；否则读取 `[database].url`，缺失或格式错误会明确报错，不回退其他来源。认证模式按 `[auth].mode` 配置（`development`、`session` 或 `external`），开发认证的主体为 `[auth].dev_user_id`（缺省 `local-developer`），不信任请求头中的用户 ID；只用于本机开发，服务应绑定 `127.0.0.1`，不能作为生产登录方案。生产环境接入外部身份提供方后设置 `mode = "external"` 并在 API 组合入口注册 provider。

模型 Key 加密主密钥 `[security].credential_encryption_key`：在设置页保存模型 Key 前必须配置（从示例复制的配置已带开发用值，可直接在本机使用），Key 以该 Fernet 密钥加密后入库。未配置或格式错误时，保存会返回 `Credential encryption key is not configured correctly`（503）。生成并写入：

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

```toml
[security]
credential_encryption_key = "<上一步输出的 44 位字符串>"
```

- API 与 worker 必须使用同一个值（读取同一份 `configs/nexus.toml` 即可；worker 在其他机器时复制该行）。修改后重启 API 与 worker。
- 已保存过模型 Key 后不要更换或删除该密钥，否则已存的 Key 无法解密，只能重新录入。
- 示例配置自带一个仅供本机开发的密钥：它随仓库公开，任何人都能解密用它加密的 Key。共享环境或生产部署必须用上面的命令生成自己的密钥，且不要提交；`configs/nexus.toml` 已被 Git 忽略。

或者使用 Python 3.11+ 环境：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
# 在 configs/nexus.toml 的 [auth] 中设置 mode = "development"
python -m pip install --upgrade pip
python scripts/install_dev.py
uvicorn nexus_api.main:app --reload
```

另一个终端，切换到 Node.js 22.12+ 后启动前端：

```bash
corepack enable   # 一次性启用 pnpm，版本由 apps/web/package.json 的 packageManager 指定
cd apps/web
pnpm install --frozen-lockfile
pnpm dev
```

访问 Vite 输出地址。开发代理将 `/api` 转发到 `127.0.0.1:8000`；API 文档为 `http://127.0.0.1:8000/docs`。生产环境需配置同源 API 代理。

```bash
uv run --locked pytest
cd apps/web
pnpm build
```

参考项目独立保留在 `/project`，不嵌入本仓库。

在另一个终端中，自动读取同一个 `configs/nexus.toml` 配置文件运行 worker：

```bash
uv run python -m nexus_worker
```

Native worker 按已发布 Native Agent 配置执行。可通过用户设置配置供应商/模型与 Key（API/worker 需同一部署加密主密钥），也可继续使用凭据引用与允许解析的环境变量；未配置时仍明确失败，不声称已调用模型。配置步骤见 [worker 使用说明](apps/worker/README.md)，对话与浏览器验证见 [Web 使用说明](apps/web/README.md)。平台 API 文档位于 `http://127.0.0.1:8000/docs`，数据库连通检查为 `http://127.0.0.1:8000/api/v1/ready`。
