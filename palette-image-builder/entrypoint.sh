#!/bin/bash
#
# Copyright (c) 2026 SiMa.ai Technologies, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# Palette Image Builder container entrypoint.
#
# For "pib build" and a shell, prepares what "rs build" expects from its
# surroundings, then runs the given command (bash when none); other pib commands run directly:
#   - automatic registration of the packaged arm64 emulator on x86 Docker hosts
#   - a local apt repo at http://localhost/deb/custom holding every .deb in
#     /workspace/custom-debs, signed with a key made for this run alone; the
#     image's apt pinning ranks it above SiMa.ai's repo, so a customer
#     kernel replaces SiMa.ai's
#   - SOURCE_DATE_EPOCH from /etc/pib-release-epoch (the release's package
#     index date, read when the image was built), for reproducible file times
# "pib package" runs sbp/setup.sh (/usr/local/lib/pib/sbp-setup) instead.
#
# Inputs (environment):
#   SWU_SIGNING_KEY,
#   SWU_SIGNING_CERT - used by sign, or by build --sign after rootfs assembly
set -eo pipefail

# Other pib commands need none of the set-up below.
case "${1:-} ${2:-}" in
    "pib doctor") python3 -m pib.emulation; exec "$@" ;;
    "pib build" | bash*) python3 -m pib.emulation ;;
    # Package builds have their own set-up (sbp/setup.sh); the container is unprivileged, so
    # the emulator is not registered here (pib doctor does). Help needs no set-up, nor does
    # "pib package" alone, a usage error; everything else (also --list) gets it.
    "pib package")
        [ $# -gt 2 ] || exec "$@"
        for arg in "${@:3}"; do case "$arg" in -h | --help) exec "$@" ;; esac; done
        if [ -x /usr/local/lib/pib/sbp-setup ]; then exec /usr/local/lib/pib/sbp-setup "$@"; fi
        exec "$@" ;;
    *) exec "$@" ;;
esac

DEBS=/workspace/custom-debs
CODENAME="$(< /etc/pib-codename)"  # the suite the local repo publishes
REPO_DIR=/var/www/html/deb/custom
KEY_UID="PIB local repo <pib-local-repo@localhost>"

# --- arm64 emulation is configured above by pib.emulation ---------------------

# Validate even a shell without image.yaml, before modifying the repo or importing
# any package. Use the same package-name policy as explicit CLI verification.
python3 -c 'from pathlib import Path; from pib.cli import check_unique_debs; check_unique_debs(sorted(Path("/workspace/custom-debs").glob("*.deb")))'

# --- local repo signing key ---------------------------------------------------
# Made fresh for each container run in a temporary directory: the repo below
# is rebuilt on every start, so nothing needs the key afterwards, and no
# private key reaches the workspace or an image layer.
GNUPGHOME="$(mktemp -d)"
export GNUPGHOME
gpg --batch --passphrase '' --quick-gen-key "$KEY_UID" ed25519 sign never 2>/dev/null || {
    echo "pib: cannot create the local repo signing key" >&2; exit 1; }
gpg --batch --export "$KEY_UID" > /usr/share/keyrings/custom-repo.gpg

# --- local repo contents ------------------------------------------------------
# Rebuilt from $DEBS on every start, so the repo holds exactly what the
# directory holds now. An empty repo is still exported: the image configs
# always list it.
rm -rf "$REPO_DIR/db" "$REPO_DIR/dists" "$REPO_DIR/pool"
shopt -s nullglob
debs=("$DEBS"/*.deb)
shopt -u nullglob
# With a workspace image.yaml, only .debs signed by the customer's key
# (debs.key) may enter the local repo. pib build checks them itself; a shell does not.
if [ -f image.yaml ] && [ ${#debs[@]} -gt 0 ] && [ "${1:-}" != pib ]; then
    pib verify-debs
fi
for deb in "${debs[@]}"; do
    # dpkg-deb expands these fields, not the shell.
    # shellcheck disable=SC2016
    f="$(dpkg-deb -W --showformat='${Architecture}|${Package}|${Version}|${Section}|${Priority}' "$deb")"
    IFS='|' read -r arch pkg ver sec pri <<<"$f"
    case "$arch" in
        arm64|all) ;;
        *) echo "pib: $deb is for $arch, not arm64" >&2; exit 1 ;;
    esac
    echo "pib: adding $pkg $ver"
    # reprepro refuses a .deb without Section/Priority; default only those.
    defaults=()
    [ -n "$sec" ] || defaults+=(-S misc)
    [ -n "$pri" ] || defaults+=(-P optional)
    reprepro -b "$REPO_DIR" --export=silent-never -C non-free "${defaults[@]}" includedeb "$CODENAME" "$deb"
done
reprepro -b "$REPO_DIR" export "$CODENAME"
# The signing key is not needed past this point: stop the agent and drop the key.
gpgconf --kill all 2>/dev/null || true
rm -rf "$GNUPGHOME"
unset GNUPGHOME

pgrep -x nginx >/dev/null 2>&1 || nginx

SOURCE_DATE_EPOCH="$(< /etc/pib-release-epoch)"
export SOURCE_DATE_EPOCH
exec "$@"
