#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/neat-deps.sh"

mkdir -p /neat-resources/core-extra /neat-resources/core-src /neat-resources/apps-src

core_target="${NEAT_CORE_TARGET:-$(neat_dependency_target core core)}"

(
  cd /neat-resources/core-extra
  echo "Installing prepackaged Neat Library: ${core_target}"
  SIMA_CLI_CHECK_FOR_UPDATE=0 sima-cli neat install "${core_target}" -t minimal
)

find /neat-resources/core-extra -type f \
  \( -name '*.deb' -o -name '*.tar.gz' -o -name '*.whl' \) -delete

git clone --depth 1 https://github.com/sima-neat/core.git /neat-resources/core-src
git clone --depth 1 https://github.com/sima-neat/apps.git /neat-resources/apps-src

chown -R root:root /neat-resources
chmod -R go-w /neat-resources
