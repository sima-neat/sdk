#!/usr/bin/env bash
if [[ $- == *i* ]]; then
  export SDK_IMAGE_TAG="${SDK_IMAGE_TAG:-version}"
  export SDK_PROMPT_HOSTNAME="${SDK_PROMPT_HOSTNAME:-neat-sdk-${SDK_IMAGE_TAG}}"
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
