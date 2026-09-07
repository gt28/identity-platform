# SSO Client Onboarding

Last updated: 2026-09-05

Every system is registered independently. Do not clone the VMP client or reuse
its secret for GitLab, cloud platforms, bastion hosts or automation.

## Required intake

The application owner must provide:

- application name, technical owner and security owner;
- environment and exact HTTPS redirect/logout URIs;
- protocol support: OIDC preferred, SAML when required;
- browser/public or server/confidential client type;
- expected audience and required claims;
- group/role mapping proposal and application-side authorization owner;
- session/logout requirements and a non-production test plan.

## Registration rules

1. Assign a unique client ID per application and environment.
2. Allow only exact redirect and origin values; wildcards require documented
   justification.
3. Use S256 PKCE for public browser clients.
4. Store confidential secrets in Ansible Vault or the platform secret manager.
5. Emit only approved claims and an application-specific audience.
6. Test login, logout, disabled users, removed groups, MFA and expired sessions.
7. Record the client owner, review date and decommission procedure.

## Declarative OIDC registry

The `identity_realm` Ansible role consumes `keycloak_oidc_clients`. VMP is the
first registered client in the example inventory. A confidential application
uses the same schema, but its secret must be supplied by Vault:

```yaml
keycloak_oidc_clients:
  - client_id: internal-system-prod
    name: Internal system production
    owner: Internal system team
    environment: production
    public_client: false
    client_secret: "{{ vault_internal_system_oidc_secret }}"
    redirect_uris:
      - https://system.example.com/oauth/callback
    post_logout_redirect_uris:
      - https://system.example.com/*
    protocol_mappers: []
```

Product-specific GitLab, private-cloud and bastion settings must be documented
and validated against the exact deployed product/version before a client entry
is activated. The platform intentionally provides no placeholder secrets or
unverified role mappings.

## VMP contract

VMP expects:

- issuer: the exact enterprise realm issuer;
- audience: `vmp-api` unless deliberately changed on both sides;
- public client: `vmp-spa` using Authorization Code with S256 PKCE;
- standard identity claims: `sub`, optional `email` and display name;
- `organization_id`: immutable tenant identifier used to locate the VMP
  organization projection.

VMP stores the issuer/subject projection and its own RBAC assignments. It does
not store the Keycloak password, refresh token, LDAP password or MFA secret.
