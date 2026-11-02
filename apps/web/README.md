# Web 对话工作台

Vue 3 / TypeScript / Element Plus，Node.js 22.12+，包管理器 pnpm 10（版本由 `package.json` 的 `packageManager` 指定）。

```bash
corepack enable   # 或 npm i -g pnpm@10.34.9
pnpm install --frozen-lockfile
pnpm dev
```

开发代理把 `/api` 转发至 `127.0.0.1:8000`。界面提供空间/已发布 Native Agent/Session 选择、连续对话、工具状态、等待输入、停止与事件游标重连。用户设置页支持多个供应商、多个模型、一次性 Key 输入、默认模型和连接测试，并可创建/发布 Native 智能体。模型随已发布 AgentVersion 固定。保存 Key 前，部署端须为 API/worker 配置相同加密主密钥，见 [worker 说明](../worker/README.md)。

文本按不可信纯文本显示，不执行 HTML；读屏状态区只报告运行状态，不逐 token 播报。Memory/SOP 草稿不等于已发布记忆，危险执行和文件产物在未接入隔离后端前不可用。

验证：

```bash
pnpm build
pnpm exec playwright install chromium
# 另一个终端保持 pnpm dev 运行
pnpm test:browser
```

浏览器测试位于 `tests/web/conversation.mjs` 和 `tests/web/model-settings.mjs`，使用确定性 API/SSE 夹具，验证发送、结果去重、等待/回答、停止、重连、安全渲染、无权清理和 375px 布局。可用 `NEXUS_WEB_TEST_URL` 指定开发服务地址。设置测试覆盖供应商/模型新增、默认选择、秘密不回显与取消清理、连接测试、发布、停用和窄屏。该测试不代表真实供应商或 PostgreSQL 部署验收。

## 模块文档

- [功能需求](docs/requirements.md)
- [模块设计](docs/design.md)

“Native 与记忆”页面维护个人执行默认值与已审核记忆/SOP。会话可选择候选回答、追加执行指令、批准或拒绝挂起操作，并保留历史创建模型分支。这些设置不修改已有发布版本；审批不替代执行时的资源授权。
