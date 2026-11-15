# 企业组织同步归属（草案，待用户确认）

以下为待确认的 OpenSpec delta；尚不是已接受的系统规格。

## ADDED Requirements

### Requirement: 手工组织管理尊重企微同步来源
组织服务 SHALL 拒绝通过手工接口更名、移动、停用或删除企微同步管理节点。节点 DTO SHALL 明确返回 `sync_managed`，包括手工根节点映射企微顶级部门的情况。启用的同步节点下 SHALL 允许创建手工子节点。

- **WHEN** 手工接口修改同步管理节点
- **THEN** 服务端返回冲突且不写入任何变化
- **WHEN** 管理员在启用的同步节点下创建手工子部门
- **THEN** 新节点保留 `manual` 来源并可按既有手工规则维护

### Requirement: 成员部门归属保留手工与同步来源
成员部门关联 SHALL 区分 `manual`、`wecom` 与两者兼有的 `mixed` 来源。企微对账 SHALL 只增删企微来源；手工写入 SHALL 只增删手工来源。仅有 wecom 来源的关联 SHALL 不允许通过手工删除接口移除；mixed 关联删除后 SHALL 保留 wecom 关联。

- **WHEN** 通讯录变化移除一个 mixed 关联
- **THEN** 只保留 manual 来源和既有主部门标记
- **WHEN** 管理员移除一个 mixed 关联
- **THEN** 只保留 wecom 来源和既有主部门标记

### Requirement: 同步状态如实反馈
管理端 SHALL 复用现有企业微信同步接口与状态字段展示排队、成功、失败、错误信息和最后同步时间。迟到轮询 SHALL 在企业、账号、权限变化或页面卸载后失效；不得将排队反馈显示为同步完成。
