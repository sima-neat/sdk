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

if [[ "${sdk_apt_channel}" == daily || "${base_sdk_version}" == 3.* ]]; then
  platform_source_options="arch=arm64 trusted=yes"
  if [[ "${sdk_apt_channel}" == release ]]; then
    wget -qO - https://repo.sima.ai/elxr/deb/simaai.gpg | \
      gpg --dearmor > /etc/apt/trusted.gpg.d/simaai.gpg
    chmod 644 /etc/apt/trusted.gpg.d/simaai.gpg
    platform_source_options="arch=arm64 signed-by=/etc/apt/trusted.gpg.d/simaai.gpg"
  fi
  cat > /etc/apt/sources.list.d/elxr.list <<EOF
deb [${platform_source_options}] ${sdk_platform_repository} agate non-free
EOF
  debian_source_options="arch=arm64 signed-by=/usr/share/keyrings/debian-archive-keyring.gpg"
  debian_archive="http://deb.debian.org/debian"
  debian_security_archive="http://deb.debian.org/debian-security"
  if [[ "${sdk_apt_channel}" == release ]]; then
    # A release sysroot keeps the Debian versions it was built from, but the
    # live archive serves only the newest version of each package. Read the
    # archive as it was when this SDK first resolved it, so every version in
    # the sysroot stays downloadable.
    snapshot_file=/usr/local/share/sima-sdk/debian-snapshot
    if [[ ! -s "${snapshot_file}" ]]; then
      mkdir -p "$(dirname "${snapshot_file}")"
      for archive in debian debian-security; do
        suites="trixie trixie-updates"
        [[ "${archive}" == debian ]] || suites="trixie-security"
        at="$(date -u +%Y%m%dT%H%M%SZ)"
        snapshot=""
        # The archive redirects any time to the snapshot that was current then.
        # It can list a new snapshot before it serves that snapshot's files, so
        # step back until one serves the Release file of every suite used here.
        for _ in {1..12}; do
          location="$(curl -fsS --retry 3 -o /dev/null -w '%{redirect_url}' \
            "https://snapshot.debian.org/archive/${archive}/${at}/")"
          [[ "${location}" =~ /archive/${archive}/([0-9]{8}T[0-9]{6}Z)/$ ]] || break
          at="${BASH_REMATCH[1]}"
          snapshot="${at}"
          for suite in ${suites}; do
            curl -fsSL -o /dev/null \
              "https://snapshot.debian.org/archive/${archive}/${at}/dists/${suite}/InRelease" || snapshot=""
          done
          [[ -z "${snapshot}" ]] || break
          at="$(date -u -d "${at:0:4}-${at:4:2}-${at:6:2} ${at:9:2}:${at:11:2}:${at:13:2} UTC 1 second ago" \
            +%Y%m%dT%H%M%SZ)"
        done
        if [[ -z "${snapshot}" ]]; then
          echo "Cannot resolve a ${archive} snapshot that serves its Release files" >&2
          exit 1
        fi
        printf '%s=%s\n' "${archive}" "${snapshot}"
      done > "${snapshot_file}.tmp"
      mv "${snapshot_file}.tmp" "${snapshot_file}"
    fi
    debian_snapshot="$(sed -n 's/^debian=//p' "${snapshot_file}")"
    debian_security_snapshot="$(sed -n 's/^debian-security=//p' "${snapshot_file}")"
    if [[ ! "${debian_snapshot}" =~ ^[0-9]{8}T[0-9]{6}Z$ || \
          ! "${debian_security_snapshot}" =~ ^[0-9]{8}T[0-9]{6}Z$ ]]; then
      echo "Invalid Debian snapshot record: ${snapshot_file}" >&2
      exit 1
    fi
    # Snapshot Release files are past their Valid-Until date by design.
    debian_source_options+=" check-valid-until=no"
    debian_archive="https://snapshot.debian.org/archive/debian/${debian_snapshot}"
    debian_security_archive="https://snapshot.debian.org/archive/debian-security/${debian_security_snapshot}"
  fi
  cat > /etc/apt/sources.list.d/debian-target.list <<EOF
deb [${debian_source_options}] ${debian_archive} trixie main
deb [${debian_source_options}] ${debian_archive} trixie-updates main
deb [${debian_source_options}] ${debian_security_archive} trixie-security main
EOF
  cat > /etc/apt/preferences.d/stable.pref <<EOF
Package: *
Pin: origin "${sdk_apt_origin}"
Pin-Priority: 100

Package: *
Pin: origin "deb.debian.org"
Pin-Priority: 100

Package: *
Pin: origin "snapshot.debian.org"
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
