# hyoga-nexus-skills

技能的解析、版本规则与脚本运行。技能只描述流程，不授予任何权限；工具调用仍经过绑定与授权检查。

## 模块结构

| 路径 | 职责 |
| --- | --- |
| `loader/` | 解析 `SKILL.md`（受限 frontmatter，无 YAML 依赖），校验名称、简介、工具与脚本声明 |
| `versions/` | 资源路径规则、大小上限、内容哈希（不可变版本的标识） |
| `guard/` | 发布检查：脚本存在性、静态提示（仅记录，不阻止发布） |
| `runner/` | 脚本子进程运行：临时工作副本、哈希校验、stdin 传参、超时、输出上限、结果转义 |

平台侧的存储、绑定与授权在 `nexus_platform.skills`；工具在 `nexus_tools.builtins.skills`。

## 当前能力

- 内联加载：`load_skill`、`read_skill_file`。
- 脚本执行：`run_skill_script`，每次调用需要审批；仅当智能体设置开启、`[skills].allow_local_scripts = true`、认证模式为开发模式时可见。
- 发布：管理员通过 `POST /api/v1/tenants/{tenant_id}/skills` 发布新版本（不可修改）。

## 限制

- 运行器不是隔离边界，脚本以服务进程用户身份运行。隔离验收见 `docs/architecture.md` 2.9 节。
- 尚未实现：信任级别与来源检疫、模型草稿的审核发布、内置技能导入、MCP。

## 文档

- 提案与任务：`openspec/changes/2026-11-04-skill-scripts/`
- 示例技能：`skills/general/`
