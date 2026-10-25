# 重实现任务与实际状态

状态：用户已明确确认，正在实施。共享契约、平台实体与 Run 职责拆分已落地；仓储隔离只完成查询、事件和领取路径，不能据此宣称 P0–P2 源码迁移完成。实际证据与剩余项见 implementation-progress.md。

## A. 已完成的准备

- [x] 核对两个本地固定版本、根许可证与当前工作区基线。
- [x] 深读 source-analysis.md 指明的循环、结束、工具屏障、压缩、挂起和授权关键函数/原测试范围，保留 18 项源码指纹。
- [x] 用真实 GA 循环做两个离线分支探针，确认 done queue 与终止回合的生命周期顺序。
- [x] 检查当前类/服务集中位置，形成平台、Native、工具的具体类与文件分布方案。

## B0. 确认及逐模块深读门禁

- [x] 用户确认本提案范围、类分布、冲突解决与暂缓边界。
- [ ] 补齐 GA 模型/历史/工具协议、prompt/schema、memory/SOP、插件与核心入口的全部适用分支及原测试。
- [ ] 补齐 WK 流驱动/停滞、compaction/token/modelcontext、resume/hitl/approval/policy 及对应测试。
- [ ] 补齐 WK P1 service/repository/handler/types/container 调用链与 Nexus 的主体/空间/事务映射。
- [ ] 每个模块在编码前具有“源函数/哈希→原行为/分支→目标类/文件→适配差异→可执行断言”清单；未满足的模块不迁移、不勾选。
- [ ] 对核心外依赖与暂缓工具逐项保留未迁移清单；不要求审查整个上游所有非核心资源才允许一个已完成深读的模块实施。
- [ ] 复用前逐片段检查许可证/依赖归属，将必需声明写入实际目标模块及包内文档；不恢复 third_party 或已删除的 pending 审查目录。

## B1. P0/P1 结构与持久化边界

- [x] 拆 core 的共享契约与平台 ORM 各领域类，保留旧导入、唯一 metadata、表名与全部约束。
- [ ] 建立实际被使用的 Repository/UnitOfWork，分离平台领域服务与 SQLAlchemy；事务内授权和写入不分裂。
- [x] 拆 Run 提交/领取/取消/事件、ExecutionPreparer/DurableRuntimeStore/输入恢复，保留现有调用入口兼容。
- [ ] 验证空库/已有库、metadata、外键与迁移往返；没有 schema 变化时不生成伪迁移。
- [ ] 验证 P1 空间隔离、撤权、发布版本、Session 固定、幂等、Outbox/lease、事件顺序回归。

## B2. 模型与上下文源码迁移

- [ ] 三协议各自建立 request/stream/response/session-state 模块，迁移 thinking/signature/reasoning metadata 的完整合法历史重放。
- [ ] 迁移 GA 文本协议、工具提示缓存与恢复分支、Mixin/模型切换与工作历史；保持已确认的传输错误/终态/用量修复。
- [ ] 迁移 tokenizer/usage 校准、发送视图 sanitize、cutpoint/compactor/summary checkpoint、耗尽标记和 once overflow recovery。
- [ ] 将原协议/压缩测试逐项转换为针对真实迁移模块的差分测试，覆盖坏输入、长上下文、取消、失败/截断和 provider state 不兼容。

## B3. 唯一执行循环、工具与 hooks

- [ ] NativeEngine facade 接入 RunOrchestrator/TurnExecutor/LoopState/ResponseClassifier/TurnFinalizer，实际替换旧混合流程。
- [ ] 迁移 GA StepOutcome/no_tool/done queue、working anchor/summary/提醒；采用已确认 round/attempt 与状态映射。
- [ ] 迁移 WK 逻辑循环的顺序、空/重复/连续截断、结束边界指令与步骤/终态事件，取消不再生成模型请求。
- [ ] 拆 ToolRegistry/Context/Definition、ToolInvoker/Scheduler/Projection/Gateway，迁移普通/生成器进度、原序结果、只读并发和写屏障。
- [ ] 迁移 typed hook 注册/注销/变换/清理与项目上下文；明确原终止回合回调差异，保持可信插件权限边界。
- [ ] 为每条已核对分支运行源/目标行为用例，不以方法名一致或假执行器代替实际迁移。

## B4. 平台恢复、动作授权和记忆整合

- [ ] 完成版本化 RunSnapshot/PendingRound/BlockedIndex、provider metadata、指令消费与已完成调用记录；旧快照兼容路径有测试。
- [ ] 恢复时按当前主体/空间/配置/授权复核，审批消费与动作执行状态分离，未知副作用不重放。
- [ ] 实现 ActionGrant 的 session scope、binding hash、risk、expiry/revocation/last-use；与资源共享和一次性审批分开，automation 边界不虚构已启用能力。
- [ ] 完成长期记忆/SOP 读取、真实整理规则、索引同步、草稿校验、发布/恢复与作用域；不将接口预留计完成。
- [ ] 必要的字段/契约增量写入模块设计和 Alembic；用户配置及授权管理提供现有前端体系内的完整入口。

## B5. 兼容验收与交付

- [ ] 保留/更新 API、SSE、Run 状态、旧导入、数据和会话的行为验收；不能通过删除旧用例回避回归。
- [ ] 用户交互按职责拆 Vue 组件/composable，使用 ui-ux-pro-max，运行前端 build/browser 与键盘/窄屏验证。
- [ ] 运行 Python、迁移、API/worker、跨空间/撤权/重复投递/崩溃恢复/取消/输入审批恢复测试，提供所有跳过的原因与边界。
- [ ] 具备环境后运行上游 Go 测试、真实供应商和 PostgreSQL 专项；未具备时保持未验收，不宣称已对齐。
- [ ] 同步模块 requirements/design/README、全局架构/目录/路线图、迁移差异和 OpenSpec，检查全部工作区、分批提交推送。
- [ ] 仅在约定核心实现、差分证据和兼容验收完成后同步规格归档；暂缓与其他阶段依赖不冒充已完成。
