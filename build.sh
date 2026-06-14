#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKERFILE="${DOCKERFILE:-${SCRIPT_DIR}/Dockerfile}"
CONTEXT_DIR="${CONTEXT_DIR:-${SCRIPT_DIR}}"
IMAGE_NAME="${IMAGE_NAME:-sdk}"
IMAGE_TAG="${IMAGE_TAG:-latest}"
MINIMAL_IMAGE="${MINIMAL_IMAGE:-0}"
SDK_BASE_IMAGE="${SDK_BASE_IMAGE:-ubuntu:24.04}"
SDK_CROSS_TOOLCHAIN_IMAGE="${SDK_CROSS_TOOLCHAIN_IMAGE:-debian:bookworm}"
DOCKER_PLATFORM="${DOCKER_PLATFORM:-}"
BASE_SDK_VERSION="${BASE_SDK_VERSION:-2.1.2}"
NEAT_BRANCH="${NEAT_BRANCH:-main}"
NEAT_VERSION="${NEAT_VERSION:-latest}"
NEAT_CORE_TARGET="${NEAT_CORE_TARGET:-}"
NEAT_INSIGHT_BRANCH="${NEAT_INSIGHT_BRANCH:-}"
NEAT_INSIGHT_VERSION="${NEAT_INSIGHT_VERSION:-}"

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
  DOCKER_PLATFORM  Docker platform to build, e.g. linux/amd64 or linux/arm64 (default: current host)
  SDK_BASE_IMAGE  Base Docker image for the SDK host/container userspace (default: ${SDK_BASE_IMAGE})
  SDK_CROSS_TOOLCHAIN_IMAGE  Base image used only to source the pinned aarch64 cross compiler (default: ${SDK_CROSS_TOOLCHAIN_IMAGE})
  BASE_SDK_VERSION  Base eLxr/SiMa SDK package version to install (default: ${BASE_SDK_VERSION})
  NEAT_BRANCH  NEAT Framework branch to bake into /neat-resources (default: ${NEAT_BRANCH})
  NEAT_VERSION  NEAT Framework version/tag to bake into /neat-resources (default: ${NEAT_VERSION})
  NEAT_CORE_TARGET  Override the Neat Core Vulcan package target from deps/manifest.json
  NEAT_INSIGHT_BRANCH  Override the Insight branch/release channel from deps/manifest.json
  NEAT_INSIGHT_VERSION  Override the Insight version/tag from deps/manifest.json
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
git_tag=""
if [[ "${GITHUB_REF_TYPE:-}" == "tag" && -n "${GITHUB_REF_NAME:-}" ]]; then
  git_tag="${GITHUB_REF_NAME}"
elif [[ -z "${GITHUB_REF_TYPE:-}" ]]; then
  git_tag="$(git -C "${SCRIPT_DIR}" describe --tags --exact-match HEAD 2>/dev/null || true)"
fi

if [[ -z "${git_branch}" ]]; then
  if [[ "${GITHUB_REF_TYPE:-}" == "branch" && -n "${GITHUB_REF_NAME:-}" ]]; then
    git_branch="${GITHUB_REF_NAME}"
  else
    git_branch="unknown"
  fi
fi

if [[ -z "${git_hash}" ]]; then
  git_hash="nogit"
fi

git_branch="${git_branch//\//_}"

if [[ -n "${git_tag}" ]]; then
  sdk_release_ref="${git_tag}"
else
  sdk_release_ref="${git_branch}-${git_hash}"
fi

host_arch="$(uname -m)"

if [[ -n "${DOCKER_PLATFORM}" ]]; then
  docker_platform="${DOCKER_PLATFORM}"
else
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
fi

image_ref="${IMAGE_NAME}:${IMAGE_TAG}"

echo "Building ${image_ref}"
echo "Host architecture: ${host_arch}"
echo "Docker platform: ${docker_platform}"
echo "Git branch: ${git_branch}"
echo "Git hash: ${git_hash}"
echo "SDK release ref: ${sdk_release_ref}"
echo "Base SDK version: ${BASE_SDK_VERSION}"
echo "SDK base image: ${SDK_BASE_IMAGE}"
echo "SDK cross toolchain image: ${SDK_CROSS_TOOLCHAIN_IMAGE}"
echo "Minimal image mode: ${MINIMAL_IMAGE}"
if [[ "${MINIMAL_IMAGE}" == "1" ]]; then
  echo "Minimal mode note: full setup-sdk is skipped; sima-cli is installed via the official installer for baked /neat-resources."
fi
echo "NEAT branch: ${NEAT_BRANCH}"
echo "NEAT version: ${NEAT_VERSION}"
echo "NEAT Core target override: ${NEAT_CORE_TARGET:-<deps/manifest.json>}"
echo "NEAT Insight branch override: ${NEAT_INSIGHT_BRANCH:-<deps/manifest.json>}"
echo "NEAT Insight version override: ${NEAT_INSIGHT_VERSION:-<deps/manifest.json>}"

if docker buildx version >/dev/null 2>&1; then
  buildx_cmd=(
    docker buildx build
    --load
    --platform "${docker_platform}"
    --build-arg MINIMAL_IMAGE="${MINIMAL_IMAGE}"
    --build-arg SDK_BASE_IMAGE="${SDK_BASE_IMAGE}"
    --build-arg SDK_CROSS_TOOLCHAIN_IMAGE="${SDK_CROSS_TOOLCHAIN_IMAGE}"
    --build-arg BASE_SDK_VERSION="${BASE_SDK_VERSION}"
    --build-arg NEAT_BRANCH="${NEAT_BRANCH}"
    --build-arg NEAT_VERSION="${NEAT_VERSION}"
    --build-arg NEAT_CORE_TARGET="${NEAT_CORE_TARGET}"
    --build-arg NEAT_INSIGHT_BRANCH="${NEAT_INSIGHT_BRANCH}"
    --build-arg NEAT_INSIGHT_VERSION="${NEAT_INSIGHT_VERSION}"
    --build-arg SDK_GIT_BRANCH="${git_branch}"
    --build-arg SDK_GIT_HASH="${git_hash}"
    --build-arg SDK_RELEASE_REF="${sdk_release_ref}"
    -f "${DOCKERFILE}"
    -t "${image_ref}"
  )
  buildx_cmd+=("${CONTEXT_DIR}")
  exec "${buildx_cmd[@]}"
fi

build_cmd=(
  docker build
  --platform "${docker_platform}"
  --build-arg MINIMAL_IMAGE="${MINIMAL_IMAGE}"
  --build-arg SDK_BASE_IMAGE="${SDK_BASE_IMAGE}"
  --build-arg SDK_CROSS_TOOLCHAIN_IMAGE="${SDK_CROSS_TOOLCHAIN_IMAGE}"
  --build-arg BASE_SDK_VERSION="${BASE_SDK_VERSION}"
  --build-arg NEAT_BRANCH="${NEAT_BRANCH}"
  --build-arg NEAT_VERSION="${NEAT_VERSION}"
  --build-arg NEAT_CORE_TARGET="${NEAT_CORE_TARGET}"
  --build-arg NEAT_INSIGHT_BRANCH="${NEAT_INSIGHT_BRANCH}"
  --build-arg NEAT_INSIGHT_VERSION="${NEAT_INSIGHT_VERSION}"
  --build-arg SDK_GIT_BRANCH="${git_branch}"
  --build-arg SDK_GIT_HASH="${git_hash}"
  --build-arg SDK_RELEASE_REF="${sdk_release_ref}"
  -f "${DOCKERFILE}"
  -t "${image_ref}"
)
build_cmd+=("${CONTEXT_DIR}")
exec "${build_cmd[@]}"
