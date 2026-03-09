#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${DOCKERFILE:-${SCRIPT_DIR}/Dockerfile}"
CONTEXT_DIR="${CONTEXT_DIR:-${SCRIPT_DIR}}"
IMAGE_NAME="${IMAGE_NAME:-elxr}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
MINIMAL_IMAGE="${MINIMAL_IMAGE:-0}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--minimal] [image_name] [image_tag]

Builds the Docker image for the current host architecture.

Environment overrides:
  DOCKERFILE   Path to the Dockerfile (default: ${DOCKERFILE})
  CONTEXT_DIR  Docker build context (default: ${CONTEXT_DIR})
  IMAGE_NAME   Docker image name (default: ${IMAGE_NAME})
  IMAGE_TAG    Docker image tag (default: ${IMAGE_TAG})
  MINIMAL_IMAGE  If set to 1, skip rustup/setup-sdk/sysroot-overlay (default: ${MINIMAL_IMAGE})
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --minimal)
      MINIMAL_IMAGE=1
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

if [[ ! -f "${DOCKERFILE}" ]]; then
  echo "Dockerfile not found: ${DOCKERFILE}" >&2
  exit 1
fi

git_branch="$(git -C "${SCRIPT_DIR}" branch --show-current 2>/dev/null || true)"
git_hash="$(git -C "${SCRIPT_DIR}" rev-parse --short HEAD 2>/dev/null || true)"

if [[ -z "${git_branch}" ]]; then
  git_branch="unknown"
fi

if [[ -z "${git_hash}" ]]; then
  git_hash="nogit"
fi

git_branch="${git_branch//\//_}"

host_arch="$(uname -m)"

case "${host_arch}" in
  x86_64|amd64)
    docker_platform="linux/amd64"
    ;;
  aarch64|arm64)
    docker_platform="linux/arm64"
    ;;
  *)
    echo "Unsupported host architecture: ${host_arch}" >&2
    exit 1
    ;;
esac

image_ref="${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building ${image_ref}"
echo "Host architecture: ${host_arch}"
echo "Docker platform: ${docker_platform}"
echo "Git branch: ${git_branch}"
echo "Git hash: ${git_hash}"
echo "Minimal image mode: ${MINIMAL_IMAGE}"

if docker buildx version >/dev/null 2>&1; then
  exec docker buildx build \
    --load \
    --platform "${docker_platform}" \
    --build-arg MINIMAL_IMAGE="${MINIMAL_IMAGE}" \
    --build-arg SDK_GIT_BRANCH="${git_branch}" \
    --build-arg SDK_GIT_HASH="${git_hash}" \
    -f "${DOCKERFILE}" \
    -t "${image_ref}" \
    "${CONTEXT_DIR}"
fi

exec docker build \
  --platform "${docker_platform}" \
  --build-arg MINIMAL_IMAGE="${MINIMAL_IMAGE}" \
  --build-arg SDK_GIT_BRANCH="${git_branch}" \
  --build-arg SDK_GIT_HASH="${git_hash}" \
  -f "${DOCKERFILE}" \
  -t "${image_ref}" \
  "${CONTEXT_DIR}"
