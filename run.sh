#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-elxr}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_WORKDIR="${CONTAINER_WORKDIR:-/workspace}"
CONTAINER_NAME="${CONTAINER_NAME:-elxr}"
GHCR_OWNER="${GHCR_OWNER:-sima-neat}"
HOST_DIR="$(pwd)"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
REMOTE_IMAGE_REF="ghcr.io/${GHCR_OWNER}/${IMAGE_NAME}:${IMAGE_TAG}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [image_name] [image_tag]

Runs the Docker image and mounts the current directory at /workspace.

Environment overrides:
  IMAGE_NAME      Docker image name (default: ${IMAGE_NAME})
  IMAGE_TAG       Docker image tag (default: ${IMAGE_TAG})
  CONTAINER_NAME  Docker container name (default: ${CONTAINER_NAME})
  CONTAINER_WORKDIR  Container path to mount into (default: ${CONTAINER_WORKDIR})
  GHCR_OWNER      GitHub Packages owner/org (default: ${GHCR_OWNER})
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ $# -ge 1 ]]; then
  IMAGE_NAME="$1"
fi

if [[ $# -ge 2 ]]; then
  IMAGE_TAG="$2"
fi

if [[ $# -gt 2 ]]; then
  usage
  exit 1
fi

IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
REMOTE_IMAGE_REF="ghcr.io/${GHCR_OWNER}/${IMAGE_NAME}:${IMAGE_TAG}"

if docker pull "${REMOTE_IMAGE_REF}" >/dev/null 2>&1; then
  IMAGE_REF="${REMOTE_IMAGE_REF}"
  echo "Using GitHub Packages image ${IMAGE_REF}"
else
  echo "GitHub Packages image unavailable, falling back to local image ${IMAGE_REF}"
fi

image_platform="$(docker image inspect "${IMAGE_REF}" --format '{{.Os}}/{{.Architecture}}' 2>/dev/null || true)"

if [[ -n "${image_platform}" ]]; then
  echo "Resolved image platform: ${image_platform}"
else
  echo "Resolved image platform: unavailable"
fi

echo "Running ${IMAGE_REF}"
echo "Mounting ${HOST_DIR} to ${CONTAINER_WORKDIR}"

exec docker run --rm -it \
  --name "${CONTAINER_NAME}" \
  --privileged \
  -v "${HOST_DIR}:${CONTAINER_WORKDIR}" \
  -w "${CONTAINER_WORKDIR}" \
  -v /dev:/dev \
  --pid=host \
  "${IMAGE_REF}" \
  /bin/bash -l
