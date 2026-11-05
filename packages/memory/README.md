# nexus-memory

已审核、可版本化的记忆规则：有界指针索引、所有者范围读取、草稿审核发布、追加式版本、归档与恢复。包内不访问数据库，依赖 `hyoga-nexus-core`。

- `src/nexus_memory/ports.py`：`MemoryRepository` 存储端口、值对象与 `MemoryNotFound` / `MemoryConflict`。
- `src/nexus_memory/service.py`：规则函数。调用方负责解析主体、开启事务和提交。
- `src/nexus_memory/switches.py`：长期记忆三级开关（空间、成员、智能体）的合并规则与智能体预算校验。
- 持久化适配器与 HTTP 相关的平台门面位于 `nexus_platform.memory`。

文档：[设计](docs/design.md)。
