# 实施任务

状态：待确认（2026-11-07）。已完成的任务才勾选。

## 0. 准备

- [ ] 0.1 补读 Hermes：`skills_guard.py` 规则表与放行逻辑、`skills_ast_audit.py`、`skill_manager_guards.py`、`skill_usage.py`；DeerFlow：`skills/mutations/service.py`、`repository.py`、`guard.py`、`scan_budget.py`、`skills/projection.py`；WeKnora：`skills/shell_staging.go`、`loader.go`。
- [ ] 0.2 读码确认：智能体绑定里「逐个关闭技能」的字段位置（`resource_bindings` 或智能体版本策略）；`session_index` / `read_for_run` 的现有过滤点；`paths.VIRTUAL_ROOTS` 与两个后端的挂载点。
- [ ] 0.3 确认后先更新文档：`docs/architecture.md` 2.6、`docs/roadmap.md` 7.1、`packages/skills/docs/design.md` 与 README、`skills/general/README.md`。

## 1. S1 来源、信任与导入

- [ ] 1.1 迁移：`skills.source` 取值迁移，`skill_versions` 增加 `trust`、`scan_version`、`scan`；升降级测试。
- [ ] 1.2 `nexus_skills.guard` 规则扫描器与 `ScanResult`；规则表带测试样例；扫描器版本号。
- [ ] 1.3 `nexus_skills.policy.decide` 与放行矩阵；逐格测试。
- [ ] 1.4 名字规则与 frontmatter `model_invocable` / `user_invocable` 解析与校验；索引与 `read_for_run` 的过滤。
- [ ] 1.5 `publish` 接入扫描与矩阵；`acknowledge_findings` 参数；审计；被阻止时的稳定错误码与发现列表。
- [ ] 1.6 管理员接口：导入内置目录（`import_builtin`）、重扫、列表返回 `source` / `trust` / 扫描结论 / `rescan_needed`。
- [ ] 1.7 智能体逐个关闭技能（产生新智能体版本）；会话快照行为测试。
- [ ] 1.8 测试：既有技能、绑定、会话快照、脚本相关测试保持通过。

## 2. S2 投射到沙箱（工具扩展 4.8 完成后开始）

- [ ] 2.1 投射器：按会话、按内容哈希原子写出，文件数与字节上限；失败降级为仅内联。
- [ ] 2.2 虚拟根 `/skills`（只读）：`paths`、`HostFileStore` 拒绝写入；docker `:ro` 挂载；bwrap `--ro-bind`。
- [ ] 2.3 `run_skill_script` 改用投射路径；失败恢复提示；原有脚本测试保持通过。
- [ ] 2.4 测试：沙箱内无法修改 `/skills`；看不到未绑定技能与其他租户技能；无沙箱时保持开发门禁。
- [ ] 2.5 在真实 Docker 与 bwrap 上验证挂载与执行（环境相关测试无环境时跳过并说明）。

## 3. S3 模型创作与审核

- [ ] 3.1 迁移：`skill_submissions`。
- [ ] 3.2 提交服务：新建、修改、基础哈希、限额、扫描、`superseded` 判定。
- [ ] 3.3 工具 `skill_propose`（`skills` 组，风险 `write`）；注册、分组一致性测试；`BUILTIN_TOOL_NAMES` 同步。
- [ ] 3.4 审核接口：列表、详情（差异与发现）、通过、拒绝（理由必填）；通过时重校验并走 `publish`；审计。
- [ ] 3.5 前端：提交列表与审核界面（文本渲染，差异展示）；智能体编辑器的技能开关。
- [ ] 3.6 测试：模型提交不改已发布版本；基础哈希变化被拒；`agent` + `dangerous` 直接拒绝；限额。

## 4. S4 压缩包导入

- [ ] 4.1 压缩包解析：文件数、总字节、单文件上限，路径穿越与符号链接拒绝。
- [ ] 4.2 导入接口：产生 `import` 提交，复用审核流程。
- [ ] 4.3 AST 审计（Python 脚本）并入扫描器，扫描器版本递增。
- [ ] 4.4 测试：恶意压缩包样例（穿越、炸弹、符号链接）。

## 5. S5 使用记录与生命周期

- [ ] 5.1 迁移：`skill_usage`。
- [ ] 5.2 `load_skill` 计数；worker 空闲评估 `stale`；归档、恢复、`pinned` 接口。
- [ ] 5.3 索引排除已归档技能；绑定显示状态。

## 6. 收尾

- [ ] 6.1 同步 `docs/architecture.md`、`docs/roadmap.md`、`packages/skills` 与平台文档、`skills/general/README.md`，只记录当前结果与明确标注的计划。
- [ ] 6.2 后端全量 pytest、迁移升降级、前端单测与构建通过。
- [ ] 6.3 规格同步到 `openspec/specs/skill-evolution/` 并归档本变更。
