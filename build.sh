#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${DOCKERFILE:-${SCRIPT_DIR}/Dockerfile}"
CONTEXT_DIR="${CONTEXT_DIR:-${SCRIPT_DIR}}"
IMAGE_NAME="${IMAGE_NAME:-sdk}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
MINIMAL_IMAGE="${MINIMAL_IMAGE:-0}"
BASE_SDK_VERSION="${BASE_SDK_VERSION:-2.1.0}"
NEAT_BRANCH="${NEAT_BRANCH:-main}"
NEAT_VERSION="${NEAT_VERSION:-latest}"
NEAT_INSIGHT_BRANCH="${NEAT_INSIGHT_BRANCH:-main}"
NEAT_INSIGHT_VERSION="${NEAT_INSIGHT_VERSION:-latest}"
NEAT_GITHUB_PAT="${NEAT_GITHUB_PAT:-${GITHUB_PAT:-}}"

usage() {
  cat <<EOF
Usage: $(basename "$0") [--minimal] [image_name] [image_tag]

Builds the Docker image for the current host architecture.

Environment overrides:
  DOCKERFILE   Path to the Dockerfile (default: ${DOCKERFILE})
  CONTEXT_DIR  Docker build context (default: ${CONTEXT_DIR})
  IMAGE_NAME   Docker image name (default: ${IMAGE_NAME})
  IMAGE_TAG    Docker image tag (default: ${IMAGE_TAG})
  MINIMAL_IMAGE  If set to 1, skip rustup/setup-sdk/sysroot-overlay and install sima-cli only for /neat-resources baking (default: ${MINIMAL_IMAGE})
  BASE_SDK_VERSION  Base eLxr/SiMa SDK package version to install (default: ${BASE_SDK_VERSION})
  NEAT_BRANCH  NEAT Framework branch to bake into /neat-resources (default: ${NEAT_BRANCH})
  NEAT_VERSION  NEAT Framework version/tag to bake into /neat-resources (default: ${NEAT_VERSION})
  NEAT_INSIGHT_BRANCH  neat-insight branch/release channel to install (default: ${NEAT_INSIGHT_BRANCH})
  NEAT_INSIGHT_VERSION  neat-insight version/tag to install, or latest (default: ${NEAT_INSIGHT_VERSION})
  NEAT_GITHUB_PAT  Secret token for cloning sima-neat/core during image build (default: from GITHUB_PAT or unset)
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
echo "Base SDK version: ${BASE_SDK_VERSION}"
echo "Minimal image mode: ${MINIMAL_IMAGE}"
if [[ "${MINIMAL_IMAGE}" == "1" ]]; then
  echo "Minimal mode note: full setup-sdk is skipped; sima-cli is installed via the official installer for baked /neat-resources."
fi
echo "NEAT branch: ${NEAT_BRANCH}"
echo "NEAT version: ${NEAT_VERSION}"
echo "NEAT Insight branch: ${NEAT_INSIGHT_BRANCH}"
echo "NEAT Insight version: ${NEAT_INSIGHT_VERSION}"

if docker buildx version >/dev/null 2>&1; then
  buildx_cmd=(
    docker buildx build
    --load
    --platform "${docker_platform}"
    --build-arg MINIMAL_IMAGE="${MINIMAL_IMAGE}"
    --build-arg BASE_SDK_VERSION="${BASE_SDK_VERSION}"
    --build-arg NEAT_BRANCH="${NEAT_BRANCH}"
    --build-arg NEAT_VERSION="${NEAT_VERSION}"
    --build-arg NEAT_INSIGHT_BRANCH="${NEAT_INSIGHT_BRANCH}"
    --build-arg NEAT_INSIGHT_VERSION="${NEAT_INSIGHT_VERSION}"
    --build-arg SDK_GIT_BRANCH="${git_branch}"
    --build-arg SDK_GIT_HASH="${git_hash}"
    -f "${DOCKERFILE}"
    -t "${image_ref}"
  )
  if [[ -n "${NEAT_GITHUB_PAT}" ]]; then
    buildx_cmd+=(--secret id=neat_github_pat,env=NEAT_GITHUB_PAT)
  fi
  buildx_cmd+=("${CONTEXT_DIR}")
  exec "${buildx_cmd[@]}"
fi

build_cmd=(
  docker build
  --platform "${docker_platform}"
  --build-arg MINIMAL_IMAGE="${MINIMAL_IMAGE}"
  --build-arg BASE_SDK_VERSION="${BASE_SDK_VERSION}"
  --build-arg NEAT_BRANCH="${NEAT_BRANCH}"
  --build-arg NEAT_VERSION="${NEAT_VERSION}"
  --build-arg NEAT_INSIGHT_BRANCH="${NEAT_INSIGHT_BRANCH}"
  --build-arg NEAT_INSIGHT_VERSION="${NEAT_INSIGHT_VERSION}"
  --build-arg SDK_GIT_BRANCH="${git_branch}"
  --build-arg SDK_GIT_HASH="${git_hash}"
  -f "${DOCKERFILE}"
  -t "${image_ref}"
)
if [[ -n "${NEAT_GITHUB_PAT}" ]]; then
  build_cmd+=(--secret id=neat_github_pat,env=NEAT_GITHUB_PAT)
  build_cmd+=("${CONTEXT_DIR}")
  exec env DOCKER_BUILDKIT=1 "${build_cmd[@]}"
fi
build_cmd+=("${CONTEXT_DIR}")
exec "${build_cmd[@]}"
