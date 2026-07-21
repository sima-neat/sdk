#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "${TMP_DIR}"' EXIT

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/neat-deps.sh"

export SDK_DEPS_MANIFEST="${TMP_DIR}/manifest.json"
cat > "${SDK_DEPS_MANIFEST}" <<'JSON'
{
  "core": {
    "ref": "v0.3.0"
  }
}
JSON

[[ "$(neat_dependency_target core core)" == "core@v0.3.0" ]]
[[ "$(neat_dependency_ref core)" == "v0.3.0" ]]

export SDK_DEPS_MANIFEST="${ROOT_DIR}/deps/manifest.json"
[[ "$(neat_dependency_ref core)" == "v0.3.0" ]]
[[ "$(neat_dependency_ref apps)" == "main:latest" ]]
[[ "$(neat_dependency_ref sima-cli)" == "v2.1.15" ]]

git_repo="${TMP_DIR}/git-source"
git init --quiet "${git_repo}"
git -C "${git_repo}" config user.name test
git -C "${git_repo}" config user.email test@example.com
printf 'source\n' > "${git_repo}/README"
git -C "${git_repo}" add README
git -C "${git_repo}" commit --quiet -m source
git -C "${git_repo}" branch -M main
git -C "${git_repo}" tag -a v1.0.0 -m v1.0.0
expected_commit="$(git -C "${git_repo}" rev-parse HEAD)"

[[ "$(neat_resolve_git_ref "${git_repo}" v1.0.0)" == "${expected_commit}" ]]
[[ "$(neat_resolve_git_ref "${git_repo}" main:latest)" == "${expected_commit}" ]]
[[ "$(neat_resolve_git_ref "${git_repo}" "${expected_commit}")" == "${expected_commit}" ]]

echo "Neat dependency manifest tests passed."
