# Specification Delta: P0 项目基线

## Status
- **Change ID**: `p0-project-baseline`
- **Status**: Completed — 锁定安装、pytest、API/worker smoke check 和 Node 22 前端构建通过

## Requirements

### ADDED Requirements

- **REQ-01 锁定工作区安装**：开发者必须能按仓库说明使用锁文件安装 Python workspace 与开发依赖；安装入口不得要求安装尚未使用的厂商运行时、数据库或领域 SDK。
- **REQ-02 健康检查**：API 必须提供版本化健康检查端点，成功时返回可机器读取的服务状态；该端点不得暗示数据库、队列或业务模块已接入。
- **REQ-03 规划能力状态**：能力目录只列出计划中的运行时、渠道和业务应用，并明确标记为 planned；未实现能力不得显示为可用或健康。
- **REQ-04 初始化 Web 入口**：Web 应用必须启动并读取 API 能力目录；加载中、API 不可达和正常空/有数据状态有明确表现。P0 不包含业务管理页或聊天执行能力。
- **REQ-05 Worker 占位声明**：Worker 启动入口必须明确表示任务调度和队列尚未配置，不得伪装成已运行的消费者。
- **REQ-06 能力状态如实披露**：README、路线图和应用入口对已实现骨架与规划能力的表述必须一致；空包、占位目录和协议草案不得表述为已实现功能。
- **REQ-07 依赖边界**：P0 不新增未被代码使用的外部依赖；共享契约仍由 `core` 承载，通用包不得依赖 `guanlan`。

### MODIFIED Requirements

无。

### REMOVED Requirements

无。
