# Native 迁移批次验证与边界

2026-10-25：用户要求继续上个任务，续接工作区已有迁移实现。提案继续保留在本目录，未归档；完整来源索引审查与双项目全量迁移没有完成。

## 当前实现

- 执行循环按 runner、turn、completion、tools、recovery 拆分并保留兼容导出；空响应/长代码澄清、完成提示队列、工作锚点与周期提醒已有本地行为测试。
- 工具支持生成器进度的公开投影、ask_user 候选项、checkpoint 的 key_info/content 兼容；显式只读幂等调用可并发，其他调用形成屏障。
- Chat Completions、Responses、Anthropic Messages 协议适配、文本工具解析、预输出重试与故障转移已有模拟测试。流输出后失败不从头重放。
- 个人执行设置、追加指令、逐调用动作审批、审批后挂起调用恢复、记忆审核发布/索引/版本恢复、保留历史的模型分支已有 SQLite API/worker 测试。
- 前端提供对应设置和会话控件。候选回答、追加指令及已有聊天/模型设置流程执行浏览器回归；记忆、审批和模型分支新页面尚未完整覆盖浏览器行为。
- 恢复工具调用同步更新错误预算及工作检查点，回归用例验证预算耗尽时失败且已完成调用不会留在待恢复列表。

## 来源与许可

GenericAgent 固定提交 `a9a36b4b219593369de01c3e5973e56ac02e568b`，重点映射 `agent_loop.py`、`ga.py`、`llmcore.py`、`plugins/hooks.py` 与记忆管理指令；WeKnora 固定提交 `e1f9a6166a593a4804a2f99f1d942919c9cc8ea7`，重点映射 `internal/agent` 执行、工具屏障、完成与恢复逻辑。MIT 声明保存于 `third_party/notices/`；没有提交第三方源码仓库。现有文件头注明来源不代表完整逐行迁移已验收，逐文件/分支来源映射仍须补齐。

## 验证限制与剩余工作

Python 全量回归、Web 类型/生产构建及浏览器夹具仅证明本地用例。唯一跳过项为 `tests/test_platform_postgres.py`：没有设置专用 `NEXUS_TEST_POSTGRES_URL`，未验证 PostgreSQL 并发、锁与迁移行为。真实供应商未调用。构建存在既有大体积 chunk 提示，测试存在 Starlette/httpx 弃用提示。

尚未完成全量源码/测试/提示词审查、逐分支差分证据、完整 hook 变换语义、全协议错误与 usage/cache 分支、完整上下文溢出恢复与预算内收尾、自动化 AgentGrant、空间共享设置及外围能力迁移。详细任务保留未勾选。沙箱与六项代码/文件/浏览器工具仍按既定边界暂缓，不开放。不得据此宣称完整对齐或归档。

## 本批执行结果

- `uv run --locked pytest -q`：47 passed、1 skipped；审批恢复回归包含在内。
- `uv run --locked pytest tests/test_native_migrations.py -q`：1 passed，断言新增六张表与 candidates 字段，并覆盖升级/重复升级/回退/再升级。
- `npm ci`：完成，0 vulnerabilities；当前 Node 20.20.2，低于仓库要求的 22.12，本机常见安装位置未发现 Node 22，因此尚未完成要求版本下验收。
- `npm run build`：类型与生产构建通过，存在 chunk 体积提示。
- `npm run test:browser`：聊天和模型设置夹具通过，包含候选项点击与追加指令幂等提交。
- 修改文档的本地链接及 `git diff --check`：通过。

## 模型错误与终态局部验收

已按用户确认完成三协议错误/终态、工具完整性、缓存用量与有界重试修复；详见 [独立批次验收](../../../openspec/changes/model-terminal-consistency/verification.md)。该批次不消除本提案的完整迁移与环境验收待办。
