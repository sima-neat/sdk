#!/usr/bin/env bash

set -euo pipefail

if [[ "${MINIMAL_IMAGE:-0}" == "1" ]]; then
  echo "Skipping rustup install for minimal image build"
  exit 0
fi

export RUSTUP_HOME=/opt/toolchain/rust
export CARGO_HOME=/opt/toolchain/rust

mkdir -p "${RUSTUP_HOME}"
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs > /tmp/rustup.sh
chmod 755 /tmp/rustup.sh
/tmp/rustup.sh -y --profile minimal
. "${CARGO_HOME}/env"
rustup target add aarch64-unknown-linux-gnu
{
  echo "export RUSTUP_HOME=${RUSTUP_HOME}"
  echo "export CARGO_HOME=${CARGO_HOME}"
} >> "${CARGO_HOME}/env"
rm /tmp/rustup.sh
