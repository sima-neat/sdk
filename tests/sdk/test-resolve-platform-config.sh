#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESOLVER="${ROOT_DIR}/scripts/resolve-platform-config.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

cat > "${tmpdir}/Packages" <<'EOF'
Package: simaai-palette-modalix
Version: 2.1.3~pre4040
Architecture: arm64

Package: another-package
Version: 9.9.9
Architecture: arm64

Package: simaai-palette-modalix
Version: 2.1.3~pre4460
Architecture: arm64

Package: simaai-palette-modalix
Version: 2.1.4~pre9999
Architecture: arm64
EOF

cat > "${tmpdir}/CurrentPackages" <<'EOF'
Package: simaai-palette-modalix
Version: 2.1.3~pre4460
Architecture: arm64

Package: simaai-palette-modalix
Version: 2.1.3~pre4593
Architecture: arm64
EOF
gzip -c "${tmpdir}/CurrentPackages" > "${tmpdir}/CurrentPackages.gz"
if command -v sha256sum >/dev/null 2>&1; then
  current_packages_digest="$(sha256sum "${tmpdir}/CurrentPackages.gz" | awk '{print $1}')"
else
  current_packages_digest="$(shasum -a 256 "${tmpdir}/CurrentPackages.gz" | awk '{print $1}')"
fi
cat > "${tmpdir}/Release" <<EOF
Acquire-By-Hash: yes
SHA256:
 ${current_packages_digest} $(wc -c < "${tmpdir}/CurrentPackages.gz" | tr -d ' ') non-free/binary-arm64/Packages.gz
EOF

cat > "${tmpdir}/curl" <<EOF
#!/usr/bin/env bash
set -euo pipefail
url="\${!#}"
case "\${url}" in
  */Release) cat "${tmpdir}/Release" ;;
  */by-hash/SHA256/${current_packages_digest}) cat "${tmpdir}/CurrentPackages.gz" ;;
  *) echo "unexpected URL: \${url}" >&2; exit 1 ;;
esac
EOF
chmod 755 "${tmpdir}/curl"

cat > "${tmpdir}/dpkg" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "$1" == "--compare-versions" && "$3" == "gt" ]]
left="${2##*~pre}"
right="${4##*~pre}"
(( left > right ))
EOF
chmod 755 "${tmpdir}/dpkg"

run_resolver() {
  PRE_RELEASE_PACKAGES_FILE="${PRE_RELEASE_PACKAGES_FILE-${tmpdir}/Packages}" \
    DPKG_COMMAND="${tmpdir}/dpkg" \
    STABLE_BASE_SDK_VERSION=2.1.3 \
    "${RESOLVER}"
}

stable="$(PRE_RELEASE_BASE= GITHUB_REF_TYPE=branch GITHUB_REF_NAME=develop run_resolver)"
grep -Fxq 'sdk_apt_channel=release' <<< "${stable}" || fail "stable channel was not selected"
grep -Fxq 'base_sdk_version=2.1.3' <<< "${stable}" || fail "stable version was incorrect"

floating="$(PRE_RELEASE_BASE=2.1.3 GITHUB_REF_TYPE=branch GITHUB_REF_NAME=develop run_resolver)"
grep -Fxq 'sdk_apt_channel=pre-release' <<< "${floating}" || fail "pre-release channel was not selected"
grep -Fxq 'base_sdk_version=2.1.3~pre4460' <<< "${floating}" || fail "floating selector did not choose the newest Debian version"

by_hash_floating="$(
  PRE_RELEASE_BASE=2.1.3 \
    PRE_RELEASE_PACKAGES_FILE= \
    PRE_RELEASE_RELEASE_URL=https://mirror.test/pre-release/dists/bookworm/Release \
    CURL_COMMAND="${tmpdir}/curl" \
    GITHUB_REF_TYPE=branch \
    GITHUB_REF_NAME=develop \
    run_resolver
)"
grep -Fxq 'base_sdk_version=2.1.3~pre4593' <<< "${by_hash_floating}" || \
  fail "floating selector did not use the current by-hash package index"

by_hash_pinned="$(
  PRE_RELEASE_BASE=2.1.3~pre4460 \
    PRE_RELEASE_PACKAGES_FILE= \
    PRE_RELEASE_RELEASE_URL=https://mirror.test/pre-release/dists/bookworm/Release \
    CURL_COMMAND="${tmpdir}/curl" \
    GITHUB_REF_TYPE=branch \
    GITHUB_REF_NAME=develop \
    run_resolver
)"
grep -Fxq 'base_sdk_version=2.1.3~pre4460' <<< "${by_hash_pinned}" || \
  fail "exact pre-release selector did not remain pinned"

pinned="$(PRE_RELEASE_BASE=2.1.3~pre4040 GITHUB_REF_TYPE=branch GITHUB_REF_NAME=main run_resolver)"
grep -Fxq 'base_sdk_version=2.1.3~pre4040' <<< "${pinned}" || fail "pinned selector changed versions"

for protected_ref in main release-2.1; do
  if PRE_RELEASE_BASE=2.1.3 GITHUB_REF_TYPE=branch GITHUB_REF_NAME="${protected_ref}" run_resolver >"${tmpdir}/out" 2>"${tmpdir}/err"; then
    fail "floating selector was accepted for protected branch ${protected_ref}"
  fi
  grep -Fq 'floating PRE_RELEASE_BASE=2.1.3 is not allowed' "${tmpdir}/err" || fail "protected branch error was unclear"
done

if PRE_RELEASE_BASE=2.1.3 GITHUB_REF_TYPE=tag GITHUB_REF_NAME=v2.1.3 run_resolver >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  fail "floating selector was accepted for a tag"
fi

if PRE_RELEASE_BASE=2.1.3~pre9999 GITHUB_REF_TYPE=branch GITHUB_REF_NAME=develop run_resolver >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  fail "missing pinned version was accepted"
fi
grep -Fq 'is not present' "${tmpdir}/err" || fail "missing pinned version error was unclear"

if PRE_RELEASE_BASE=latest GITHUB_REF_TYPE=branch GITHUB_REF_NAME=develop run_resolver >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  fail "malformed selector was accepted"
fi

patterns_file="${ROOT_DIR}/config/platform-package-patterns.txt"
grep -Fxq 'simaai-palette-modalix' "${patterns_file}" || fail "Modalix palette is not platform-versioned"
grep -Fxq 'simaai-palette-davinci' "${patterns_file}" || fail "Davinci palette is not platform-versioned"
if grep -Fxq 'simaai-palette-*' "${patterns_file}"; then
  fail "palette wildcard incorrectly forces simaai-palette-upgrade to the platform version"
fi
if grep -Fq '"simaai-palette-*"' "${ROOT_DIR}/scripts/simaai_setup_sdk.py" || \
   grep -Fq '  simaai-palette-*' "${ROOT_DIR}/scripts/validate-sysroot-package-versions.sh"; then
  fail "fallback platform patterns still classify simaai-palette-upgrade as platform-versioned"
fi

apt_config_script="${ROOT_DIR}/scripts/configure-apt-repos.sh"
grep -Fq 'sdk_fallback_repository="https://repo.sima.ai/elxr/deb/release"' "${apt_config_script}" || \
  fail "pre-release APT configuration does not retain the release repository fallback"
grep -Fq 'sdk_fallback_origin="repo.sima.ai"' "${apt_config_script}" || \
  fail "release fallback APT origin is not the repository hostname"
grep -Fq 'deb [trusted=yes] ${sdk_fallback_repository} bookworm non-free' "${apt_config_script}" || \
  fail "release fallback is not written to the APT source list"

for apt_script in \
  "${apt_config_script}" \
  "${ROOT_DIR}/scripts/install-sysroot-overlay.sh" \
  "${ROOT_DIR}/scripts/setup-sdk-sysroot.sh" \
  "${ROOT_DIR}/scripts/sysroot.sh"; do
  if grep -Fq 'repo.sima.ai/elxr"' "${apt_script}"; then
    fail "APT origin includes a URL path instead of only the hostname in ${apt_script}"
  fi
done

docker_workflow="${ROOT_DIR}/.github/workflows/docker-build.yml"
grep -Fq 'pre_release_base:' "${docker_workflow}" || \
  fail "manual workflow dispatch does not expose a pre-release selector"
grep -Fq 'PRE_RELEASE_BASE: ${{ inputs.pre_release_base || vars.PRE_RELEASE_BASE }}' "${docker_workflow}" || \
  fail "manual pre-release selector does not override the repository variable"

echo "platform config resolver tests passed"
