# 股票分析流程探讨记录

状态：讨论整理稿，不是已批准的功能设计或实施承诺。本文归属 P7「股票研究技能」，用于记录此前关于 XGBoost、智能体多空讨论、专家研报与规则的交流；具体流程和能力仍需在进入 P7 设计时通过 OpenSpec 分析并确认。

## 讨论结论

### XGBoost 与智能体的关系

XGBoost 更适合封装为股票领域工具，由股票分析 Skill 描述何时、为何以及如何调用；Skill 本身是工作流程指引，不负责运行模型，也不授予工具权限。工具根据明确的数据时点和预测任务执行模型，返回结构化结果，例如预测目标、预测周期、分数或概率、模型/数据版本、验证指标和适用限制。智能体把结果作为量化证据，结合其他材料分析，不将单一模型分数直接等同于买卖结论。

工具授权仍由平台在实际执行时校验；股票工具实现及结构化股票数据属于 `guanlan` 领域模块。知识文档、智能体记忆与结构化行情/财务数据应分别管理。

### 专家研报与规则

专家研报可以进入知识库，作为可检索、可引用的研究材料，但原文不会自动成为稳定、可执行的规则。研报应保留来源、作者、发布日期、适用市场/行业和文档版本；检索时结合标的、行业与时间范围，并呈现证据引用及相互矛盾的观点。

可将反复出现且适用范围明确的方法进一步提炼为结构化分析规则，例如指标口径、估值步骤、风险检查项、适用条件和失效条件。提炼结果需要专家审核和版本管理。硬约束尽可能由程序校验；需要解释和权衡的部分交给智能体，并要求给出依据与不确定性。规则与知识库原文应能追溯关联，避免模型把个别研报观点误当作普遍规则。

### 多空研究员讨论

TradingAgents 展示了一种可参考的流程：先由不同分析员生成共享研究报告，再由多头与空头研究员围绕这些报告提出论点并回应对方，最后研究经理阅读辩论记录，权衡两边的证据并输出结构化投资计划。多空立场主要由角色提示词引导，讨论上下文来自分析报告和前序发言；它不是金融规则引擎，也不是投票机制。对本项目而言，这是候选工作流参考，不意味着直接复制实现。

若后续采用该模式，专家规则用于约束证据口径、检查项和论证要求；研报知识库提供可追溯材料；XGBoost 工具提供量化结果。多空双方都应能看到相关证据，并说明接受、质疑或无法判断的理由。研究经理负责综合，不应只按发言先后、票数或模型分数裁决。

### `daily_stock_analysis` 可借鉴点

本地参考仓库：[`ZhuLinsen/daily_stock_analysis`](https://github.com/ZhuLinsen/daily_stock_analysis)。它更偏向专业分工、阶段编排和结构化综合，并非 TradingAgents 式多头/空头轮流辩论。以下只记录对 P7 股票领域流程有启发的模式，不表示直接复用其代码或改变 Hyoga Nexus 平台底座的参考边界。

- **专业分工与统一综合**：技术、情报、风险和专项策略分析各自产出结构化观点，最后由决策 Agent 综合。观澜可据此明确每一步的职责、输入、输出和失败/缺失状态。
- **按成本选择分析深度**：通过 quick、standard、full、specialist 等路径选择分析阶段。观澜可在 P7 设计时评估是否提供不同分析深度，而不是默认每次运行全部阶段。
- **结构化中间观点**：将方向、置信度、依据、关键价位、风险标记等作为中间结果，使下游综合和报告能够检查输入。XGBoost 也可作为一种结构化量化观点来源，携带预测目标、周期、模型版本、验证摘要和限制。
- **Skill 与工具分工**：Skill 指导采用何种分析策略及调用顺序；工具负责取数和可复现计算。Skill 只提供指引，不自行扩大工具权限。
- **风险清单与程序护栏**：把需要检查的风险项、严重程度和降级要求写清楚；对于可确定判断的硬约束，使用程序校验，避免只靠模型自由发挥。
- **输入质量可见**：用统一分析上下文记录行情、日线、技术、新闻等数据块的来源、时点、缺失和降级情况，让报告解释证据限制。

这些模式可纳入候选股票分析步骤：专项分析输出并行或按序完成后，进入综合结论与风险复核。是否并行、阶段配置、结构化观点 Schema 和质量护栏细则均留待 P7 OpenSpec 阶段确认。此处不把 `daily_stock_analysis` 的 Agent 编排器当作 Hyoga Nexus Runtime 或平台架构的替代品。

### Qlib 可借鉴点

本地参考仓库：[`microsoft/qlib`](https://github.com/microsoft/qlib)。Qlib 是量化研究框架，适合参考建模、信号评估和投资策略回测闭环；它本身不是 Agent 编排框架。仓库中的 XGBoost Alpha158 示例将数据集、模型、时间切分、预测信号分析、组合策略与回测配置组合成可复现工作流。

- **训练与在线分析分开**：模型训练、验证和发布属于离线量化研究/模型管理流程；智能体分析时调用已选定版本的模型推理工具，不应在每轮对话中临时训练模型。
- **定义模型信号契约**：工具结果应说明标的或股票池、预测目标与周期、数据时点、特征/模型版本、分数或排序含义及适用限制。模型输出是量化证据，不天然等价于买入/卖出建议。
- **验证信号与策略表现**：除预测误差外，还需评估信号质量和采用策略后的组合表现；回测明确基准、持仓策略、交易成本和测试时间段，并避免未来信息泄漏。历史回测结果与智能体对当前行情的解释分开呈现。
- **保留可复现配置**：将数据集/特征定义、训练验证区间、模型参数、预测产物和回测配置关联版本，便于解释某条量化结论的来源并重跑评估。

对应到候选股票分析步骤，可在在线流程的“量化建模（可选）”之前增加独立的离线模型生命周期：数据与特征准备 → 时间切分训练/验证 → 信号评估 → 策略回测 → 模型版本发布。在线流程只加载已发布模型生成预测结果，再由 Skill 指引调用时机，由分析员和研究经理结合基本面、技术面、新闻、风险及数据质量进行解释。模型训练服务、模型产物存储、推理工具、权限及验收方式均待 P7 OpenSpec 阶段设计确认。

## 对应股票分析步骤模块

以下是讨论归纳出的候选步骤，用于对齐 P7「股票研究技能」范围；不是已定稿的产品流程：

| 步骤 | 目的 | 可能使用的能力 | 主要产物 |
|---|---|---|---|
| 1. 明确分析任务 | 确定标的、市场、分析问题、预测周期和数据截止时点 | 股票分析 Skill、参数校验 | 任务范围与 as-of 时点 |
| 2. 准备数据与证据 | 获取结构化行情/财务等数据，并检索相关公告、研报等文档 | `guanlan` 数据工具、授权知识库检索 | 带来源、版本和时点的证据集 |
| 3. 形成分项分析 | 按技术、基本面、事件/舆情等角度整理观察；区分事实、推断和缺失信息 | 分析工具、专家规则、知识库引用 | 分析员报告 |
| 4. 量化建模（可选） | 对明确的目标和周期运行模型，提供可解释且有版本信息的量化参考 | XGBoost 预测工具 | 预测结果、验证摘要、限制条件 |
| 5. 多空论证 | 多头提出支持论据，空头提出反证与下行风险，双方针对证据回应 | 多空研究员、共同证据与规则 | 有来源引用的辩论记录 |
| 6. 综合研究结论 | 权衡论据质量、证据强弱、模型适用性和不确定性 | 研究经理 | 结构化研究计划与结论理由 |
| 7. 风险复核与报告 | 检查风险、情景和结论边界，整理可追溯输出 | 风险分析、报告生成 | 含数据时点、引用、风险和限制的报告 |
| 8. 评估与回测（适用时） | 评估研究质量或策略表现，防止未来数据泄漏 | `evals/`、`guanlan/backtesting/` | 可复现评估记录 |

步骤 4、5、7、8 是否必选，及其输入输出契约、角色和轮次限制均待后续设计确定。历史策略回测不能由智能体的文字结论替代，需单独处理复权、交易成本、停复牌、退市和未来信息泄漏。

## 边界与后续

- 本文不表示当前仓库已经实现股票数据采集、知识库、XGBoost、辩论工作流或回测能力。
- 股票业务逻辑放在 `guanlan`；公共 Agent/Runtime/工具协议保持领域无关。
- 研报是知识证据；结构化行情和财务数据属于领域数据；规则需审核、版本化，三者不互相替代。
- 进入 P7 详细设计或实现前，按仓库规范创建 OpenSpec 提案，确认数据来源、规则治理、模型评估、权限、报告格式与验收标准。

## 参考

- [TradingAgents 多空辩论流程](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/graph/setup.py)
- [TradingAgents 多头研究员](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/researchers/bull_researcher.py)
- [TradingAgents 空头研究员](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/researchers/bear_researcher.py)
- [TradingAgents 研究经理](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/managers/research_manager.py)
- [`daily_stock_analysis` 项目](https://github.com/ZhuLinsen/daily_stock_analysis)、[Agent 编排器](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/src/agent/orchestrator.py)、[技术分析 Agent](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/src/agent/agents/technical_agent.py)、[风险 Agent](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/src/agent/agents/risk_agent.py)、[决策 Agent](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/src/agent/agents/decision_agent.py)、[分析上下文包](https://github.com/ZhuLinsen/daily_stock_analysis/blob/main/docs/analysis-context-pack.md)
- [Microsoft Qlib](https://github.com/microsoft/qlib)、[XGBoost Alpha158 工作流](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/XGBoost/workflow_config_xgboost_Alpha158.yaml)、[代码组装工作流示例](https://github.com/microsoft/qlib/blob/main/examples/workflow_by_code.py)
- P6 的数据源与 AkShare 讨论见 [观澜数据平台探讨记录](guanlan-data-platform-discussion.md)。
- 本项目 [总体架构](../architecture.md)、[实施计划](../roadmap.md) 与 [资源模型](../resource-model.md)。
