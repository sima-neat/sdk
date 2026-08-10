#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/neat-deps.sh"

mkdir -p /neat-resources/core-extra /neat-resources/core-src /neat-resources/apps-src

core_target="${NEAT_CORE_TARGET:-$(neat_dependency_target core core)}"
core_source_ref="${NEAT_CORE_SOURCE_REF:?NEAT_CORE_SOURCE_REF is required}"
apps_source_ref="${NEAT_APPS_SOURCE_REF:?NEAT_APPS_SOURCE_REF is required}"

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

(
  cd /neat-resources/core-extra
  echo "Installing prepackaged Neat Library: ${core_target}"
  SIMA_CLI_CHECK_FOR_UPDATE=0 sima-cli neat install "${core_target}" -t minimal
)

find /neat-resources/core-extra -type f \
  \( -name '*.deb' -o -name '*.tar.gz' -o -name '*.whl' \) -delete

echo "Installing Neat Core source at ${core_source_ref}"
clone_at_commit https://github.com/sima-neat/core.git /neat-resources/core-src "${core_source_ref}"
echo "Installing Neat Apps source at ${apps_source_ref}"
clone_at_commit https://github.com/sima-neat/apps.git /neat-resources/apps-src "${apps_source_ref}"

chown -R root:root /neat-resources
chmod -R go-w /neat-resources
