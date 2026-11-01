# 目录用途

页面路由（vue-router，history 模式）。

- `index.ts`：路由表与旧 hash 链接的改写（`redirectLegacyHash`）。
- `navigation.ts`：侧栏分组与页面，以及旧 hash 页面到新路径的映射。

平台管理路由带 `requiresAdmin`，由 `layouts/AppLayout.vue` 检查。
