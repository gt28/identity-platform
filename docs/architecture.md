# Enterprise SSO Architecture

Status: deployment boundary established; production HA and directory-specific
integration remain environment gates.  
Last updated: 2026-09-07

## System boundary

```text
LDAP / Active Directory
        |
        v
Enterprise Identity Platform
Keycloak + MFA + OIDC/SAML + audit
        |
        +-- VMP
        +-- GitLab
        +-- Private cloud
        +-- Bastion host
        +-- Future internal systems
```

LDAP/AD is the authoritative workforce directory for employee identity,
employment state and organizational attributes. Keycloak federates those
identities, applies authentication policy and issues application-specific
tokens or assertions. Keycloak is not the authoritative store for VMP assets,
Findings, approvals or other business authorization data.

## Ownership

Source and CI are independent in
[gt28/identity-platform](https://github.com/gt28/identity-platform).
[gt28/vmp](https://github.com/gt28/vmp) consumes OIDC and the documented identity
projection contract. No parent checkout or submodule is required to deploy or
test either repository. Local lab CA and identity manifests are ignored runtime
artifacts, transferred through explicit paths rather than tracked in Git.

| Concern | Owner |
| --- | --- |
| Joiner/mover/leaver identity | LDAP/AD and IAM process |
| Login, MFA, recovery and SSO sessions | Identity platform |
| OIDC/SAML clients and claims | Identity platform with application owner approval |
| VMP tenant, roles and resource scopes | VMP |
| GitLab projects/groups and repository permissions | GitLab |
| Cloud projects/tenants and infrastructure permissions | Cloud platform |
| Bastion targets and command authorization | Bastion platform |

Central groups may be used as coarse entitlement inputs, but every relying
system must enforce its own least-privilege authorization. A single universal
"administrator" role must not be propagated to every application.

## Trust model

- Each relying system has a unique client ID, redirect URI allowlist and
  audience.
- Browser applications use Authorization Code with S256 PKCE and no client
  secret.
- Server-side applications use confidential clients with independently rotated
  secrets or private-key authentication.
- Production issuers, authorization endpoints and JWKS endpoints use trusted
  HTTPS.
- Tokens contain the minimum approved claims. Passwords and LDAP bind
  credentials never enter relying applications.
- Client registrations, realm policy, LDAP federation and protocol mappers are
  managed declaratively and reviewed as code.

## Availability and recovery

### Host operating systems

Ubuntu Server 24.04 LTS is the primary target for the company environment;
Enterprise Linux 9 remains supported. Package installation and service names
are OS-specific tasks beneath the same roles; realm, LDAP and client contracts
are shared. Unknown distributions and versions fail before host mutations.

Ubuntu uses Noble APT with a fingerprint-verified, repository-scoped Docker key,
AppArmor, `ssh` and `chrony`; EL9 retains signed RPM packages, SELinux, `sshd`
and `chronyd`. Ubuntu bind mounts omit SELinux relabel flags. Firewalld remains
the host firewall manager on both families; an enabled Ubuntu UFW configuration
is an explicit migration gate, not something automation silently disables.
Docker-published port access requires separate upstream/forwarding policy review.

SSH hardening requires an existing non-root sudo account and approved keys.
Ubuntu cloud-init configuration precedence is handled by an early managed drop-in
and effective-policy validation. Existing Ubuntu container packages are not
removed without explicit operator approval. Package updates/reboots are opt-in
in the Ubuntu inventory and do not share the identity release lifecycle.

Support evidence has two levels: offline expression/template regression tests
and an opt-in real Ubuntu VM installation/PKCE/idempotence/restart workflow.
Company host reboot, LDAP and production security acceptance remain required;
static validation must not be presented as a production deployment test.
See [Ubuntu deployment](ubuntu-24.04.md).

### Production service

The included Compose automation is a hardened single-node baseline. A company
SSO production service additionally requires multiple Keycloak instances,
tested load-balancer and proxy behavior, shared encrypted PostgreSQL with PITR,
cross-zone failure planning, rolling upgrade tests, session behavior tests,
backups, monitoring and an emergency access procedure.

Loss of SSO affects every connected system. Its SLO, incident response,
maintenance window and recovery exercises must therefore be owned independently
from any one application.
