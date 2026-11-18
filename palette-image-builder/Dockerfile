# Copyright (c) 2026 SiMa.ai Technologies, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
# SiMa.ai Palette Image Builder (PIB) container.
#
# Standalone SDK companion image. Build on native amd64 or arm64 runners.
# The pinned OCI index selects the matching eLxr base for each architecture.
# Customers pull the published image; see docs/palette-image-builder.md.
ARG BASE_IMAGE=elxrlinux/elxr@sha256:922b153fccfe20337d71586dc9a6823cbe4cf0769ecec431279c662029814058
FROM ${BASE_IMAGE}
LABEL org.opencontainers.image.title="Palette Image Builder" \
      org.opencontainers.image.source="https://github.com/sima-neat/sdk"

# SiMa.ai's public apt repo; CODENAME names its suite for this release.
ARG SIMAAI_APT_URL=https://repo.sima.ai/elxr/deb/release
# Fingerprint of simaai-public.asc, the key SiMa.ai's public repo is
# signed with. The build refuses a key file that does not match it.
ARG SIMAAI_KEY_FPR=1E527426828B89232E080FD44F87A7B80CFC8F4B

ENV DEBIAN_FRONTEND=noninteractive
ENV LANG=C.UTF-8

# rucksack and its helpers come from eLxr; prefer its builds over Debian's.
RUN printf 'Package: *\nPin: origin mirror.elxr.dev\nPin-Priority: 900\n' \
        > /etc/apt/preferences.d/99pablo-repository && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        gnupg \
        wget \
        git \
        python3-pip \
# Build backend for the pib package below; pip gets no index to fetch one.
        python3-setuptools \
# Image assembly: rucksack runs the stages, pasha (below) provides the
# modules. pasha's own Python dependencies come from Debian so the pip
# install of the wheel can skip PyPI.
        python3-rucksack \
        python3-stevedore \
        python3-yaml \
        python3-rich \
# Rootfs bootstrap: mmdebstrap runs arm64 maintainer scripts under
# qemu-user-static.
        mmdebstrap \
        arch-test \
# "boot A/B + LVM" disk layout and its file systems.
        udev \
        kmod \
        parted \
        fdisk \
        lvm2 \
        dosfstools \
        mtools \
        e2fsprogs \
        cpio \
        gzip \
        xz-utils \
        zstd \
# Boot partition (FIT/boot.scr/env) and .swu signing.
        u-boot-tools \
        device-tree-compiler \
        openssl \
# PKCS#11 (HSM/YubiKey) signing: pib sign --pkcs11 uses the engine.
        libengine-pkcs11-openssl \
        opensc \
        libpcsclite1 \
# Local apt repo for the customer's .debs.
        reprepro \
        nginx && \
    if [ "$(dpkg --print-architecture)" = amd64 ]; then \
        apt-get install -y --no-install-recommends qemu-user-static binfmt-support; \
    fi && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# The release this image builds (pib refuses an image.yaml for another) and its eLxr
# suite; the image configs include both files.
COPY RELEASE /etc/pib-release
COPY CODENAME /etc/pib-codename
RUN CODENAME="$(cat /etc/pib-codename)" && \
    python3 -c 'import re, sys; sys.exit(not re.fullmatch(r"[a-z][a-z0-9]*", sys.argv[1]))' "$CODENAME" || \
    { echo "CODENAME must hold one suite name such as agate, not '$CODENAME'" >&2; exit 1; }

# Download standard Python dependencies with exact wheel hashes. SiMa Pasha and
# elxr-config use commit-pinned URLs and checksums recorded in deps/artifacts.json.
# Downloaded binaries exist only in this build layer, never in the SDK Git tree.
RUN --mount=type=bind,source=deps,target=/tmp/deps \
    python3 /tmp/deps/fetch-artifacts.py --destination /tmp/pib-artifacts \
        --release "$(cat /etc/pib-release)" --codename "$(cat /etc/pib-codename)" && \
    pip install --no-cache-dir --break-system-packages --ignore-installed \
        --index-url https://pypi.org/simple --only-binary=:all: --require-hashes \
        -r /tmp/deps/debsbom-requirements.txt && \
    pip install --no-cache-dir --no-deps --break-system-packages \
        /tmp/pib-artifacts/pasha-$(cat /etc/pib-release)-py3-none-any.whl && \
    mkdir -p /usr/share/pib/elxr-config && \
    tar -xzf /tmp/pib-artifacts/elxr-config-1.1.0-elxr14.tar.gz \
        -C /usr/share/pib/elxr-config --strip-components=1 --exclude='esp.img' && \
    cp -a /tmp/pib-artifacts/upstream/configs /tmp/pib-artifacts/upstream/files \
        /tmp/pib-artifacts/upstream/scripts /usr/share/pib/ && \
    rm -rf /tmp/pib-artifacts && \
    python3 -c "from importlib.metadata import entry_points; \
missing = {'bootstrap.mmdebstrap', 'image.compress', 'image.raw', 'installer.disk.lvm', \
'installer.disk.lvm.teardown', 'installer.disk.parted', 'simaai.bootloader', \
'simaai.swupdate', 'utils.run_shell'} - set(entry_points(group='pasha.modules').names); \
assert not missing, f'pasha wheel lacks modules: {sorted(missing)}'"

# SiMa.ai apt key from the pinned upstream checkout, checked by fingerprint; then the
# date of its signed InRelease, the entrypoint's SOURCE_DATE_EPOCH.
RUN cp /usr/share/pib/configs/images/files/simaai-public.asc /tmp/simaai-public.asc && \
    export GNUPGHOME="$(mktemp -d)" && \
    keys="$(gpg --show-keys --with-colons /tmp/simaai-public.asc | \
           awk -F: '$1 == "pub" { n++ } $1 == "fpr" && !f { f = $10 } END { print n, f }')" && \
    if [ "$keys" != "1 $SIMAAI_KEY_FPR" ]; then \
        echo "simaai-public.asc: keys and fingerprint '$keys', expected '1 $SIMAAI_KEY_FPR'" >&2; \
        exit 1; \
    fi && \
    gpg --dearmor < /tmp/simaai-public.asc > /usr/share/keyrings/simaai-public.gpg && \
    wget -q -O /tmp/InRelease "${SIMAAI_APT_URL}/dists/$(cat /etc/pib-codename)/InRelease" && \
    gpgv --keyring /usr/share/keyrings/simaai-public.gpg /tmp/InRelease && \
    date -u -d "$(sed -n 's/^Date: //p' /tmp/InRelease)" +%s > /etc/pib-release-epoch && \
    rm -r /tmp/InRelease "$GNUPGHOME"

# Local apt repo layout, served by nginx at http://localhost/deb/custom.
# No signing key is baked in: entrypoint.sh creates a fresh one on every container run, so
# no two customers (and no published image layer) share it.
RUN mkdir -p /var/www/html/deb/custom/conf && \
    cp /usr/share/pib/files/distributions /var/www/html/deb/custom/conf/distributions && \
    sed -i "s/@CODENAME@/$(cat /etc/pib-codename)/" /var/www/html/deb/custom/conf/distributions && \
    cp /usr/share/pib/files/nginx.conf /etc/nginx/sites-enabled/default

# pib CLI, next to pasha so it matches this image's modules; --no-deps as for pasha.
# rw: setuptools builds in-tree, and those writes are discarded with the mount.
RUN --mount=type=bind,source=pib,target=/tmp/pib,rw \
    pip install --no-cache-dir --no-deps --break-system-packages --no-index \
        --no-build-isolation /tmp/pib && \
    pib --version

# The image configs and the files they need ship in the image; pib init copies
# them into a workspace (PIB_CONFIGS or --configs picks another set).
COPY examples/ /usr/share/pib/examples/
COPY --chmod=755 entrypoint.sh /usr/local/bin/pib-entrypoint

# SiMa.ai's repo for pib build, which makes the MIRROR_1 apt line of
# configs/images/image-stages.yaml from it and /etc/pib-codename. No SWU signing
# key is set or shipped; pib build uses a throwaway one and pib sign the customer's.
ENV PIB_SIMA_APT_URL=${SIMAAI_APT_URL}

# Extract this launcher from the pulled image; no source checkout is needed.
# CI embeds this build's commit-tagged image ref so copied launchers keep their toolchain.
ARG PIB_DEFAULT_IMAGE=ghcr.io/sima-neat/palette-image-builder:latest
COPY --chmod=755 host/pib /usr/local/share/pib/host/pib
RUN sed -i "s|ghcr.io/sima-neat/palette-image-builder:latest|${PIB_DEFAULT_IMAGE}|g" /usr/local/share/pib/host/pib
COPY UPSTREAM /usr/share/doc/palette-image-builder/UPSTREAM

WORKDIR /workspace

ENTRYPOINT ["/usr/local/bin/pib-entrypoint"]
CMD ["pib", "--help"]
