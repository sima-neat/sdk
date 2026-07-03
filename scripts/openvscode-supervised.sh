#!/usr/bin/env bash
set -euo pipefail

if [[ "${OPENVSCODE_SERVER_SUPERVISED:-1}" == "0" ]]; then
  echo "OpenVSCode Server supervision disabled by OPENVSCODE_SERVER_SUPERVISED=0"
  exit 0
fi

exec /usr/local/bin/sima-code "${OPENVSCODE_WORKSPACE:-/workspace}"
