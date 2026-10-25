# 本批验收与边界

用户已明确确认提案后实施。本批完成模型错误与终态局部修复，不代表 GenericAgent/WeKnora 全量源码迁移完成。

## 实际结果

- Responses 非流式 failed/error/未知状态不会返回正常 done；SSE 要求 completed/incomplete。
- Anthropic 记录 initial input 与工具闭合，未闭合不交付调用；过滤和截断不会触发工具。
- Chat 保留严格 finish_reason，支持稀疏/缺省索引的独立调用，重复名称不拼坏。
- 永久身份/参数/额度拒绝不重试；暂时故障按既有用户配置、预算、Retry-After 和取消恢复。缓冲输出失败也不会被外层路由重发。
- 缓存总量按协议计算；累计 usage 不重复相加。内部恢复元数据留在 runtimes，core/API/数据库 schema 未变。

## 验证证据

- `uv run --locked pytest -q -rs`：240 passed、1 skipped，26.36 秒。跳过 `tests/test_platform_postgres.py`，未配置专用 `NEXUS_TEST_POSTGRES_URL`；没有验证 PostgreSQL 迁移、并发或部署。存在一条 Starlette/httpx 弃用警告。
- 其中 `tests/test_model_terminals.py` 193 项覆盖三协议正常/过滤/截断/失败、HTTP 分类与请求次数、工具身份与闭合、累计 usage、部分流恢复、Retry-After/取消、worker 失败和事件重放。全部使用本地 HTTPX/SQLite 夹具，没有真实模型请求。
- `apps/web: npm run build`：类型与生产构建通过；Vite 有大于 500 kB 的 chunk 提示，未改变前端产物组织。
- `apps/web: NEXUS_WEB_TEST_URL=http://127.0.0.1:5189 npm run test:browser`：会话和设置页浏览器夹具通过，含 1440px/375px、去重/重连/停止/焦点、一次性 Key 与发布；不代表真实后端/供应商验收。
- OpenSpec 严格校验、来源映射、本地链接与 git diff --check 在交付前检查。

## 来源与未验收范围

参考固定版本为 GenericAgent `a9a36b4b219593369de01c3e5973e56ac02e568b` 与 WeKnora `e1f9a6166a593a4804a2f99f1d942919c9cc8ea7`。本批没有新依赖或复制整个上游仓库。

环境没有 Go 可执行文件，未运行上游 Go 测试；原测试只做源码核对。真实模型供应商未在线验收；PostgreSQL 按既有安排最后验收。沙箱/六项执行工具仍暂缓。完整 thinking/signature 历史、全部厂商参数、多模态、早期工具进度及缓存状态治理继续保留在完整迁移清单，不被本批归档消除。

无数据库迁移或新增配置。新增稳定错误码可能使过去被笼统归为 provider_unavailable 的永久错误更早失败，这是已确认的行为调整。Chat DONE-only 兼容收紧、部分流不重发、工具截断优先等差异已按本提案确认。
