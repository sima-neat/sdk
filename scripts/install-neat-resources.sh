#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/neat-deps.sh"

core_target="${NEAT_CORE_TARGET:-$(neat_dependency_target core core)}"
core_source_ref="${NEAT_CORE_SOURCE_REF:-}"
core_source_reason="${NEAT_CORE_SOURCE_REASON:-}"
apps_source_ref="${NEAT_APPS_SOURCE_REF:-}"
resources_root="${NEAT_RESOURCES_ROOT:-/neat-resources}"
core_status_file="${NEAT_CORE_STATUS_FILE:-/var/lib/sima-sdk/neat-core-release}"
sima_cli_command="${SIMA_CLI_COMMAND:-sima-cli}"
resources_owner="${NEAT_RESOURCES_OWNER:-root:root}"

write_core_status() {
  local status="$1"
  local reason="$2"
  local status_tmp

  reason="${reason//$'\n'/ }"
  mkdir -p "$(dirname "${core_status_file}")"
  status_tmp="${core_status_file}.tmp"
  cat > "${status_tmp}" <<EOF
Neat Core = ${status}
Neat Core Requested = ${core_target}
Neat Core Reason = ${reason}
EOF
  mv "${status_tmp}" "${core_status_file}"

  printf '\n=== Neat Core bundle result ===\n'
  printf 'Neat Core: %s\n' "${status}"
  printf 'Requested: %s\n' "${core_target}"
  printf 'Reason: %s\n' "${reason}"
  printf '===============================\n\n'
}

clear_partial_resources() {
  if [[ -d "${resources_root}" ]]; then
    find "${resources_root}" -mindepth 1 -delete
  fi
}

skip_reason=""
if [[ "${1:-}" == "--skip" ]]; then
  skip_reason="${2:?--skip requires a reason}"
elif [[ $# -gt 0 ]]; then
  echo "Usage: $(basename "$0") [--skip REASON]" >&2
  exit 2
fi

if [[ -n "${skip_reason}" ]]; then
  clear_partial_resources
  write_core_status "not bundled" "${skip_reason}"
  exit 0
fi

if [[ -z "${core_source_ref}" ]]; then
  clear_partial_resources
  write_core_status "not bundled" "${core_source_reason:-requested Core source ref is unavailable}"
  exit 0
fi

if [[ -z "${apps_source_ref}" ]]; then
  echo "NEAT_APPS_SOURCE_REF is required when bundling Core resources." >&2
  exit 1
fi

mkdir -p "${resources_root}/core-extra" "${resources_root}/core-src" "${resources_root}/apps-src"

clone_at_commit() {
  local repository="$1"
  local destination="$2"
  local commit="$3"

  if [[ ! "${commit}" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "Source revision for ${repository} must be a full Git commit SHA: ${commit}" >&2
    return 1
  fi

  git init --quiet "${destination}"
  git -C "${destination}" remote add origin "${repository}"
  git -C "${destination}" fetch --quiet --depth 1 origin "${commit}"
  git -C "${destination}" checkout --quiet --detach FETCH_HEAD

  local resolved expected
  resolved="$(git -C "${destination}" rev-parse HEAD)"
  resolved="$(printf '%s' "${resolved}" | tr '[:upper:]' '[:lower:]')"
  expected="$(printf '%s' "${commit}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${resolved}" != "${expected}" ]]; then
    echo "Resolved ${repository} to ${resolved}, expected ${commit}." >&2
    return 1
  fi
}

install_log="$(mktemp)"
pushd "${resources_root}/core-extra" >/dev/null
echo "Installing prepackaged Neat Library: ${core_target}"
set +e
SIMA_CLI_CHECK_FOR_UPDATE=0 "${sima_cli_command}" neat install "${core_target}" -t minimal \
  2>&1 | tee "${install_log}"
install_status=${PIPESTATUS[0]}
set -e
popd >/dev/null

if [[ "${install_status}" -ne 0 ]]; then
  if grep -Eqi 'is not compatible|not compatible with this package' "${install_log}"; then
    rm -f "${install_log}"
    clear_partial_resources
    write_core_status "not bundled" "requested Core artifact is incompatible with this SDK platform"
    exit 0
  fi
  if grep -Eqi 'GET https://artifacts[.]neat[.]sima[.]ai/.+ failed: (403|404)|artifact[^[:cntrl:]]*(not found|does not exist|unavailable)|no matching artifacts? found' "${install_log}"; then
    rm -f "${install_log}"
    clear_partial_resources
    write_core_status "not bundled" "requested Core artifact is not published yet"
    exit 0
  fi
  rm -f "${install_log}"
  echo "Core installation failed for an unexpected reason; refusing to produce a partial SDK." >&2
  exit "${install_status}"
fi
rm -f "${install_log}"

find "${resources_root}/core-extra" -type f \
  \( -name '*.deb' -o -name '*.tar.gz' -o -name '*.whl' \) -delete

echo "Installing Neat Core source at ${core_source_ref}"
clone_at_commit "${NEAT_CORE_REPOSITORY:-https://github.com/sima-neat/core.git}" \
  "${resources_root}/core-src" "${core_source_ref}"
echo "Installing Neat Apps source at ${apps_source_ref}"
clone_at_commit "${NEAT_APPS_REPOSITORY:-https://github.com/sima-neat/apps.git}" \
  "${resources_root}/apps-src" "${apps_source_ref}"

if [[ -n "${resources_owner}" ]]; then
  chown -R "${resources_owner}" "${resources_root}"
fi
chmod -R go-w "${resources_root}"
write_core_status "bundled" "compatible Core artifact and source were installed"
