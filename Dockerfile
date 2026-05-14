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
ARG SDK_SYSROOT_PKG_LIST="libarpack2 libarpack2-dev libblas-dev libblas3 libblkid-dev libbsd0 libcharls2 libelf1 libexpat1 libffi-dev libffi8 libgdal32 libgfortran5 libglib2.0-0 libgomp1 libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libgstrtspserver-1.0-0 libgstrtspserver-1.0-dev libjpeg62-turbo libjson-glib-dev liblapack-dev liblapack3 liblzma5 libmount-dev libopenblas-pthread-dev libopenblas0-pthread libopenjp2-7 libpng16-16 libpython3.11-dev libqt5gui5 libsepol-dev libssl3 libsuperlu-dev libsuperlu5 libtiff6 liburcu-dev libwebp7 python3-dev python3.11-dev zlib1g"
ENV SDK_PKG_LIST="\
	libgrpc-dev,\
	protobuf-compiler-grpc,\
	${SDK_PKG_LIST}"
ENV NEAT_INSIGHT_VENV_DIR=/opt/neat-insight/venv
ENV NEAT_INSIGHT_PORT=9900
ENV NEAT_INSIGHT_SUPERVISED=1
ENV RUSTUP_HOME=/opt/toolchain/rust
ENV CARGO_HOME=/opt/toolchain/rust
ENV PATH="${NEAT_INSIGHT_VENV_DIR}/bin:${CARGO_HOME}/bin:${PATH}"

ENV DEBIAN_FRONTEND=noninteractive

COPY config/platform-package-patterns.txt /usr/local/share/sima-sdk/platform-package-patterns.txt
COPY scripts/configure-apt-repos.sh /usr/local/bin/configure-apt-repos.sh

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

RUN chmod 755 /usr/local/bin/configure-apt-repos.sh && \
    configure-apt-repos.sh "${BASE_SDK_VERSION}"

RUN apt-get update --allow-releaseinfo-change && \
    apt-get install -y --no-install-recommends \
      python3-apt-ostree \
      vim \
      make \
      cmake \
      default-jre-headless \
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
      plantuml \
      supervisor \
      mkcert && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

COPY scripts/simaai-init-build-env /opt/bin/simaai-init-build-env
COPY scripts/simaai_setup_sdk.py /opt/bin/simaai_setup_sdk.py
COPY scripts/install-rustup.sh /usr/local/bin/install-rustup.sh
COPY scripts/install-sima-cli.sh /usr/local/bin/install-sima-cli.sh
COPY scripts/setup-sdk-sysroot.sh /usr/local/bin/setup-sdk-sysroot.sh
COPY scripts/validate-sysroot-package-versions.sh /usr/local/bin/validate-sysroot-package-versions.sh
RUN chmod 755 /opt/bin/simaai-init-build-env \
              /opt/bin/simaai_setup_sdk.py \
              /usr/local/bin/install-rustup.sh \
              /usr/local/bin/install-sima-cli.sh \
              /usr/local/bin/setup-sdk-sysroot.sh \
              /usr/local/bin/validate-sysroot-package-versions.sh

# Ensure images expose a docker group so downstream setup scripts can
# reliably add users with `usermod -a -G docker <user>`.
RUN getent group docker >/dev/null || groupadd --system docker

RUN install-rustup.sh

RUN setup-sdk-sysroot.sh "${BASE_SDK_VERSION}" "${SDK_PKG_LIST}" && \
    install-sima-cli.sh && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /tmp/*

COPY scripts/install-sysroot-overlay.sh /usr/local/bin/install-sysroot-overlay.sh
COPY scripts/install-sdk-sysroot-overlay.sh /usr/local/bin/install-sdk-sysroot-overlay.sh
COPY config/sysroot-overlay.conf /usr/local/share/sima-sdk/sysroot-overlay.conf
COPY config/supervisor-neat-insight.conf /etc/supervisor/conf.d/neat-insight.conf
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/insight-admin.sh /usr/local/bin/insight-admin
COPY scripts/devkit.sh /usr/local/bin/devkit.sh
RUN chmod 755 /usr/local/bin/install-sysroot-overlay.sh && \
    chmod 755 /usr/local/bin/install-sdk-sysroot-overlay.sh && \
    chmod 755 /usr/local/bin/docker-entrypoint.sh && \
    chmod 755 /usr/local/bin/insight-admin && \
    ln -sf /usr/local/bin/insight-admin /usr/local/bin/install-neat-insight && \
    chmod 755 /usr/local/bin/devkit.sh && \
    install-sdk-sysroot-overlay.sh

RUN /usr/local/bin/insight-admin update "${NEAT_INSIGHT_BRANCH}" "${NEAT_INSIGHT_VERSION}" && \
    chmod -R a+rwX "${NEAT_INSIGHT_VENV_DIR}"

COPY config/profile.d/*.sh /etc/profile.d/
RUN chmod 755 /etc/profile.d/neat-sdk-prompt.sh \
              /etc/profile.d/pkg-config-sysroot.sh

RUN printf 'SDK Version = %s_Palette_SDK_neat_%s_%s\neLXr Version = %s_release_neat_%s_%s\n' \
    "${BASE_SDK_VERSION}" "${SDK_GIT_BRANCH}" "${SDK_GIT_HASH}" \
    "${BASE_SDK_VERSION}" "${SDK_GIT_BRANCH}" "${SDK_GIT_HASH}" \
    > /etc/sdk-release

WORKDIR /workspace

# Preinstall Neat Framework and resources
COPY scripts/install-neat-resources.sh /usr/local/bin/install-neat-resources.sh
RUN chmod 755 /usr/local/bin/install-neat-resources.sh
RUN --mount=type=secret,id=neat_github_pat \
    install-neat-resources.sh

# Expose required ports
EXPOSE 9900 9000-9079 9100-9179 8081 8554

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/bin/bash", "-l"]
