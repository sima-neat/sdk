#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SYSROOT_COMMAND="${ROOT_DIR}/scripts/sysroot.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

if [[ "$(id -u)" -eq 0 ]]; then
  fail "this test must run as an unprivileged user"
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

# This fixture exercises the legacy overlay format, independent of the host image.
export SDK_RELEASE_FILE="${tmpdir}/sdk-release"
printf 'Platform Channel = pre-release\n' > "${SDK_RELEASE_FILE}"
sysroot="${tmpdir}/sysroot"
mkdir -p "${sysroot}/var/lib/sima-sdk" "${tmpdir}/bin"
cat > "${sysroot}/var/lib/sima-sdk/sysroot-overlay" <<'EOF'
Overlay State = active
Platform Revision = 3.0.0~pre4617
Platform Repository = https://debian.neat.sima.ai/pre-release
EOF

cat > "${tmpdir}/bin/apt-cache" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source_file=""
preferences_file=""
while [[ "${1:-}" == "-o" ]]; do
  case "${2:-}" in
    Dir::Etc::sourcelist=*) source_file="${2#*=}" ;;
    Dir::Etc::preferences=*) preferences_file="${2#*=}" ;;
  esac
  shift 2
done

[[ -r "${source_file}" ]]
[[ -r "${preferences_file}" ]]
[[ "${source_file}" != "${SIMA_FORBIDDEN_APT_SOURCE_FILE:?}" ]]
[[ "${preferences_file}" != "${SIMA_FORBIDDEN_APT_PREFERENCES_FILE:?}" ]]
grep -Fq 'deb [arch=arm64 trusted=yes] https://debian.neat.sima.ai/pre-release bookworm non-free' \
  "${source_file}"
grep -Fq 'Pin: version 3.0.0~pre4617' "${preferences_file}"

case "${1:-}" in
  policy)
    printf '%s\n' '  Candidate: (none)'
    ;;
  search)
    if [[ "${2:-}" == '^libopencv-dnn[0-9]+$' ]]; then
      printf '%s\n' 'libopencv-dnn4 - unprivileged overlay test'
    fi
    ;;
esac
EOF
chmod 755 "${tmpdir}/bin/apt-cache"

forbidden_source="/root/sima-sdk-test/sources.list"
forbidden_preferences="/root/sima-sdk-test/preferences"
output="$(
  PATH="${tmpdir}/bin:${PATH}" \
  SYSROOT="${sysroot}" \
  PLATFORM_PACKAGE_PATTERNS_FILE="${ROOT_DIR}/config/platform-package-patterns.txt" \
  SYSROOT_UPDATE_APT_SOURCE_FILE="${forbidden_source}" \
  SYSROOT_UPDATE_APT_PREFERENCES_FILE="${forbidden_preferences}" \
  SIMA_FORBIDDEN_APT_SOURCE_FILE="${forbidden_source}" \
  SIMA_FORBIDDEN_APT_PREFERENCES_FILE="${forbidden_preferences}" \
    "${SYSROOT_COMMAND}" install opencv_dnn --dry-run
)"

grep -Fq 'Resolved opencv_dnn -> libopencv-dnn4' <<< "${output}" || \
  fail "unprivileged dry run did not resolve the overlay component alias"
grep -Fq 'Dry run install:' <<< "${output}" || \
  fail "unprivileged dry run did not print the planned install"
[[ ! -e "${forbidden_source}" ]] || fail "dry run wrote the forbidden APT source"
[[ ! -e "${forbidden_preferences}" ]] || fail "dry run wrote the forbidden APT preferences"

echo "unprivileged sysroot dry-run tests passed"
