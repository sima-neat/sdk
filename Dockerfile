# syntax=docker/dockerfile:1.7
# Generated Dockerfile for modalix.
ARG SDK_BASE_IMAGE=ubuntu:24.04
ARG SDK_CROSS_TOOLCHAIN_IMAGE=debian:bookworm
FROM ${SDK_CROSS_TOOLCHAIN_IMAGE} AS cross-toolchain

ENV DEBIAN_FRONTEND=noninteractive

COPY scripts/install-cross-toolchain.sh /usr/local/bin/install-cross-toolchain.sh
RUN chmod 755 /usr/local/bin/install-cross-toolchain.sh && \
    install-cross-toolchain.sh

FROM ${SDK_BASE_IMAGE}

ARG SDK_PKG_LIST
ARG SDK_GIT_BRANCH=unknown
ARG SDK_GIT_HASH=nogit
ARG SDK_RELEASE_REF=unknown-nogit
ARG BASE_SDK_VERSION=2.1.2
ARG MINIMAL_IMAGE=0
ARG NEAT_BRANCH=main
ARG NEAT_VERSION=latest
ARG NEAT_CORE_TARGET=
ARG NEAT_INSIGHT_BRANCH=
ARG NEAT_INSIGHT_VERSION=
ARG OPENVSCODE_SERVER_VERSION=openvscode-server-v1.109.5
ARG SDK_SYSROOT_PKG_LIST="libarpack2 libarpack2-dev libblas-dev libblas3 libblkid-dev libbsd0 libcharls2 libcpp-httplib-dev libelf1 libexpat1 libffi-dev libffi8 libgdal32 libgfortran5 libglib2.0-0 libgomp1 libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev libgstrtspserver-1.0-0 libgstrtspserver-1.0-dev libjpeg62-turbo libjson-glib-dev liblapack-dev liblapack3 liblzma5 libmount-dev libopenblas-pthread-dev libopenblas0-pthread libopenjp2-7 libpng16-16 libpython3.11-dev libqt5gui5 libsepol-dev libspdlog-dev libssl3 libstdc++6 libsuperlu-dev libsuperlu5 libtiff6 liburcu-dev libwebp7 python3-dev python3.11-dev zlib1g"
ENV SDK_PKG_LIST="\
	libgrpc-dev,\
	protobuf-compiler-grpc,\
	${SDK_PKG_LIST}"
ENV NEAT_INSIGHT_VENV_DIR=/opt/neat-insight/venv
ENV NEAT_INSIGHT_PORT=9900
ENV NEAT_INSIGHT_SUPERVISED=1
ENV OPENVSCODE_SERVER_DIR=/opt/openvscode-server
ENV OPENVSCODE_SERVER_EXTENSIONS_DIR=/opt/openvscode-server/extensions
ENV OPENVSCODE_SERVER_PORT=9999
ENV OPENVSCODE_SERVER_SUPERVISED=1
ENV PIP_DEFAULT_TIMEOUT=120
ENV PIP_RETRIES=10
ENV RUSTUP_HOME=/opt/toolchain/rust
ENV CARGO_HOME=/opt/toolchain/rust
ENV SDK_GIT_BRANCH="${SDK_GIT_BRANCH}"
ENV SDK_RELEASE_REF="${SDK_RELEASE_REF}"
ENV SDK_IMAGE_BRANCH="${SDK_GIT_BRANCH}"
ENV SDK_IMAGE_TAG="${SDK_RELEASE_REF}"
ENV SDK_PROMPT_HOSTNAME="neat-sdk-${SDK_RELEASE_REF}"
ENV PATH="${OPENVSCODE_SERVER_DIR}/bin:${NEAT_INSIGHT_VENV_DIR}/bin:${CARGO_HOME}/bin:${PATH}"

ENV DEBIAN_FRONTEND=noninteractive

RUN if [ -f /etc/apt/sources.list.d/ubuntu.sources ]; then \
      sed -i "/^Types: deb/a Architectures: $(dpkg --print-architecture)" /etc/apt/sources.list.d/ubuntu.sources; \
    fi

RUN dpkg --add-architecture arm64 && \
    dpkg --add-architecture arc && \
    dpkg --add-architecture armhf

RUN apt-get clean && \
    apt-get update --allow-releaseinfo-change && \
    apt-get install -y --no-install-recommends \
      wget \
      gnupg \
      ca-certificates \
      iputils-ping \
      python3 \
      python3-apt && \
    rm -rf /var/lib/apt/lists/*

RUN python3 -c 'import apt'

RUN apt-get update --allow-releaseinfo-change && \
    apt-get install -y --no-install-recommends \
      vim \
      make \
      cmake \
      debian-archive-keyring \
      default-jre-headless \
      pkgconf \
      sudo \
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
      libgmp10 \
      libisl23 \
      libjansson4 \
      libmpc3 \
      libmpfr6 \
      libssl-dev \
      libgnutls28-dev \
      libzstd1 \
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

RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      amd64) openvscode_arch="x64" ;; \
      arm64) openvscode_arch="arm64" ;; \
      armhf) openvscode_arch="armhf" ;; \
      *) echo "Unsupported OpenVSCode Server architecture: $(dpkg --print-architecture)" >&2; exit 1 ;; \
    esac; \
    openvscode_archive="${OPENVSCODE_SERVER_VERSION}-linux-${openvscode_arch}.tar.gz"; \
    curl -fsSL --retry 3 --retry-delay 2 \
      "https://github.com/gitpod-io/openvscode-server/releases/download/${OPENVSCODE_SERVER_VERSION}/${openvscode_archive}" \
      -o "/tmp/${openvscode_archive}"; \
    mkdir -p "${OPENVSCODE_SERVER_DIR}"; \
    tar -xzf "/tmp/${openvscode_archive}" -C "${OPENVSCODE_SERVER_DIR}" --strip-components=1; \
    rm -f "/tmp/${openvscode_archive}"; \
    mkdir -p "${OPENVSCODE_SERVER_EXTENSIONS_DIR}"; \
    chmod -R a+rwX "${OPENVSCODE_SERVER_EXTENSIONS_DIR}"; \
    chmod -R a+rX "${OPENVSCODE_SERVER_DIR}"

COPY --from=cross-toolchain /opt/cross-toolchain/ /
COPY --from=cross-toolchain /opt/cross-toolchain/ /opt/bookworm-cross-toolchain/
COPY scripts/pin-cross-toolchain.sh /usr/local/bin/pin-cross-toolchain.sh

RUN chmod 755 /usr/local/bin/pin-cross-toolchain.sh && \
    pin-cross-toolchain.sh && \
    aarch64-linux-gnu-gcc --version && \
    aarch64-linux-gnu-g++ --version && \
    aarch64-linux-gnu-ld --version && \
    printf 'int main(void) { return 0; }\n' > /tmp/cross-smoke.c && \
    aarch64-linux-gnu-gcc -c -o /tmp/cross-smoke.o /tmp/cross-smoke.c && \
    printf '#include <iostream>\nint main() { std::cout << "ok\\\\n"; return 0; }\n' > /tmp/cross-smoke.cpp && \
    aarch64-linux-gnu-g++ -o /tmp/cross-smoke-cxx /tmp/cross-smoke.cpp && \
    rm -f /tmp/cross-smoke.o /tmp/cross-smoke.c /tmp/cross-smoke.cpp /tmp/cross-smoke-cxx

COPY config/platform-package-patterns.txt /usr/local/share/sima-sdk/platform-package-patterns.txt
COPY deps/manifest.json /usr/local/share/sima-sdk/deps/manifest.json
COPY scripts/configure-apt-repos.sh /usr/local/bin/configure-apt-repos.sh

RUN chmod 755 /usr/local/bin/configure-apt-repos.sh && \
    configure-apt-repos.sh "${BASE_SDK_VERSION}"

RUN mkdir -p /tmp/supervisor /var/log/supervisor && \
    mkdir -p /etc/supervisor/conf.available && \
    chmod 1777 /tmp/supervisor && \
    chmod -R a+rwX /var/log/supervisor && \
    sed -i \
      -e 's#file=/var/run/supervisor.sock#file=/tmp/supervisor/supervisor.sock#' \
      -e 's#pidfile=/var/run/supervisord.pid#pidfile=/tmp/supervisor/supervisord.pid#' \
      -e 's#serverurl=unix:///var/run/supervisor.sock#serverurl=unix:///tmp/supervisor/supervisor.sock#' \
      /etc/supervisor/supervisord.conf

COPY scripts/simaai-init-build-env /opt/bin/simaai-init-build-env
COPY scripts/simaai_setup_sdk.py /opt/bin/simaai_setup_sdk.py
COPY scripts/install-rustup.sh /usr/local/bin/install-rustup.sh
COPY scripts/install-sima-cli.sh /usr/local/bin/install-sima-cli.sh
COPY scripts/sima-code.sh /usr/local/bin/sima-code
COPY scripts/neat-deps.sh /usr/local/bin/neat-deps.sh
COPY scripts/setup-sdk-sysroot.sh /usr/local/bin/setup-sdk-sysroot.sh
COPY scripts/validate-sysroot-package-versions.sh /usr/local/bin/validate-sysroot-package-versions.sh
RUN chmod 755 /opt/bin/simaai-init-build-env \
              /opt/bin/simaai_setup_sdk.py \
              /usr/local/bin/install-rustup.sh \
              /usr/local/bin/install-sima-cli.sh \
              /usr/local/bin/sima-code \
              /usr/local/bin/neat-deps.sh \
              /usr/local/bin/setup-sdk-sysroot.sh \
              /usr/local/bin/validate-sysroot-package-versions.sh

# Ensure images expose a docker group so downstream setup scripts can
# reliably add users with `usermod -a -G docker <user>`.
RUN getent group docker >/dev/null || groupadd --system docker

RUN install-rustup.sh

RUN setup-sdk-sysroot.sh "${BASE_SDK_VERSION}" "${SDK_PKG_LIST}" && \
    install-sima-cli.sh && \
    cp -a /opt/bookworm-cross-toolchain/. / && \
    pin-cross-toolchain.sh && \
    aarch64-linux-gnu-gcc --version && \
    aarch64-linux-gnu-g++ --version && \
    aarch64-linux-gnu-ld --version && \
    printf '#include <iostream>\nint main() { std::cout << "ok\\\\n"; return 0; }\n' > /tmp/cross-smoke.cpp && \
    aarch64-linux-gnu-g++ -o /tmp/cross-smoke-cxx /tmp/cross-smoke.cpp && \
    rm -f /tmp/cross-smoke.cpp /tmp/cross-smoke-cxx && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*.deb /tmp/*

COPY scripts/install-sysroot-overlay.sh /usr/local/bin/install-sysroot-overlay.sh
COPY scripts/install-sdk-sysroot-overlay.sh /usr/local/bin/install-sdk-sysroot-overlay.sh
COPY scripts/sysroot.sh /usr/local/bin/sysroot
COPY config/sysroot-overlay.conf /usr/local/share/sima-sdk/sysroot-overlay.conf
COPY config/supervisor-neat-insight.conf /etc/supervisor/conf.available/neat-insight.conf
COPY config/supervisor-openvscode.conf /etc/supervisor/conf.available/openvscode.conf
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
COPY scripts/insight-admin.sh /usr/local/bin/insight-admin
COPY scripts/neat-insight-supervised.sh /usr/local/bin/neat-insight-supervised
COPY scripts/openvscode-supervised.sh /usr/local/bin/openvscode-supervised
COPY scripts/devkit.sh /usr/local/bin/devkit.sh
COPY scripts/devkit-sync-rsync.sh /usr/local/bin/devkit-sync-rsync.sh
RUN chmod 755 /usr/local/bin/install-sysroot-overlay.sh && \
    chmod 755 /usr/local/bin/install-sdk-sysroot-overlay.sh && \
    chmod 755 /usr/local/bin/sysroot && \
    chmod 755 /usr/local/bin/docker-entrypoint.sh && \
    chmod 755 /usr/local/bin/insight-admin && \
    chmod 755 /usr/local/bin/neat-insight-supervised && \
    chmod 755 /usr/local/bin/openvscode-supervised && \
    ln -sf /usr/local/bin/insight-admin /usr/local/bin/install-neat-insight && \
    chmod 755 /usr/local/bin/devkit.sh && \
    chmod 755 /usr/local/bin/devkit-sync-rsync.sh && \
    install-sdk-sysroot-overlay.sh

RUN if [ -n "${NEAT_INSIGHT_BRANCH}${NEAT_INSIGHT_VERSION}" ]; then \
      /usr/local/bin/insight-admin update "${NEAT_INSIGHT_BRANCH:-main}" "${NEAT_INSIGHT_VERSION:-latest}"; \
    else \
      /usr/local/bin/insight-admin update; \
    fi && \
    chmod -R a+rwX "${NEAT_INSIGHT_VENV_DIR}"

COPY config/profile.d/*.sh /etc/profile.d/
RUN chmod 755 /etc/profile.d/neat-sdk-prompt.sh \
              /etc/profile.d/pkg-config-sysroot.sh

RUN if printf '%s' "${SDK_RELEASE_REF}" | grep -Eq '^v[0-9]+[.][0-9]+[.][0-9]+'; then \
      printf 'SDK Release = %s\nPlatform Version = %s\nSDK Version = %s_Palette_SDK_neat_%s\neLXr Version = %s_release_neat_%s\n' \
        "${SDK_RELEASE_REF}" \
        "${BASE_SDK_VERSION}" \
        "${BASE_SDK_VERSION}" "${SDK_RELEASE_REF}" \
        "${BASE_SDK_VERSION}" "${SDK_RELEASE_REF}"; \
    else \
      printf 'SDK Release = %s\nPlatform Version = %s\nSDK Version = %s_Palette_SDK_neat_%s_%s\neLXr Version = %s_release_neat_%s_%s\n' \
        "${SDK_RELEASE_REF}" \
        "${BASE_SDK_VERSION}" \
        "${BASE_SDK_VERSION}" "${SDK_GIT_BRANCH}" "${SDK_GIT_HASH}" \
        "${BASE_SDK_VERSION}" "${SDK_GIT_BRANCH}" "${SDK_GIT_HASH}"; \
    fi > /etc/sdk-release

WORKDIR /workspace

# Preinstall Neat Framework and resources
COPY scripts/install-neat-resources.sh /usr/local/bin/install-neat-resources.sh
RUN chmod 755 /usr/local/bin/install-neat-resources.sh
RUN install-neat-resources.sh

# Expose required ports
EXPOSE 9900 9999 9000-9079 9100-9179 8081 8554

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["/bin/bash", "-l"]
