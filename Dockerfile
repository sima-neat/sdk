# syntax=docker/dockerfile:1.7
# Generated Dockerfile for modalix.
FROM debian:bookworm

ARG SDK_PKG_LIST
ARG SDK_GIT_BRANCH=unknown
ARG SDK_GIT_HASH=nogit
ARG BASE_SDK_VERSION=2.0.0
ARG MINIMAL_IMAGE=0
ARG NEAT_BRANCH=main
ARG NEAT_VERSION=latest
ARG NEAT_INSIGHT_BRANCH=main
ARG NEAT_INSIGHT_VERSION=latest
ARG SDK_SYSROOT_PKG_LIST="libarpack2 libarpack2-dev libblas-dev libblas3 libgfortran5 libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libgstrtspserver-1.0-0 libgstrtspserver-1.0-dev liblapack-dev liblapack3 libopenblas-pthread-dev libopenblas0-pthread libqt5gui5 libsuperlu-dev libsuperlu5"
ENV SDK_PKG_LIST="\
	libgrpc-dev,\
	protobuf-compiler-grpc,\
	${SDK_PKG_LIST}"
ENV NEAT_INSIGHT_VENV_DIR=/opt/neat-insight/venv
ENV NEAT_INSIGHT_PORT=9900
ENV NEAT_INSIGHT_SUPERVISED=1
ENV PATH="${NEAT_INSIGHT_VENV_DIR}/bin:${PATH}"

ENV DEBIAN_FRONTEND=noninteractive

RUN dpkg --add-architecture arm64 && \
    dpkg --add-architecture arc && \
    dpkg --add-architecture armhf

RUN apt-get clean && \
    apt-get update --allow-releaseinfo-change && \
    apt-get install -y --no-install-recommends \
      wget \
      curl \
      gnupg \
      ca-certificates \
      iputils-ping \
      python3 && \
    rm -rf /var/lib/apt/lists/*

RUN wget -qO - https://mirror.elxr.dev/elxr/public.gpg | gpg --dearmor -o /etc/apt/trusted.gpg.d/elxr.gpg
RUN wget -qO - https://packages.fluentbit.io/fluentbit.key | gpg --dearmor > /etc/apt/trusted.gpg.d/fluentbit.gpg
RUN wget --no-check-certificate -O - https://repo.sima.ai/elxr/deb/simaai.gpg | gpg --dearmor > /etc/apt/trusted.gpg.d/simaai.gpg

RUN chmod 644 /etc/apt/trusted.gpg.d/elxr.gpg && \
    chmod 644 /etc/apt/trusted.gpg.d/fluentbit.gpg && \
    chmod 644 /etc/apt/trusted.gpg.d/simaai.gpg

RUN echo "deb [signed-by=/etc/apt/trusted.gpg.d/elxr.gpg] https://mirror.elxr.dev/elxr aria main" > /etc/apt/sources.list.d/elxr.list
RUN echo "deb [signed-by=/etc/apt/trusted.gpg.d/fluentbit.gpg] https://packages.fluentbit.io/debian/bookworm bookworm main" >> /etc/apt/sources.list.d/elxr.list
RUN echo "deb [trusted=yes] https://repo.sima.ai/elxr/deb/release bookworm non-free  # simaai repo" >> /etc/apt/sources.list.d/elxr.list

RUN echo "Package: *" > /etc/apt/preferences.d/stable.pref
RUN echo "Pin: origin \"repo.sima.ai/elxr\"" >> /etc/apt/preferences.d/stable.pref
RUN echo "Pin-Priority: 999" >> /etc/apt/preferences.d/stable.pref

# The SiMa palette package has loose dependencies. Keep SDK-versioned packages
# on BASE_SDK_VERSION so fresh CI builds do not mix newer sysroot packages into
# an older SDK image when repo.sima.ai publishes a later release.
RUN printf '%s\n' \
      'Package: simaai-* appcomplex a65apps evtransforms inferencetools vdpcli mpktools vdpspy vdp-llm-libs swsoc-* smifb-* libcamera libcamera-tools' \
      "Pin: version ${BASE_SDK_VERSION}" \
      'Pin-Priority: 1001' \
    > /etc/apt/preferences.d/simaai-sdk-version.pref

RUN apt-get update --allow-releaseinfo-change && \
    apt-get install -y --no-install-recommends \
      python3-apt-ostree \
      vim \
      make \
      cmake \
      pkgconf \
      gcc-aarch64-linux-gnu \
      sudo \
      g++-aarch64-linux-gnu \
      device-tree-compiler \
      bison \
      flex \
      quilt \
      zlib1g-dev \
      bzip2 \
      bc \
      rsync \
      kmod \
      cpio \
      git \
      curl \
      htop \
      file \
      libssl-dev \
      libgnutls28-dev \
      openssh-client \
      sshpass \
      python3-dev \
      python3-venv \
      ffmpeg \
      libffi8 \
      libmediainfo0v5 \
      supervisor \
      mkcert \
      simaai-sdk-tools=${BASE_SDK_VERSION} && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Ensure images expose a docker group so downstream setup scripts can
# reliably add users with `usermod -a -G docker <user>`.
RUN getent group docker >/dev/null || groupadd --system docker

RUN if [ "${MINIMAL_IMAGE}" != "1" ]; then \
      export RUSTUP_HOME=/opt/toolchain/rust && \
      export CARGO_HOME=/opt/toolchain/rust && \
      mkdir -p "${RUSTUP_HOME}" && \
      curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs > /tmp/rustup.sh && \
      chmod 755 /tmp/rustup.sh && \
      /tmp/rustup.sh -y --profile minimal && \
      echo "export RUSTUP_HOME=${RUSTUP_HOME}" >> "${CARGO_HOME}/env" && \
      echo "export CARGO_HOME=${CARGO_HOME}" >> "${CARGO_HOME}/env" && \
      . "${CARGO_HOME}/env" && \
      rustup target add aarch64-unknown-linux-gnu && \
      rm /tmp/rustup.sh; \
    else \
      echo "Skipping rustup install for minimal image build"; \
    fi

ENV RUSTUP_HOME=/opt/toolchain/rust
ENV CARGO_HOME=/opt/toolchain/rust
ENV PATH=/opt/toolchain/rust/bin:${PATH}

RUN if [ "${MINIMAL_IMAGE}" != "1" ]; then \
      python3 /opt/bin/simaai_setup_sdk.py modalix "${BASE_SDK_VERSION}" "${SDK_PKG_LIST}"; \
    else \
      mkdir -p /opt/toolchain/aarch64/modalix/usr/include \
               /opt/toolchain/aarch64/modalix/usr/lib \
               /opt/toolchain/aarch64/modalix/usr/lib/pkgconfig \
               /opt/toolchain/aarch64/modalix/usr/lib/aarch64-linux-gnu \
               /opt/toolchain/aarch64/modalix/usr/lib/aarch64-linux-gnu/pkgconfig \
               /opt/toolchain/aarch64/modalix/usr/share/pkgconfig; \
    fi && \
    curl -fsSL https://docs.sima.ai/_static/tools/sima-cli-installer.sh | bash && \
    test -x /root/.sima-cli/.venv/bin/sima-cli && \
    ln -sf /root/.sima-cli/.venv/bin/sima-cli /usr/local/bin/sima-cli && \
    /usr/local/bin/sima-cli --help >/dev/null 2>&1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /tmp/*

COPY scripts/install-sysroot-overlay.sh /usr/local/bin/install-sysroot-overlay.sh
COPY config/sysroot-overlay.conf /usr/local/share/sima-sdk/sysroot-overlay.conf
COPY config/supervisor-neat-insight.conf /etc/supervisor/conf.d/neat-insight.conf
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/insight-admin.sh /usr/local/bin/insight-admin
COPY scripts/devkit.sh /usr/local/bin/devkit.sh
RUN chmod 755 /usr/local/bin/install-sysroot-overlay.sh && \
    chmod 755 /usr/local/bin/docker-entrypoint.sh && \
    chmod 755 /usr/local/bin/insight-admin && \
    ln -sf /usr/local/bin/insight-admin /usr/local/bin/install-neat-insight && \
    chmod 755 /usr/local/bin/devkit.sh && \
    if [ "${MINIMAL_IMAGE}" != "1" ]; then \
      /bin/bash -lc 'set -euo pipefail; \
        overlay_pkgs=(); \
        for pkg in ${SDK_SYSROOT_PKG_LIST}; do \
          overlay_pkgs+=("${pkg}:arm64"); \
        done; \
        /usr/local/bin/install-sysroot-overlay.sh /opt/toolchain/aarch64/modalix "${overlay_pkgs[@]}"'; \
      chmod -R a+rX /opt/toolchain/aarch64/modalix/usr/include; \
    else \
      echo "Skipping sysroot overlay for minimal image build"; \
    fi

RUN /usr/local/bin/insight-admin update "${NEAT_INSIGHT_BRANCH}" "${NEAT_INSIGHT_VERSION}" && \
    chmod -R a+rwX "${NEAT_INSIGHT_VENV_DIR}"

RUN cat > /etc/profile.d/neat-sdk-prompt.sh <<'EOF'
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
EOF
RUN chmod 755 /etc/profile.d/neat-sdk-prompt.sh

RUN cat > /etc/profile.d/pkg-config-sysroot.sh <<'EOF'
#!/usr/bin/env bash
export SYSROOT="${SYSROOT:-/opt/toolchain/aarch64/modalix}"
if [[ -z "${PKG_CONFIG:-}" || ! -x "${PKG_CONFIG}" ]]; then
  export PKG_CONFIG="/usr/bin/pkg-config"
fi
if [[ -z "${PKG_CONFIG_EXECUTABLE:-}" || ! -x "${PKG_CONFIG_EXECUTABLE}" ]]; then
  export PKG_CONFIG_EXECUTABLE="${PKG_CONFIG}"
fi
export PKG_CONFIG_SYSROOT_DIR="${PKG_CONFIG_SYSROOT_DIR:-$SYSROOT}"
export PKG_CONFIG_LIBDIR="${PKG_CONFIG_LIBDIR:-$SYSROOT/usr/lib/aarch64-linux-gnu/pkgconfig:$SYSROOT/usr/lib/pkgconfig:$SYSROOT/usr/share/pkgconfig}"
unset PKG_CONFIG_PATH || true
export LDFLAGS="--sysroot=$SYSROOT -L$SYSROOT/usr/lib/aarch64-linux-gnu -L$SYSROOT/lib/aarch64-linux-gnu ${LDFLAGS:-}"
EOF
RUN chmod 755 /etc/profile.d/pkg-config-sysroot.sh

RUN printf 'SDK Version = %s_Palette_SDK_neat_%s_%s\neLXr Version = %s_release_neat_%s_%s\n' \
    "${BASE_SDK_VERSION}" "${SDK_GIT_BRANCH}" "${SDK_GIT_HASH}" \
    "${BASE_SDK_VERSION}" "${SDK_GIT_BRANCH}" "${SDK_GIT_HASH}" \
    > /etc/sdk-release

WORKDIR /workspace

# Preinstall Neat Framework and resources
RUN --mount=type=secret,id=neat_github_pat \
    mkdir -p /neat-resources/core-extra /neat-resources/core-src /neat-resources/apps-src && \
    wget -O /tmp/install-neat.sh https://tools.sima-neat.com/install-neat.sh && \
    cd /neat-resources/core-extra && \
    bash /tmp/install-neat.sh --minimum "${NEAT_BRANCH}" "${NEAT_VERSION}" && \
    rm -f /tmp/install-neat.sh && \
    find /neat-resources/core-extra -type f \
      \( -name '*.deb' -o -name '*.tar.gz' -o -name '*.whl' \) -delete && \
    if [ -f /run/secrets/neat_github_pat ] && [ -s /run/secrets/neat_github_pat ]; then \
      NEAT_GITHUB_PAT="$(cat /run/secrets/neat_github_pat)" && \
      git clone --depth 1 "https://${NEAT_GITHUB_PAT}@github.com/sima-neat/core.git" /neat-resources/core-src && \
      git -C /neat-resources/core-src remote set-url origin https://github.com/sima-neat/core.git; \
    else \
      echo "Skipping sima-neat/core clone; neat_github_pat build secret not provided"; \
    fi && \
    git clone --depth 1 https://github.com/sima-neat/apps.git /neat-resources/apps-src

# Expose required ports
EXPOSE 9900 9000-9079 9100-9179 8081 8554

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/bin/bash", "-l"]
