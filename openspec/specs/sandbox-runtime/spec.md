# 沙箱档位

## Requirements

### Requirement: 命名档位与执行授权

部署 SHALL 提供 local、bwrap、Docker、SSH 和 HTTPS 托管执行档位。智能体通过档位名称选择执行环境。全局启用、档位状态、验收和工具授权 SHALL 共同决定执行工具是否可用。local SHALL 仅在开发认证和部署允许时启用。SSH SHALL 仅在部署显式授权可信执行且通过对应验收时启用。

#### Scenario: 远程档位通过验收

- **WHEN** 启用的 SSH 或 HTTPS 托管档位通过验收且智能体选择了该档位
- **THEN** 命令在经过身份验证的远端执行，文件工具和产物登记使用同一个租户和会话工作区

#### Scenario: 档位暂停

- **WHEN** 平台管理员暂停档位
- **THEN** 新 Run 不获得依赖此档位的执行工具

### Requirement: 企业管理端展示配置和验收

企业管理端 SHALL 按后端和名称筛选已配置档位。企业管理员 SHALL 能查看运行策略、可用性与最近的验收项目。平台管理员 SHALL 能调整超时和暂停状态。返回的详情 SHALL 排除连接凭据。

#### Scenario: 企业空间管理员打开配置

- **WHEN** 当前空间的 owner 或 admin 打开已配置档位
- **THEN** 系统展示后端能力与最近报告，平台管理员可以保存策略
