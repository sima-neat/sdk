#!/usr/bin/env bash

set -euo pipefail

mkdir -p /neat-resources/core-extra /neat-resources/core-src /neat-resources/apps-src

wget -O /tmp/install-neat.sh https://tools.sima-neat.com/install-neat.sh
(
  cd /neat-resources/core-extra
  bash /tmp/install-neat.sh --minimum "${NEAT_BRANCH:-main}" "${NEAT_VERSION:-latest}"
)
rm -f /tmp/install-neat.sh

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
