# 开发规范

- 后端、运行时适配器、连接器和领域逻辑使用 Python 3.11+；Web 使用 Vue 3、TypeScript 和 Element Plus。
- 开始功能开发前，阅读 `docs/architecture.md`、`docs/directory-layout.md` 和 `docs/roadmap.md` 中相关阶段的内容。
- 修改平台底座或 Native Runtime 行为前，阅读 `docs/reference-analysis.md`，并检查其中固定版本的 WeKnora 和 GenericAgent 实现。WeKnora 是平台组织方式和能力设计的参考；GenericAgent 是 Native 执行循环、工具分发、生命周期、记忆和 SOP 的参考。保留相关行为与扩展点，不得简化、删除或缩减核心能力。改动只能新增能力，并保持向后兼容。若技术栈或安全要求使实现方式必须调整，应记录映射关系并证明调整保留或扩展了原有行为。复用源码前必须核对许可证并记录归属信息。
- 每项新功能或功能调整都必须先创建 OpenSpec 提案，写明范围、需求、设计和实施任务，并等待用户明确确认后再编码。小需求可以直接实现；用户明确要求跳过 OpenSpec 时也可直接修改。仅修改文档或进行非功能性维护时，无需等待此项确认。
- 后端、平台、Runtime、持久化或 API 工作须阅读 `rules/backend.md`；Web 界面工作须阅读 `rules/frontend.md`。同时涉及 API 和界面时，两份规范都要阅读。
- `core` 只包含共享契约，不得依赖其他本地包或厂商 SDK。
- 通用包不得导入 `guanlan`。领域扩展应在应用入口组合。
- `platform` 管理智能体、会话、资源和授权；`runtimes` 负责执行。不得在 SDK 自带的执行循环外再套一层 Native 循环。
- 厂商 SDK 类型必须留在 Runtime 适配器中；平台专属消息类型必须留在连接器中。
- Skill 指令不能授予额外权限。实际调用工具或访问文档时，必须校验资源授权并记录访问。
- 知识文档、用户或智能体记忆，以及结构化股票数据必须分别管理。
- Skill 内容放在顶层 `skills/`，实现代码放在 `packages/skills`；软件测试放在 `tests/`，质量评估样例放在 `evals/`，金融回测放在 `guanlan/backtesting/`。
- 不得提交凭据、数据转储或第三方源码仓库。若后续复用代码，应记录锁定版本和归属信息。
- 清楚区分计划中的脚手架与已经实现的功能。只有代码实际使用依赖时，才添加包依赖。
- 每项任务完成后，检查整个工作区，将所有待提交的非敏感变更提交，并推送当前分支到 GitHub。不得遗漏其他待提交变更；凭据、数据转储和第三方源码仓库始终不得提交。若提交或推送失败，应说明具体阻碍并保留现有改动。
- 按需运行 `uv sync --locked --extra dev` 和相关 pytest 检查；前端改动运行 `npm ci` 和 `npm run build`。仅修改文档时检查链接和差异，无需运行完整程序测试。
