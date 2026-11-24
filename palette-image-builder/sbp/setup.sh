#!/bin/bash
#
# Copyright (c) 2026 SiMa.ai Technologies, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# "pib package" set-up. pib-entrypoint runs it, as root, before pib package (not for its help);
# then the pib command runs, as root too, like every pib command (it hands what it writes back
# to PIB_UID:PIB_GID). It prepares what sbp expects from SiMa's eLxr builder image (swsoc-elxr
# Dockerfile and files/startup.sh):
#   - sbp's settings, for this process only: pib build reads several of the same names
#     (BUILD, BUILD_TYPE, REPO, KEY_PATH), so none is set in the image
#   - sbp's own local apt repo ${REPO_ROOT}${BUILD_TYPE} on the pib-package volume (not PIB's
#     /var/www/html/deb/custom, which pib build rebuilds from custom-debs/ on every start),
#     served at http://localhost/deb/ by nginx on 127.0.0.1 only and signed with a key made
#     for this run alone; sbp re-signs it after every package, so the key lives as long as the run
#   - /etc/apt/sources.list.d/simaai.list in the form sbp rewrites, and pins: sbp's repo 999,
#     SiMa.ai's release repo 950, eLxr 900, as SiMa's CI ranks them. The repo holds the kernel
#     sbp built (6.18.3-<n>, below SiMa's 6.18.3-2796): only the pin makes kernel-module
#     packages compile against it rather than against SiMa's headers.
#   - git: read-only host repositories stand in for remote ones, so no credential enters the
#     container: mirrors of SiMa.ai's private Bitbucket repositories (PIB_GIT_MIRRORS), and
#     the user's own kernel repository (PIB_KERNEL_SRC)
set -euo pipefail

die() { echo "pib: $*" >&2; exit 1; }

export SBP_WORKSPACE=/var/tmp/pib-package
export REPO_ROOT=/var/tmp/pib-package/repo/    # sbp appends BUILD_TYPE: keep the trailing /
export BUILD_TYPE=custom                       # release, pre-release and daily are SiMa CI's
export REPO_PUSH=http://localhost              # anything else makes sbp scp/ssh its packages away
export REPO_PULL=http://localhost/deb/custom   # only what sbp built: a missing package fails loudly
# sbp imports from DAILY_MIRROR (unverified) unless every group is selected; pib package always
# passes -g all, and a mirror that does not exist turns any slip into an error, not an import.
export DAILY_MIRROR=http://localhost/pib-no-daily-mirror
export KEY_PATH=/usr/share/keyrings/simaai-public.gpg
export GIT_CACHE_BYPASS=1                      # else sbp keeps a full extra copy of each clone
export CCACHE_MAXSIZE="${PIB_CCACHE_SIZE:-5G}" # ccache on the volume
export PYTHONDONTWRITEBYTECODE=1
# Who built it, in the packages and the kernel's version string: not this container's name.
export KBUILD_BUILD_USER=pib KBUILD_BUILD_HOST=pib-package
export DEBFULLNAME="PIB local build" DEBEMAIL=pib-package@localhost

codename="$(< /etc/pib-codename)"
release="$(< /etc/pib-release)"
repo="${REPO_ROOT}${BUILD_TYPE}"

# --- the volume: sbp's work tree, ccache and local repo, for one release ------------------------
mkdir -p "$repo/conf"
mark="$SBP_WORKSPACE/.pib-release"
if [[ -f "$mark" && "$(< "$mark")" != "$release $codename" ]]; then
    die "the pib-package volume holds builds for $(< "$mark"), not $release $codename;" \
        "set PIB_PACKAGE_VOLUME to another name, or remove the volume (docker volume rm <name>)"
fi
printf '%s %s\n' "$release" "$codename" > "$mark"

# --- sbp's local apt repo, signed with a key made for this run ----------------------------------
# sbp names the keyring of its localhost lines itself: /usr/share/keyrings/custom-repo.gpg.
sed "s/@CODENAME@/${codename}/" /usr/share/pib/sbp/distributions.in > "$repo/conf/distributions"
GNUPGHOME="$(mktemp -d)"
export GNUPGHOME
key_uid="PIB package local repo <pib-package@localhost>"
gpg --batch --quiet --passphrase '' --quick-gen-key "$key_uid" ed25519 sign never 2>/dev/null || \
    die "cannot create the local repo signing key"
gpg --batch --export "$key_uid" > /usr/share/keyrings/custom-repo.gpg
reprepro -b "$repo" --silent export "$codename"

# --- nginx: sbp's repo only, on loopback; the image's own site is for pib build ------------------
rm -f /etc/nginx/sites-enabled/*
sed "s#@REPO_ROOT@#${REPO_ROOT%/}#" /usr/share/pib/sbp/nginx.conf.in \
    > /etc/nginx/sites-enabled/pib-package
nginx -q -t && nginx

# --- apt: pins, and the simaai.list template sbp rewrites (sbp modules/pacman.py) -----------------
cp /usr/share/pib/sbp/90-pib-sbp.pref /etc/apt/preferences.d/90-pib-sbp.pref
printf 'deb [signed-by=/usr/share/keyrings/custom-repo.gpg] %s %s non-free #simaai repo\n' \
    "$REPO_PULL" "$codename" > /etc/apt/sources.list.d/simaai.list
if ! apt-get update -qq -o Acquire::Retries=3 > /tmp/pib-package-apt-update.log 2>&1; then
    cat /tmp/pib-package-apt-update.log >&2
    die "apt-get update failed"
fi
grep -E '^(W|E|Err):' /tmp/pib-package-apt-update.log >&2 || true

# --- git: host repositories stand in for remote ones (read-only, no credentials) -----------------
#   - A mirror /mirrors/<name>.git stands in for SiMa.ai's Bitbucket repository <name>.git
#     (sima-ai; private, and the container has no credentials): every URL form sbp's configs use
#     is rewritten into the mirrors directory, so a repository without a mirror fails at once,
#     locally. GitHub URLs are never rewritten: what a GitHub URL names is what gets built.
#   - The user's kernel repository (PIB_KERNEL_SRC: the launcher mounts its git directory, a
#     checkout's .git or a bare repository) stands in for the URL below, which pib package writes
#     into the kernel's config (sbp clones only http, https and ssh URLs). It is not a real host
#     (.invalid): should the map ever be missing, the clone fails instead of fetching anything else.
#   - A remote kernel repository is cloned from pib package's copy of it on the volume, mapped
#     for sbp alone (pib package, GIT_CONFIG_* variables), so that pib's own fetch of it still
#     reaches it.
# git makes a local copy (no pack walk over every object, as file:// would). The settings go to this
# container's system config, not to GIT_CONFIG_* variables: git drops those for the process that
# reads a local source repository, and safe.directory (the repositories belong to the host user,
# not root) must reach it. Git never asks for credentials here: nobody could answer.
export GIT_TERMINAL_PROMPT=0
export PIB_KERNEL_SRC_URL=https://pib.invalid/PIB_KERNEL_SRC.git
if [[ -n "${PIB_GIT_MIRRORS:-}" ]]; then
    [[ -d "$PIB_GIT_MIRRORS" ]] || die "PIB_GIT_MIRRORS=$PIB_GIT_MIRRORS is not mounted"
    for form in ssh://git@ssh.bitbucket.org/sima-ai/ ssh://git@bitbucket.org/sima-ai/ \
                git@bitbucket.org:sima-ai/ https://bitbucket.org/sima-ai/; do
        git config --system --add "url.${PIB_GIT_MIRRORS%/}/.insteadOf" "$form"
    done
    shopt -s nullglob
    for mirror in "$PIB_GIT_MIRRORS"/*.git; do
        git config --system --add safe.directory "$mirror"
    done
    shopt -u nullglob
fi
if [[ -n "${PIB_KERNEL_SRC:-}" ]]; then
    [[ -d "$PIB_KERNEL_SRC" ]] || die "PIB_KERNEL_SRC=$PIB_KERNEL_SRC is not mounted"
    git config --system --add "url.${PIB_KERNEL_SRC}.insteadOf" "$PIB_KERNEL_SRC_URL"
    git config --system --add safe.directory "$PIB_KERNEL_SRC"  # a git directory: git -C and clones
fi

# pib package builds only after this set-up: run any other way (inside pib shell, say), sbp
# would use its own defaults and publish into PIB's own local repo.
export PIB_PACKAGE_SETUP=1
cd /workspace
exec "$@"
