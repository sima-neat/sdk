# Generated Dockerfile for modalix Build:release[2.0.0]
FROM debian:bookworm

ARG SDK_PKG_LIST
ARG SDK_GIT_BRANCH=unknown
ARG SDK_GIT_HASH=nogit
ENV SDK_PKG_LIST="\
	libgrpc-dev,\
	protobuf-compiler-grpc,\
	libarpack2,\
	libarpack2-dev,\
	libblas-dev,\
	libblas3,\
	libgfortran5,\
	libgstrtspserver-1.0-0,\
	libgstrtspserver-1.0-dev,\
	liblapack-dev,\
	liblapack3,\
	libopenblas-pthread-dev,\
	libopenblas0-pthread,\
	libqt5gui5,\
	libsuperlu-dev,\
	libsuperlu5,\
	${SDK_PKG_LIST}"

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
      python3 \
      python3-pip

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

RUN apt-get update --allow-releaseinfo-change && \
    apt-get install -y --no-install-recommends \
      python3-apt-ostree \
      vim \
      make \
      cmake \
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
      libssl-dev \
      libgnutls28-dev \
      openssh-client \
      python3-dev \
      simaai-sdk-tools

RUN curl -fsSL https://docs.sima.ai/_static/tools/sima-cli-installer.sh | bash

RUN export RUSTUP_HOME=/opt/toolchain/rust && \
    export CARGO_HOME=/opt/toolchain/rust && \
    mkdir -p "${RUSTUP_HOME}" && \
    curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs > /tmp/rustup.sh && \
    chmod 755 /tmp/rustup.sh && \
    /tmp/rustup.sh -y && \
    echo "export RUSTUP_HOME=${RUSTUP_HOME}" >> "${CARGO_HOME}/env" && \
    echo "export CARGO_HOME=${CARGO_HOME}" >> "${CARGO_HOME}/env" && \
    . "${CARGO_HOME}/env" && \
    rm /tmp/rustup.sh

RUN python3 /opt/bin/simaai_setup_sdk.py modalix 2.0.0 "${SDK_PKG_LIST}"

RUN printf 'SDK Version = 2.0.0_Palette_SDK_neat_%s_%s\neLXr Version = 2.0.0_release_neat_%s_%s\n' \
    "${SDK_GIT_BRANCH}" "${SDK_GIT_HASH}" "${SDK_GIT_BRANCH}" "${SDK_GIT_HASH}" \
    > /etc/sdk-release

RUN touch /root/.bash_profile && \
    grep -qxF 'if [ -f ~/.bashrc ]; then' /root/.bash_profile || \
    printf '\nif [ -f ~/.bashrc ]; then\n  . ~/.bashrc\nfi\n' >> /root/.bash_profile
RUN echo "source /opt/bin/simaai-init-build-env modalix" >> /root/.bashrc

CMD ["/bin/bash", "-l"]
