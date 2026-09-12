#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SYSROOT_COMMAND="${ROOT_DIR}/scripts/sysroot.sh"

if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo env PATH="${PATH}" "${BASH_SOURCE[0]}"
fi

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT

cat > "${tmpdir}/sdk-release" <<'EOF'
SDK Release = develop-test
SDK Profile = platform-cross
Platform Version = 3.0.0~pre4460
Platform Base = 3.0.0
Platform Channel = pre-release
Platform Repository = https://debian.neat.sima.ai/pre-release
EOF

cat > "${tmpdir}/Packages" <<'EOF'
Package: simaai-palette-modalix
Version: 3.0.0~pre4593
Architecture: arm64

Package: simaai-palette-modalix
Version: 2.2.0~pre9000
Architecture: arm64

Package: simaai-palette-modalix
Version: 3.0.0~pre4617
Architecture: arm64

Package: simaai-palette-modalix
Version: 3.0.0
Architecture: arm64

Package: simaai-palette-modalix
Version: 3.0.0~pre4617
Architecture: arm64
EOF

cat > "${tmpdir}/fake-platform-setup" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

revision="$1"
download_dir="${SYSROOT_UPDATE_DOWNLOAD_DIR:?}"
sysroot="${SYSROOT:?}"
printf '%s\t%s\t%s\n' \
  "${revision}" \
  "${SIMAAI_SETUP_DOWNLOAD_ONLY:-0}" \
  "${SIMAAI_PLATFORM_BUILD_REVISION:-}" >> "${SYSROOT_UPDATE_TEST_LOG:?}"
if [[ "${SDK_APT_CHANNEL}" == daily ]]; then
  [[ -z "${SIMAAI_PLATFORM_BUILD_REVISION}" && ! -e "${SYSROOT_UPDATE_APT_PREFERENCES_FILE}" ]]
else
  for origin in \
    debian.neat.sima.ai \
    repo.sima.ai \
    mirror.elxr.dev \
    deb.debian.org \
    security.debian.org; do
    grep -A1 -F "Pin: origin \"${origin}\"" "${SYSROOT_UPDATE_APT_PREFERENCES_FILE:?}" | \
      grep -Fq 'Pin-Priority: 1001'
  done
  grep -A1 -F 'Pin: release o=Ubuntu' "${SYSROOT_UPDATE_APT_PREFERENCES_FILE:?}" | \
    grep -Fq 'Pin-Priority: 100'
  [[ "${SIMAAI_VALIDATE_TARGET_ORIGIN:-}" == "1" ]]
  if [[ -n "${SYSROOT_UPDATE_APT_CANDIDATE_TEST:-}" ]]; then
    python3 "${SYSROOT_UPDATE_APT_CANDIDATE_TEST}" \
      "${SYSROOT_UPDATE_APT_PREFERENCES_FILE:?}"
  fi
fi
rm -rf "${download_dir}"
mkdir -p "${download_dir}"
package_root="$(mktemp -d)"
trap 'rm -rf "${package_root}"' EXIT
mkdir -p "${package_root}/DEBIAN" "${package_root}/usr/lib/aarch64-linux-gnu"
chmod 755 "${package_root}/DEBIAN"
cat > "${package_root}/DEBIAN/control" <<CONTROL
Package: simaai-palette-modalix
Version: ${revision}
Architecture: arm64
Maintainer: SDK Test <sdk-test@example.invalid>
Description: sysroot update test fixture
CONTROL
printf '%s\n' "${revision}" > "${package_root}/usr/lib/aarch64-linux-gnu/sysroot-update-test.txt"
dpkg-deb --build "${package_root}" "${download_dir}/simaai-palette-modalix_${revision}_arm64.deb" >/dev/null
if [[ "${SYSROOT_UPDATE_TEST_FAIL:-0}" == "1" ]]; then
  exit 42
fi
if [[ "${SIMAAI_SETUP_DOWNLOAD_ONLY:-0}" != "1" ]]; then
  mkdir -p "${sysroot}/usr/lib/aarch64-linux-gnu" "${sysroot}/usr/include/simaai"
  cp "${package_root}/usr/lib/aarch64-linux-gnu/sysroot-update-test.txt" \
    "${sysroot}/usr/lib/aarch64-linux-gnu/sysroot-update-test.txt"
  printf '#define SIMAAI_TEST 1\n' > "${sysroot}/usr/include/simaai/stdc-predef.h"
  printf 'prefix=%s/usr\n' "${sysroot}" > "${sysroot}/test.pc"
  ln -sfn "${sysroot}/usr/include/simaai/stdc-predef.h" "${sysroot}/header-link"
  chmod 0750 "${sysroot}/usr/include/simaai"
  chmod 0640 "${sysroot}/usr/include/simaai/stdc-predef.h"
  mkdir -p "${sysroot}/var/lib/sima-sdk"
  printf 'simaai-palette-modalix\tarm64\t%s\t/usr/lib/aarch64-linux-gnu\n' "${revision}" > \
    "${sysroot}/var/lib/sima-sdk/sysroot-packages.tsv"
  sha256sum "${download_dir}"/*.deb > "${sysroot}/var/lib/sima-sdk/packages.sha256"
fi
[[ "${SYSROOT_UPDATE_TEST_FAIL:-0}" != extract ]] || exit 42
if [[ "${SYSROOT_UPDATE_TEST_FAIL:-}" == interrupt ]]; then
  touch "${SYSROOT_UPDATE_TEST_LOG}.ready"
  sleep 60
fi

EOF
chmod 755 "${tmpdir}/fake-platform-setup"

common_env=(
  "SYSROOT=${tmpdir}/sysroot"
  "SDK_RELEASE_FILE=${tmpdir}/sdk-release"
  "SYSROOT_PLATFORM_SETUP=${tmpdir}/fake-platform-setup"
  "PLATFORM_PACKAGE_PATTERNS_FILE=${ROOT_DIR}/config/platform-package-patterns.txt"
  "PRE_RELEASE_PACKAGES_FILE=${tmpdir}/Packages"
  "SYSROOT_UPDATE_APT_SOURCE_FILE=${tmpdir}/apt/sources/pre-release.list"
  "SYSROOT_UPDATE_APT_PREFERENCES_FILE=${tmpdir}/apt/preferences/pre-release.pref"
  "SYSROOT_UPDATE_DOWNLOAD_DIR=${tmpdir}/downloads"
  "SYSROOT_UPDATE_TEST_LOG=${tmpdir}/setup.log"
)

run_sysroot() {
  env "${common_env[@]}" "${SYSROOT_COMMAND}" "$@"
}

mkdir -p "${tmpdir}/sysroot/var/lib/sima-sdk"
printf 'base-sdk-package\tarm64\t1.0.0\t/usr/lib\n' > \
  "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-packages.tsv"
mkdir -p "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-packages"
cat > "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-packages/simaai-palette-modalix_arm64.manifest" <<'EOF'
Package: simaai-palette-modalix
Architecture: arm64
Version: 3.0.0~pre4460

usr/lib/aarch64-linux-gnu/old-file.txt
EOF
cat > "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-packages/manual-package_arm64.manifest" <<'EOF'
Package: manual-package
Architecture: arm64
Version: 9.8.7

opt/manual-package/libmanual.so
EOF
initial_list="$(run_sysroot list)"
grep -Eq '^base-sdk-package[[:space:]]+arm64[[:space:]]+1\.0\.0[[:space:]]+/usr/lib$' \
  <<< "${initial_list}" || \
  fail "list did not read the image-default package inventory"

initial_status="$(run_sysroot status)"
grep -Fq 'Sysroot overlay state:    inactive' <<< "${initial_status}" || \
  fail "clean SDK did not report an inactive overlay"

if run_sysroot update >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  fail "noninteractive update without a selector succeeded"
fi
grep -Fq 'interactive revision selection requires a TTY' "${tmpdir}/err" || \
  fail "non-TTY error was unclear"

if run_sysroot update 2.2.0~pre9000 >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  fail "cross-base update succeeded"
fi
grep -Fq 'SDK Platform Base is 3.0.0' "${tmpdir}/err" || \
  fail "cross-base rejection was unclear"

if run_sysroot update 3.0.0~pre9999 >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  fail "missing pre-release revision succeeded"
fi
grep -Fq 'is not available' "${tmpdir}/err" || fail "missing revision rejection was unclear"

dry_run="$(
  env "${common_env[@]}" \
    SYSROOT_UPDATE_APT_CANDIDATE_TEST="${ROOT_DIR}/tests/sdk/test-sysroot-apt-candidate.py" \
    "${SYSROOT_COMMAND}" update 3.0.0~pre4593 --dry-run
)"
grep -Fq 'Dry run complete: 3.0.0~pre4593 resolved and validated' <<< "${dry_run}" || \
  fail "exact dry run did not validate the selected revision"
[[ ! -e "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-overlay" ]] || \
  fail "dry run created overlay metadata"
grep -Fxq $'3.0.0~pre4593\t1\t4593' "${tmpdir}/setup.log" || \
  fail "exact dry run did not constrain dependencies to the selected build cohort"

latest_dry_run="$(run_sysroot update --latest --yes --dry-run)"
grep -Fq 'Dry run complete: 3.0.0~pre4617 resolved and validated' <<< "${latest_dry_run}" || \
  fail "latest resolution did not select the newest eligible revision"
grep -Fxq $'3.0.0~pre4617\t1\t4617' "${tmpdir}/setup.log" || \
  fail "latest dry run did not constrain dependencies to the selected build cohort"

# A fresh SDK image has an image inventory but no manifests created by
# `sysroot install`.  Optional manifest bookkeeping must remain a successful
# no-op so a fully extracted update can still be committed as active.
fresh_sysroot="${tmpdir}/fresh-sysroot"
mkdir -p "${fresh_sysroot}/var/lib/sima-sdk"
printf 'base-sdk-package\tarm64\t1.0.0\t/usr/lib\n' > \
  "${fresh_sysroot}/var/lib/sima-sdk/sysroot-packages.tsv"
fresh_update_output="$(
  env "${common_env[@]}" SYSROOT="${fresh_sysroot}" \
    "${SYSROOT_COMMAND}" update 3.0.0~pre4593
)"
grep -Fq 'Sysroot overlay is active at 3.0.0~pre4593' <<< "${fresh_update_output}" || \
  fail "fresh SDK update without tracked manifests did not activate the overlay"
grep -Fxq 'Overlay State = active' \
  "${fresh_sysroot}/var/lib/sima-sdk/sysroot-overlay" || \
  fail "fresh SDK update was left incomplete"

if env "${common_env[@]}" SYSROOT_UPDATE_TEST_FAIL=1 \
  "${SYSROOT_COMMAND}" update 3.0.0~pre4593 >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  fail "failed platform setup was reported as successful"
fi
failed_status="$(run_sysroot status)"
grep -Fq 'Sysroot overlay state:    incomplete' <<< "${failed_status}" || \
  fail "failed update did not leave visible incomplete overlay state"
grep -Fq 'WARNING: The sysroot overlay is not complete' <<< "${failed_status}" || \
  fail "incomplete overlay did not report recovery guidance"
if env "${common_env[@]}" SYSROOT_INSTALLER=/bin/true \
  "${SYSROOT_COMMAND}" install test-package:arm64 >"${tmpdir}/out" 2>"${tmpdir}/err"; then
  fail "package install proceeded against an incomplete overlay"
fi
grep -Fq 'sysroot overlay state is incomplete' "${tmpdir}/err" || \
  fail "package install did not explain the incomplete overlay rejection"

update_output="$(run_sysroot update 3.0.0~pre4617)"
grep -Fq 'Sysroot overlay is active at 3.0.0~pre4617' <<< "${update_output}" || \
  fail "exact update did not activate the overlay"
grep -Fxq '3.0.0~pre4617' "${tmpdir}/sysroot/usr/lib/aarch64-linux-gnu/sysroot-update-test.txt" || \
  fail "platform setup did not update the sysroot"
[[ "$(stat -c '%a' "${tmpdir}/sysroot/usr/include/simaai")" == "755" ]] || \
  fail "update left an extracted sysroot directory inaccessible to non-root users"
[[ "$(stat -c '%a' "${tmpdir}/sysroot/usr/include/simaai/stdc-predef.h")" == "644" ]] || \
  fail "update left an extracted sysroot file unreadable to non-root users"
grep -Fxq 'Platform Revision = 3.0.0~pre4617' "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-overlay" || \
  fail "overlay revision was not recorded"
awk -F '\t' '$1 == "simaai-palette-modalix" && $2 == "arm64" && $3 == "3.0.0~pre4617" && $4 == "/usr/lib/aarch64-linux-gnu" { found = 1 } END { exit !found }' \
  "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-packages.tsv" || \
  fail "package inventory was not recorded"
updated_list="$(run_sysroot list)"
grep -Eq '^simaai-palette-modalix[[:space:]]+arm64[[:space:]]+3\.0\.0~pre4617[[:space:]]+/usr/lib/aarch64-linux-gnu$' \
  <<< "${updated_list}" || \
  fail "list did not report the updated full package inventory"
grep -Eq '^manual-package[[:space:]]+arm64[[:space:]]+9\.8\.7[[:space:]]+/opt/manual-package$' \
  <<< "${updated_list}" || \
  fail "platform update dropped a manually installed package from the inventory"
grep -Fxq 'Version: 3.0.0~pre4617' \
  "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-packages/simaai-palette-modalix_arm64.manifest" || \
  fail "update did not refresh an existing tracked package manifest"
grep -Fxq $'3.0.0~pre4617\t0\t4617' "${tmpdir}/setup.log" || \
  fail "actual update did not constrain dependencies to the selected build cohort"
mkdir -p "${tmpdir}/bin"
cat > "${tmpdir}/fake-installer" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
[[ "${SDK_APT_CHANNEL:-}" == "pre-release" ]]
grep -Fq 'Pin: version 3.0.0~pre4617' "${SYSROOT_UPDATE_APT_PREFERENCES_FILE:?}"
[[ "${2:-}" == "libopencv-dnn4:arm64" ]]
printf 'overlay-selection-ok\n' > "${SYSROOT_UPDATE_INSTALL_TEST_LOG:?}"
EOF
cat > "${tmpdir}/bin/apt-get" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
archive_dir=""
for argument in "$@"; do
  case "${argument}" in
    Dir::Cache::archives=*) archive_dir="${argument#*=}" ;;
  esac
done
if [[ -n "${archive_dir}" ]]; then
  mkdir -p "${archive_dir}"
  cp "${SYSROOT_UPDATE_DOWNLOAD_DIR}"/*.deb "${archive_dir}/"
fi
EOF
cat > "${tmpdir}/bin/apt-cache" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
source_file="${SYSROOT_UPDATE_APT_SOURCE_FILE:?}"
preferences_file="${SYSROOT_UPDATE_APT_PREFERENCES_FILE:?}"
while [[ "${1:-}" == "-o" ]]; do
  case "${2:-}" in
    Dir::Etc::sourcelist=*) source_file="${2#*=}" ;;
    Dir::Etc::preferences=*) preferences_file="${2#*=}" ;;
  esac
  shift 2
done
if [[ "${SIMA_EXPECT_UNPRIVILEGED_DRY_RUN:-0}" == "1" ]]; then
  [[ "${source_file}" != "${SIMA_ORIGINAL_APT_SOURCE_FILE:?}" ]]
  [[ "${preferences_file}" != "${SIMA_ORIGINAL_APT_PREFERENCES_FILE:?}" ]]
fi
grep -Fq 'deb [arch=arm64 trusted=yes] https://debian.neat.sima.ai/pre-release bookworm non-free' \
  "${source_file}"
grep -Fq 'Pin: version 3.0.0~pre4617' "${preferences_file}"
for origin in \
  debian.neat.sima.ai \
  repo.sima.ai \
  mirror.elxr.dev \
  deb.debian.org \
  security.debian.org; do
  grep -A1 -F "Pin: origin \"${origin}\"" "${preferences_file}" | \
    grep -Fq 'Pin-Priority: 990'
done
case "${1:-}" in
  policy)
    printf '%s\n' '  Candidate: (none)'
    ;;
  search)
    if [[ "${2:-}" == '^libopencv-dnn[0-9]+$' ]]; then
      printf '%s\n' 'libopencv-dnn4 - test overlay component'
    fi
    ;;
esac
EOF
chmod 755 "${tmpdir}/fake-installer" "${tmpdir}/bin/apt-get" "${tmpdir}/bin/apt-cache"
overlay_dry_run="$(
  env "${common_env[@]}" \
    PATH="${tmpdir}/bin:${PATH}" \
    SIMA_EXPECT_UNPRIVILEGED_DRY_RUN=1 \
    SIMA_ORIGINAL_APT_SOURCE_FILE="${tmpdir}/apt/sources/pre-release.list" \
    SIMA_ORIGINAL_APT_PREFERENCES_FILE="${tmpdir}/apt/preferences/pre-release.pref" \
    "${SYSROOT_COMMAND}" install opencv_dnn --dry-run
)"
grep -Fq 'Resolved opencv_dnn -> libopencv-dnn4' <<< "${overlay_dry_run}" || \
  fail "dry-run component alias resolution did not use active overlay APT selection"
[[ ! -e "${tmpdir}/apt/sources/pre-release.list" ]] || \
  fail "dry-run component alias resolution did not clean up its temporary APT source"
[[ ! -e "${tmpdir}/apt/preferences/pre-release.pref" ]] || \
  fail "dry-run component alias resolution did not clean up its temporary APT pin"
env "${common_env[@]}" \
  PATH="${tmpdir}/bin:${PATH}" \
  SYSROOT_INSTALLER="${tmpdir}/fake-installer" \
  SYSROOT_UPDATE_INSTALL_TEST_LOG="${tmpdir}/install.log" \
  "${SYSROOT_COMMAND}" install opencv_dnn >/dev/null
grep -Fxq 'overlay-selection-ok' "${tmpdir}/install.log" || \
  fail "package install did not reconstruct active overlay APT selection"

incomplete_prompt_output="$(
  cp "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-overlay" "${tmpdir}/active-overlay"
  sed -i 's/^Overlay State = active$/Overlay State = incomplete/' \
    "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-overlay"
  SYSROOT="${tmpdir}/sysroot" \
  SDK_PROMPT_HOSTNAME=neat-sdk-test \
  bash --noprofile --norc -ic \
    "source '${ROOT_DIR}/config/profile.d/neat-sdk-prompt.sh'; printf '%s\\n' \"\${SDK_PROMPT_HOSTNAME}\"" \
    2>/dev/null
)"
mv "${tmpdir}/active-overlay" "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-overlay"
grep -Fq 'neat-sdk-test-overlay-incomplete-3-0-0-pre4617' <<< "${incomplete_prompt_output}" || \
  fail "interactive prompt mislabeled an incomplete overlay as active"

setup_count_before="$(wc -l < "${tmpdir}/setup.log" | tr -d ' ')"
idempotent_output="$(run_sysroot update 3.0.0~pre4617)"
setup_count_after="$(wc -l < "${tmpdir}/setup.log" | tr -d ' ')"
grep -Fq 'no changes are required' <<< "${idempotent_output}" || \
  fail "same-revision update was not reported as idempotent"
[[ "${setup_count_before}" == "${setup_count_after}" ]] || \
  fail "same-revision update invoked platform setup"

overlay_status="$(run_sysroot status)"
grep -Fq 'Sysroot overlay state:    active' <<< "${overlay_status}" || \
  fail "active overlay state was not reported"
grep -Fq 'Sysroot overlay revision: 3.0.0~pre4617' <<< "${overlay_status}" || \
  fail "active overlay revision was not reported"

prompt_output="$(
  SYSROOT="${tmpdir}/sysroot" \
  SDK_PROMPT_HOSTNAME=neat-sdk-test \
  bash --noprofile --norc -ic \
    "source '${ROOT_DIR}/config/profile.d/neat-sdk-prompt.sh'; printf '%s\\n' \"\${SDK_PROMPT_HOSTNAME}\"" \
    2>/dev/null
)"
grep -Fq 'neat-sdk-test-overlay-3-0-0-pre4617' <<< "${prompt_output}" || \
  fail "interactive prompt did not expose the active overlay"

[[ ! -e "${tmpdir}/apt/sources/pre-release.list" ]] || fail "temporary APT source was not cleaned up"
[[ ! -e "${tmpdir}/apt/preferences/pre-release.pref" ]] || fail "temporary APT preferences were not cleaned up"

# Exercise daily routing with the same installer fixture and transaction checks.
sed -i -e 's/Platform Channel = pre-release/Platform Channel = daily/' \
  -e 's@https://debian.neat.sima.ai/pre-release@https://debian.neat.sima.ai/daily@' \
  "${tmpdir}/sdk-release"
mkdir -p "${tmpdir}/bin"
cat > "${tmpdir}/bin/aarch64-linux-gnu-g++" <<'EOF'
#!/bin/bash
case "$1" in
  -dumpversion) echo 14 ;;
  -dumpmachine) echo aarch64-linux-gnu ;;
  --version) echo 'fixture GCC 14' ;;
  *) cat >/dev/null; [[ "${SYSROOT_UPDATE_TEST_FAIL:-}" != compiler ]] ;;
esac
EOF
chmod +x "${tmpdir}/bin/aarch64-linux-gnu-g++"
common_env+=("SYSROOT_INSTALLER=/bin/true" "SYSROOT_DIRECTORY_HELPER=${ROOT_DIR}/scripts/sysroot-directory.py" "PATH=${tmpdir}/bin:${PATH}")
SDK_PKG_LIST=" libz-dev, liba-dev,libz-dev " /usr/bin/python3 "${ROOT_DIR}/scripts/sysroot-directory.py" init "${tmpdir}/sysroot"
initial_generation="$(readlink -f "${tmpdir}/sysroot")"
[[ "$(cat "${initial_generation}/var/lib/sima-sdk/requested-packages")" == $'liba-dev\nlibz-dev' ]]
sed -i 's/^Platform Version = .*/Platform Version = 3.0.0~git202609070138.4a147cf-1157/' "${tmpdir}/sdk-release"
rm "${initial_generation}/var/lib/sima-sdk/sysroot-overlay"
env "${common_env[@]}" SDK_PKG_LIST=liba-dev,libz-dev "${SYSROOT_COMMAND}" update 3.0.0~git202609070138.4a147cf-1157
[[ "$(readlink -f "${tmpdir}/sysroot")" == "${initial_generation}" ]]
echo obsolete > "${initial_generation}/usr/include/obsolete.h"
daily_revision=3.0.0~git202609120138.dcab8a6-1369
for invalid in 3.0.0~pre4617 2.2.0~git202609120138.dcab8a6-1369 --latest; do
  if run_sysroot update "${invalid}" >"${tmpdir}/out" 2>&1; then
    fail "daily update accepted ${invalid}"
  fi
done
# An absolute path alone must not authorize replacing an unrelated directory.
mkdir "${tmpdir}/unmanaged"
echo preserve > "${tmpdir}/unmanaged/existing-file"
for operation in update rollback; do
  extra=()
  [[ "${operation}" != update ]] || extra=("${daily_revision}")
  if run_sysroot "${operation}" --sysroot "${tmpdir}/unmanaged" "${extra[@]}" > "${tmpdir}/out" 2>&1; then
    fail "accepted an unmanaged sysroot"
  fi
  grep -q 'Not an initialized SDK sysroot' "${tmpdir}/out"
  [[ "$(cat "${tmpdir}/unmanaged/existing-file")" == preserve ]]
  [[ ! -e "${tmpdir}/unmanaged.update" ]]
done
cp "${tmpdir}/sdk-release" "${tmpdir}/image-metadata"
cp -a "${initial_generation}" "${tmpdir}/before-daily"
run_sysroot update "${daily_revision}" --dry-run
diff -r "${tmpdir}/before-daily" "${initial_generation}"
if env "${common_env[@]}" SYSROOT_UPDATE_TEST_FAIL=extract \
  "${SYSROOT_COMMAND}" update "${daily_revision}"; then
  fail "partial daily extraction reported success"
fi
diff -r "${tmpdir}/before-daily" "${initial_generation}"
[[ "$(readlink -f "${tmpdir}/sysroot")" == "${initial_generation}" ]]
run_sysroot update "${daily_revision}"
[[ ! -e "${tmpdir}/sysroot/usr/include/obsolete.h" ]]
[[ -e "${tmpdir}/sysroot.update/previous/usr/include/obsolete.h" ]]
grep -Fq "Sysroot overlay revision: ${daily_revision}" <<< "$(run_sysroot status)"
grep -Fxq 'Platform Channel = daily' "${tmpdir}/sysroot/var/lib/sima-sdk/sysroot-overlay"
cmp "${tmpdir}/image-metadata" "${tmpdir}/sdk-release"
[[ -d "${tmpdir}/sysroot" && ! -L "${tmpdir}/sysroot" ]]
selected="$(stat -c %i "${tmpdir}/sysroot")"
run_sysroot update "${daily_revision}"
[[ "$(stat -c %i "${tmpdir}/sysroot")" == "${selected}" ]]
run_sysroot rollback
[[ -e "${tmpdir}/sysroot/usr/include/obsolete.h" ]]
# A -> B -> C -> A replaces the directory without obsolete files.
for revision in "${daily_revision}" 3.0.0~git202609112047.4066d33-1350 3.0.0~git202609070138.4a147cf-1157; do
  run_sysroot update "${revision}"
  grep -Fxq "${revision}" "${tmpdir}/sysroot/usr/lib/aarch64-linux-gnu/sysroot-update-test.txt"
done
before="$(stat -c %i "${tmpdir}/sysroot")"
if env "${common_env[@]}" SYSROOT_UPDATE_TEST_FAIL=compiler "${SYSROOT_COMMAND}" update "${daily_revision}"; then
  fail "compiler failure activated a generation"
fi
[[ "$(stat -c %i "${tmpdir}/sysroot")" == "${before}" ]]
setsid env "${common_env[@]}" SYSROOT_UPDATE_TEST_FAIL=interrupt "${SYSROOT_COMMAND}" update "${daily_revision}" &
updater=$!
for attempt in {1..100}; do
  [[ ! -e "${tmpdir}/setup.log.ready" ]] || break
  sleep 0.02
done
if [[ ! -e "${tmpdir}/setup.log.ready" ]]; then kill -KILL -- "-${updater}"; fail "updater did not reach extraction"; fi
kill -KILL -- "-${updater}"
wait "${updater}" 2>/dev/null || true
[[ "$(stat -c %i "${tmpdir}/sysroot")" == "${before}" ]]
run_sysroot update "${daily_revision}"
(
  flock -x 9
  if run_sysroot update "${daily_revision}"; then fail "concurrent update accepted"; fi
) 9>/var/lock/sima-sdk-sysroot.lock

# Same revision rebuilds for changed requests, but ordering/duplicates do not.
for packages in 'libz-dev, liba-dev,libz-dev' ''; do
  before="$(stat -c %i "${tmpdir}/sysroot")"
  env "${common_env[@]}" SDK_PKG_LIST="${packages}" "${SYSROOT_COMMAND}" update "${daily_revision}"
  [[ "$(stat -c %i "${tmpdir}/sysroot")" != "${before}" ]]
  selected="$(stat -c %i "${tmpdir}/sysroot")"
  normalized="$(cat "${tmpdir}/sysroot/var/lib/sima-sdk/requested-packages")"
  expected=""
  [[ -z "${packages}" ]] || expected=$'liba-dev\nlibz-dev'
  [[ "${normalized}" == "${expected}" ]]
  equivalent="${packages:+ liba-dev ,libz-dev }"
  env "${common_env[@]}" SDK_PKG_LIST="${equivalent}" "${SYSROOT_COMMAND}" update "${daily_revision}"
  [[ "$(stat -c %i "${tmpdir}/sysroot")" == "${selected}" ]]
done

grep -Fxq "prefix=${tmpdir}/sysroot/usr" "${tmpdir}/sysroot/test.pc"
[[ "$(readlink "${tmpdir}/sysroot/header-link")" == "${tmpdir}/sysroot/usr/include/simaai/stdc-predef.h" ]]
# Model interruption after removing the old directory but before activation.
cp -a "${tmpdir}/sysroot.update/previous" "${tmpdir}/expected-recovery"
touch "${tmpdir}/sysroot.update/pending"
rm -rf "${tmpdir}/sysroot"
mkdir -p "${tmpdir}/sysroot"
echo partial > "${tmpdir}/sysroot/interrupted-file"
if run_sysroot update "${daily_revision}" --dry-run; then fail "dry run ignored interrupted replacement"; fi
/usr/bin/python3 "${ROOT_DIR}/scripts/sysroot-directory.py" recover "${tmpdir}/sysroot"
diff -r "${tmpdir}/expected-recovery" "${tmpdir}/sysroot"
[[ ! -e "${tmpdir}/sysroot.update/pending" ]]
# Reject an uninitialized backup without touching the active sysroot.
touch "${tmpdir}/sysroot.update/pending"
rm "${tmpdir}/sysroot.update/previous/var/lib/sima-sdk/requested-packages"
if /usr/bin/python3 "${ROOT_DIR}/scripts/sysroot-directory.py" recover "${tmpdir}/sysroot"; then
  fail "recovery accepted an uninitialized backup"
fi
diff -r "${tmpdir}/expected-recovery" "${tmpdir}/sysroot"
echo "sysroot update tests passed"
