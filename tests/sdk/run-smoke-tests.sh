#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${IMAGE_REF:-}" ]]; then
  echo "IMAGE_REF is required." >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTAINER_ID="$(docker ps -q --filter "ancestor=${IMAGE_REF}" | head -n 1)"

if [[ -z "${CONTAINER_ID}" ]]; then
  echo "No running SDK container found for image ${IMAGE_REF}." >&2
  docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}' >&2
  exit 1
fi

REMOTE_DIR="/tmp/neat-sdk-smoke-tests"
docker exec "${CONTAINER_ID}" rm -rf "${REMOTE_DIR}"
docker cp "${SCRIPT_DIR}/." "${CONTAINER_ID}:${REMOTE_DIR}"
docker exec "${CONTAINER_ID}" chmod +x "${REMOTE_DIR}/run-in-container.sh"
docker exec "${CONTAINER_ID}" bash "${REMOTE_DIR}/run-in-container.sh"
