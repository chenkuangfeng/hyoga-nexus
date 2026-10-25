# 配置设计

`nexus.example.toml` 提供数据库表和 URL 样例，`nexus.toml` 为忽略的本地配置。platform 的 `configuration.py` 集中读取并校验，入口使用解析结果，配置模块不连接数据库、不修改进程环境变量。优先级与错误处理见[配置入口](../README.md)。

[智能体](../agents/README.md)、[模型](../models/README.md)、[渠道](../channels/README.md)目录仅为预留；本次不增加这些配置的执行能力。
