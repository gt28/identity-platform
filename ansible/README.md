# Enterprise identity-platform automation

This directory owns Linux and Keycloak configuration for the independent
company SSO platform after the operating system is installed. The roles
support Ubuntu Server 24.04 LTS and Enterprise Linux 9 hosts reachable by SSH;
the VirtualBox bootstrap in `../infra/virtualbox` is only an EL9 lab provisioner.

For the company Ubuntu environment, start with the dedicated
[Ubuntu 24.04 deployment guide](../docs/ubuntu-24.04.md). It explains the inventory,
initial SSH/sudo prerequisites, AppArmor, firewalld/UFW boundary, Noble APT trust,
safe handling of conflicting container packages, and real-host acceptance tests.

The end-to-end lab, production, LDAP, verification, recovery, rotation and
upgrade procedure is in [`../docs/deployment.md`](../docs/deployment.md). This
file documents the Ansible implementation and its direct commands.

## Roles

- `system_baseline`: optional package updates, SELinux on EL9 or AppArmor on Ubuntu, chrony,
  firewalld, auditd, rsyslog, SSH key enforcement, password locking, and SSH
  hardening.
- `docker_engine`: Docker's signed RPM or Noble APT repository, Docker Engine and Compose,
  daemon log rotation, and explicit operator access.
- `keycloak`: direct HTTPS, an optimized Keycloak image, optional local
  PostgreSQL, external PostgreSQL support, resource limits, read-only container
  filesystem, and trust anchors.
- `identity_realm`: company realm security policy, brute-force protection,
  audit events, TOTP policy, a declarative registry of isolated OIDC clients,
  token claim mappers, optional read-only LDAP federation over LDAPS or
  StartTLS, and an opt-in simulated company directory.

## Controller setup

Use Python 3.12 or newer on the controller. From the `identity-platform`
directory:

```bash
python3 -m venv .venv-ansible
.venv-ansible/bin/pip install -r ansible/requirements-controller.txt
cd ansible
../.venv-ansible/bin/ansible-galaxy collection install \
  -r requirements.yml -p .collections
```

The lab inventory generates independent random Keycloak and database passwords
under ignored `ansible/.private/` files. It never reuses a host login password.

## Lab deployment

Create the VM on the Intel Mac as described in
[`infra/virtualbox/README.md`](../infra/virtualbox/README.md), then run:

```bash
cd ansible
ansible-playbook playbooks/site.yml
ansible-playbook playbooks/verify.yml
```

The checked-in lab inventory connects to `192.168.2.144:2222` and advertises
Keycloak at `https://192.168.2.144:8443/realms/company`. Its self-signed service
certificate is exported to `ansible/.private/auth-lab.crt` for controller-side
verification.
The lab-only repository and container image mirror overrides can be removed on
networks that reach the upstream registries directly.

### Simulated 50-person company

The demo company is deliberately separate from `site.yml` so sample accounts
cannot appear in production by accident:

```bash
cd ansible
ansible-playbook playbooks/demo_company.yml
```

The playbook creates one company group, department subgroups, and 50 Keycloak
users with independent random initial passwords. VMP role values are used only
to create a password-free application projection manifest; they are not stored
as workforce attributes in Keycloak. The manifest is written to
`ansible/.private/demo-company-identities.json`; passwords remain in ignored
files under `ansible/.private/demo-company-passwords/`.

The optional demo exports a password-free VMP identity projection manifest as
one application adapter. From a separate VMP checkout alongside this repository,
provision those projections without sending identity-provider passwords to VMP:

```bash
docker compose -f docker-compose.yml -f docker-compose.auth-lab.yml run --rm -T \
  backend python -m app.cli.provision_company --input - \
  < ../identity-platform/ansible/.private/demo-company-identities.json
```

The CLI is idempotent. It creates the organization, maps Keycloak subject IDs to
VMP users, and assigns the declared built-in VMP roles. It never reads or stores
an identity-provider password.

Run a protocol-level login smoke test without disabling certificate validation:

```bash
backend/.venv/bin/python scripts/verify_oidc_login.py \
  --issuer https://192.168.2.144:8443/realms/company \
  --client-id vmp-spa --audience vmp-api \
  --organization-id northstar-tech \
  --redirect-uri http://127.0.0.1:3000/auth/callback \
  --ca-file ../identity-platform/ansible/.private/auth-lab.crt \
  --username vmp.admin \
  --password-file ../identity-platform/ansible/.private/demo-company-passwords/vmp.admin \
  --vmp-base-url http://127.0.0.1:3000
```

The script exercises the same Authorization Code plus PKCE exchange used by the
browser and then calls VMP `/api/v1/identity/me`. It never prints the password,
authorization code, or tokens.

## Production inventory

Copy the examples to active inventory files and replace every environment value:

```bash
cp inventories/production/hosts.example.yml inventories/production/hosts.yml
cp inventories/production/group_vars/auth_servers.example.yml \
  inventories/production/group_vars/auth_servers.yml
mkdir -p inventories/production/group_vars/all
ansible-vault create inventories/production/group_vars/all/vault.yml
```

Define `vault_keycloak_admin_user`, `vault_keycloak_admin_password`,
`vault_keycloak_db_password`, and `vault_keycloak_ldap_bind_credential` in the
Vault file. Then deploy and verify with the production inventory:

```bash
ansible-playbook -i inventories/production/hosts.yml playbooks/site.yml \
  --ask-vault-pass
ansible-playbook -i inventories/production/hosts.yml playbooks/verify.yml \
  --ask-vault-pass
```

Add each relying application to `keycloak_oidc_clients`; never reuse VMP's
client ID or secret. See `../docs/client-onboarding.md` for the intake and
authorization-boundary rules.

Production must provide a trusted TLS certificate and key, encrypted external
PostgreSQL with backups and point-in-time recovery, DNS, monitoring, and secret
rotation. The included Compose deployment is a hardened single-node baseline,
not a complete highly available topology. Before enabling distributed cache,
design and test cross-host JGroups traffic, load balancing, failure-domain
placement, graceful drain, and database-backed discovery.

LDAP remains disabled until the following values are supplied:

- directory product/version and redundant LDAPS hostnames or StartTLS endpoint;
- trusted CA chain, DNS reachability, and allowed network path from Keycloak;
- base DN, users DN, optional groups DN, and any required LDAP search filter;
- dedicated read-only bind DN and secret, never a directory administrator;
- username, RDN, immutable UUID, email, first-name, last-name, department, and
  organization/tenant attributes plus user object classes;
- group membership attribute/schema and approved coarse entitlement claims;
- import/edit mode, full and changed-user sync intervals, deletion/disable
  behavior, collision policy, expected user count, and one non-privileged test
  account.

If the directory has no stable tenant attribute, agree on a governed tenant
mapping before enabling federation. VMP tokens must still contain the exact
`organization_id` used by the VMP organization projection; other applications
should receive only the claims defined in their own onboarding contract.

## Quality gates

```bash
python -m unittest discover -s tests -v
ansible-playbook playbooks/preflight.yml --syntax-check
ansible-playbook playbooks/site.yml --syntax-check
ansible-lint
```

`playbooks/verify.yml` checks master and application discovery documents,
advertised HTTPS issuers, running/healthy Compose services, and Ubuntu security
services. A second unchanged `site.yml` run should report `changed=0`.
The root `identity-ubuntu-smoke.yml` workflow performs a real deployment, PKCE
login and container restart on a disposable Ubuntu 24.04 VM when manually run.
