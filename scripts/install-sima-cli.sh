#!/usr/bin/env bash

set -euo pipefail

curl -fsSL https://docs.sima.ai/_static/tools/sima-cli-installer.sh | bash
test -x /root/.sima-cli/.venv/bin/sima-cli
ln -sf /root/.sima-cli/.venv/bin/sima-cli /usr/local/bin/sima-cli
/usr/local/bin/sima-cli --help >/dev/null 2>&1
