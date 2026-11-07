# 技能演进：来源与信任、投射到沙箱执行、模型创作与审核、导入入口、使用记录

## 状态

待确认（2026-11-07）。下文「待确认的决定」逐项给出推荐，确认前不编码。

## 原因

技能的基础已经实现（归档提案 `2026-11-04-skill-scripts`）：`SKILL.md` 解析、不可变版本、绑定与发布前依赖校验、内联加载、会话技能索引快照、脚本子进程运行、管理员发布。对照架构 2.6、路线图 7.1 与 Hermes、DeerFlow、WeKnora、deepseek-harness、octop-harness 的技能实现后，缺口如下：

1. **没有来源与信任体系**：`skills.source` 只有 `installed` / `builtin` 两个取值；`guard` 的静态提示「仅记录、不阻止」，外部包与内置包没有区别对待。
2. **脚本不在隔离环境运行**：`runner` 以服务进程用户身份运行子进程，只能在开发门禁下使用。
3. **模型不能沉淀技能**：架构 2.6 规定「模型提交草稿、审核后发布」，目前没有草稿、审核、并发保护。
4. **没有导入入口**：`import_builtin` 只是服务层函数，`skills/general`、`skills/guanlan` 的内容进不了库。
5. **没有调用方控制**：无法声明「只给用户用」或「只给模型用」。
6. **没有使用记录**：技能只增不减，无法判断哪些已经不用。
7. `nexus_skills` 的 `projection/`、`review/`、`registry/`、`bindings/` 四个目录是空壳。

## 参考源码

本地副本 `/project/opensource/agents/`。下表只列已读到的部分；`tasks.md` 第 0 节要求实施前补读其余。

| 项目 | 文件 | 借鉴点 |
| --- | --- | --- |
| Hermes | `tools/skills_guard.py` | 来源分 `builtin` / `trusted` / `community` / `agent-created`；「信任级别 × 扫描结论」放行矩阵；扫描器带版本号；扫描结果缓存 |
| | `tools/skills_ast_audit.py`、`skill_linter.py`、`skill_provenance.py` | AST 审计；技能来源记录 |
| | `tools/skill_manager_tool.py`、`skill_manager_guards.py`、`skill_manager_batch.py` | 智能体创建与修改技能的工具及多层防护 |
| | `tools/skill_usage.py` | 使用记录写在旁路文件而非 frontmatter；`created_by: agent` 显式标记；active → stale → archived；`pinned` |
| DeerFlow | `skills/mutations/`、`extension-api/.../skill_mutations.py` | 条件更新：`AssetRevision`（incarnation、序号、内容摘要），基础版本不符即拒绝；待审提案上限；扫描预算与并发限制 |
| | `skills/projection.py`、`skills/security_scanner.py`、`security_static_scanner.py` | 只把启用的技能树只读投射进沙箱；静态扫描 |
| | `authz/skill_filter.py` | 可见性过滤加激活时二次检查（`skill:activate`） |
| WeKnora | `internal/agent/skills/skill.go`、`loader.go` | 三层渐进披露；名字规则与保留词 |
| | `skills/shell_staging.go`、`tools/skill_runtime_guard.go` | 技能资源按内容版本暂存进会话沙箱，宿主不执行、不自动装依赖；文件数与字节上限；失败提示 |
| deepseek-harness | `snapshots/session/skill-load/.../SKILL.md` | frontmatter 的 `disable-model-invocation`、`user-invocable` |
| octop-harness | `skills/catalog.py`、`middleware/skill_filter.py` | 目录分类；智能体级禁用 |

## 范围

### 范围内

**A. 来源与信任（平台、持久化、API 变化）**
1. `skills.source` 取值扩为 `builtin` / `admin` / `import` / `agent`（旧值 `installed` 迁移为 `admin`）；版本新增 `trust`、`scan_version`、`scan`（结构化发现，取代只记录的 `scan_hints`，旧数据保留）。
2. `nexus_skills.guard` 升级为规则扫描器：网络请求、凭据读取、敏感路径写入、混淆、提示注入指令；发现分 `low` / `medium` / `high` / `critical`，结论 `safe` / `caution` / `dangerous`。扫描器带版本号，升级后旧版本标为「需重扫」。
3. 放行矩阵（Hermes 的做法，按本平台调整）：

| 来源 | safe | caution | dangerous |
| --- | --- | --- | --- |
| `builtin` | 放行 | 放行 | 放行 |
| `admin`（管理员直接发布） | 放行 | 放行 | 需管理员显式确认（`acknowledge_findings`），写审计 |
| `import`（外部包） | 放行 | 阻止，管理员可放行 | 阻止，管理员可放行 |
| `agent`（模型提交） | 放行 | 进人工审核 | 拒绝 |

4. 放行的人、理由、被放行的发现写入审计。

**B. 目录与调用方控制（平台、Runtime 变化）**
5. 名字规则：小写字母、数字、连字符，长度 1–64；保留词 `anthropic`、`claude`。已发布的不合规名字不改，新发布按新规则。
6. frontmatter 新增 `model_invocable`（默认真；假则不进入模型的技能索引，`load_skill` 也拒绝）与 `user_invocable`（默认真；本变更只保存并校验，用户侧调用入口待有斜杠命令时接入，标注为计划）。
7. 智能体绑定的技能可逐个关闭，不需要重新发布技能；关闭产生新的智能体版本。会话技能索引快照照旧在会话首个 Run 冻结，变化对新会话生效。

**C. 投射到沙箱执行（Runtime、沙箱变化；依赖沙箱可用）**
8. 沙箱可用时，把本会话绑定的技能按内容哈希只读投射到会话沙箱的 `/skills/<name>@<hash12>/`（DeerFlow 投射 + WeKnora 暂存）：宿主目录按会话建立，沙箱只读挂载；文件数与总字节有上限；宿主不执行、不自动安装依赖。
9. `run_skill_script` 在沙箱内以投射路径运行脚本，工作目录 `/workspace`，参数仍经 stdin，每次调用仍需审批。「沙箱可用时走沙箱」由工具扩展提案任务 4.8 负责，本变更只提供投射路径并替换 4.8 的临时复制方式。
10. 沙箱不可用时保持现有开发门禁；本地子进程运行器保留到沙箱验收在真实环境通过后再评估移除（不在本变更删除）。

**D. 模型创作与审核（核心契约、平台、API、界面变化）**
11. 新表 `skill_submissions` 统一承载「模型提交」与「外部包导入」：来源（`agent` / `import`）、目标技能名、内容（`SKILL.md` 与文件）、基础版本哈希、扫描结果、状态（`pending` / `approved` / `rejected` / `superseded`）、提交人、审核人、理由。
12. 工具 `skill_propose`（`skills` 组，风险 `write`）：模型提交新建或修改；**不能直接写已发布版本**。修改必须带基础版本哈希，审核发布时若当前版本哈希已变，提交置 `superseded`，要求重新提交（DeerFlow `AssetRevision` 的简化）。
13. 每租户待审提交上限（默认 20）、每用户每小时提交上限；超限返回稳定错误码。
14. 审核：管理员列表、详情（与上一版本的差异、扫描发现）、通过、拒绝（须填理由）。通过时重新校验依赖与扫描，再走既有 `publish`。第一期只有人工审核。

**E. 导入入口（API 变化）**
15. 管理员接口：导入内置技能目录（调用 `import_builtin`）；上传技能压缩包（解析、扫描、产生 `import` 提交，放行后发布）。压缩包有文件数、总字节、单文件、路径穿越与符号链接检查。
16. 不做外部市场与 URL 联网安装。

**F. 使用记录与生命周期（后期）**
17. 新表 `skill_usage`：按租户与技能记录加载次数、最后使用时间、状态（`active` / `stale` / `archived`）、`pinned`。归档的技能不进索引，历史版本保留，可恢复。

### 范围外

- 外部市场、URL 与 Git 仓库安装（信任问题单独评估）。
- 模型扫描（DeerFlow 的 LLM 扫描）：成本与不确定性高。
- 规则自动审核发布：第一期只做人工，数据积累后再议。
- MCP 客户端与服务端（路线图 7.2、7.3）。
- 外部 Runtime（Codex、Claude）的技能转换细节：沿用架构 2.6 现有约定。
- 观澜技能内容本身：`skills/guanlan` 的编写不在本变更。

## 待确认的决定

1. **提交模型**
   - 推荐：模型提交与外部包导入共用 `skill_submissions` 一张表和同一套审核界面。
   - 备选：各一张表，界面也分开。
2. **`admin` 来源遇到 `dangerous`**
   - 推荐：允许，但必须显式确认并写审计。管理员是租户内最高信任方，直接阻止会逼他们绕开系统。
   - 备选：一律阻止。
3. **`import` 来源遇到 `caution`**
   - 推荐：阻止，管理员可逐次放行并留理由。规则扫描是启发式的，宁可误拦。
   - 备选：放行但标记「需关注」。
4. **审核方式**
   - 推荐：第一期只做人工审核，不做自动发布。
   - 备选：同期加规则自动审核（只允许无脚本、仅内联、扫描 `safe` 的提交）。
5. **与工具扩展提案 4.8 的分工**
   - 推荐：4.8 保持在 `2026-11-07-tool-expansion`，由它完成「沙箱可用时 `run_skill_script` 走沙箱」；本变更第 C 节在其之后提供投射路径并替换临时复制方式，因此 C 节排在 4.8 之后实施。
   - 备选：把 4.8 移入本变更（需要同时修改工具扩展提案的任务，范围变更要另行说明）。
6. **本地运行器**
   - 推荐：本变更不删除，沙箱在真实环境验收通过后另行评估。
   - 备选：C 节完成即删除，开发模式也只走沙箱。
7. **`user_invocable`**
   - 推荐：先保存并校验，调用入口待斜杠命令设计时接入。
   - 备选：本变更同时做斜杠命令入口（涉及前端与会话输入，范围明显扩大）。
8. **阶段安排**
   - 推荐：按 S1 → S2 → S3 → S4 → S5 分阶段，每阶段独立可验收；S2 在工具扩展 4.8 完成后开始。
   - 备选：S1 与 S3 合并交付。

## 验收

- 不同来源的技能按放行矩阵处理；被阻止的发布返回稳定错误码和发现列表；放行写审计。
- 模型经 `skill_propose` 提交的内容不改动任何已发布版本；基础版本变化后审核被拒绝并提示重提。
- 管理员能导入 `skills/general`，重复导入报告 `unchanged`；同名的非内置技能不被替换。
- 沙箱可用时，技能脚本在 `/skills/...` 只读路径下运行，沙箱内无法修改技能文件，也看不到未绑定的技能。
- 设置 `model_invocable: false` 的技能不出现在索引中，`load_skill` 拒绝加载。
- 既有技能、智能体版本与会话快照的行为不变；全量测试通过，迁移可升可降。
