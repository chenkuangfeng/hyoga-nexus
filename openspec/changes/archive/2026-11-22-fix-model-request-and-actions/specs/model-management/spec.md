## ADDED Requirements

### Requirement: 未指定思考强度

Chat Completions SHALL 在思考强度为空时使用服务商默认行为。模型配置的新版本 SHALL 将显式提交的空字符串作为清除设置处理。

#### Scenario: 运行已有模型或测试草稿

- **WHEN** 模型选项包含空字符串思考强度
- **THEN** 上游请求省略 `reasoning_effort`

#### Scenario: 清除已有思考强度

- **WHEN** 用户提交空字符串作为思考强度并保存模型
- **THEN** 新版本省略思考强度字段，历史版本保留原值
