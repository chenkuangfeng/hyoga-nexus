---
name: text-stats
description: 统计一段文本的字符数、单词数与行数，用于检查文章长度是否符合要求
tools: []
---

# 文本统计

当用户需要知道一段文本的长度时使用本技能。

1. 如果不确定统计口径，先用 `read_skill_file` 读取 `refs/usage.md`。
2. 调用 `exec_skill`，参数为 `{"name": "text-stats", "script": "scripts/count.py", "stdin": "<待统计的文本，原样放入>"}`。文本通过标准输入传入，不要自行转义，也不要把它放进命令行参数。
3. 脚本输出 JSON，包含 `characters`、`words`、`lines` 三项。用这三项回答用户，不要自行估算。
4. 文本超过 20000 字符时，告知用户需要分段统计，不要截断后直接报告结果。
