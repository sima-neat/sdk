#!/usr/bin/env bash

set -euo pipefail

mkdir -p /neat-resources/core-extra /neat-resources/core-src /neat-resources/apps-src

(
  cd /neat-resources/core-extra
  SIMA_CLI_CHECK_FOR_UPDATE=0 sima-cli neat install core@develop -t minimal
)

find /neat-resources/core-extra -type f \
  \( -name '*.deb' -o -name '*.tar.gz' -o -name '*.whl' \) -delete

if [[ -f /run/secrets/neat_github_pat && -s /run/secrets/neat_github_pat ]]; then
  NEAT_GITHUB_PAT="$(cat /run/secrets/neat_github_pat)"
  git clone --depth 1 "https://${NEAT_GITHUB_PAT}@github.com/sima-neat/core.git" /neat-resources/core-src
  git -C /neat-resources/core-src remote set-url origin https://github.com/sima-neat/core.git
else
  echo "Skipping sima-neat/core clone; neat_github_pat build secret not provided"
fi

git clone --depth 1 https://github.com/sima-neat/apps.git /neat-resources/apps-src

chown -R root:root /neat-resources
chmod -R go-w /neat-resources
