# 目录用途

通用技能目录。每个子目录是一个技能，入口为 `SKILL.md`，资源放在同一目录的 `refs/`，脚本放在 `scripts/`。

## 当前技能

| 技能 | 形式 | 说明 |
| --- | --- | --- |
| `weekly-report` | 内联 | 按结构整理周报草稿，依赖 `read_memory`、`search_memory` |
| `text-stats` | 内联 + 脚本 | 统计文本字符、词、行数；脚本用 `exec_skill` 在所选沙箱档位运行 |

这些技能用于验证技能加载、资源读取与脚本运行流程，导入后是**内置技能**，所有空间可见可分配。导入由平台管理员完成：`POST /api/v1/platform/skills/import-builtin`，或在仓库根目录执行 `uv run python -m nexus_api.cli import-builtin-skills`（读取 `[skills].builtin_dir`，缺省 `skills`；重复执行安全，未变化的目录报告 `unchanged`）。

脚本由 `exec_skill` 在智能体所选的沙箱档位里运行（`local` 档位仅开发模式可用；见 `docs/architecture.md` 2.6、2.9 节与提案 `openspec/changes/archive/2026-11-07-skill-evolution`）。
