#!/usr/bin/env bash
if [[ $- == *i* ]]; then
  export SDK_IMAGE_BRANCH="${SDK_IMAGE_BRANCH:-${SDK_GIT_BRANCH:-main}}"
  export SDK_IMAGE_TAG="${SDK_IMAGE_TAG:-latest}"
  _sdk_prompt_slug() {
    local value="${1-}"
    value="${value//\//-}"
    value="${value//_/-}"
    value="$(printf '%s' "${value}" | tr '[:upper:]' '[:lower:]')"
    value="$(printf '%s' "${value}" | sed -E 's/[^a-z0-9-]+/-/g; s/-+/-/g; s/^-|-$//g')"
    printf '%s' "${value:-unknown}"
  }
  export SDK_PROMPT_HOSTNAME="${SDK_PROMPT_HOSTNAME:-neat-sdk-$(_sdk_prompt_slug "${SDK_IMAGE_BRANCH}")-$(_sdk_prompt_slug "${SDK_IMAGE_TAG}")}"
  _sdk_rewrite_prompt_hostname() {
    local prompt="${1-}"
    prompt="${prompt//\\h/${SDK_PROMPT_HOSTNAME}}"
    prompt="${prompt//\\H/${SDK_PROMPT_HOSTNAME}}"
    printf '%s' "${prompt}"
  }
  if [[ -n "${DEVKIT_SYNC_ORIG_PS1:-}" ]]; then
    DEVKIT_SYNC_ORIG_PS1="$(_sdk_rewrite_prompt_hostname "${DEVKIT_SYNC_ORIG_PS1}")"
    export DEVKIT_SYNC_ORIG_PS1
  fi
  if [[ -n "${PS1:-}" ]]; then
    PS1="$(_sdk_rewrite_prompt_hostname "${PS1}")"
    export PS1
  fi
  if declare -F __devkit_apply_prompt >/dev/null 2>&1; then
    __devkit_apply_prompt
  fi
fi
