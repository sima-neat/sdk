#!/usr/bin/env bash

set -euo pipefail

base_sdk_version="${1:?Usage: configure-apt-repos.sh BASE_SDK_VERSION [PATTERNS_FILE]}"
patterns_file="${2:-/usr/local/share/sima-sdk/platform-package-patterns.txt}"

if [[ ! -f "${patterns_file}" ]]; then
  echo "Platform package patterns file not found: ${patterns_file}" >&2
  exit 1
fi

wget -qO - https://mirror.elxr.dev/elxr/public.gpg | gpg --dearmor -o /etc/apt/trusted.gpg.d/elxr.gpg
wget -qO - https://packages.fluentbit.io/fluentbit.key | gpg --dearmor > /etc/apt/trusted.gpg.d/fluentbit.gpg
wget --no-check-certificate -O - https://repo.sima.ai/elxr/deb/simaai.gpg | gpg --dearmor > /etc/apt/trusted.gpg.d/simaai.gpg

chmod 644 /etc/apt/trusted.gpg.d/elxr.gpg \
          /etc/apt/trusted.gpg.d/fluentbit.gpg \
          /etc/apt/trusted.gpg.d/simaai.gpg

cat > /etc/apt/sources.list.d/elxr.list <<'EOF'
deb [signed-by=/etc/apt/trusted.gpg.d/elxr.gpg] https://mirror.elxr.dev/elxr aria main
deb [signed-by=/etc/apt/trusted.gpg.d/fluentbit.gpg] https://packages.fluentbit.io/debian/bookworm bookworm main
deb [trusted=yes] https://repo.sima.ai/elxr/deb/release bookworm non-free  # simaai repo
EOF

cat > /etc/apt/preferences.d/stable.pref <<'EOF'
Package: *
Pin: origin "repo.sima.ai/elxr"
Pin-Priority: 999
EOF

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
