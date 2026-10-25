# 待确认分析与实施方案（Pending Review）

本目录集中存放尚未最终确认归档的架构分析、源码差距审计、分阶段实施方案与领域设计讨论文档。进入正式功能编码前，须按 `AGENTS.md` 与 OpenSpec 流程完成用户确认。

## 目录索引

| 文档 / 目录 | 对应阶段 | 说明 |
| :--- | :--- | :--- |
| [open-source-agents-analysis-and-solution.md](open-source-agents-analysis-and-solution.md) | 全局架构 | 九大开源智能体（`GenericAgent`、`WeKnora`、`RAGFlow`、`DeerFlow`、`FastGPT`、`LobeHub`、`TradingAgents/-CN`、`Hermes Agent`、`DeepSeek Harness`）源码剖析与全功能智能体架构及代码分层方案 |
| [omni-agent-phased-implementation-plan.md](omni-agent-phased-implementation-plan.md) | P2+ ~ P9 | 全功能智能体（Omni-Agent）映射到 `hyoga-nexus` 的四阶段十里程碑落地方案与待确认决策清单 |
| [native-reference-audit.md](native-reference-audit.md) & [reference-source-inventory.tsv](reference-source-inventory.tsv) | P2+ | `GenericAgent` 与 `WeKnora` 锁定版本源码差距审计与文件级来源索引 |
| [native-reference-parity/](native-reference-parity/proposal.md) | P2+ | Native 双参考项目完整源码迁移提案（`proposal.md`、`design.md`、`tasks.md`、`specs/`） |
| [knowledge-base-implementation.md](knowledge-base-implementation.md) | P3 | Python 知识库、混合检索与可选图谱增强（GraphRAG）分步实施计划 |
| [guanlan-data-platform-discussion.md](guanlan-data-platform-discussion.md) | P6 | 观澜股票数据平台与外部数据源（如 AkShare）适配讨论记录 |
| [stock-analysis-discussion.md](stock-analysis-discussion.md) | P7 | 股票分析流程、多空辩论（`TradingAgents`）、分工编排与量化回测（`Qlib`）探讨记录 |

增补源码证据：[GenericAgent 外围入口与协作审查](reference-peripheral-review.md)，包含 UltraPlan、Agent BBS、HTTP App、Python 执行头、中英文记忆模板与配置向导的分支、适配边界与待验证项。

审查排期与逐项职责：[范围盘点](reference-review-plan.md)、[工作清单](reference-review-worklist.tsv)；完整模块证据：[hooks 与插件](reference-hooks-review.md)。

Native 核心模型证据：[模型协议、历史与故障转移审查](reference-model-review.md)，含非流式错误终态复现和待修复批次。

WeKnora 模型链路：[请求与终态审查](reference-weknora-protocol-review.md)；待确认批次：[模型错误与终态一致性](../../openspec/changes/model-terminal-consistency/proposal.md)。
