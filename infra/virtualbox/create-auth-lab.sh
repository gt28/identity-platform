#!/usr/bin/env bash
set -euo pipefail

readonly VBOXMANAGE_DEFAULT="/Applications/VirtualBox.app/Contents/MacOS/VBoxManage"
readonly ISO_NAME_DEFAULT="Rocky-9.8-x86_64-boot.iso"
readonly ISO_URL_DEFAULT="https://mirrors.huaweicloud.com/rockylinux/9/isos/x86_64/${ISO_NAME_DEFAULT}"
readonly ISO_SHA256_DEFAULT="d6eeefdc8437c593d41a3150fcca4a734c55642ed472eecdda99720bb1370881"

VM_NAME="auth-lab"
VM_HOSTNAME="auth-lab.local"
VM_MEMORY_MB="6144"
VM_CPUS="4"
VM_DISK_MB="61440"
HOST_SSH_PORT="2222"
HOST_HTTPS_PORT="8443"
WAIT_SECONDS="3600"
VBOXMANAGE="${VBOXMANAGE:-${VBOXMANAGE_DEFAULT}}"
ISO_URL="${ISO_URL:-${ISO_URL_DEFAULT}}"
ISO_SHA256="${ISO_SHA256:-${ISO_SHA256_DEFAULT}}"
ISO_NAME="${ISO_NAME:-${ISO_NAME_DEFAULT}}"
ISO_CACHE_DIR="${ISO_CACHE_DIR:-${HOME}/VirtualBox ISOs}"
VM_BASE_DIR="${VM_BASE_DIR:-${HOME}/VirtualBox VMs}"
SSH_PUBLIC_KEY_FILE="${HOME}/.ssh/id_ed25519.pub"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KICKSTART_TEMPLATE="${SCRIPT_DIR}/rocky9-ks.cfg.tpl"

usage() {
  printf '%s\n' \
    "Usage: $0 [options]" \
    "  --ssh-public-key FILE   Public key injected during installation" \
    "  --vm-name NAME          Virtual machine name (default: auth-lab)" \
    "  --hostname FQDN         Guest hostname (default: auth-lab.local)" \
    "  --memory MB             Guest memory (default: 6144)" \
    "  --cpus COUNT            Guest vCPUs (default: 4)" \
    "  --disk MB               Virtual disk size (default: 61440)" \
    "  --ssh-port PORT         Host NAT port for guest SSH (default: 2222)" \
    "  --https-port PORT       Host NAT port for guest HTTPS (default: 8443)" \
    "  --wait-seconds SECONDS  Installation wait limit (default: 3600)"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --ssh-public-key)
      SSH_PUBLIC_KEY_FILE="$2"
      shift 2
      ;;
    --vm-name)
      VM_NAME="$2"
      shift 2
      ;;
    --hostname)
      VM_HOSTNAME="$2"
      shift 2
      ;;
    --memory)
      VM_MEMORY_MB="$2"
      shift 2
      ;;
    --cpus)
      VM_CPUS="$2"
      shift 2
      ;;
    --disk)
      VM_DISK_MB="$2"
      shift 2
      ;;
    --ssh-port)
      HOST_SSH_PORT="$2"
      shift 2
      ;;
    --https-port)
      HOST_HTTPS_PORT="$2"
      shift 2
      ;;
    --wait-seconds)
      WAIT_SECONDS="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

for numeric_value in \
  "${VM_MEMORY_MB}" \
  "${VM_CPUS}" \
  "${VM_DISK_MB}" \
  "${HOST_SSH_PORT}" \
  "${HOST_HTTPS_PORT}" \
  "${WAIT_SECONDS}"; do
  if [[ ! "${numeric_value}" =~ ^[0-9]+$ ]]; then
    printf 'Expected a positive integer, got: %s\n' "${numeric_value}" >&2
    exit 2
  fi
done

if [[ ! -x "${VBOXMANAGE}" ]]; then
  printf 'VBoxManage not found or not executable: %s\n' "${VBOXMANAGE}" >&2
  exit 1
fi

if [[ ! -r "${SSH_PUBLIC_KEY_FILE}" ]]; then
  printf 'SSH public key is not readable: %s\n' "${SSH_PUBLIC_KEY_FILE}" >&2
  exit 1
fi

if [[ ! -r "${KICKSTART_TEMPLATE}" ]]; then
  printf 'Kickstart template is not readable: %s\n' "${KICKSTART_TEMPLATE}" >&2
  exit 1
fi

if "${VBOXMANAGE}" showvminfo "${VM_NAME}" >/dev/null 2>&1; then
  printf 'Refusing to overwrite existing VM: %s\n' "${VM_NAME}" >&2
  exit 1
fi

mkdir -p "${ISO_CACHE_DIR}" "${VM_BASE_DIR}"
ISO_PATH="${ISO_CACHE_DIR}/${ISO_NAME}"

if [[ ! -f "${ISO_PATH}" ]]; then
  printf 'Downloading %s\n' "${ISO_URL}"
  curl \
    --fail \
    --location \
    --retry 3 \
    --continue-at - \
    --output "${ISO_PATH}.part" \
    "${ISO_URL}"
  mv "${ISO_PATH}.part" "${ISO_PATH}"
fi

ACTUAL_ISO_SHA256="$(shasum -a 256 "${ISO_PATH}" | awk '{print $1}')"
if [[ "${ACTUAL_ISO_SHA256}" != "${ISO_SHA256}" ]]; then
  printf 'ISO checksum mismatch for %s\n' "${ISO_PATH}" >&2
  printf 'Expected: %s\nActual:   %s\n' "${ISO_SHA256}" "${ACTUAL_ISO_SHA256}" >&2
  exit 1
fi

TASK_TMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/auth-lab-bootstrap.XXXXXX")"
cleanup() {
  rm -rf -- "${TASK_TMP_DIR}"
}
trap cleanup EXIT

INSTALL_PASSWORD_FILE="${TASK_TMP_DIR}/install-password"
RENDERED_KICKSTART="${TASK_TMP_DIR}/rocky9-ks.cfg"
umask 077
openssl rand -base64 36 >"${INSTALL_PASSWORD_FILE}"
SSH_PUBLIC_KEY="$(tr -d '\r\n' <"${SSH_PUBLIC_KEY_FILE}")"
awk -v public_key="${SSH_PUBLIC_KEY}" \
  '{gsub(/@@ANSIBLE_SSH_PUBLIC_KEY@@/, public_key); print}' \
  "${KICKSTART_TEMPLATE}" >"${RENDERED_KICKSTART}"

VM_DIR="${VM_BASE_DIR}/${VM_NAME}"
VM_DISK_PATH="${VM_DIR}/${VM_NAME}.vdi"

"${VBOXMANAGE}" createvm \
  --name "${VM_NAME}" \
  --ostype RedHat9_64 \
  --basefolder "${VM_BASE_DIR}" \
  --register

"${VBOXMANAGE}" modifyvm "${VM_NAME}" \
  --memory "${VM_MEMORY_MB}" \
  --cpus "${VM_CPUS}" \
  --ioapic on \
  --acpi on \
  --rtcuseutc on \
  --paravirtprovider kvm \
  --nestedpaging on \
  --largepages on \
  --boot1 dvd \
  --boot2 disk \
  --boot3 none \
  --boot4 none \
  --graphicscontroller vmsvga \
  --vram 16 \
  --nic1 nat \
  --nictype1 82540EM \
  --cableconnected1 on \
  --natpf1 "ssh,tcp,,${HOST_SSH_PORT},,22" \
  --natpf1 "keycloak,tcp,,${HOST_HTTPS_PORT},,443"

"${VBOXMANAGE}" createmedium disk \
  --filename "${VM_DISK_PATH}" \
  --size "${VM_DISK_MB}" \
  --format VDI

"${VBOXMANAGE}" storagectl "${VM_NAME}" \
  --name SATA \
  --add sata \
  --controller IntelAhci \
  --bootable on

"${VBOXMANAGE}" storageattach "${VM_NAME}" \
  --storagectl SATA \
  --port 0 \
  --device 0 \
  --type hdd \
  --medium "${VM_DISK_PATH}"

"${VBOXMANAGE}" storagectl "${VM_NAME}" \
  --name IDE \
  --add ide \
  --controller PIIX4 \
  --bootable on

"${VBOXMANAGE}" storageattach "${VM_NAME}" \
  --storagectl IDE \
  --port 0 \
  --device 0 \
  --type dvddrive \
  --medium emptydrive

"${VBOXMANAGE}" unattended install "${VM_NAME}" \
  --iso="${ISO_PATH}" \
  --user=ansible \
  --password-file="${INSTALL_PASSWORD_FILE}" \
  --full-user-name="Ansible Automation" \
  --hostname="${VM_HOSTNAME}" \
  --locale=en_US \
  --country=CN \
  --time-zone=Asia/Shanghai \
  --package-selection-adjustment=minimal \
  --script-template="${RENDERED_KICKSTART}" \
  --extra-install-kernel-parameters="inst.ks=cdrom:/ks.cfg" \
  --no-install-additions \
  --start-vm=headless

printf 'Waiting for the guest SSH handshake on 127.0.0.1:%s\n' "${HOST_SSH_PORT}"
STARTED_AT="$(date +%s)"
while ! ssh-keyscan -T 5 -p "${HOST_SSH_PORT}" 127.0.0.1 2>/dev/null | grep -q '^\[127\.0\.0\.1\]'; do
  NOW="$(date +%s)"
  if (( NOW - STARTED_AT >= WAIT_SECONDS )); then
    printf 'Timed out waiting for the guest SSH service. VM was left intact for diagnosis.\n' >&2
    exit 1
  fi
  sleep 10
done

printf 'VM %s is ready. SSH through host port %s; HTTPS will use host port %s.\n' \
  "${VM_NAME}" "${HOST_SSH_PORT}" "${HOST_HTTPS_PORT}"
