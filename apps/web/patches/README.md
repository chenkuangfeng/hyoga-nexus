# 前端依赖补丁

`tdesign-vue-next@1.20.10.patch` 只修改两处声明引用：配置类型直接读取原 `GlobalIconConfig`，树组件的图标类型直接重导出原图标组件。避免类型检查为两个类型请求展开 2350 个图标的总入口；不改变类型结构、配置键或运行时代码。

补丁由 pnpm 的 `patchedDependencies` 和唯一锁文件管理，`corepack pnpm install --frozen-lockfile` 自动应用。升级 TDesign 或图标版本时，须核对原声明路径、重新生成补丁，并运行完整类型检查、生产构建和生产预览回归，不能直接忽略补丁失配。
