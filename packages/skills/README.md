# hyoga-nexus-skills

技能的解析、版本规则与脚本运行。技能只描述流程，不授予任何权限；工具调用仍经过绑定与授权检查。

## 模块结构

| 路径 | 职责 |
| --- | --- |
| `loader/` | 解析 `SKILL.md`（YAML `safe_load` 前置块，保守修复，未知键保留），校验名称、简介、工具与脚本声明 |
| `versions/` | 资源路径规则、大小上限、内容哈希（不可变版本的标识） |
| `exec.py` | 运行脚本的纯规则：路径规范化、解释器选择、哈希、参数检查、命令行组装 |
| `guard/` | 发布检查：脚本存在性、静态提示；`guard/scan.py` 规则扫描器（版本化、按严重度给出 `safe` / `caution` / `dangerous`） |
| `policy.py` | 放行矩阵：来源 × 扫描结论 → 放行 / 需确认 / 阻止 / 审核 / 拒绝 |
| `bundle/` | 技能包 zip：不可信压缩包的安全解包（条目、字节、压缩比、路径、符号链接）、仓库压缩包里裁出一个技能目录、规范打包（同内容同字节） |
| `verify.py` | 安装前的验证关：`.py` 用 `ast`、`.sh` 用 `sh -n`、`.js` 用 `node --check`，解释器缺失只给 `note`；`requirements.txt` 格式与已装包核对 |
| `source.py` | 远程来源解析：github、gitlab、skills.sh、registry（ClawHub）、直链，归一为下载地址与子目录（不联网） |

平台侧的存储、绑定与授权在 `nexus_platform.skills`；工具在 `nexus_tools.builtins.skills`。

## 当前能力

- 内联加载：`load_skill`、`read_skill_file`。
- 脚本执行：`exec_skill(name, script, args?, stdin?, timeout_seconds?)` 在智能体所选的沙箱档位里运行技能目录内的一个脚本文件。脚本无需在 frontmatter 声明，`args` 作为参数列表传入、不经 shell 解释，`stdin` 最多 65536 字节；解释器按扩展名或 `#!` 行在 `python3`、`bash` / `sh`、`node` 中选择；技能被只读投射，脚本从 `$NEXUS_SKILL_DIR` 找到自己的文件，通过 `$NEXUS_DATA_DIR` 读写当前用户的持久数据（临时文件位于 `$TMPDIR`，即 `data/tmp`），并把交付物写到 `$NEXUS_SKILL_OUTPUT_DIR`。仅当智能体设置 `skill_scripts` 开启且所选档位通过隔离验收时出现；生产 `local` 档位必须在 Linux 上由 bubblewrap 执行。运行位置由技能的 `execution` 声明与档位共同决定，不满足时不运行、不回退。风险等级与审批沿用 `sandbox_exec` 和 `tool_access`。
- 发布：管理员通过 `POST /api/v1/tenants/{tenant_id}/skills` 发布新版本（不可修改）；发布前做规则扫描并按来源查放行矩阵，`dangerous` 须带 `acknowledge_findings` 确认，被拦截时错误里带发现列表；`POST .../skills/{name}/versions/{version}/rescan` 用当前扫描器重扫。
- 内置技能：平台管理员 `POST /api/v1/platform/skills/import-builtin` 或 `uv run python -m nexus_api.cli import-builtin-skills` 把仓库 `skills/`（`[skills].builtin_dir`）发布到系统租户，所有空间可见可分配；内容相同报告 `unchanged`，升级产生新版本；同名的空间技能拒绝（`skill_name_taken_by_builtin`）。
- 上传与导出：`POST .../skills/upload`（原始 zip 请求体，≤32 MB，管理员）与 `GET .../skills/{name}/bundle?version=`；包内二进制文件只存于版本的 zip，运行时与文本文件一起投射进沙箱，内容哈希覆盖二进制。
- 远程来源：`POST .../skills/install-remote`（管理员，必须带 `confirm`）经 `nexus_core.egress` 下载（只允许公网地址、逐跳校验、字节与时间上限），裁出技能目录后走与上传相同的检查；版本记录来源，`POST .../skills/{name}/check-update` 只比较内容、不自动更新。
- 安装状态机：带依赖清单的版本先是 `installing`（不被使用，原版本继续服务），worker 在所选档位的临时环境里构建依赖，核对清单包已装后原子换入，再 `ready` 并移动当前版本指针；失败为 `failed` 并保留 zip，`.../versions/{n}/reinstall` 直接重试（也用于给另一档位补建环境），`.../stop-install` 停止，`.../install` 查状态与日志尾部；worker 每约 5 分钟清理失去心跳的构建、残留暂存目录与无人引用的旧环境。
- 私有技能：属于某个用户，不登记为平台资源、不绑定，该用户的会话自动并入索引。对话里用 `skill_manage` 改草稿、`skill_save`（每次确认）保存为新版本、`skill_rollback` 回退；接口 `/tenants/{id}/my-skills*` 列表、版本、回退、归档、恢复。守卫取自 Hermes：先看后改、补丁须唯一匹配、附属文件限 `refs/ scripts/ assets/ templates/`、数量与大小有上限；`nexus_skills.lint` 给出不阻止的建议。
- 共享到空间库：私有技能「复制」进库，两者此后互不影响。管理员（`tools:manage`）直接发布；持 `skills:submit` 的成员 `POST /skill-submissions` 提交，管理员在 `/skill-submissions/{id}/review` 读内容、扫描发现和与库版本的差异，`approve`（重扫并复核库未变化、走同一发布流水线、来源 `user`）或 `reject`（理由必填）。限额：待审总数 20、每人同时 5、每人每小时 10。
- 检索与使用记录：`skill_search` 在本次 Run 能用的技能里搜（绑定的加本人私有的），索引放不下时用它找其余的；`load_skill` 计次、`exec_skill` 刷新最近使用时间，编辑器显示（只记录，不自动归档）。
- 前置块：YAML（`safe_load`），未知键保留并提示，缩进与冒号问题保守修复；名字为小写字母、数字与连字符；`model_invocable: false` 不进索引；`execution: local` 仅限内置。

## 限制

- 脚本只在通过隔离验收的档位运行；生产 `local` 使用 Linux bubblewrap，脚本只能看到当前用户数据目录、当前 Run 输出、只读技能和必要系统运行库。多 Worker 需共享 workspace 持久卷。隔离验收见 `docs/architecture.md` 2.9 节。
- 尚未实现：私有技能与对话式创建、技能包（分发单位）、MCP。远程来源的 ClawHub 下载地址与 GitHub、GitLab 真实服务未联网验证。

## 文档

- 提案与任务：`openspec/changes/2026-11-04-skill-scripts/`
- 示例技能：`skills/general/`
