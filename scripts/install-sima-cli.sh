#!/usr/bin/env bash

set -euo pipefail

root_venv=/root/.sima-cli/.venv
install_venv=/opt/sima-cli/venv
installer=/tmp/sima-cli-install.py
installer_url=https://artifacts.neat.sima.ai/sima-cli/install.py
installer_sha256=9d7acf0bfb24f7b32abd305754359744f1034bbd1a440b6310037eef90696c25
sima_cli_ref="${SIMA_CLI_REF:?SIMA_CLI_REF is required}"
sima_cli_version="${SIMA_CLI_VERSION:?SIMA_CLI_VERSION is required}"

curl --fail --silent --show-error --location --retry 3 \
  "${installer_url}" \
  --output "${installer}"
printf '%s  %s\n' "${installer_sha256}" "${installer}" | sha256sum --check -

if [[ "${sima_cli_ref}" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([A-Za-z0-9_.-]+)?$ ]]; then
  if [[ "${sima_cli_version}" != "latest" ]]; then
    echo "PyPI release ref ${sima_cli_ref} does not accept an artifact version." >&2
    exit 1
  fi
  python3 "${installer}" "${sima_cli_ref}" --noninteractive
else
  python3 "${installer}" "${sima_cli_ref}" "${sima_cli_version}" --noninteractive
fi

test -x "${root_venv}/bin/sima-cli"
if [[ "${sima_cli_ref}" =~ ^v[0-9]+[.][0-9]+[.][0-9]+([A-Za-z0-9_.-]+)?$ ]]; then
  installed_version="$(
    "${root_venv}/bin/python" -c \
      'import importlib.metadata; print(importlib.metadata.version("sima-cli"))'
  )"
  if [[ "v${installed_version}" != "${sima_cli_ref}" ]]; then
    echo "Installed sima-cli ${installed_version}, expected ${sima_cli_ref}." >&2
    exit 1
  fi
fi

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
