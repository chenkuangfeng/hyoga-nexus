# 记忆包设计

## 职责与边界

- 规则：草稿只能由所有者审核发布；发布、编辑、恢复都追加版本，不改写历史；归档只隐藏条目，不删除来源。
- 索引：`index()` 输出有界的指针列表（上限 6000 字符），正文由模型按授权逐条读取。
- 边界：不导入 SQLAlchemy 或平台包；不解析主体。调用方传入已解析的 `owner_id`。

## 依赖方向

```text
nexus_platform.memory (门面 + SqlMemoryRepository)  ──>  nexus_memory (规则 + 端口)  ──>  nexus_core
```

平台的 `runs` 只通过门面调用记忆，不直接导入仓储。门面把 `MemoryNotFound` / `MemoryConflict` 转为平台的 `NotFound` / `Conflict`，HTTP 响应不变。

## 事务

规则函数不开启或提交事务。门面在 `db.begin()` 内解析用户并调用规则，使身份检查与写入处于同一事务。行锁由端口的 `lock=True` 或 `draft_for_review` 请求。

## 测试

- `tests/test_memory_rules.py`：内存仓储实现端口，覆盖审核、越权、重复审核、版本冲突、类型冲突、恢复、归档和索引上限，不依赖数据库。
- `tests/test_native_parity.py` 仍通过 API 覆盖完整流程，包括审核、读取、恢复与归档。
