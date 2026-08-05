#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
workflow="${repo_root}/.github/workflows/sync-debian-pre-release-mirror.yml"
sync_script="${repo_root}/scripts/sync-debian-pre-release-mirror.sh"
documentation="${repo_root}/docs/debian-pre-release-mirror.md"

bash -n "${sync_script}"
python3 -m py_compile "${repo_root}/scripts/validate-debian-mirror.py"
python3 -m py_compile "${repo_root}/scripts/compare-debian-mirror-inventories.py"
python3 -m py_compile "${repo_root}/scripts/prepare-debian-by-hash.py"
python3 "${repo_root}/tests/sdk/test-debian-by-hash.py"

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
grep -Fq -- '--ignore-release-gpg' "${sync_script}"
grep -Fq 'Acquire-By-Hash' "${repo_root}/scripts/prepare-debian-by-hash.py"
grep -Fq -- '-name Release -print0' "${sync_script}"
grep -Fq 'deb [trusted=yes] https://debian.neat.sima.ai/pre-release bookworm non-free' "${documentation}"
if grep -Eq 'gpgv|SIGNING_KEY|PINNED_KEY' "${sync_script}" "${workflow}"; then
  echo "The internal pre-release mirror must not require an APT signing key" >&2
  exit 1
fi
grep -Fq 'Added package files:' "${sync_script}"
grep -Fq 'Removed from package indexes:' "${sync_script}"
grep -Fq 'Package version changes:' "${sync_script}"
grep -Fq 'pool filename(s) with different content; refusing publication' "${sync_script}"
# shellcheck disable=SC2016
grep -Fq '.mirror/inventories/${source_digest}.json' "${sync_script}"
# shellcheck disable=SC2016
grep -Fq '.mirror/changes/${source_digest}.json' "${sync_script}"

# These grep patterns intentionally match literal shell expressions in the
# implementation rather than expanding them in this test process.
# shellcheck disable=SC2016
pool_upload_line="$(grep -nF 's3 sync "${REPOSITORY}/pool/' "${sync_script}" | cut -d: -f1)"
# shellcheck disable=SC2016
by_hash_upload_line="$(grep -nF 's3 sync "${PUBLISH_DISTS}/' "${sync_script}" | head -n 1 | cut -d: -f1)"
# shellcheck disable=SC2016
release_upload_line="$(grep -nF 'aws s3 cp "${PUBLISH_DISTS}/${SUITE}/Release"' "${sync_script}" | cut -d: -f1)"
manifest_upload_line="$(grep -n 'pre-release/.mirror/publication.json' "${sync_script}" | tail -n 1 | cut -d: -f1)"

test "${pool_upload_line}" -lt "${by_hash_upload_line}"
test "${by_hash_upload_line}" -lt "${release_upload_line}"
test "${release_upload_line}" -lt "${manifest_upload_line}"

echo "Debian mirror workflow checks passed"
