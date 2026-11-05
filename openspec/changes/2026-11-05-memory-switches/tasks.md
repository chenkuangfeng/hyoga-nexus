# 实施任务

状态：已确认（2026-11-05），实施中。

## 0. 准备

- [x] 0.1 阅读 WeKnora `enabledScope`、`ApplyAgentMemoryPreference`、`agent_service.go` 记忆工具过滤、`MemoryWorkspaceSettings.vue`、`MemorySettings.vue`。
- [x] 0.2 核对 Nexus 记忆注入、工具注册、抓取排队与现有记忆接口。
- [x] 0.3 用户确认决定 1–4（全部采用推荐方案）。
- [x] 0.4 核对现有 `GET /memory` 是否返回已归档条目；缺少时「已归档」标签页按占位处理，并记录在本文件中。
  - 结果：`list_memory` 只返回未归档条目与待审核草稿，「已归档」标签页按占位处理。

## 1. 后端

- [x] 1.1 迁移：`memory_space_settings` 表，以及 `memory_capture_settings.memory_enabled` 列；测试升级和降级。
- [x] 1.2 `nexus_memory.switches.resolve` 纯函数与单元测试（覆盖全部开关组合与关闭原因优先级）。
- [x] 1.3 平台门面 `memory_state`，以及 `memory-settings`、`memory-preferences` 接口（授权、校验、审计）。
- [x] 1.4 智能体草稿 `budgets.memory` 校验（422）与发布冻结。
- [x] 1.5 准备阶段：记忆关闭时不注入索引、不建快照；工具定义移除 `memory` 分组。
- [x] 1.6 网关复核：记忆工具调用返回 `memory_disabled` 并写审计。
- [x] 1.7 抓取：记忆关闭或写入方式为 `explicit` 时不排队；worker 领取时复核（不调用模型，以 `memory_disabled` 跳过并完成）。
- [x] 1.8 pytest：三级组合、工具过滤、中途关闭、抓取不排队、接口 404/403/422、迁移升降级（`tests/test_memory_switches.py`，32 项）。
  - 快照复用：关闭时不建快照已覆盖；重新开启后复用沿用 `test_memory_snapshot.py` 的已有行为，未单独测试。

## 2. 前端

- [ ] 2.1 `api/nexus-memory.ts` 与映射函数（单元测试）。
- [ ] 2.2 `NexusMemoryWorkspaceSettings.vue`（空间设置，非管理员只读，缺失项占位）。
- [ ] 2.3 `NexusMemorySettings.vue`（个人开关、自动提炼、待审核、生效中、已归档，缺失项占位）。
- [ ] 2.4 `NexusAgentEditorModal.vue` 与 `nexusAgentForm.ts`：长期记忆开关（单元测试覆盖继承与关闭）。
- [ ] 2.5 设置页分区指向新组件；`memory`、`mymemory` 加入 `config/phase1.ts`；断言不再请求 `/api/v1/memory/*` 的 WeKnora 路径。
- [ ] 2.6 文案：所有语言包补齐新增键。

## 3. 文档与规格

- [x] 3.1 `packages/memory/docs/design.md`、`packages/platform/docs/design.md`：开关规则与使用点。
- [ ] 3.2 新增规格 `openspec/specs/memory-switches/spec.md`（由本变更的 `specs/` 归档生成）。
- [ ] 3.3 父提案 `2026-11-02-weknora-parity/tasks.md` 第 51 行与能力对照表第 23 项更新状态。
