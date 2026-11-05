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

- [x] 2.1 `api/nexus-agents.ts` 与映射函数（`views/agent/nexusAgentForm.ts`，单元测试 6 项）。
- [x] 2.2 `/platform/agents` 路由指向按 WeKnora 模板重写的 `NexusAgentList.vue`（原 `AgentList.vue` 与 WeKnora 专属 store 耦合，见 design.md 第 1 节）；列表、搜索、新建、复制、删除、开始对话接入 Nexus（按更新时间排序，未提供 WeKnora 的排序控件）。
- [x] 2.3 `NexusAgentEditorModal.vue`：基本信息、提示词、模型配置、工具配置；其余分区不出现；保存即发布（决定 3）。
- [x] 2.4 工具配置：分组目录、可写/需审批/只读标记、未启用工具对管理员可启用、对成员不可选（决定 4）。
- [x] 2.5 新增文案（`nexusAgent`、`nexusModels`）补齐 zh-CN、en-US，并同步 zh-TW、ja-JP、ko-KR、ru-RU（语言包键一致性测试要求）。

## 3. 前端：模型设置

- [x] 3.1 `api/nexus-models.ts` 与供应商/模型映射（`views/settings/nexusModelCards.ts`，单元测试 5 项）。
- [x] 3.2 按 WeKnora 模板重写 `NexusModelSettings.vue`、`NexusModelEditorDialog.vue` 并替换设置页的 `models` 分区；`models` 加入 `config/phase1.ts`。
- [x] 3.3 默认模型（卡片菜单按作用域设置，见 design.md 第 3 节）与连接测试（草稿与已保存模型）。

## 4. 验证

- [x] 4.1 `uv run --locked pytest`：755 通过、1 跳过（新增 `tests/test_agent_editor.py` 7 项）。
- [x] 4.2 前端单元测试：全量 2059 项中 2051 通过、5 跳过；3 项样式守卫失败（复制的 WeKnora 样式含字面量圆角、字号与时长）已改为设计令牌并复测通过。`nexusPagesUsePlatformApi.test.ts` 断言新页面不请求 WeKnora 接口。
- [ ] 4.3 `pnpm build`（未完成：本机内存 1 GB，无法完整构建；已对新文件做 SFC 编译、LESS 编译与限定范围的 `vue-tsc` 检查，均通过）。
- [ ] 4.4 浏览器验证（未完成：需要可用的后端、真实模型与浏览器环境）：创建智能体 → 选择工具与模型参数 → 开始对话 → 工具调用可见。

## 5. 文档与收尾

- [x] 5.1 更新 `apps/web/docs`、`apps/api/docs`、`packages/platform/docs/design.md`（`packages/tools` 无模块文档，目录说明写在 `builtins/catalog.py` docstring）。
- [x] 5.2 更新 `docs/roadmap.md`（3.25）与父提案 `2026-11-02-weknora-parity/tasks.md` 的进度。
- [ ] 5.3 同步 OpenSpec 规格并归档（未完成：规格增量已写入本变更的 `specs/`，待 4.3、4.4 验证后合并到 `openspec/specs/` 并归档）。
