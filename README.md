# Hyoga Nexus · 织枢

基于 Python 的可扩展智能体平台。**观澜 Guanlan** 是首个股票研究应用，通用平台可服务其他业务。

## 技术栈

后端及业务包：Python 3.11+ / FastAPI；前端：Vue 3 / TypeScript / Element Plus / Vite。推荐 Node.js 22.12+。

## 目录

```text
apps/
  api/                 # HTTP API
  worker/              # 后台任务入口
  web/                 # Element Plus 工作台
packages/
  core/                # 通用协议与平台核心
  runtimes/            # 模型/SDK 适配
  connectors/          # 消息渠道适配
  skills/              # 通用技能机制
  guanlan/             # 股票数据、分析与回测
skills/guanlan/        # 股票领域技能规格草稿
tests/                # 软件回归测试
docs/                 # 架构与迭代路线
infra/                # 部署配置预留
```

## 本地开发

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e packages/core -e packages/runtimes -e packages/connectors -e packages/skills -e packages/guanlan -e '.[dev]'
uvicorn nexus_api.main:app --reload
```

也可以安装 uv 后使用 `uv sync --extra dev`，再执行 `uv run uvicorn nexus_api.main:app --reload`。

另一个终端启动前端：

```bash
cd apps/web
npm ci
npm run dev
```

访问 Vite 输出的地址；开发代理将 `/api` 转发到 `127.0.0.1:8000`。API 文档：`http://127.0.0.1:8000/docs`。生产环境需配置同源 API 反向代理。

```bash
pytest
cd apps/web && npm run build
```

## 当前范围

已实现健康检查、能力目录 API、读取 API 的前端骨架及通用协议。SDK、消息渠道、数据采集和技能执行均未实现，页面明确显示待接入状态。

详见 [架构](docs/architecture.md) 和 [路线](docs/roadmap.md)。原先拉取的参考项目独立保留在 `/project`，不复制进本仓库。
