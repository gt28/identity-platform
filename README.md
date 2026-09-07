# Enterprise Identity Platform

This is the independent company SSO repository:
[gt28/identity-platform](https://github.com/gt28/identity-platform).
It has its own Git history, CI pipeline, deployment configuration and release
boundary. [VMP](https://github.com/gt28/vmp) is a relying application, not the
owner of this infrastructure.

The platform provides:

- Keycloak as the OIDC/SAML identity broker and SSO session authority;
- LDAP or Active Directory federation for workforce identity lifecycle;
- MFA, passwordless/authentication policy, brute-force protection and login
  auditing;
- one isolated client registration for every relying system;
- hardened Ubuntu Server 24.04 LTS and Enterprise Linux 9 automation through Ansible;
- a development authentication lab that is separate from application-local
  demo identity providers.

VMP, GitLab, private-cloud platforms, bastion hosts and future applications are
clients of this platform. They must not share client IDs or client secrets.
Application-specific permissions remain in each application; the identity
platform supplies verified identity and broadly governed group claims.

## Directory layout

```text
identity-platform/
├── ansible/             Keycloak, realm, LDAP and client automation
├── docs/                Architecture and client-onboarding contracts
└── infra/virtualbox/    Optional lab VM bootstrap
```

Start with [architecture.md](docs/architecture.md), follow the complete
[deployment guide](docs/deployment.md), then use
[client-onboarding.md](docs/client-onboarding.md) for every relying system.
Ansible implementation details remain in [ansible/README.md](ansible/README.md).

Ubuntu is the recommended host for the current company environment. Use the
[Ubuntu 24.04 deployment guide](docs/ubuntu-24.04.md) and its dedicated inventory.
Other Ubuntu versions and openEuler are not yet supported. Offline compatibility
tests and a manually triggered disposable Ubuntu VM smoke workflow are included;
production host acceptance is a separate deployment gate.

## Repository ownership

Clone and operate this repository independently of VMP:

```bash
git clone https://github.com/gt28/identity-platform.git
cd identity-platform
```

There is no VMP submodule or parent-repository dependency. Both repositories can
be cloned into sibling directories for the optional local SSO lab integration.
Before the first shared SSO release, enforce:

- identity-team CODEOWNERS and protected production environments;
- independent security review, image promotion and maintenance windows;
- secrets from Vault or a platform secret manager, never application `.env`
  files;
- independent PostgreSQL backup/PITR, restore drills and availability targets;
- centralized monitoring and security-event export.

`.github/workflows/ci.yml` runs this repository's syntax, compatibility and
production lint checks. The Ubuntu VM smoke workflow is separate and manually
triggered. After installing the controller dependencies, `make syntax`,
`make lint` and `make test` run local checks. The current CODEOWNERS entry is
`@gt28`; replace it with the real IAM/Infrastructure team and enable required
reviews through repository settings. Neither team access nor branch protection
is automatically provisioned by these files.

The local `docker-compose.development.yml` Keycloak remains in the VMP repository solely for
offline development. It is not an installation method for this platform.
