#!/usr/bin/env bash

set -euo pipefail

neat_deps_manifest_path() {
  local script_dir repo_manifest image_manifest
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_manifest="${script_dir}/../deps/manifest.json"
  image_manifest="/usr/local/share/sima-sdk/deps/manifest.json"

  if [[ -n "${SDK_DEPS_MANIFEST:-}" ]]; then
    printf '%s\n' "${SDK_DEPS_MANIFEST}"
  elif [[ -f "${image_manifest}" ]]; then
    printf '%s\n' "${image_manifest}"
  else
    printf '%s\n' "${repo_manifest}"
  fi
}

neat_dependency_target() {
  local key="$1"
  local repo="$2"
  local manifest

  manifest="$(neat_deps_manifest_path)"
  python3 - "${manifest}" "${key}" "${repo}" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
key, repo = sys.argv[2:4]


def validate_ref(raw: str) -> str:
    ref = raw.strip()
    if not ref:
        raise SystemExit(f"ERROR: {manifest_path} dependency {key!r} has an empty ref.")
    if "@" in ref or any(ch.isspace() for ch in ref):
        raise SystemExit(
            f"ERROR: {manifest_path} dependency {key!r} ref must not contain '@' or whitespace: {ref!r}"
        )
    if ":" not in ref:
        if not re.fullmatch(r"[A-Za-z0-9._/-]+", ref):
            raise SystemExit(
                f"ERROR: {manifest_path} dependency {key!r} ref must be a git tag/ref like v0.1.0: {ref!r}"
            )
        return ref
    if ref.count(":") != 1:
        raise SystemExit(
            f"ERROR: {manifest_path} dependency {key!r} ref must be tag, branch:latest, or branch:githash: {ref!r}"
        )
    branch, spec = (part.strip() for part in ref.split(":", 1))
    if not branch or not spec:
        raise SystemExit(
            f"ERROR: {manifest_path} dependency {key!r} ref must include both branch and spec: {ref!r}"
        )
    if not re.fullmatch(r"[A-Za-z0-9._/-]+", branch):
        raise SystemExit(
            f"ERROR: {manifest_path} dependency {key!r} branch contains unsupported characters: {branch!r}"
        )
    if spec != "latest" and not re.fullmatch(r"[A-Fa-f0-9]+", spec):
        raise SystemExit(
            f"ERROR: {manifest_path} dependency {key!r} spec must be 'latest' or a git hash: {spec!r}"
        )
    return f"{branch}:{spec}"


if not manifest_path.exists():
    raise SystemExit(f"ERROR: dependency manifest not found: {manifest_path}")

data = json.loads(manifest_path.read_text(encoding="utf-8"))
value = data.get(key)
if value is None:
    raise SystemExit(f"ERROR: {manifest_path} must define dependency {key!r}.")

if isinstance(value, str):
    print(f"{repo}@{validate_ref(value)}")
    raise SystemExit(0)

if isinstance(value, dict):
    ref = str(value.get("ref", "")).strip()
    if ref:
        print(f"{repo}@{validate_ref(ref)}")
        raise SystemExit(0)

    raise SystemExit(f"ERROR: {manifest_path} dependency {key!r} must define a non-empty ref.")

raise SystemExit(
    f"ERROR: {manifest_path} field {key!r} must be a string or object with "
    "{'ref':'...'} using tag, branch:latest, or branch:githash."
)
PY
}

neat_dependency_ref() {
  local key="$1"
  local marker="manifest-ref"
  local target

  target="$(neat_dependency_target "${key}" "${marker}")"
  printf '%s\n' "${target#"${marker}"@}"
}

neat_resolve_git_ref() {
  local repository="$1"
  local spec="$2"
  local branch version refs resolved

  if [[ "${spec}" =~ ^[0-9a-fA-F]{40}$ ]]; then
    printf '%s\n' "${spec}" | tr '[:upper:]' '[:lower:]'
    return
  fi

  if [[ "${spec}" == *:* ]]; then
    branch="${spec%%:*}"
    version="${spec#*:}"
    if [[ -z "${branch}" || "${version}" != "latest" ]]; then
      echo "Git source refs must use branch:latest, a tag, or a full commit SHA: ${spec}" >&2
      return 1
    fi
    resolved="$(git ls-remote "${repository}" "refs/heads/${branch}" | awk 'NR == 1 {print $1}')"
  else
    refs="$(git ls-remote "${repository}" "refs/tags/${spec}" "refs/tags/${spec}^{}")"
    resolved="$(awk '$2 ~ /\^\{\}$/ {print $1; exit}' <<< "${refs}")"
    if [[ -z "${resolved}" ]]; then
      resolved="$(awk 'NR == 1 {print $1}' <<< "${refs}")"
    fi
  fi

  if [[ ! "${resolved}" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo "Unable to resolve ${repository} ref ${spec} to a full Git commit SHA." >&2
    return 1
  fi
  printf '%s\n' "${resolved}" | tr '[:upper:]' '[:lower:]'
}

neat_resolve_dependency_source_ref() {
  local key="$1"
  local repository="$2"

  neat_resolve_git_ref "${repository}" "$(neat_dependency_ref "${key}")"
}
