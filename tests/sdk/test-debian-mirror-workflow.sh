#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
workflow="${repo_root}/.github/workflows/sync-debian-pre-release-mirror.yml"
sync_script="${repo_root}/scripts/sync-debian-pre-release-mirror.sh"

bash -n "${sync_script}"
python3 -m py_compile "${repo_root}/scripts/validate-debian-mirror.py"

grep -Fq 'workflow_dispatch:' "${workflow}"
grep -Fq 'schedule:' "${workflow}"
grep -Fq 'cron: "27 9 * * *"' "${workflow}"
grep -Fq 'github.event_name }}" == "schedule"' "${workflow}"
grep -Fq "inputs.minimum_free_gib || '100'" "${workflow}"
grep -Fq 'runs-on: [self-hosted, Linux, X64, apt-mirror]' "${workflow}"
grep -Fq 'cancel-in-progress: false' "${workflow}"
grep -Fq 'environment: production' "${workflow}"
grep -Fq 'id-token: write' "${workflow}"
grep -Fq -- '--rsync-extra=none' "${sync_script}"
grep -Fq -- '--omit-suite-symlinks' "${sync_script}"

# These grep patterns intentionally match literal shell expressions in the
# implementation rather than expanding them in this test process.
# shellcheck disable=SC2016
pool_upload_line="$(grep -nF 's3 sync "${REPOSITORY}/pool/' "${sync_script}" | cut -d: -f1)"
# shellcheck disable=SC2016
dists_upload_line="$(grep -nF 's3 sync "${REPOSITORY}/dists/' "${sync_script}" | cut -d: -f1)"
inrelease_upload_line="$(grep -n 'for metadata_name in Release Release.gpg InRelease' "${sync_script}" | cut -d: -f1)"
manifest_upload_line="$(grep -n 'pre-release/.mirror/publication.json' "${sync_script}" | tail -n 1 | cut -d: -f1)"

test "${pool_upload_line}" -lt "${dists_upload_line}"
test "${dists_upload_line}" -lt "${inrelease_upload_line}"
test "${inrelease_upload_line}" -lt "${manifest_upload_line}"

echo "Debian mirror workflow checks passed"
