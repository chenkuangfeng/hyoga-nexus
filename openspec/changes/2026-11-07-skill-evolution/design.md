# 设计：技能演进

状态：待确认。以下为推荐方案下的设计，决定变更后同步修改。

## 1. 现状与扩展点

已有（不推翻）：`skills`（租户内唯一名、`source`、`current_version_id`）、`skill_versions`（不可变，含 `content_hash`、`scan_hints`）、`skill_version_files`、`session_skill_snapshots`（会话首个 Run 冻结索引，保护提示缓存）、`resource_bindings(kind='skill')`、`nexus_platform.skills.service`（`publish`、`session_index`、`read_for_run`、`prepare_script`、`import_builtin`）、`load_skill` / `read_skill_file` / `run_skill_script`。

## 2. 来源、信任与扫描

```text
提交内容 ──► 解析与名字校验（loader）──► 规则扫描（guard，带 scanner_version）
                                             │ 结论 safe / caution / dangerous
              来源（builtin/admin/import/agent）┤
                                             ▼
                              放行矩阵 policy.decide(source, verdict) → allow | need_ack | pending_review | block
```

- `nexus_skills.guard`：纯函数 `scan(parsed, files) -> ScanResult(version, verdict, findings)`；`findings` 每项含 `rule`、`severity`、`category`、`path`、`line`、`excerpt`（截断）。规则表短而可审，每条带测试样例。Hermes 自己记录了「正则无法把写文件调用和动态目标关联」的缺口，因此扫描只是门禁之一，运行时授权与沙箱仍然有效。
- `nexus_skills.policy`（新）：`decide(source, verdict, acknowledged) -> Decision`，矩阵是一张常量表，测试逐格覆盖。
- 持久化：`skill_versions` 新增 `trust`（发布时的来源信任级）、`scan_version`、`scan`（JSON）；`scan_hints` 保留以兼容旧行。`skills.source` 取值迁移 `installed → admin`。
- 重扫：扫描器版本变化时，列表接口把低于当前版本的行标为 `rescan_needed`；管理员可触发重扫，重扫结果只追加到版本的 `scan`，不修改内容。已绑定的版本不因重扫自动失效。

## 3. 提交与审核

```text
skill_propose(name, skill_md, files, base_hash?) ─┐
POST .../skills:import (zip)  ───────────────────┤► skill_submissions(pending) ─► 管理员审核
                                                   │       │ 通过：重校验依赖 + 重扫 + 基础哈希 → publish
                                                   │       └ 拒绝：理由必填
```

- `skill_submissions`：`id`、`tenant_id`、`origin`(agent|import)、`name`、`skill_md`、`files`(JSON，受大小上限)、`base_hash`(新建为空)、`scan`、`state`、`submitted_by`、`run_id?`、`reviewed_by`、`review_reason`、时间戳。
- 并发保护：通过时在事务内读取技能当前 `content_hash`；与 `base_hash` 不同则置 `superseded`。新建时若同名技能已存在，同样 `superseded`。
- 限额：待审总数与每用户每小时提交数（读配置，默认 20 / 10）。
- `skill_propose` 在 `skills` 组，风险 `write`；`agent` 来源遇 `dangerous` 在工具内直接返回拒绝，不入库。工具结果不含扫描细节以外的内部信息。
- 提交内容属于模型生成数据，审核界面显示时按纯文本渲染；差异对比由服务端计算，只比较文本。
- 审计：提交、通过、拒绝、放行发现、重扫，均记 `audit`。

## 4. 目录与调用方控制

- `loader` 的受限 frontmatter 新增布尔键 `model_invocable`、`user_invocable`；未知键仍然报错，保持「受限」。
- 会话索引（`session_index`）只列 `model_invocable` 为真且未被智能体关闭的技能；`read_for_run` 复核同样条件，直接按名调用也拒绝。
- 智能体逐个关闭：存在 `resource_bindings` 的绑定配置里（具体字段位置见 `tasks.md` 2.x 的读码结论），变化产生新的智能体版本，沿用不可变约定。

## 5. 投射到沙箱

```text
会话沙箱目录：  <workspace_root>/<tenant>/<session>/{workspace, outputs, skills}
                                                              │ 只读挂载为 /skills
skills/<name>@<hash12>/{SKILL.md, refs/, scripts/}    ← 仅本会话绑定且启用的技能，按 content_hash 命名
```

- 投射在会话的第一次沙箱使用前完成，文件由数据库内容原子写出；总文件数 ≤ 1000、总字节 ≤ 32 MB（WeKnora 上限）；超限则该会话的投射失败，技能脚本不可用但内联加载不受影响。
- 虚拟根新增只读的 `/skills`：`paths.VIRTUAL_ROOTS` 增加该根，`HostFileStore` 对其写入一律拒绝；docker 后端加 `-v <dir>:/skills:ro`，bwrap 后端加 `--ro-bind`。容器是长期的，所以投射目录在容器创建时挂载，技能集合在会话内不变（与会话索引快照一致）。
- 其他会话与其他租户的技能不在该目录中。
- `run_skill_script`：命令为 `cd /workspace && <解释器> /skills/<name>@<hash>/scripts/<file>`，参数经 stdin 传入；解释器白名单沿用 `guard`；输出转义沿用 `runner`。依赖由沙箱镜像提供，不在运行时安装；失败时附带 WeKnora 式的恢复提示（镜像缺少解释器或模块）。

## 6. 使用记录

- `skill_usage(tenant_id, skill_name)` 主键；`load_skill` 成功时递增（Run 内同一技能只计一次）；与加载同事务，失败不影响加载。
- 生命周期：由 worker 空闲时每日评估，超过阈值天数（配置，默认 90）未用且未 `pinned` 的 `active` 置 `stale`；`stale` 再过阈值由管理员决定归档。不自动归档。
- 归档的技能：不进新会话的索引，绑定显示「已归档」；历史版本与已有会话快照不变。

## 7. 兼容与迁移

- 迁移：新增列有默认值；`installed → admin`；新表两张。降级删除新表与新列。
- 既有智能体版本、会话快照、绑定不变；`model_invocable` 默认真，因此行为不变。
- 公开 API 只增不改；旧发布接口在 `admin` 来源下行为一致，只多返回扫描结论。

## 8. 风险

- 规则扫描的覆盖有限，`import` 来源一律从严；真实效果需用已知恶意样例与大量正常技能验证误报率。
- bwrap 后端每条命令一个隔离环境，`/skills` 的 `--ro-bind` 需要在真实 bwrap 上验证。
- 投射目录按会话复制，技能很多时磁盘占用上升；上限已设，必要时改为按哈希共享后硬链接。
