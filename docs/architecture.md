# 架构边界

采用 Python 多包单仓库。通用层不依赖股票领域。

- apps/api：FastAPI HTTP 服务，未来提供认证、会话、任务与管理 API。
- apps/worker：后台执行入口，队列与调度尚未实现。
- apps/web：Vue 3 + TypeScript + Element Plus，共用管理与业务工作台。
- packages/core：Agent、消息、事件和工具协议。
- packages/runtimes：Codex、Claude Code、DeepSeek Harness 的隔离适配目录。
- packages/connectors：企业微信、微信、QQ 与 Web 接入目录。
- packages/skills：通用技能注册与执行机制预留。
- packages/guanlan：股票领域数据、研究、回测模块。
- skills/guanlan：股票领域技能规格草稿。
- tests：软件回归测试；策略历史回测位于 Guanlan backtesting，二者区分。
- infra：部署配置预留。

股票数据平台后续处理证券主数据、交易日历、行情、基本面、公告、热点与龙虎榜；采集应支持调度、去重、重试、数据时间与来源记录。存储、队列、权限及部署方案尚未确定。

Codex、Claude Code 的真实 Python 接入方式与版本在实现时核对官方文档；DeepSeek Harness SDK 的具体项目和协议待确认，不假设存在统一 SDK。微信/QQ 接入方式和企业微信机器人发送、回调能力也需分别确认。

当前仅健康检查、能力目录 API 和读取该目录的前端可运行；无实际模型执行、消息发送、行情采集或股票分析功能。
