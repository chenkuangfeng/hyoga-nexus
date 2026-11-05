# 实施任务

状态：已确认（2026-11-05），实施中。

## 0. 准备

- [x] 0.1 阅读 WeKnora `AgentList.vue`、`AgentEditorModal.vue`（基本信息、提示词、模型配置、工具配置分区）、`ModelSettings.vue`、`ModelEditorDialog.vue`、`api/agent`、`api/model`。
- [x] 0.2 核对 Nexus 智能体、模型设置、内置工具与 Native 预算的现有接口与字段。
- [x] 0.3 用户确认决定 1–4（全部采用推荐方案）。

## 1. 后端

- [x] 1.1 `packages/tools`：内置工具声明 `label`、`group`；目录查询函数。
- [x] 1.2 `GET /tenants/{tenant_id}/agent-tools`（授权、`enabled_in_tenant`、`default_tools`）。
- [x] 1.3 `budgets.generation` 校验；Native 运行准备阶段合并到模型选项（决定 1）。
- [x] 1.4 智能体归档（`DELETE`）与复制（`POST .../copy`），列表、建会话、提交 Run 的归档检查（决定 2）。
- [x] 1.5 pytest：授权（404/403）、校验（422）、审计、归档后行为、生成参数进入模型请求。

## 2. 前端：智能体

- [ ] 2.1 `api/nexus-agents.ts` 与映射函数（含单元测试）。
- [ ] 2.2 `/platform/agents` 路由指向 `AgentList.vue`；列表、搜索、排序、新建、复制、删除、开始对话接入 Nexus。
- [ ] 2.3 `AgentEditorModal.vue`：基本信息、提示词、模型配置、工具配置接入；隐藏其余分区；保存语义按决定 3。
- [ ] 2.4 工具配置：分组目录、风险与审批标记、未启用工具的处理（决定 4）。
- [ ] 2.5 新增文案补齐中英文。

## 3. 前端：模型设置

- [ ] 3.1 `api/nexus-models.ts` 与供应商/模型映射（含单元测试）。
- [ ] 3.2 `ModelSettings.vue`、`ModelEditorDialog.vue` 接入；隐藏不支持的入口；`models` 加入 `config/phase1.ts`。
- [ ] 3.3 默认模型（类型 × 作用域）与连接测试。

## 4. 验证

- [ ] 4.1 `uv run --locked pytest`。
- [ ] 4.2 前端单元测试；断言两个页面不再请求 WeKnora 接口。
- [ ] 4.3 `pnpm build`（需内存充足环境）。
- [ ] 4.4 浏览器验证：创建智能体 → 选择工具与模型参数 → 开始对话 → 工具调用可见。

## 5. 文档与收尾

- [ ] 5.1 更新 `apps/web/docs/design.md`、`packages/tools`、`apps/api` 相关文档。
- [ ] 5.2 更新 `docs/roadmap.md` 与父提案 `2026-11-02-weknora-parity/tasks.md` 的进度。
- [ ] 5.3 同步 OpenSpec 规格（`model-management`，新增 `agent-editor`）并归档。
