# Nexus Web

Vue 3、TypeScript、TDesign、Pinia、vue-router、vue-i18n 与 Vite。页面基于 WeKnora 固定版本 `e1f9a6166`，按 Nexus 的身份、企业和 Run/Event API 接入。

本目录是 pnpm workspace，使用 Node.js 22.12+ 与 pnpm 10.34.9。

| 项目 | 职责 | 当前状态 |
| --- | --- | --- |
| [core](core/README.md) | 公共 API、认证、语言、主题、登录与改密、共享编辑器与渠道组件 | 三项目共享能力；应用不得相互依赖 |
| [workspace](workspace/README.md) | 员工工作台与 embed 独立入口 | 对话、智能体、知识库、渠道、工具箱、账户设置等员工功能 |
| [admin](admin/README.md) | 企业管理后台，部署路径 `/admin/` | 独立权限外壳，提供企业、成员、角色、资源、模型、工具、知识库、渠道、用量、运行状态及审计治理页面 |

## 使用

在本目录运行：

```bash
corepack enable
corepack pnpm install --frozen-lockfile
corepack pnpm dev:workspace # 5173
corepack pnpm dev:admin     # 5174/admin/
```

`pnpm dev` 是工作台开发命令的别名。两个服务默认将 `/api` 代理到 `http://127.0.0.1:8000`，可用 `VITE_DEV_PROXY_TARGET` 覆盖。两个应用默认同域部署，共用认证存储；真实权限始终由后端校验。

## 构建与检查

- `pnpm build`：串行构建 `workspace/dist` 与 `admin/dist`。
- `pnpm type-check`：串行检查公共包和两个应用。
- `pnpm test`：工程依赖边界、公共包及两个应用的测试。
- `pnpm preview`：预览工作台；`pnpm --filter @nexus-web/admin preview`：预览管理后台。
- 生产静态部署的 Nginx 路由示例见 [nginx.example.conf](docs/nginx.example.conf)。
- `pnpm check-i18n`：检查公共语言包；语言键扫描覆盖三个项目。

完整构建与工作台类型检查需要内存充足的机器。本地约 1.9GB RAM 环境曾发生退出码 137；降低 Node 堆限制后，工作台类型检查仍触及堆上限。SFC 编译与依赖边界检查不能代替完整构建、类型检查和浏览器验收。已接入 `pnpm test:browser`：串行启动双应用并运行 Playwright。首次执行 `pnpm test:browser:install` 准备 Chromium，可通过 `test:browser:workspace` / `test:browser:admin` 单独回归；`pnpm type-check:browser` 检查测试代码。首批使用模拟 API，不能替代 E2.8 真实服务、生产包和全部业务验收；静态 `.browser.test.mjs` 仍不算浏览器测试。运行方式、覆盖范围和报告见 [浏览器回归说明](e2e/README.md)。

## 文档

- [需求](docs/requirements.md)
- [设计](docs/design.md)
- [实施任务](../../openspec/changes/2026-11-11-enterprise-saas/tasks.md)
- [部署与反向代理](docs/nginx.example.conf)

企业解析引擎治理由 Admin `/parsers` 提供，面向当前企业 owner/admin。工作台旧 parser 书签显示管理应用迁移说明；知识库内选择解析规则继续保留。目录状态表示配置是否齐全，服务连通测试仍待后端契约。
