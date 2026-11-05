# 记忆包设计

## 职责与边界

- 规则：草稿只能由所有者审核发布；发布、编辑、恢复都追加版本，不改写历史；归档只隐藏条目，不删除来源。
- 提议：`propose()` 先经 `text.screen` 拒绝威胁、脱敏敏感值，再做指纹去重、墓碑检查、预算检查与编辑基线检查；拒绝与重复是结果而非异常，模型据此调整。
- 索引：`index()` 只列出启用、未归档、未过期的条目，输出上限 6000 字符，超限时按行截断并注明省略数量；正文由模型按授权逐条读取，读取结果以 `<user_memory>` 包裹。
- 检索：`search()` 为关键词检索，只返回指针与片段；可用性（启停、有效期）由检索规则与仓储查询共同保证。
- 停用与有效期：`set_availability()` 与归档分开，停用保留版本，只影响索引与检索。
- 开关：`switches.resolve()` 合并空间、成员、智能体三级开关，三者都允许时记忆才可用；任一级关闭时，平台不注入索引、移除 `MEMORY_TOOL_NAMES` 中的工具、拒绝记忆调用、不排队自动抓取。写入方式 `explicit` 只禁止自动抓取。关闭不删除任何数据。参考 WeKnora `enabledScope`。
- 边界：不导入 SQLAlchemy 或平台包；不解析主体。调用方传入已解析的 `owner_id`。

## 依赖方向

```text
nexus_platform.memory (门面 + SqlMemoryRepository)  ──>  nexus_memory (规则 + 端口)  ──>  nexus_core
```

平台的 `runs` 只通过门面调用记忆，不直接导入仓储。门面把 `MemoryNotFound` / `MemoryConflict` 转为平台的 `NotFound` / `Conflict`，HTTP 响应不变。

## 事务

规则函数不开启或提交事务。门面在 `db.begin()` 内解析用户并调用规则，使身份检查与写入处于同一事务。行锁由端口的 `lock=True` 或 `draft_for_review` 请求。

## 测试

- `tests/test_memory_rules.py`、`tests/test_memory_stage1_rules.py`：内存仓储实现端口，覆盖审核、越权、重复审核、版本冲突、类型冲突、恢复、归档、提议筛查、去重、墓碑、预算、索引截断、读取包裹与检索，不依赖数据库。
- `tests/test_memory_text.py`：分词、威胁规则、脱敏、指纹。
- `tests/test_memory_switches.py`：三级开关组合、接口授权与校验、Run 准备与工具授权、自动抓取、迁移升降级。
- `tests/test_memory_search_sqlite.py`：真实 SQLite 上的 FTS5 与回退路径一致性、版本替代、启停与有效期、时区、回滚、模型工具端到端。
- `tests/test_memory_stage1_migration.py`、`tests/test_memory_stage1_api.py`：迁移回填与升降级；启停与有效期的 HTTP 契约。
- `tests/test_native_parity.py` 仍通过 API 覆盖完整流程，包括审核、读取、恢复与归档。

## 会话内快照（阶段二）

快照由平台层保存与刷新（`nexus_platform.memory.snapshots`），本包只提供索引文本。第一个 Run 生成索引并存入会话快照表，之后的 Run 复用同一文本；刷新即删除该行。`version_key` 为所有者已发布条目的指纹，只用于提示快照是否过时，不会自动刷新。
