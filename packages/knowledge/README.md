# hyoga-nexus-knowledge

知识库的纯领域逻辑：解析、分块、检索融合、证据登记与引用、向量引擎端口及实现、存储后端、能力目录。
不依赖 SQLAlchemy 与平台包；持久化、授权、作业与接口在 `packages/platform/src/nexus_platform/knowledge` 和 `apps/api`。

## 模块

| 目录 | 内容 |
| --- | --- |
| `capabilities.py` | 能力目录：WeKnora 知识库全部功能逐项标注已实现或待实现及阶段，`verified` 标注是否经过真实环境验证 |
| `ingest/` | `parse`（文本、Markdown、CSV、JSON、文本型 PDF）、`chunk`（段内定长重叠，保留页码与标题路径） |
| `index/` | `VectorIndex` 端口；引擎 `sqlite`（已测试）、`postgres`、`qdrant`、`elasticsearch`、`milvus`（已实现，未经真实环境验证）；`schemas` 为设置页表单字段 |
| `retrieval/fuse.py` | 关键词与向量的加权 RRF 融合 |
| `evidence/` | 每个 Run 的 `[ID:n]` 证据登记与引用校验 |
| `providers/blob.py` | 原文件存储后端（`local`） |
| `text.py` | 关键词通道的 CJK 二元分词 |
| `graph/` | 占位，GraphRAG 与图谱见 K2 |

## 使用要点

- 引擎在导入 `nexus_knowledge.index` 时注册并同时标记能力目录；新增引擎只需实现 `VectorIndex` 并 `register_engine`。
- 每个引擎的两个检索方法都必须接收 `Scope`（版本 ID）并在引擎内过滤，空范围直接返回空；这是 Pre-Filter 的一部分。
- 未实现的功能通过 `capabilities.require_available` 以 `CapabilityPlanned` 拒绝（API 返回 422 `capability_planned`）。

提案与进度：`openspec/changes/2026-11-06-knowledge-base`；文档：[requirements](docs/requirements.md)、[design](docs/design.md)；评估：`evals/knowledge`。
