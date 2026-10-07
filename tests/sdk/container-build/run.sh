#!/usr/bin/env bash
set -euo pipefail

container_id="${1:-}"
if [[ -z "${container_id}" ]]; then
  echo "Usage: $(basename "$0") SDK_CONTAINER_ID" >&2
  exit 2
fi

remote_root=/tmp/neat-sdk-smoke-tests/container-build
image="neat-sdk-buildx-smoke:${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
remote_user="$(docker exec "${container_id}" printenv OPENVSCODE_SERVER_USER 2>/dev/null || true)"
remote_user="${remote_user:-root}"

cleanup() {
  docker exec -u "${remote_user}" "${container_id}" \
    docker image rm -f "${image}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker exec -u root "${container_id}" chown -R "${remote_user}" "${remote_root}"
docker exec -u "${remote_user}" "${container_id}" bash -lc "
  set -euo pipefail
  source /opt/bin/simaai-init-build-env modalix >/dev/null
  docker buildx version
  docker buildx inspect --bootstrap
  rm -rf \"${remote_root}/context/neat-artifacts\"
  mkdir -p \"${remote_root}/context/neat-artifacts\"
  sima_neat_config=\"\$(find \"\${SYSROOT}/usr\" -type f -name SimaNeatConfig.cmake -print -quit)\"
  if [[ -n \"\${sima_neat_config}\" ]]; then
    cmake -S \"${remote_root}/hello-neat\" -B \"${remote_root}/hello-neat/build\" -DCMAKE_BUILD_TYPE=Release
    cmake --build \"${remote_root}/hello-neat/build\" -j\"\$(nproc)\"
    file \"${remote_root}/hello-neat/build/sima_neat_hello\" | grep -Eq 'aarch64|ARM aarch64|ARM64'
    cp \"${remote_root}/hello-neat/build/sima_neat_hello\" \"${remote_root}/context/neat-artifacts/sima_neat_hello\"
  else
    echo 'SimaNeat is not bundled; skipping the optional Hello Neat artifact.'
  fi
  \"\${CC}\" \${CFLAGS} \"${remote_root}/context/main.c\" -o \"${remote_root}/context/buildx-smoke\"
  file \"${remote_root}/context/buildx-smoke\" | grep -Eq 'aarch64|ARM aarch64|ARM64'
  docker buildx build --platform linux/arm64 --load -t \"${image}\" \"${remote_root}/context\"
  test \"\$(docker image inspect \"${image}\" --format '{{.Architecture}}')\" = arm64
  if [[ -n \"\${sima_neat_config}\" ]]; then
    docker run --rm --entrypoint test \"${image}\" -x /opt/neat/bin/sima_neat_hello
  else
    test \"\$(docker run --rm --entrypoint find \"${image}\" /opt/neat/bin -mindepth 1 -print -quit)\" = ''
  fi
  test \"\$(docker run --rm \"${image}\")\" = neat-sdk-buildx-arm64-ok
"

echo "SDK Buildx ARM64 image smoke test passed."
