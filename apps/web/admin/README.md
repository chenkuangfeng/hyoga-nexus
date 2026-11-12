# @nexus-web/admin

企业管理后台 Vite 应用，base 为 `/admin/`，与工作台独立构建。当前提供登录、强制改密及入口状态骨架，管理业务页面尚未接入。

`src/router.ts` 刷新服务端成员身份，页面按当前企业的 `entries` 显示管理入口状态；缺失管理入口时显示无权限。共享登录与改密来自 `@nexus-web/core`，不导入工作台。后端接口仍负责每次请求的真实授权。未知路径使用公共 404 页面，不再显示为管理首页。邀请和无企业身份的开户流程跳转到员工应用，并保留原始查询参数。

在 `apps/web/` 运行 `pnpm dev:admin`（5174/admin/）、`pnpm --filter @nexus-web/admin build` 、`pnpm --filter @nexus-web/admin test` 或 `pnpm --filter @nexus-web/admin preview`。产物为 `admin/dist`。完整页面与菜单权限实现见企业化提案 E2.5。
