# 目录用途

通用技能目录。每个子目录是一个技能，入口为 `SKILL.md`，资源放在同一目录的 `refs/`，脚本放在 `scripts/`。

## 当前技能

| 技能 | 形式 | 说明 |
| --- | --- | --- |
| `weekly-report` | 内联 | 按结构整理周报草稿，依赖 `read_memory`、`search_memory` |
| `text-stats` | 内联 + 脚本 | 统计文本字符、词、行数；脚本 `count` 需要门禁开启 |

这些技能只是示例，用于验证技能加载、资源读取与脚本运行流程。发布到租户需要管理员调用发布服务（`nexus_platform.skills.service.publish`），目前没有 HTTP 导入入口。

脚本运行只在开发门禁下可用（见 `docs/architecture.md` 2.9 节与提案 `openspec/changes/2026-11-04-skill-scripts`）。
