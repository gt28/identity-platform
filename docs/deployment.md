# 企业统一身份平台部署手册

状态：独立部署边界、单节点实验室自动化和生产输入模板已具备；高可用生产拓扑仍是
环境实施门槛。  
最后更新：2026-09-07

公司现有 Ubuntu 环境优先使用 [Ubuntu Server 24.04 LTS 专用部署指南](ubuntu-24.04.md)。
它包含 Ubuntu inventory、APT、AppArmor、SSH/UFW 预检和测试路径；本页仍保留
EL9/VirtualBox 实验室和共享 SSO 生产要求。

本手册部署公司统一 SSO，而不是 VMP 的一个附属容器。Keycloak、LDAP/AD
federation、MFA、SSO session、客户端注册和身份审计由身份平台团队负责。VMP、
GitLab、私有云和堡垒机是独立 relying party。

## 1. 支持范围

当前自动化支持：

- Ubuntu Server 24.04 LTS / Enterprise Linux 9 主机安全基线；
- Docker Engine 和 Compose；
- Keycloak 26.7.2 优化镜像；
- HTTPS、审计事件、暴力破解保护、TOTP 策略；
- 独立 OIDC client 声明；
- 可选的 LDAPS/StartTLS 只读 LDAP federation；
- 实验室自签名证书和 50 人模拟公司。

当前自动化是加固的单节点基线，不等同于高可用生产 SSO。生产还需要多个
Keycloak 实例、负载均衡、外部 PostgreSQL、跨故障域设计、PITR、监控告警和恢复
演练。

## 2. 仓库和职责边界

身份平台已经位于独立仓库
[gt28/identity-platform](https://github.com/gt28/identity-platform)，VMP 位于
[gt28/vmp](https://github.com/gt28/vmp)。各自拥有 Git 历史和 CI，不使用嵌套仓库或
submodule。投产前仍需落实：

- 身份平台团队 CODEOWNERS；
- 独立 CI、镜像发布和受保护 production environment；
- Ansible Vault 或企业 Secret Manager；
- 独立维护窗口、SLO、on-call、备份和灾备流程；
- Keycloak 事件及管理员事件导出到安全日志平台。

VMP 仓库、VMP `.env` 和 VMP 数据库不得保存 LDAP bind 密码、Keycloak 管理员
密码、MFA secret 或其他系统的 client secret。

## 3. 前置条件

### 3.1 Ansible controller

- Python 3.12 或更高版本；
- OpenSSH client；
- 可以读取批准的部署 SSH private key；
- 可以访问目标主机 SSH、软件仓库和容器 registry；
- 生产环境可以访问 Ansible Vault 或 Secret Manager；
- 时间同步正常。

### 3.2 目标主机

- Ubuntu Server 24.04 LTS（推荐）或 Enterprise Linux 9 兼容系统；
- 至少 4 vCPU、8 GB 内存和 60 GB 磁盘作为实验室起点；
- 固定 DNS/IP；
- TCP 443 供应用访问，SSH 仅允许管理网络；
- Ubuntu AppArmor 或 EL9 SELinux enforcing，以及 firewalld 和 chrony；
- 生产证书、私钥和完整 CA chain；
- 生产使用外部加密 PostgreSQL；
- 需要 LDAP 时，目标主机可访问冗余 LDAPS 或 StartTLS endpoint。

## 4. 配置 controller

首先克隆独立仓库：

```bash
git clone https://github.com/gt28/identity-platform.git
cd identity-platform
```

从身份平台仓库根目录执行：

```bash
python3.12 -m venv .venv-ansible
.venv-ansible/bin/pip install \
  --requirement ansible/requirements-controller.txt
cd ansible
../.venv-ansible/bin/ansible-galaxy collection install \
  --requirements-file requirements.yml \
  --collections-path .collections
```

执行质量检查：

```bash
../.venv-ansible/bin/ansible-playbook --syntax-check playbooks/site.yml
../.venv-ansible/bin/ansible-playbook --syntax-check playbooks/demo_company.yml
../.venv-ansible/bin/ansible-playbook --syntax-check playbooks/verify.yml
../.venv-ansible/bin/ansible-lint --profile production playbooks roles
```

`.collections/`、`.private/` 和本地虚拟环境不进入版本控制。

## 5. 实验环境部署

### 5.1 创建 VirtualBox VM（可选）

仓库提供的 VM bootstrap 面向 Intel Mac + VirtualBox：

```bash
cd infra/virtualbox
./create-auth-lab.sh --ssh-public-key ~/.ssh/id_ed25519.pub
cd ../..
```

默认创建：

- VM `auth-lab`；
- SSH：host `2222` → guest `22`；
- Keycloak HTTPS：host `8443` → guest `443`；
- 地址由现有实验 inventory 设为 `192.168.2.144`。

其他虚拟化平台可提供 EL9 或 Ubuntu 24.04 VM。Ubuntu 必须使用
[专用 inventory 和步骤](ubuntu-24.04.md)，不要复制 EL9 lab 的 CentOS Docker 源。

### 5.2 检查 inventory

在运行前确认：

```text
ansible/inventories/lab/hosts.yml
ansible/inventories/lab/group_vars/auth_servers.yml
```

重点检查 SSH 地址/端口、controller 公钥、Keycloak 外部地址、证书 SAN 和 VMP
回调 URI。实验 inventory 会在忽略的 `.private/` 下生成独立随机管理员密码和数据库
密码，不复用主机登录密码。

### 5.3 部署和验证

```bash
cd ansible
../.venv-ansible/bin/ansible-playbook playbooks/site.yml
../.venv-ansible/bin/ansible-playbook playbooks/verify.yml
```

部署完成后确认：

```bash
curl --cacert .private/auth-lab.crt \
  https://192.168.2.144:8443/realms/company/.well-known/openid-configuration
```

再次执行 `site.yml` 应尽量显示 `changed=0`。自动化管理 `/opt/keycloak`，不要在目标
主机手工编辑生成的 Compose、环境文件或证书文件；手工改动会被下一次部署覆盖。

### 5.4 创建模拟公司（可选）

```bash
../.venv-ansible/bin/ansible-playbook playbooks/demo_company.yml
```

该 playbook 创建 50 个实验用户、部门层级和 VMP 身份投影 manifest。密码分别位于：

```text
ansible/.private/demo-company-passwords/
```

VMP 管理员用户是 `vmp.admin`。manifest 位于：

```text
ansible/.private/demo-company-identities.json
```

这些账号不得用于共享测试、staging 或生产。VMP 连接和投影步骤见
[VMP 部署手册](https://github.com/gt28/vmp/blob/main/docs/deployment.md#4-连接独立-company-sso-实验环境)。

## 6. 生产 inventory 准备

下面是共享生产模板入口。Ubuntu 的分层 inventory 创建方法见
[Ubuntu 配置步骤](ubuntu-24.04.md#4-创建-ubuntu-inventory)，其公钥、软件源和升级
设置覆盖共享模板中的同名项。

先复制模板，不要直接修改 example 文件：

```bash
cd ansible
cp inventories/production/hosts.example.yml \
  inventories/production/hosts.yml
cp inventories/production/group_vars/auth_servers.example.yml \
  inventories/production/group_vars/auth_servers.yml
mkdir -p inventories/production/group_vars/all
ansible-vault create inventories/production/group_vars/all/vault.yml
```

Vault 至少定义：

```yaml
vault_keycloak_admin_user: <独立紧急管理账号>
vault_keycloak_admin_password: <至少 24 字符的随机密码>
vault_keycloak_db_password: <独立数据库密码>
vault_keycloak_ldap_bind_credential: <只读 LDAP bind 密码>
```

生产 inventory 必须替换所有 example 值：

- 主机地址、SSH 用户、公钥和时区；
- SSO DNS、外部 HTTPS URL、证书和私钥路径；
- 外部 PostgreSQL JDBC URL、账号、TLS 模式和 CA；
- LDAP 产品、URL、base/users/groups DN、bind DN 和 immutable UUID；
- 每个 application/environment 的 client ID、回调、logout URI、audience 和 claims；
- 容器镜像 registry、digest/tag、CPU/内存和数据库连接池预算。

生产不应依赖 `keycloak_manage_postgres: true`。应配置独立运行、加密、可备份且具有
PITR 的 PostgreSQL 服务。

## 7. LDAP/AD 接入门槛

开启 `keycloak_ldap_enabled: true` 前必须确认：

1. 使用 LDAPS，或明确启用并验证 StartTLS；
2. Keycloak 信任目录 CA，证书 SAN 与访问主机名匹配；
3. bind 账号只读且不是目录管理员；
4. `username`、RDN、immutable UUID、email、姓名、部门属性映射准确；
5. 人员禁用/离职行为、用户删除、冲突和重命名策略已测试；
6. full sync、changed sync 周期符合账号回收目标；
7. 组映射只提供受治理的粗粒度 entitlement，不把应用细权限集中到 Keycloak；
8. `organization_id` 有稳定、受治理的来源或映射规则；
9. 使用普通测试账号完成登录、禁用、改组、离职和恢复演练。

身份平台负责“用户是谁和是否可以登录”。VMP、GitLab、云平台和堡垒机分别负责
其资源授权。

## 8. 应用客户端注册

所有客户端都放入 `keycloak_oidc_clients` 声明，并遵循
[客户端接入规范](client-onboarding.md)：

- 每个应用、每个环境使用唯一 client ID；
- public browser client 使用 Authorization Code + S256 PKCE，不保存 secret；
- confidential client 的 secret 来自 Vault/Secret Manager，至少 24 字符；
- redirect/origin 使用精确 allowlist；
- 每个 API 使用独立 audience；
- claims 最小化，并记录 application owner 和 security owner；
- 禁止 GitLab、VMP、私有云和堡垒机共用 client 或 secret。

新增或修改 client 后，先在非生产验证 login、logout、过期 session、禁用用户、MFA
和权限回收，再进入生产审批。

## 9. 生产部署流程

当前 playbook 只应在正式 HA 架构评审通过后作为节点配置基础使用：

```bash
cd ansible
ansible-playbook \
  --inventory inventories/production/hosts.yml \
  playbooks/site.yml \
  --ask-vault-pass

ansible-playbook \
  --inventory inventories/production/hosts.yml \
  playbooks/verify.yml \
  --ask-vault-pass
```

上线顺序：

1. 冻结并评审 realm、LDAP mapper、认证流程和 client diff；
2. 确认 PostgreSQL 最新备份、PITR 和恢复演练；
3. 在 staging 对同一 Keycloak 镜像和配置执行升级；
4. 验证 discovery、JWKS、OIDC/SAML、MFA、禁用用户和所有关键 client；
5. 按节点滚动部署，先从 load balancer drain；
6. 观察登录成功率、错误率、延迟、数据库连接和 event export；
7. 完成生产 smoke test，再关闭变更窗口。

当前模板使用 `keycloak_cache: local`。在未完成跨节点 JGroups、数据库发现、负载
均衡 sticky/session 行为和故障切换测试前，不要仅把 inventory 增加多个主机就宣称
实现了 HA。

## 10. 验证清单

自动验证：

```bash
ansible-playbook \
  --inventory inventories/production/hosts.yml \
  playbooks/verify.yml \
  --ask-vault-pass
```

人工验证至少包括：

- 外部 discovery issuer 与配置 URL 完全一致；
- JWKS 可访问、算法受限、密钥轮换可被客户端接受；
- 管理控制台不暴露给普通办公网或公网；
- 登录、MFA、退出、session timeout 和全局登出符合策略；
- LDAP 禁用用户不能再建立新 session；
- 各应用 token 的 audience/claims 不互相泄露；
- redirect URI 不接受未批准 host 或 wildcard；
- Keycloak login/admin events 已进入安全日志平台；
- PostgreSQL、节点、证书、LDAP、DNS 和时间同步均有监控告警；
- 紧急管理账号受控、可用并有使用审计。

## 11. 备份和恢复

生产权威状态位于外部 PostgreSQL。必须提供：

- 加密 base backup 和连续 WAL/PITR；
- 跨故障域备份副本及保留策略；
- 定期恢复到隔离环境；
- realm、client、mapper 和 policy 的声明式配置版本；
- Vault/Secret Manager 的独立恢复流程；
- 恢复后强制验证登录、client、LDAP federation、MFA 和 event export。

Keycloak container 和本地 cache 不是备份对象。实验室自带 PostgreSQL 仅用于可丢弃
环境，不能承担公司 SSO 的生产恢复目标。

## 12. 凭据和证书轮换

- TLS：部署新证书和完整 chain，验证 reload/滚动重启及所有 relying party；
- confidential client secret：允许新旧凭据短期重叠时先更新 consumer，再撤销旧值；
- LDAP bind secret：先在目录轮换，再更新 Vault 并验证 federation；
- Keycloak 管理密码：通过受控维护流程更新 Vault 和运行环境；
- signing key：确认所有 client 支持 JWKS refresh，再执行受控轮换。

不得把真实 secret 作为 Ansible extra-var 直接写入 shell history。

## 13. 升级和回滚

升级 Keycloak 前：

1. 阅读目标版本 migration/compatibility 说明；
2. 对生产数据库建立可恢复时间点；
3. 在 staging 使用生产规模数据副本执行升级和所有 client 回归；
4. 固定批准的镜像 digest；
5. 验证数据库 schema migration、主题/provider 兼容性和回滚限制。

Keycloak 数据库升级通常不能依赖简单镜像降级回滚。失败时应按批准的数据库恢复点
和旧版本镜像恢复完整环境，而不是只替换容器 tag。

## 14. 故障排查

| 现象 | 检查项 |
| --- | --- |
| playbook 无法连接 | inventory 地址、SSH key、端口、管理网 ACL、sudo |
| Keycloak health 不通过 | `/opt/keycloak` Compose 日志、证书权限、数据库和内存 |
| issuer 不匹配 | `keycloak_external_url`、DNS、反向代理和 `KC_HOSTNAME` |
| 浏览器循环登录 | redirect URI、cookie/domain、时间同步、session policy |
| VMP 会话无效 | VMP issuer/audience/JWKS/CA 与 client mapper 是否一致 |
| LDAP 用户搜不到 | users DN、object class、search scope、bind 权限和 mapper |
| LDAP TLS 失败 | CA chain、SAN、LDAPS/StartTLS 模式和系统时间 |
| 用户禁用后仍有旧 session | token/session 生命周期、全局登出和撤销策略 |
| 新 client 无法登录 | public/confidential 类型、PKCE、secret、redirect/origin allowlist |

## 15. 上线门槛

满足以下条件前不能称为公司生产 SSO：

- 已拆分独立仓库、所有权、CI/CD 和 secret 边界；
- 多节点 Keycloak 和负载均衡故障切换经过演练；
- PostgreSQL PITR 达到批准的 RPO/RTO；
- LDAP/AD 冗余、禁用/离职和属性映射经过验收；
- MFA、紧急访问、证书和 signing key 轮换有 runbook；
- 监控、告警、审计导出和 24x7 责任人已生效；
- VMP、GitLab、私有云和堡垒机分别完成 client 安全评审；
- 完成容量、升级、灾备和安全事件演练。
