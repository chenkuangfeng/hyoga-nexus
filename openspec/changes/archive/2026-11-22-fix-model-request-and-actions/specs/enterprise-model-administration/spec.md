## ADDED Requirements

### Requirement: 操作弹层布局

企业模型和服务商操作弹层 SHALL 使用独立于触发按钮的内容宽度，并保持操作标签可读。

#### Scenario: 在窄屏打开模型卡片操作

- **WHEN** 管理员展开模型操作弹层
- **THEN** 常规操作标签保持单行，弹层留在视口内，支持键盘连续聚焦和 Escape 返回触发按钮
