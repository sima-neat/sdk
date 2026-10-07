#!/usr/bin/env bash
set -euo pipefail

image_ref="${1:-}"
if [[ -z "${image_ref}" ]]; then
  echo "Usage: $(basename "$0") SDK_IMAGE_REF" >&2
  exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
sdk_arch="$(docker image inspect "${image_ref}" --format '{{.Architecture}}')"
container_name="neat-sdk-buildx-smoke-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
remote_root=/tmp/neat-sdk-smoke-tests/container-build
remote_user=buildx-smoke

cleanup() {
  docker rm -f "${container_name}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run -d --name "${container_name}" \
  -e NEAT_INSIGHT_SUPERVISED=0 \
  -e OPENVSCODE_SERVER_SUPERVISED=0 \
  -e OPENVSCODE_SERVER_USER="${remote_user}" \
  -e DOCKER_HOST=unix:///var/run/docker.sock \
  -v /var/run/docker.sock:/var/run/docker.sock \
  "${image_ref}" sleep infinity >/dev/null

docker exec -u root "${container_name}" mkdir -p "$(dirname "${remote_root}")"
docker cp "${script_dir}/." "${container_name}:${remote_root}"
docker cp "${script_dir}/../hello-neat" "${container_name}:${remote_root}/hello-neat"
docker exec -u root "${container_name}" bash -lc "
  set -euo pipefail
  useradd --create-home --shell /bin/bash '${remote_user}'
  socket_gid=\$(stat -c %g /var/run/docker.sock)
  groupmod -o -g \"\${socket_gid}\" docker
  usermod -aG docker '${remote_user}'
  chown -R '${remote_user}' '${remote_root}'
  chmod +x '${remote_root}/run.sh'
"

"${script_dir}/run.sh" "${container_name}"

echo "ARM64 container build validated from the ${sdk_arch} SDK image."
