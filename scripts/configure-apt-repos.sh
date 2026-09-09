#!/usr/bin/env bash

set -euo pipefail

base_sdk_version="${1:?Usage: configure-apt-repos.sh BASE_SDK_VERSION [PATTERNS_FILE]}"
patterns_file="${2:-/usr/local/share/sima-sdk/platform-package-patterns.txt}"
sdk_apt_channel="${SDK_APT_CHANNEL:-release}"
sdk_platform_repository="${SDK_PLATFORM_REPOSITORY:-}"
sdk_apt_origin="${SDK_APT_ORIGIN:-}"
sdk_fallback_repository=""
sdk_fallback_origin=""

case "${sdk_apt_channel}" in
  release)
    sdk_platform_repository="${sdk_platform_repository:-https://repo.sima.ai/elxr/deb/release}"
    sdk_apt_origin="${sdk_apt_origin:-repo.sima.ai}"
    ;;
  daily)
    sdk_platform_repository="${sdk_platform_repository:-https://debian.neat.sima.ai/daily}"
    sdk_apt_origin="${sdk_apt_origin:-debian.neat.sima.ai}"
    ;;
  pre-release)
    sdk_platform_repository="${sdk_platform_repository:-https://debian.neat.sima.ai/pre-release}"
    sdk_apt_origin="${sdk_apt_origin:-debian.neat.sima.ai}"
    # The pre-release mirror is an overlay, not a complete replacement for the
    # release repository. Some SDK-pinned dependencies, including Modalix UAPI
    # headers, intentionally remain available only from the release channel.
    sdk_fallback_repository="https://repo.sima.ai/elxr/deb/release"
    sdk_fallback_origin="repo.sima.ai"
    ;;
  *)
    echo "Unsupported SDK_APT_CHANNEL: ${sdk_apt_channel}" >&2
    exit 1
    ;;
esac

if [[ ! -f "${patterns_file}" ]]; then
  echo "Platform package patterns file not found: ${patterns_file}" >&2
  exit 1
fi

if [[ "${sdk_apt_channel}" == daily ]]; then
  cat > /etc/apt/sources.list.d/elxr.list <<EOF
deb [arch=arm64 trusted=yes] ${sdk_platform_repository} agate non-free
EOF
  cat > /etc/apt/sources.list.d/debian-target.list <<'EOF'
deb [arch=arm64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian trixie main
deb [arch=arm64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian trixie-updates main
deb [arch=arm64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian-security trixie-security main
EOF
  cat > /etc/apt/preferences.d/stable.pref <<EOF
Package: *
Pin: origin "${sdk_apt_origin}"
Pin-Priority: 100

Package: *
Pin: origin "deb.debian.org"
Pin-Priority: 100
EOF
  # Agate components have independent versions. Only Palette equals the
  # selected platform version; the downloader resolves component versions.
  cat > /etc/apt/preferences.d/simaai-sdk-version.pref <<EOF
Package: simaai-palette-modalix
Pin: version ${base_sdk_version}
Pin-Priority: 1001

Package: simaai-palette-modalix
Pin: version *
Pin-Priority: -1
EOF
  exit 0
fi

wget -qO - https://mirror.elxr.dev/elxr/public.gpg | gpg --dearmor -o /etc/apt/trusted.gpg.d/elxr.gpg
wget --no-check-certificate -O - https://repo.sima.ai/elxr/deb/simaai.gpg | gpg --dearmor > /etc/apt/trusted.gpg.d/simaai.gpg

chmod 644 /etc/apt/trusted.gpg.d/elxr.gpg \
          /etc/apt/trusted.gpg.d/simaai.gpg

host_id=""
if [[ -r /etc/os-release ]]; then
  # shellcheck disable=SC1091
  . /etc/os-release
  host_id="${ID:-}"
fi

cat > /etc/apt/sources.list.d/elxr.list <<EOF
deb [signed-by=/etc/apt/trusted.gpg.d/elxr.gpg] https://mirror.elxr.dev/elxr aria main
deb [trusted=yes] ${sdk_platform_repository} bookworm non-free  # simaai ${sdk_apt_channel} repo
EOF

if [[ -n "${sdk_fallback_repository}" ]]; then
  cat >> /etc/apt/sources.list.d/elxr.list <<EOF
deb [trusted=yes] ${sdk_fallback_repository} bookworm non-free  # simaai release fallback
EOF
fi

if [[ "${host_id}" == "ubuntu" ]]; then
  cat > /etc/apt/sources.list.d/debian-target.list <<'EOF'
deb [arch=arm64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian bookworm main
deb [arch=arm64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian bookworm-updates main
deb [arch=arm64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg] http://deb.debian.org/debian-security bookworm-security main
EOF

  cat > /etc/apt/preferences.d/stable.pref <<EOF
Package: *
Pin: origin "${sdk_apt_origin}"
Pin-Priority: 100

Package: *
Pin: origin "mirror.elxr.dev"
Pin-Priority: 100

Package: *
Pin: origin "deb.debian.org"
Pin-Priority: 100

EOF

  if [[ -n "${sdk_fallback_origin}" ]]; then
    cat >> /etc/apt/preferences.d/stable.pref <<EOF
Package: *
Pin: origin "${sdk_fallback_origin}"
Pin-Priority: 100

EOF
  fi
else
  cat > /etc/apt/preferences.d/stable.pref <<EOF
Package: *
Pin: origin "${sdk_apt_origin}"
Pin-Priority: 999
EOF

  if [[ -n "${sdk_fallback_origin}" ]]; then
    cat >> /etc/apt/preferences.d/stable.pref <<EOF

Package: *
Pin: origin "${sdk_fallback_origin}"
Pin-Priority: 100
EOF
  fi
fi

platform_packages="$(
  sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "${patterns_file}" |
    tr '\n' ' ' |
    sed 's/[[:space:]]*$//'
)"

cat > /etc/apt/preferences.d/simaai-sdk-version.pref <<EOF
Package: ${platform_packages}
Pin: version ${base_sdk_version}
Pin-Priority: 1001

Package: ${platform_packages}
Pin: version *
Pin-Priority: -1
EOF
