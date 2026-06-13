#!/usr/bin/env bash

set -euo pipefail

root_venv=/root/.sima-cli/.venv
install_venv=/opt/sima-cli/venv

if ! curl -fsSL https://artifacts.neat.sima.ai/sima-cli/linux-mac.sh | bash; then
  test -x "${root_venv}/bin/sima-cli"
fi
test -x "${root_venv}/bin/sima-cli"
rm -rf /opt/sima-cli
mkdir -p /opt/sima-cli
cp -a "${root_venv}" "${install_venv}"
while IFS= read -r -d '' launcher; do
  sed -i '1 s#/root/.sima-cli/.venv#/opt/sima-cli/venv#' "${launcher}"
done < <(grep -IlZ '^#!.*/root/.sima-cli/.venv' "${install_venv}"/bin/* 2>/dev/null || true)
chmod -R a+rwX /opt/sima-cli
cat >/usr/local/bin/sima-cli <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${HOME:-}" || ! -d "${HOME}" || ! -w "${HOME}" ]]; then
  export HOME="/tmp/sima-cli-home-$(id -u)"
  mkdir -p "${HOME}"
fi

exec /opt/sima-cli/venv/bin/sima-cli "$@"
EOF
chmod 755 /usr/local/bin/sima-cli
/usr/local/bin/sima-cli --help >/dev/null 2>&1
