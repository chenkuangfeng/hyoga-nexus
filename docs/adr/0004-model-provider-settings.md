# ADR-0004：用户模型设置与加密凭据

状态：已采用，2026-10-25。

## 决策
用户在设置页管理个人与空间共享的 OpenAI-compatible 供应商及多个模型。Key 经 API 一次性接收，使用 cryptography 的 Fernet 认证加密保存在独立凭据表；部署主密钥经环境注入 API/worker，不在数据库或仓库中保存。库由 platform 实际使用，版本通过 uv.lock 锁定；不手写密码算法。缺少主密钥或密文无效时拒绝解析，无明文回退。[Fernet 官方说明](https://cryptography.io/en/latest/fernet/)。

HTTPX 由 Runtime 实际使用。目的地址检查与 DNS/IP 固定放在 transport 中，覆盖 API 连接测试和 worker 正式调用；保留域名 TLS 校验、禁用重定向与环境代理。[HTTPX transport 文档](https://www.python-httpx.org/advanced/transports/)。SNI 扩展已核对锁定 httpcore 源码，DNS/IP/Host/SNI 行为有本地测试。

## 权限与兼容
个人设置限定本人使用；共享设置由空间管理员管理。创建自己的 Native 智能体向成员开放；编辑/发布他人智能体仍要求管理员。所有执行入口继续复核模型可用性和归属，不能通过智能体共享扩大凭据权限。

既有 environment 凭据保持兼容。显式模型优先于个人默认和空间默认。默认变化不改已有 AgentVersion 或 Session。模型编辑产生新版本，并推进相关默认；更换地址要求新 Key 和新引用，旧版本保留旧地址/凭据；同地址 Key 替换属于显式轮换，后续解析生效。

## 运维边界
主密钥丢失无法恢复密文；应通过部署秘密管理备份。当前主密钥轮换需受控离线重加密，不提供自动轮换接口。供应商 Key 可通过界面替换。停用不撤回供应商已接收的请求，下一次受控授权/模型回合拒绝执行。真实供应商与 PostgreSQL 专项仍需目标环境验收。
