# Web 对话工作台

Vue 3 / TypeScript / Element Plus，Node.js 22.12+。

```bash
npm ci
npm run dev
```

开发代理把 `/api` 转发至 `127.0.0.1:8000`。界面提供空间/已发布 Native Agent/Session 选择、连续对话、工具状态、等待输入、停止与事件游标重连。智能体和模型配置目前通过后端 `/docs` 管理，模型随已发布 AgentVersion 固定。

文本按不可信纯文本显示，不执行 HTML；读屏状态区只报告运行状态，不逐 token 播报。Memory/SOP 草稿不等于已发布记忆，危险执行和文件产物在未接入隔离后端前不可用。

验证：

```bash
npm run build
npx playwright install chromium
# 另一个终端保持 npm run dev 运行
npm run test:browser
```

浏览器测试位于 `tests/web/conversation.mjs`，使用确定性 API/SSE 夹具，验证发送、结果去重、等待/回答、停止、重连、安全渲染、无权清理和 375px 布局。可用 `NEXUS_WEB_TEST_URL` 指定开发服务地址。该测试不代表真实供应商或 PostgreSQL 部署验收。
