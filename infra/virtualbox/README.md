# VirtualBox lab bootstrap

This directory contains the only host-specific part of the authentication lab.
It creates a new VirtualBox VM, verifies the installation ISO, and injects the
controller SSH public key during Kickstart. It does not configure Keycloak or
the post-install Linux operating system; Ansible owns that state.

The default ISO is the Rocky Linux 9.8 boot image from a mirror listed by the
official Rocky mirror manager. Its SHA-256 value is pinned to the value in the
Rocky project's per-image checksum file. Kickstart installs the core package
set from the same mirror. This avoids the inconsistent size and checksum that
the Rocky 9.8 minimal-image checksum file reported during this deployment.
Ansible updates the installed host before it installs services.

The download URL, image name, checksum, ISO cache directory, VM base directory,
and `VBoxManage` path can all be overridden with the matching uppercase
environment variables.

Run this on the Intel Mac host:

```bash
./create-auth-lab.sh --ssh-public-key ~/.ssh/id_ed25519.pub
```

Defaults:

- VM: `auth-lab`, 4 vCPU, 6144 MB memory, 60 GB dynamically allocated disk
- network: VirtualBox NAT
- SSH: host TCP 2222 to guest TCP 22
- Keycloak HTTPS: host TCP 8443 to guest TCP 443

The script refuses to overwrite an existing VM. A failed installation is left
intact so its VirtualBox and Anaconda logs can be inspected.
