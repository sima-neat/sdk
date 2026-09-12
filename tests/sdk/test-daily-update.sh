#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
if [[ "$(id -u)" -ne 0 ]]; then
  exec sudo env PATH="${PATH}" bash "${BASH_SOURCE[0]}"
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "${tmpdir}"' EXIT
revision=3.0.0~git202609070138.4a147cf-1157
next_revision=3.0.0~git202609120100.abcdef0-1369
sysroot="${tmpdir}/sysroot"
mkdir -p "${sysroot}/var/lib/sima-sdk"
printf 'original\n' > "${sysroot}/original"
cat > "${tmpdir}/sdk-release" <<'META'
SDK Release = daily-test
Platform Base = 3.0.0
Platform Version = 3.0.0~git202609060100.abcdef0-1100
Platform Channel = daily
Platform Repository = https://debian.neat.sima.ai/daily
META
cp "${tmpdir}/sdk-release" "${tmpdir}/image-metadata"

cat > "${tmpdir}/setup" <<'SETUP'
#!/usr/bin/env bash
set -euo pipefail
[[ "${SDK_APT_CHANNEL}" == daily ]]
[[ "${SIMAAI_VALIDATE_TARGET_ORIGIN}" == 1 ]]
printf '%s\t%s\n' "$1" "${SIMAAI_SETUP_DOWNLOAD_ONLY}" >> "${TEST_LOG}"
if [[ "${TEST_FAIL:-}" == resolve ]]; then exit 42; fi
if [[ "${SIMAAI_SETUP_DOWNLOAD_ONLY}" == 1 ]]; then exit 0; fi
printf '%s\n' "$1" > "${SYSROOT}/original"
printf 'new file\n' > "${SYSROOT}/new-file"
mkdir -p "${SYSROOT_UPDATE_DOWNLOAD_DIR}"
printf 'simaai-palette-modalix\tall\t%s\t/usr/lib\n' "$1" > \
  "${SYSROOT}/var/lib/sima-sdk/sysroot-packages.tsv"
if [[ "${TEST_FAIL:-}" == extract ]]; then exit 43; fi
SETUP
cat > "${tmpdir}/finalize" <<'FINALIZE'
#!/usr/bin/env bash
set -euo pipefail
[[ "$2" == --finalize-only ]]
printf 'finalized\n' > "$1/finalized"
if [[ "${TEST_FAIL:-}" == finalize ]]; then exit 44; fi
FINALIZE
chmod +x "${tmpdir}/setup" "${tmpdir}/finalize"

run_sysroot() {
  SYSROOT="${sysroot}" SDK_RELEASE_FILE="${tmpdir}/sdk-release" \
    SYSROOT_PLATFORM_SETUP="${tmpdir}/setup" SYSROOT_INSTALLER="${tmpdir}/finalize" \
    SYSROOT_UPDATE_DOWNLOAD_DIR="${tmpdir}/downloads" TEST_LOG="${tmpdir}/setup.log" \
    bash "${ROOT_DIR}/scripts/sysroot.sh" "$@"
}

# Validate the exact selector and platform before invoking the installer.
for invalid in '--latest --yes' '3.0.0' '3.0.0~pre1234' '2.2.0~git202609070138.4a147cf-1157'; do
  # Intentional word splitting for the option fixture.
  if run_sysroot update ${invalid} >"${tmpdir}/out" 2>&1; then
    echo "invalid daily selector accepted: ${invalid}" >&2
    exit 1
  fi
done
[[ ! -e "${tmpdir}/setup.log" ]]

cp -a "${sysroot}" "${tmpdir}/original-sysroot"
run_sysroot update "${revision}" --dry-run
cmp "${tmpdir}/sdk-release" "${tmpdir}/image-metadata"
diff -r "${sysroot}" "${tmpdir}/original-sysroot"
grep -Fxq "${revision}"$'\t1' "${tmpdir}/setup.log"

# Resolution and partial extraction failures must restore both files and metadata.
for failure in resolve extract finalize; do
  if TEST_FAIL="${failure}" run_sysroot update "${revision}"; then
    echo "${failure} failure reported success" >&2
    exit 1
  fi
  diff -r "${sysroot}" "${tmpdir}/original-sysroot"
  cmp "${tmpdir}/sdk-release" "${tmpdir}/image-metadata"
done

run_sysroot update "${revision}"
grep -Fxq "${revision}" "${sysroot}/original"
[[ -f "${sysroot}/finalized" ]]
status="$(run_sysroot status)"
grep -Fq 'Sysroot overlay state:    active' <<<"${status}"
grep -Fq "Sysroot overlay revision: ${revision}" <<<"${status}"
grep -Fq 'Sysroot channel:          daily' <<<"${status}"
grep -Fq 'Sysroot repository:       https://debian.neat.sima.ai/daily' <<<"${status}"
cmp "${tmpdir}/sdk-release" "${tmpdir}/image-metadata"

before="$(wc -l < "${tmpdir}/setup.log")"
run_sysroot update "${revision}"
[[ "$(wc -l < "${tmpdir}/setup.log")" == "${before}" ]]

# A failed replacement must preserve an already active overlay too.
cp -a "${sysroot}" "${tmpdir}/active-sysroot"
if TEST_FAIL=extract run_sysroot update "${next_revision}"; then exit 1; fi
diff -r "${sysroot}" "${tmpdir}/active-sysroot"
run_sysroot update "${next_revision}"
grep -Fq "Sysroot overlay revision: ${next_revision}" <<<"$(run_sysroot status)"
[[ -z "$(find "${tmpdir}" -maxdepth 1 -name 'sysroot.update.*' -print)" ]]
cmp "${tmpdir}/sdk-release" "${tmpdir}/image-metadata"
echo 'daily sysroot update tests passed'
