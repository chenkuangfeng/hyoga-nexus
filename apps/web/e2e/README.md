# 双应用浏览器回归

在 `apps/web/` 使用 Node.js 22.12+ 和 pnpm 10：

```bash
corepack pnpm install --frozen-lockfile
corepack pnpm test:browser:install
corepack pnpm test:browser
```

`test:browser` 依次运行 workspace 与 enterprise 项目，使用单 worker 执行 Chromium 用例。工作台项目启动两个 Vite 服务以验证同源企业管理入口，企业项目只启动企业应用。可独立执行 `test:browser:workspace` 或 `test:browser:enterprise`，也可追加 Playwright 参数。工作台和企业服务分别占用 `127.0.0.1:5193` 和 `127.0.0.1:5194`。进程退出后，Playwright 关闭其启动的服务。

Linux 缺少系统库时可先执行 `corepack pnpm exec playwright install --with-deps chromium`。受限环境可通过 `NEXUS_E2E_CHROMIUM_PATH` 指定与 Playwright 版本匹配的 Chromium；默认使用 Playwright 管理的浏览器，不在仓库写入机器专属路径。为减少依赖优化的瞬时内存，Vite 子进程默认使用 `GOMEMLIMIT=192MiB`、`GOMAXPROCS=2`，已有环境值优先。

测试 Vite 配置复用各应用配置，仅关闭自动依赖扫描并显式预打包首批路径需要的依赖，避免首个登录用例前扫描所有 Office/图表懒加载页面。没有替换路由、组件或业务模块；这也不替代默认开发/生产配置的完整验收。

## 首批覆盖

- workspace/enterprise 的独立登录页与 1440、720、375px 页面宽度。
- 企业管理解析卡片/配置抽屉的确认保存、密钥占位保留、布尔 false 保留和窄屏布局。
- 九组管理导航及其权限过滤、折叠提示与键盘展开。
- 存储卡片新增、抽屉保存与路径不外显；向量库卡片键盘编辑、抽屉保存及窄屏布局。
- 用量分组查询与旧报表快照、成员限额确认保存/移除、无目录权限时不读取目录，以及可选目录失败反馈和窄屏布局。
- 工作台旧 parser 书签的迁移说明、显式管理链接和无治理接口请求。
- 员工三项主菜单、三项账户设置弹窗、旧工具箱地址退出及会话产物折叠/失败重试/会话隔离。
- 系统编辑方式偏好、模型表单抽屉、替换路由编辑及浏览器返回关闭。

用例使用真实应用路由、Vue 和 TDesign；认证与业务接口由 `fixtures.ts` 明确模拟，凭据仅为测试占位，不连接本地数据库。未声明的 `/api/v1/` 请求返回 501 并使测试失败，页面脚本错误也使测试失败。新增业务应逐项声明响应，不能添加一律成功的兜底处理。

工作台浏览器用例覆盖同源跳转、会话复用和普通成员入口隐藏。浏览器模拟接口与服务端授权测试共同覆盖入口行为，真实解析服务与完整业务验收由 E2.8 跟踪。

失败截图、trace 与 HTML 报告分别位于 `test-results/<app>/` 和 `playwright-report/<app>/`，均由 Git 忽略。可用 `corepack pnpm exec playwright show-report playwright-report/enterprise` 查看报告；按失败日志中的命令打开 trace。

## 生产产物回归

执行 `corepack pnpm build` 后运行 `corepack pnpm test:browser:preview`。也可追加 `workspace` 或 `enterprise` 只验证一个应用。该模式使用真实 `dist` 与应用原预览配置，不使用测试专用依赖优化；报告保存在 `playwright-report/preview-<app>/`。

除相同的登录、解析保存与旧书签用例外，工作台还实际执行发布的 Mermaid 渲染、PDF.js worker 解析、完整高亮器、KaTeX 公式和 SheetJS 表格读写，并检查 VueOffice 模块加载。模拟 API 不覆盖真实服务，也不代表所有文件格式的真实文档验收完成。
