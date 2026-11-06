# 知识库设计

## 分层

纯领域（本包）→ 平台（`nexus_platform.knowledge`：`access` 授权、`stores` 向量库与存储注册、`service` 库与文档、`jobs` 可恢复作业、`search` Pre-Filter 与混合检索、`tools` Run 侧工具与引用）→ 接口（`apps/api/.../http/knowledge.py`）与 worker（`knowledge_index.py`）。

## 关键流程

1. 上传：计算 SHA-256；库内已有相同哈希则返回已有文档；否则写原文件再建待处理版本与索引作业。
2. 索引作业（worker）：`pending → parsed`（解析与分块，替换版本的块）→ `embedded`（按批写入向量库，`indexed_count` 断点续做）→ `ready`（同一事务切换文档的当前版本，旧版本标 `superseded` 并清理其索引行）。解析错误直接失败；其他错误 30 秒、2 分钟、10 分钟退避，第 4 次失败。作业以 10 分钟租约领取。
3. 检索：`resolve_scope` 在平台库算出可读库与当前版本；每个库在其向量库上以 `Scope` 做服务端过滤；融合后回平台库取文本，再按范围过滤一次。向量通道的查询向量用查询者自己的 Key 计算，失败则关闭该通道并写审计 `knowledge.search_degraded`。
4. 引用：工具返回的块按首次出现编号，证据登记存入 Run 进度；重复正文只输出编号；Run 完成时解析最终回答的 `[ID:n]`。

## 数据

平台库保存库、文档、不可变版本、块（文本与位置）、作业、向量库与存储后端注册（密钥用部署密钥按记录 ID 绑定加密，列表打码）。向量与关键词索引是派生数据，由所选向量库保存，可由块重建。

## 配置

`[knowledge]`：`data_dir`（内置存储目录）、`max_upload_mb`、`index_concurrency`，见 `configs/nexus.example.toml`。

## 已知限制

PostgreSQL、Qdrant、Elasticsearch、Milvus 引擎代码未经真实环境验证；本机内存不足以运行 `pnpm build`，前端以单元测试和局部类型检查验证。
