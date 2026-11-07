# hyoga-nexus-skills

技能的解析、版本规则与脚本运行。技能只描述流程，不授予任何权限；工具调用仍经过绑定与授权检查。

## 模块结构

| 路径 | 职责 |
| --- | --- |
| `loader/` | 解析 `SKILL.md`（受限 frontmatter，无 YAML 依赖），校验名称、简介、工具与脚本声明 |
| `versions/` | 资源路径规则、大小上限、内容哈希（不可变版本的标识） |
| `exec.py` | 运行脚本的纯规则：路径规范化、解释器选择、哈希、参数检查、命令行组装 |
| `guard/` | 发布检查：脚本存在性、静态提示；`guard/scan.py` 规则扫描器（版本化、按严重度给出 `safe` / `caution` / `dangerous`） |
| `policy.py` | 放行矩阵：来源 × 扫描结论 → 放行 / 需确认 / 阻止 / 审核 / 拒绝 |
| `runner/` | 脚本子进程运行：临时工作副本、哈希校验、stdin 传参、超时、输出上限、结果转义 |

平台侧的存储、绑定与授权在 `nexus_platform.skills`；工具在 `nexus_tools.builtins.skills`。

## 当前能力

- 内联加载：`load_skill`、`read_skill_file`。
- 脚本执行：`exec_skill(name, script, args?, stdin?, timeout_seconds?)` 在智能体所选的沙箱档位里运行技能目录内的一个脚本文件。脚本无需在 frontmatter 声明，`args` 作为参数列表传入、不经 shell 解释，`stdin` 最多 65536 字节；解释器按扩展名或 `#!` 行在 `python3`、`bash` / `sh`、`node` 中选择；技能被只读投射到沙箱，脚本从 `$NEXUS_SKILL_DIR` 找到自己的文件、把成品写到 `$NEXUS_SKILL_OUTPUT_DIR`。仅当智能体设置 `skill_scripts` 开启且所选档位可用（docker / bwrap 通过验收，或 `local` 档位在开发模式且 `allow_local`）时才出现；运行位置由技能的 `execution` 声明与档位共同决定，不满足时不运行、不回退。风险等级与审批沿用 `sandbox_exec` 和 `tool_access`。
- 发布：管理员通过 `POST /api/v1/tenants/{tenant_id}/skills` 发布新版本（不可修改）；发布前做规则扫描并按来源查放行矩阵，`dangerous` 须带 `acknowledge_findings` 确认，被拦截时错误里带发现列表；`POST .../skills/{name}/versions/{version}/rescan` 用当前扫描器重扫。
- 内置技能：平台管理员 `POST /api/v1/platform/skills/import-builtin` 或 `uv run python -m nexus_api.cli import-builtin-skills` 把仓库 `skills/`（`[skills].builtin_dir`）发布到系统租户，所有空间可见可分配；内容相同报告 `unchanged`，升级产生新版本；同名的空间技能拒绝（`skill_name_taken_by_builtin`）。
- 前置块：YAML（`safe_load`），未知键保留并提示，缩进与冒号问题保守修复；名字为小写字母、数字与连字符；`model_invocable: false` 不进索引；`execution: local` 仅限内置。

## 限制

- 运行器不是隔离边界，脚本以服务进程用户身份运行。隔离验收见 `docs/architecture.md` 2.9 节。
- 尚未实现：`agent` / `user` 来源的审核发布、上传与远程来源安装、私有技能与对话式创建、技能包、MCP。

## 文档

- 提案与任务：`openspec/changes/2026-11-04-skill-scripts/`
- 示例技能：`skills/general/`
