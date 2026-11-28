## ADDED Requirements

### Requirement: 来源明确的上下文装配

Native SHALL 将宿主注入的工具目录、技能目录、记忆、知识库目录、检查点和插件内容表达为带版本、来源、生命周期及依赖的装配输入。消息内容与工具 schema SHALL 独立装配并确定性排序，原始消息 SHALL 保持为对话唯一来源。

#### Scenario: 相同输入重复装配
- **WHEN** 主体、配置、来源版本、消息水位、逻辑时间和内容快照相同
- **THEN** 输出 messages/tools 的顺序、字节与摘要相同，提供方完成顺序不影响结果

#### Scenario: 插件越过能力边界
- **WHEN** 普通资料 provider 尝试输出 system 指令或直接修改 tools
- **THEN** 装配拒绝该输出，插件不能取得调用授权或污染共享注册表

### Requirement: 每次实际模型请求重新授权

系统 SHALL 在每个模型 attempt（含重试、等待恢复）发送前检查主体、模型及装配来源当前权限；内容缓存 SHALL NOT 缓存 allow/deny。工具调用 SHALL 继续独立授权。

#### Scenario: 缓存命中但来源已撤权
- **WHEN** 已命中的目录、历史、记忆或插件内容来源被撤权、禁用、删除或到期
- **THEN** 系统不再发送该 Run 的旧装配内容，并安全终止；已执行的工具不重放

#### Scenario: 普通发布更新
- **WHEN** 新工具或新技能版本发布但当前 Run 引用版本仍合法
- **THEN** 当前 Run 继续使用冻结版本，下个 Run 按既有快照刷新语义选择内容

### Requirement: 外部资料不占用准备事务

系统 SHALL 在数据库事务外执行外部 provider 调用，以短事务复核租约、水位、版本、取消与授权后提交 Run 上下文。

#### Scenario: 提供方超时
- **WHEN** 可选 provider 超时
- **THEN** 跳过该提供方内容，记录无敏感正文的错误事件，不让等待占用数据库事务，迟到结果不得提交

#### Scenario: 旧 worker 完成准备
- **WHEN** 事务外工作返回时 worker 已失去租约或 Run 已取消
- **THEN** 不提交装配快照、不调用模型、不覆盖新 worker 的状态

### Requirement: 缓存与快照保持来源隔离

缓存 SHALL 使用主体/空间作用域、资源版本与渲染版本隔离；快照 SHALL 保存来源依赖。旧格式缺少依赖的裸文本 SHALL 在授权后重建，不能直接沿用。

#### Scenario: 删除已冻结记忆
- **WHEN** session snapshot 内的常驻记忆被删除
- **THEN** 下一请求不再注入该文本；历史、检查点或摘要不能清除其已记录的来源限制

### Requirement: 动态资料布局兼容与验收

系统 SHALL 先保留当前布局验证对象重构；目标布局将动态资料作为独立 user 资料块置于完整工具交换之后。默认布局切换 SHALL 以性能与质量评测通过为前提。

#### Scenario: 动态资料进入工具调用链
- **WHEN** assistant tool_calls 与对应 tool results 位于当前历史尾部
- **THEN** 动态资料只能在整个交换之后插入，不拆开调用与结果，不修改原始用户消息

#### Scenario: 无可用摘要的长历史
- **WHEN** 历史长度超过读取批次大小且没有合法摘要覆盖
- **THEN** 分批读取现有回放规则要求保留的消息，不能以硬窗口静默丢失用户请求和最终回答

### Requirement: 提示缓存前缀稳定化

Native 默认 SHALL 将工作锚点放在完整历史/工具交换之后，显式关闭配置继续有效；会话检查点 SHALL 为尾部 user 参考资料，不进入 system。使用统计变化 SHALL NOT 改变常驻内容的选择与排列；授权、到期、内容版本和显式重要度变化仍实时生效。工具和目录 SHALL 使用确定性的排序及序列化。

#### Scenario: 连续模型回合
- **WHEN** 只有工作锚点或检查点变化
- **THEN** 前面的指令与历史保持相同，工具调用与结果不会被拆开，源消息不改写。

### Requirement: 按供应商协议启用缓存

原生 Anthropic Messages SHALL 为工具、system 和最近消息设置合计至多四个 ephemeral 断点；Chat Completions 与 Responses SHALL NOT 携带 Anthropic 专属字段。缓存命中统计 SHALL 使用供应商 usage，不以本地前缀字节数冒充真实 token。

#### Scenario: 尾部参考资料与压缩边界
- **WHEN** 最新用户问题之后有检查点、召回资料或工作锚点
- **THEN** 裁剪与摘要仍保护该真实用户问题，不将尾部参考当作新任务边界；预算不足时明确失败而非静默丢弃当前问题。
