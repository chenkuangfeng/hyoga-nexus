# Nexus Web

Vue 3、TypeScript、TDesign、Pinia、vue-router、vue-i18n 与 Vite。页面基于 WeKnora 固定版本 `e1f9a6166`，按 Nexus 的身份、企业和 Run/Event API 接入。

本目录是 pnpm workspace，使用 Node.js 22.12+ 与 pnpm 10.34.9。

| 项目 | 职责 | 当前状态 |
| --- | --- | --- |
| [core](core/README.md) | 公共 API、认证、语言、主题、登录与改密、共享编辑器与渠道组件 | 三项目共享能力；应用不得相互依赖 |
| [workspace](workspace/README.md) | 员工工作台与 embed 独立入口 | 对话、智能体、知识库、渠道、工具箱、账户设置等员工功能 |
| [enterprise](enterprise/README.md) | 企业管理应用，部署路径 `/enterprise/` | 独立权限外壳，提供企业、成员、角色、资源、模型、工具、知识库、渠道、用量、运行状态及审计治理页面 |

## 使用

在本目录运行：

```bash
corepack enable
corepack pnpm install --frozen-lockfile
corepack pnpm dev:workspace # 5173
corepack pnpm dev:enterprise     # 5174/enterprise/
```

要在开发环境从工作台免密进入企业管理，请同时启动两个应用。工作台在当前地址的 `/enterprise/` 代理企业管理应用，保留当前浏览器会话和所选企业。生产部署将两个构建产物放在同一站点，配置见 [Nginx 示例](docs/nginx.example.conf)。

`pnpm dev` 是工作台开发命令的别名。两个服务默认将 `/api` 代理到 `http://127.0.0.1:8000`，可用 `VITE_DEV_PROXY_TARGET` 覆盖。两个应用默认同域部署，共用认证存储；真实权限始终由后端校验。

### 从旧版 `admin` 目录升级

更新到使用 `enterprise` 目录的版本后，停止旧前端进程，在 `apps/web` 重新执行 `corepack pnpm install --frozen-lockfile`。pnpm 会为新目录生成依赖链接，旧目录的安装状态不能直接用于新包。

如果企业管理仍提示 `Failed to resolve import "vue"`，从 `apps/web` 运行 `corepack pnpm --filter @nexus-web/enterprise exec node -p "require.resolve('vue')"`。如果解析失败，执行 `corepack pnpm install --frozen-lockfile --force` 重建链接，再用 `corepack pnpm dev:enterprise` 启动。

## 构建与检查

- `pnpm build`：串行构建 `workspace/dist` 与 `enterprise/dist`。
- `pnpm type-check`：串行检查公共包和两个应用。
- `pnpm test`：工程依赖边界、公共包及两个应用的测试。
- `pnpm preview`：预览工作台；`pnpm --filter @nexus-web/enterprise preview`：预览管理后台。
- 生产静态部署的 Nginx 路由示例见 [nginx.example.conf](docs/nginx.example.conf)。
- `pnpm check-i18n`：检查公共语言包；语言键扫描覆盖三个项目。

构建和类型检查通过串行工具控制内存峰值：构建使用同源预打包依赖，类型检查保留全部源码/模板并按原生引用工程运行。Node 默认堆为 768MB，环境 `NODE_OPTIONS` 可覆盖；小内存机器上请依次运行类型检查、完整构建和全量测试，不并行启动这些任务。实现和限制见 [设计](docs/design.md)。浏览器测试使用 `pnpm test:browser`；生产构建后使用 `pnpm test:browser:preview`。首次执行 `pnpm test:browser:install` 准备 Chromium，`pnpm type-check:browser` 检查测试代码。模拟 API 回归不替代真实服务与全部业务验收；静态 `.browser.test.mjs` 不算浏览器测试。详见 [浏览器回归说明](e2e/README.md)。

## 文档

- [需求](docs/requirements.md)
- [设计](docs/design.md)
- [实施任务](../../openspec/changes/2026-11-11-enterprise-saas/tasks.md)
- [部署与反向代理](docs/nginx.example.conf)

企业解析引擎治理由企业管理应用 `/parsers` 提供，面向当前企业 owner/admin。工作台旧 parser 书签显示管理应用迁移说明；知识库内选择解析规则继续保留。目录状态表示配置是否齐全，服务连通测试仍待后端契约。
