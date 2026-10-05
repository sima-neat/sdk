#!/usr/bin/env bash
set -euo pipefail

readonly PACKAGECLOUD_KEY_URL="https://packagecloud.io/nE0sIghT/apt-mirror2/gpgkey"
readonly PACKAGECLOUD_KEY_FINGERPRINT="DDE9C7D7C3EEBA0B18758002D8DAB1FC88E4447F"
readonly PACKAGECLOUD_KEYRING="/etc/apt/keyrings/nE0sIghT_apt-mirror2-archive-keyring.gpg"
readonly PACKAGECLOUD_SOURCE="/etc/apt/sources.list.d/nE0sIghT_apt-mirror2.list"

if command -v apt-mirror2 >/dev/null; then
  apt-mirror2 --version
  exit 0
fi

sudo apt-get update
if ! apt-cache show apt-mirror2 >/dev/null 2>&1; then
  # apt-mirror2 is native in newer Ubuntu releases. Upstream publishes signed
  # Packagecloud builds for older supported releases where Ubuntu does not.
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != ubuntu ]]; then
    echo "apt-mirror2 is unavailable from the configured APT repositories on ${PRETTY_NAME:-this host}." >&2
    exit 1
  fi

  case "${VERSION_ID:-}" in
    22.04|24.04|26.04) ;;
    *)
      echo "Unsupported Ubuntu release for the apt-mirror2 fallback: ${VERSION_ID:-unknown}" >&2
      exit 1
      ;;
  esac

  packagecloud_dist="${VERSION_CODENAME:-}"
  if [[ -z "${packagecloud_dist}" ]]; then
    echo "Ubuntu VERSION_CODENAME is required to configure apt-mirror2." >&2
    exit 1
  fi

  temp_dir="$(mktemp -d)"
  trap 'rm -rf -- "${temp_dir}"' EXIT
  key_file="${temp_dir}/packagecloud.asc"
  keyring_file="${temp_dir}/packagecloud.gpg"
  source_file="${temp_dir}/apt-mirror2.list"

  curl --fail --silent --show-error --location \
    --output "${key_file}" "${PACKAGECLOUD_KEY_URL}"
  if ! gpg --batch --show-keys --with-colons "${key_file}" | \
    awk -F: '$1 == "fpr" {print $10}' | \
    grep -Fxq "${PACKAGECLOUD_KEY_FINGERPRINT}"; then
    echo "apt-mirror2 Packagecloud signing key fingerprint did not match." >&2
    exit 1
  fi
  gpg --batch --yes --dearmor --output "${keyring_file}" "${key_file}"

  printf '%s\n' \
    "deb [signed-by=${PACKAGECLOUD_KEYRING}] https://packagecloud.io/nE0sIghT/apt-mirror2/ubuntu/ ${packagecloud_dist} main" \
    >"${source_file}"
  sudo install -d -m 0755 /etc/apt/keyrings
  sudo install -m 0644 "${keyring_file}" "${PACKAGECLOUD_KEYRING}"
  sudo install -m 0644 "${source_file}" "${PACKAGECLOUD_SOURCE}"
  sudo apt-get update
fi

sudo env DEBIAN_FRONTEND=noninteractive \
  apt-get install -y --no-install-recommends apt-mirror2

# Ubuntu's native package exposes apt-mirror2. The upstream Packagecloud build
# retains its historical apt-mirror entry point, so normalize the executable
# name expected by the synchronization script.
if ! command -v apt-mirror2 >/dev/null && command -v apt-mirror >/dev/null; then
  if [[ -e /usr/local/bin/apt-mirror2 ]]; then
    echo "/usr/local/bin/apt-mirror2 exists but is not executable from PATH." >&2
    exit 1
  fi
  sudo ln -s "$(command -v apt-mirror)" /usr/local/bin/apt-mirror2
fi

apt-mirror2 --version
