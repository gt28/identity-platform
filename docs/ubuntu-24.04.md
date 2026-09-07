# Ubuntu Server 24.04 LTS 部署

更新日期：2026-09-07。Ubuntu 24.04 是本项目推荐的身份平台宿主机版本。
本页对应 `ansible/inventories/ubuntu/`，不要求安装 RHEL 或重新创建 EL9 虚拟机。

## 支持边界

| 项目 | 当前实现 |
| --- | --- |
| 操作系统 | Ubuntu Server 24.04 LTS（含同系列点版本）；保留 EL9 分支 |
| 架构 | `x86_64` → Docker `amd64`；`aarch64` → Docker `arm64` |
| 系统安全 | AppArmor、auditd、firewalld、SSH 公钥认证、chrony |
| 容器 | Docker CE、Buildx、Compose CLI 插件，APT Noble 仓库和独立签名密钥 |
| Keycloak | 复用现有镜像、HTTPS、数据库、realm、LDAP 和 OIDC client 自动化 |
| 验证状态 | 离线分支/模板/安全断言测试；提供真实 Ubuntu VM smoke workflow |

这不代表已在你们的生产主机验收。投产前必须在隔离的同版本 VM 上执行安装、登录、
幂等性、主机重启及 LDAP 回归。ARM64 必须额外验证所用镜像 tag 和内部镜像仓确实
提供对应架构。Ubuntu 22.04/26.04、Debian 和 openEuler 不会被隐式放行。

## 与 EL9 的差异

- Ubuntu 使用 APT，不访问 CentOS RPM 仓库；APT 信任通过 `Signed-By` 限定到
  Docker keyring，并核对公钥指纹。
- Ubuntu 使用 AppArmor，不安装或强制启用 SELinux。部署会检查 `aa-enabled` 和
  Docker 的 AppArmor 支持；容器不设置 `apparmor=unconfined`。
- Ubuntu 的服务名是 `ssh`、`chrony`；EL9 保留 `sshd`、`chronyd`。
- Ubuntu 的证书 bind mount 使用 `:ro`，EL9 保留 SELinux 的 `:ro,Z`。
- SSH 使用 `00-identity-hardening.conf`，优先于 cloud-init 常见的
  `50-cloud-init.conf`，并检查 `sshd -T` 的有效配置。
- 系统包升级和重启在 Ubuntu inventory 中默认关闭，由维护窗口单独批准。

## 1. 准备专用 Ubuntu 主机

不要直接在运行 Kubernetes、其他容器工作负载或承担公司防火墙职责的共享宿主机上
运行本角色。它管理 Docker daemon 配置、SSH 和主机防火墙，Docker 配置变化可能
重启 daemon。建议为身份平台使用专用 VM。

准备以下条件：

1. Ubuntu Server 24.04 LTS，已应用公司批准的安全更新。
2. SSH 公钥、一个已经存在的非 root sudo 账号和可用的带外控制台。
3. 目标 `/usr/bin/python3`、`python3-apt`，controller Python 3.12。
4. 主机能够访问 Ubuntu 和 Docker APT 仓库，或者已审核的内网镜像。
5. 主机能拉取批准的 Keycloak/PostgreSQL 镜像，且能访问数据库、LDAP、DNS、NTP。
6. 正式 SSO DNS、受信任证书及完整链、外部 PostgreSQL、备份和 Vault。

在主机上检查操作系统与管理访问：

```bash
cat /etc/os-release
uname -m
python3 --version
sudo -v
sudo sshd -t
```

如果 Python 的 APT 绑定尚未安装，由现有主机管理员安装：

```bash
sudo apt-get update
sudo apt-get install python3 python3-apt openssh-server
```

自动化不会创建初始 SSH 登录通道。先由公司的主机交付流程创建 `ansible` 用户、
安装批准的公钥并确认 sudo 可用。角色安装公钥后会锁定该账号的密码、禁用 root
和密码 SSH 登录；保留一个已验证的管理会话和带外恢复路径。

## 2. 防火墙与已有容器检查

角色统一管理 **firewalld**。检测到 `/etc/ufw/ufw.conf` 中 `ENABLED=yes` 时会
在修改系统前终止。不要直接关闭正在保护生产主机的 UFW；先评审现有规则，并在
维护窗口完成策略迁移。已有自定义 nftables/iptables/firewalld 规则也要由运维核对。

Docker 发布的端口不能仅依靠 UFW 或普通主机 INPUT 规则保护。当前 Keycloak
Compose 发布主机 TCP 443，必须在安全组/上游 ACL 或经过测试的 Docker 转发链中
限制来源。只允许管理网络访问 SSH；对 Keycloak 管理端点另行限制访问。禁止为了
部署成功而全局关闭防火墙或 AppArmor。

检测到 `docker.io`、旧 `docker-compose`、`containerd`、`runc` 等冲突包时默认
拒绝替换。只有在已迁移相关工作负载、确认这是专用主机后，才可显式设置：

```yaml
docker_remove_conflicting_packages: true
```

此设置会卸载已检测到的冲突包。它不是原地迁移 Kubernetes 或其他容器平台的工具，
也不应作为绕过预检的常规开关。

若曾手工安装 Docker，预检还会检查 `/etc/apt/sources.list.d/docker*.list`。
先备份旧源、确认其中的镜像站和签名设置，把批准值迁入 inventory 后再移走旧
`.list` 文件，避免与角色管理的 `docker.sources` 发生 `Signed-By` 冲突。
其他文件名中的 Docker 条目及 `/etc/apt/sources.list` 也需要人工核对；自动化不会
遍历删除现有 APT 配置。

## 3. 安装 controller

克隆独立身份平台仓库后安装 controller，不需要克隆 VMP：

```bash
git clone https://github.com/gt28/identity-platform.git
cd identity-platform
python3.12 -m venv .venv-ansible
.venv-ansible/bin/python -m pip install -r ansible/requirements-controller.txt
cd ansible
../.venv-ansible/bin/ansible-galaxy collection install -r requirements.yml -p .collections
```

后续命令都在 `identity-platform/ansible/` 下执行，使用专用虚拟环境。

## 4. 创建 Ubuntu inventory

以下复制命令只在首次创建环境时执行，不能覆盖已有配置：

```bash
umask 077
mkdir -p inventories/ubuntu/group_vars/all
cp -n inventories/ubuntu/hosts.example.yml inventories/ubuntu/hosts.yml
cp -n inventories/production/group_vars/auth_servers.example.yml \
  inventories/ubuntu/group_vars/all/identity.yml
cp -n inventories/ubuntu/group_vars/auth_servers.example.yml \
  inventories/ubuntu/group_vars/auth_servers.yml
../.venv-ansible/bin/ansible-vault create inventories/ubuntu/group_vars/all/vault.yml
```

配置的职责和优先级：

| 文件 | 内容 |
| --- | --- |
| `hosts.yml` | Ubuntu 主机 IP、SSH 用户/端口、`/usr/bin/python3` |
| `group_vars/all/identity.yml` | 通用 SSO 域名、TLS、数据库、realm、客户端和 LDAP 配置 |
| `group_vars/auth_servers.yml` | Ubuntu 特定的软件源、安全公钥、时区和升级选项，覆盖 all 中的同名项 |
| `group_vars/all/vault.yml` | 加密的管理员、数据库和 LDAP bind 凭据 |

活跃配置和私密文件已排除版本控制。示例文件可以提交，但不得写入真实 secret。
不要运行 `ansible-inventory --list` 并把输出发到工单，它可能展开 Vault 凭据。

必须替换：

- `hosts.yml` 中的 `10.20.30.41` 和实际 SSH 用户。
- `auth_servers.yml` 的 `system_admin_user` 和 `system_admin_public_keys`，必须与
  已验证的管理账号一致。
- `identity.yml` 中所有 `example.com`、证书路径、数据库、LDAP 配置和 VMP callback。
- Vault 的 `vault_keycloak_admin_user`、`vault_keycloak_admin_password`、
  `vault_keycloak_db_password`；启用 LDAP 时还需 `vault_keycloak_ldap_bind_credential`。

通用 production 示例默认启用 LDAP。尚未准备好目录时，明确设置
`keycloak_ldap_enabled: false`，不能让示例 FreeIPA 地址进入实际部署。
使用内部 CA 时，Keycloak 容器和 Ansible controller 都必须信任相应 CA；不要把
`keycloak_realm_validate_certs` 改为 false 来绕过生产证书错误。

内网 Docker 镜像可以覆盖 `docker_repository_base_url`、`docker_gpg_key_url` 和
经安全团队审核的 `docker_gpg_fingerprint`，但须提供 Noble 的 `amd64`/`arm64` 包。
不要将当前 EL9 lab inventory 的 CentOS 镜像地址用于 Ubuntu。
如需固定包版本，可在 `docker_packages` 中使用 APT 的 `package=version` 格式，
同时核对 Docker Engine、CLI、containerd、Buildx 和 Compose 的兼容组合。

## 5. 预检、部署和验证

先检查 SSH host key 指纹并通过正常 SSH 建立信任，不要关闭 HostKeyChecking。

```bash
../.venv-ansible/bin/ansible -i inventories/ubuntu/hosts.yml auth_servers \
  -m ansible.builtin.ping --ask-vault-pass
../.venv-ansible/bin/ansible-playbook -i inventories/ubuntu/hosts.yml \
  playbooks/preflight.yml --ask-vault-pass
../.venv-ansible/bin/ansible-playbook -i inventories/ubuntu/hosts.yml \
  playbooks/site.yml --syntax-check
../.venv-ansible/bin/ansible-playbook -i inventories/ubuntu/hosts.yml \
  playbooks/site.yml --ask-vault-pass
../.venv-ansible/bin/ansible-playbook -i inventories/ubuntu/hosts.yml \
  playbooks/verify.yml --ask-vault-pass
```

若初始 sudo 需要密码，添加 `--ask-become-pass`。预检验证系统、架构、账号、公钥和
UFW 配置及旧 Docker APT 源；Docker 冲突包检查在 Docker 安装角色中执行。`--syntax-check` 只验证
语法，不验证网络、包可用性或 Keycloak。首次全量 `--check` 不能替代真实 VM 测试，
因为未安装的包、签名密钥和容器尚不存在。

`verify.yml` 会检查 Ubuntu 服务、AppArmor、Compose 版本、issuer，以及 Keycloak
和可选本地 PostgreSQL 的 `running`/`healthy` 状态。它不把“输出中出现容器名字”
当成健康。外部 TLS 验证还要从浏览器和应用网络分别执行：

```bash
curl --fail --show-error \
  https://sso.example.com/realms/company/.well-known/openid-configuration
```

然后按照 [VMP 身份集成约定](https://github.com/gt28/vmp/blob/main/docs/identity-integration.md)配置客户端和身份投影，
用真实用户验证登录、MFA、退出和禁用用户。密码不传入 VMP 配置。

## 6. 安装、幂等性和重启验收

在隔离 Ubuntu VM 上完成：

1. 全新安装 `site.yml`，确认每个任务成功且容器健康。
2. 不改配置再执行一次 `site.yml`，要求 `changed=0`，保存回顾结果。
3. 测试 Code + S256 PKCE、应用 audience、LDAP 用户和授权边界。
4. 检查 `sshd -T`，保留原会话并尝试第二个公钥 SSH 会话。
5. 经批准重启测试 VM，恢复 SSH 后重新执行 `verify.yml` 和登录测试。
6. 验证数据库故障、CA 错误、端口 ACL、审计和备份恢复。

每次变更包源、基础镜像、内核或安全基线后重复这些检查。生产系统包更新由维护
策略管理；如允许角色执行更新，设置 `system_update_packages: true`。只有同时设置
`system_reboot_after_update: true` 且存在 `/var/run/reboot-required` 时，Ubuntu
分支才自动重启；未批准重启时，由运维跟进该标记。

## 7. 仓库测试

在 Ansible 目录执行：

```bash
../.venv-ansible/bin/python -m unittest discover -s tests -v
../.venv-ansible/bin/ansible-lint --profile production playbooks roles tests/*.yml inventories/ubuntu
```

离线测试覆盖实际 Ansible 条件和 Jinja 模板，不修改宿主机、不连接身份服务器。

GitHub Actions 的 **Identity Ubuntu 24.04 VM Smoke** 工作流由运维手动触发，在
一次性的 `ubuntu-24.04` hosted VM 上执行系统加固、Docker/Keycloak 安装、第二次
幂等部署、真实 HTTPS/PKCE 登录、禁用 password grant 检查和容器重启恢复。
它不会连接公司服务器，也不会自动执行公司主机重启或 LDAP 接入。

不得把 `tests/smoke-inventory.yml` 用在生产、共享服务器或 self-hosted runner 上。
smoke 的随机凭据和证书只留在一次性 runner 的 `.private` 中，不上传为 artifacts。
本次交付未运行该远程工作流；通过离线测试不等于已经通过 VM 安装验收。

## 8. 故障排查

| 现象 | 处理 |
| --- | --- |
| Unsupported operating system | 确认 `/etc/os-release` 是 Ubuntu 24.04，不删除系统版本断言 |
| UFW is enabled | 先迁移并审批防火墙策略，不自动停用 UFW |
| Conflicting packages found | 确认是否有 Kubernetes/现有容器，迁移后才批准卸载 |
| Docker APT key mismatch | 核对内网源、公钥和审核指纹，不使用 `trusted=yes` |
| AppArmor 检查失败 | 检查内核启动参数和宿主安全基线，按维护流程恢复 AppArmor |
| SSH 有效策略不符 | 检查更早的 Include/drop-in、主配置和 Match 块 |
| Docker 安装后旧容器异常 | 应用不应共用这个宿主机；依据迁移前备份和变更记录恢复 |
| HTTPS 本机成功、远端失败 | 检查上游 ACL、Docker 发布端口、DNS 和证书信任 |

SSO 的高可用、数据库 PITR、管理员访问隔离、告警、LDAP 和应急恢复仍遵循
[身份平台主部署手册](deployment.md)。增加 Ubuntu 支持不改变这些上线门槛。

## 参考依据

- [Docker Ubuntu 安装及防火墙注意事项](https://docs.docker.com/engine/install/ubuntu/)
- [Ubuntu AppArmor](https://documentation.ubuntu.com/server/how-to/security/apparmor/)
- [Ansible Compose CLI 插件要求](https://docs.ansible.com/ansible/latest/collections/community/docker/docker_compose_v2_module.html)
