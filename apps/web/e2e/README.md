# 双应用浏览器回归

在 `apps/web/` 使用 Node.js 22.12+ 和 pnpm 10：

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm test:browser:install
corepack pnpm test:browser
```

`test:browser` 依次运行 workspace 与 admin 项目，每次仅启动一个真实 Vite 应用，单 worker 执行 Chromium 用例。独立执行使用 `test:browser:workspace` 或 `test:browser:admin`；可追加 Playwright 参数，例如 `corepack pnpm test:browser:admin --list`。两个项目默认分别占用 `127.0.0.1:5193`、`127.0.0.1:5194`，端口被占用时失败，不复用未知开发进程。进程退出由 Playwright 关闭其启动的服务。

Linux 缺少系统库时可先执行 `corepack pnpm exec playwright install --with-deps chromium`。受限环境可通过 `NEXUS_E2E_CHROMIUM_PATH` 指定与 Playwright 版本匹配的 Chromium；默认使用 Playwright 管理的浏览器，不在仓库写入机器专属路径。为减少依赖优化的瞬时内存，Vite 子进程默认使用 `GOMEMLIMIT=192MiB`、`GOMAXPROCS=2`，已有环境值优先。

测试 Vite 配置复用各应用配置，仅关闭自动依赖扫描并显式预打包首批路径需要的依赖，避免首个登录用例前扫描所有 Office/图表懒加载页面。没有替换路由、组件或业务模块；这也不替代默认开发/生产配置的完整验收。

## 首批覆盖

- workspace/admin 的独立登录页与 1440、720、375px 页面宽度。
- Admin 解析卡片/配置抽屉的确认保存、密钥占位保留、布尔 false 保留和窄屏布局。
- WeKnora 设置分组、全部现有导航入口、去除企业修饰词、折叠提示与键盘展开。
- 存储卡片新增、抽屉保存与路径不外显；向量库卡片键盘编辑、抽屉保存及窄屏布局。
- 工作台旧 parser 书签的迁移说明、显式管理链接和无治理接口请求。

用例使用真实应用路由、Vue 和 TDesign；认证与业务接口由 `fixtures.ts` 明确模拟，凭据仅为测试占位，不连接本地数据库。未声明的 `/api/v1/` 请求返回 501 并使测试失败，页面脚本错误也使测试失败。新增业务应逐项声明响应，不能添加一律成功的兜底处理。

模拟接口通过只说明覆盖的前端行为正常，不替代服务端授权、真实解析服务、完整生产构建或 E2.8 全部业务验收。工作台迁移链接保留应用现有开发端口 5174，测试不点击它，以免访问本地其他开发服务。

失败截图、trace 与 HTML 报告分别位于 `test-results/<app>/` 和 `playwright-report/<app>/`，均由 Git 忽略。可用 `corepack pnpm exec playwright show-report playwright-report/admin` 查看报告；按失败日志中的命令打开 trace。

## 生产产物回归

执行 `corepack pnpm build` 后运行 `corepack pnpm test:browser:preview`。也可追加 `workspace` 或 `admin` 只验证一个应用。该模式使用真实 `dist` 与应用原预览配置，不使用测试专用依赖优化；报告保存在 `playwright-report/preview-<app>/`。

除相同的登录、解析保存与旧书签用例外，工作台还实际执行发布的 Mermaid 渲染、PDF.js worker 解析、完整高亮器、KaTeX 公式和 SheetJS 表格读写，并检查 VueOffice 模块加载。模拟 API 不覆盖真实服务，也不代表所有文件格式的真实文档验收完成。
