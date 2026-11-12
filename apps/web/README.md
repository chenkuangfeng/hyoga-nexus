# Nexus Web

Vue 3、TypeScript、TDesign、Pinia、vue-router、vue-i18n 与 Vite。页面基于 WeKnora 固定版本 `e1f9a6166`，按 Nexus 的身份、企业和 Run/Event API 接入。

本目录是 pnpm workspace，使用 Node.js 22.12+ 与 pnpm 10.34.9。

| 项目 | 职责 | 当前状态 |
| --- | --- | --- |
| [core](core/README.md) | 公共 API、认证、语言、主题、登录与改密 | 已抽取基础模块，编辑器等共用组件仍待迁移 |
| [workspace](workspace/README.md) | 员工工作台与 embed 入口 | 现有应用已移入，平台管理与桌面自动登录已移除，菜单与资源归属重构仍在实施 |
| [admin](admin/README.md) | 企业管理后台，部署路径 `/admin/` | 独立入口与认证骨架，业务页面尚未接入 |

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
- `pnpm check-i18n`：检查公共语言包；语言键扫描覆盖三个项目。

完整构建与工作台类型检查需要内存充足的机器。本地约 1.9GB RAM 环境曾发生退出码 137；降低 Node 堆限制后，工作台类型检查仍触及堆上限。SFC 编译与依赖边界检查不能代替完整构建、类型检查和浏览器验收。浏览器测试命令尚待 E2.8 接入，不能将现有静态 `.browser.test.mjs` 用例当作浏览器验收。

## 文档

- [需求](docs/requirements.md)
- [设计](docs/design.md)
- [实施任务](../../openspec/changes/2026-11-11-enterprise-saas/tasks.md)
