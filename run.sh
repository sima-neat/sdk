#!/usr/bin/env bash

set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-elxr}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
CONTAINER_WORKDIR="${CONTAINER_WORKDIR:-/workspace}"
CONTAINER_NAME="${CONTAINER_NAME:-elxr}"
GHCR_OWNER="${GHCR_OWNER:-sima-neat}"
PREFER_LOCAL="${PREFER_LOCAL:-0}"
HOST_DIR="$(pwd)"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"
REMOTE_IMAGE_REF="ghcr.io/${GHCR_OWNER}/${IMAGE_NAME}:${IMAGE_TAG}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--prefer-local] [image_name] [image_tag]

Runs the Docker image and mounts the current directory at /workspace.

Environment overrides:
  IMAGE_NAME      Docker image name (default: ${IMAGE_NAME})
  IMAGE_TAG       Docker image tag (default: ${IMAGE_TAG})
  CONTAINER_NAME  Docker container name (default: ${CONTAINER_NAME})
  CONTAINER_WORKDIR  Container path to mount into (default: ${CONTAINER_WORKDIR})
  GHCR_OWNER      GitHub Packages owner/org (default: ${GHCR_OWNER})
  PREFER_LOCAL    If set to 1, prefer a local image before GHCR (default: ${PREFER_LOCAL})
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --prefer-local)
      PREFER_LOCAL=1
      shift
      ;;
    *)
      break
      ;;
  esac
done

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

if [[ "${PREFER_LOCAL}" == "1" ]] && docker image inspect "${IMAGE_REF}" >/dev/null 2>&1; then
  echo "Preferring local image ${IMAGE_REF}"
elif [[ "${PREFER_LOCAL}" == "1" ]]; then
  echo "Preferred local image ${IMAGE_REF} not found, trying GitHub Packages image ${REMOTE_IMAGE_REF}"
  if docker pull "${REMOTE_IMAGE_REF}"; then
    IMAGE_REF="${REMOTE_IMAGE_REF}"
    echo "Using GitHub Packages image ${IMAGE_REF}"
  else
    echo "Unable to pull GitHub Packages image ${REMOTE_IMAGE_REF}" >&2
    exit 1
  fi
else
  echo "Trying GitHub Packages image ${REMOTE_IMAGE_REF}"
  if docker pull "${REMOTE_IMAGE_REF}"; then
    IMAGE_REF="${REMOTE_IMAGE_REF}"
    echo "Using GitHub Packages image ${IMAGE_REF}"
  elif docker image inspect "${IMAGE_REF}" >/dev/null 2>&1; then
    echo "GitHub Packages image unavailable, falling back to local image ${IMAGE_REF}"
  else
    echo "Unable to pull GitHub Packages image ${REMOTE_IMAGE_REF}" >&2
    echo "Local fallback image ${IMAGE_REF} is also not present." >&2
    echo "If the GHCR package is private, run: docker login ghcr.io" >&2
    exit 1
  fi
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
