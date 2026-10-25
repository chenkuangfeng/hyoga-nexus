# model-terminal-consistency Specification

## Purpose
统一 Native 三协议模型的错误、终态、工具完整性与用量语义，确保失败不被视为完成、未完整确认的工具不执行，恢复过程有界且不重复输出。

## Requirements

### Requirement: 模型失败必须保持失败语义

三协议适配器 MUST 将明确失败、永久拒绝和无效终态映射为稳定错误，MUST NOT 返回正常完成或将对应 Run 标记 completed；公开错误 MUST NOT 包含凭据、原始供应商正文或认证 header。

#### Scenario: Responses 非流式失败

- **WHEN** HTTP 200 的 Responses JSON status 为 failed，无论是否有 error.message 或 output
- **THEN** 模型请求失败且无正常 done，已有可见片段不伪装为最终成功

#### Scenario: 永久拒绝与暂时故障

- **WHEN** 请求收到身份/参数/额度拒绝或选定暂时 HTTP/网络故障
- **THEN** 按设计错误表分类，永久拒绝不得重试或切换，暂时故障仅在预输出且预算允许时恢复

### Requirement: 终态与工具完整性必须先于执行

适配器 MUST 校验协议终态、工具身份与参数完整性，MUST NOT 执行未闭合、歧义、过滤或截断响应中的工具；正常请求 MUST 只输出一次 core done。

#### Scenario: Anthropic 工具没有闭合

- **WHEN** tool_use 块未收到 content_block_stop，即便已有 tool_use stop reason 与 message_stop
- **THEN** 请求以不完整失败，不交付可执行工具

#### Scenario: 终态缺失

- **WHEN** Responses 缺 completed/incomplete 或 Chat 缺有效 finish_reason 即结束
- **THEN** 请求显式失败，部分文本保留且不重发本次请求

#### Scenario: 截断和过滤优先

- **WHEN** 响应同时包含工具与 length/content_filter 或等价协议原因
- **THEN** 工具不执行，沿既有截断恢复/过滤失败流程处理，不被 tool_calls 覆盖

#### Scenario: 独立关联工具

- **WHEN** Responses 工具片段按 item_id 或回退 output_index 交错到达，或 Chat 使用稀疏索引
- **THEN** 调用按各自身份正确聚合，缺失/歧义失败，合法零参数调用保留

### Requirement: 恢复必须有界并避免重复输出

重试与路由 MUST 遵守已有预算/设置，MUST 在文本/工具输出后禁止本次重发；Retry-After MUST 有界且可取消，MUST NOT 因缩短厂商等待而提前重试。

#### Scenario: 部分流后失败

- **WHEN** 已输出文本或工具后发生可重试类别错误
- **THEN** 保留部分输出并失败，本次不重试或拼接另一个节点，已执行工具不重放

#### Scenario: 等待中取消

- **WHEN** 指数退避或 Retry-After 等待中收到取消
- **THEN** 及时结束等待并释放资源，不发出下一次请求

### Requirement: 用量必须遵守协议口径

用量归一 MUST 区分缓存子集与额外输入，MUST 合并累计 usage 而不重复累加，MUST 对无效数字给出受控行为。

#### Scenario: Responses 缓存属于输入子集

- **WHEN** input=100、output=20、cached=40 且 total 缺失
- **THEN** total 为 120，cache_read 为 40

#### Scenario: Anthropic 输入包含独立缓存项

- **WHEN** 普通 input=100、cache_read=40、cache_creation=10，累计 output=55
- **THEN** total 为 205，重复 usage 快照不再次增加总量
