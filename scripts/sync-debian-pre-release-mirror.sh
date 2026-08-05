#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

UPSTREAM_HOST="sw-web.eng.sima.ai"
UPSTREAM_ROOT="deb/pre-release"
UPSTREAM_BASE_URL="http://${UPSTREAM_HOST}/${UPSTREAM_ROOT}"
SUITE="bookworm"
COMPONENT="non-free"
ARCHITECTURES="arm64,arc,armhf,i386,amd64"
EXPECTED_KEY_FINGERPRINT="${DEBIAN_MIRROR_SIGNING_KEY_FINGERPRINT:-1BF9F1E5FB3390385B218F1787E953B7D88B741D}"
PINNED_KEY="${DEBIAN_MIRROR_SIGNING_KEY_PATH:-${REPO_DIR}/config/keys/simaai-pre-release.asc}"

PUBLISH=false
FORCE=false
MINIMUM_FREE_GIB="${MINIMUM_FREE_GIB:-100}"
WORK_ROOT="${DEBIAN_MIRROR_WORK_ROOT:-/var/lib/sima-neat/debian-mirror}"
AWS_REGION="${AWS_REGION:-us-west-2}"
BUCKET="${VULCAN_DEBIAN_MIRROR_BUCKET:-}"
KMS_KEY_ID="${VULCAN_DEBIAN_MIRROR_KMS_KEY_ID:-}"
CLOUDFRONT_DISTRIBUTION_ID="${VULCAN_DEBIAN_MIRROR_CLOUDFRONT_DISTRIBUTION_ID:-}"

usage() {
  cat <<'EOF'
Usage: sync-debian-pre-release-mirror.sh [options]

Options:
  --publish            Upload a validated mirror to the production S3 bucket.
  --force              Sync even when the published InRelease digest is unchanged.
  --work-root PATH     Persistent mirror workspace.
  --minimum-free-gib N Required free space before mirroring (default: 100).
  --help               Show this help.
EOF
}

while (($#)); do
  case "$1" in
    --publish) PUBLISH=true ;;
    --force) FORCE=true ;;
    --work-root) WORK_ROOT="${2:?--work-root requires a path}"; shift ;;
    --minimum-free-gib) MINIMUM_FREE_GIB="${2:?--minimum-free-gib requires a value}"; shift ;;
    --help) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

for command in aws curl debmirror flock gpg gpgv jq python3 sha256sum; do
  command -v "${command}" >/dev/null || {
    echo "Required command is unavailable: ${command}" >&2
    exit 1
  }
done

if ! [[ "${MINIMUM_FREE_GIB}" =~ ^[0-9]+$ ]]; then
  echo "--minimum-free-gib must be a non-negative integer" >&2
  exit 2
fi

if [[ -z "${BUCKET}" || -z "${KMS_KEY_ID}" || -z "${CLOUDFRONT_DISTRIBUTION_ID}" ]]; then
  echo "VULCAN_DEBIAN_MIRROR_BUCKET, VULCAN_DEBIAN_MIRROR_KMS_KEY_ID, and VULCAN_DEBIAN_MIRROR_CLOUDFRONT_DISTRIBUTION_ID are required" >&2
  exit 1
fi

mkdir -p "${WORK_ROOT}"
exec 9>"${WORK_ROOT}/sync.lock"
if ! flock -n 9; then
  echo "Another Debian mirror synchronization owns ${WORK_ROOT}/sync.lock" >&2
  exit 1
fi

REPOSITORY="${WORK_ROOT}/repository"
STATE_DIR="${WORK_ROOT}/state"
mkdir -p "${REPOSITORY}" "${STATE_DIR}"
TEMP_DIR="$(mktemp -d "${WORK_ROOT}/run.XXXXXX")"
trap 'rm -rf -- "${TEMP_DIR}"' EXIT

KEYRING="${STATE_DIR}/simaai-pre-release.gpg"
INRELEASE="${TEMP_DIR}/InRelease"
VALIDATION_JSON="${TEMP_DIR}/validation.json"
PUBLICATION_JSON="${TEMP_DIR}/publication.json"

actual_fingerprint="$(gpg --batch --show-keys --with-colons "${PINNED_KEY}" | awk -F: '$1 == "fpr" {print $10; exit}')"
if [[ "${actual_fingerprint}" != "${EXPECTED_KEY_FINGERPRINT}" ]]; then
  echo "Pinned key fingerprint mismatch: expected ${EXPECTED_KEY_FINGERPRINT}, got ${actual_fingerprint}" >&2
  exit 1
fi
gpg --batch --yes --dearmor --output "${KEYRING}" "${PINNED_KEY}"

getent hosts "${UPSTREAM_HOST}" >/dev/null
curl --fail --silent --show-error --location --max-time 120 \
  --output "${INRELEASE}" "${UPSTREAM_BASE_URL}/dists/${SUITE}/InRelease"
gpgv --keyring "${KEYRING}" "${INRELEASE}"

source_digest="$(sha256sum "${INRELEASE}" | awk '{print $1}')"
source_date="$(sed -n 's/^Date: //p' "${INRELEASE}" | head -n 1)"
source_architectures="$(sed -n 's/^Architectures: //p' "${INRELEASE}" | head -n 1)"
source_components="$(sed -n 's/^Components: //p' "${INRELEASE}" | head -n 1)"

[[ " ${source_architectures} " == *" arm64 "* ]]
[[ " ${source_architectures} " == *" arc "* ]]
[[ " ${source_architectures} " == *" armhf "* ]]
[[ " ${source_architectures} " == *" i386 "* ]]
[[ " ${source_architectures} " == *" amd64 "* ]]
[[ " ${source_components} " == *" ${COMPONENT} "* ]]

previous_digest="$(
  aws s3 cp "s3://${BUCKET}/pre-release/.mirror/publication.json" - \
    --region "${AWS_REGION}" --only-show-errors 2>/dev/null |
    jq -r '.source.inrelease_sha256 // empty' 2>/dev/null || true
)"

if [[ "${FORCE}" != true && -n "${previous_digest}" && "${source_digest}" == "${previous_digest}" ]]; then
  echo "Upstream InRelease is unchanged (${source_digest}); nothing to publish."
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf "## Debian mirror synchronization\n\nNo change: \`%s\`\n" "${source_digest}" >>"${GITHUB_STEP_SUMMARY}"
  fi
  exit 0
fi

available_kib="$(df -Pk "${WORK_ROOT}" | awk 'NR == 2 {print $4}')"
required_kib="$((MINIMUM_FREE_GIB * 1024 * 1024))"
if ((available_kib < required_kib)); then
  echo "Insufficient free space under ${WORK_ROOT}: require ${MINIMUM_FREE_GIB} GiB" >&2
  exit 1
fi

debmirror "${REPOSITORY}" \
  --host="${UPSTREAM_HOST}" \
  --root="${UPSTREAM_ROOT}" \
  --method=http \
  --dist="${SUITE}" \
  --section="${COMPONENT}" \
  --arch="${ARCHITECTURES}" \
  --nosource \
  --rsync-extra=none \
  --omit-suite-symlinks \
  --keyring="${KEYRING}" \
  --progress

gpgv --keyring "${KEYRING}" "${REPOSITORY}/dists/${SUITE}/InRelease"
mirrored_digest="$(sha256sum "${REPOSITORY}/dists/${SUITE}/InRelease" | awk '{print $1}')"
if [[ "${mirrored_digest}" != "${source_digest}" ]]; then
  echo "Mirrored InRelease changed during synchronization; refusing publication" >&2
  exit 1
fi

python3 "${SCRIPT_DIR}/validate-debian-mirror.py" \
  "${REPOSITORY}" \
  --suite "${SUITE}" \
  --component "${COMPONENT}" \
  --architectures "${ARCHITECTURES}" \
  --output "${VALIDATION_JSON}"

package_count="$(jq -r '.package_count' "${VALIDATION_JSON}")"
total_bytes="$(jq -r '.total_bytes' "${VALIDATION_JSON}")"
publication_time="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
jq -n \
  --arg source_url "${UPSTREAM_BASE_URL}" \
  --arg source_date "${source_date}" \
  --arg source_digest "${source_digest}" \
  --arg published_at "${publication_time}" \
  --arg repository "${GITHUB_REPOSITORY:-local}" \
  --arg workflow_run "${GITHUB_RUN_ID:-local}" \
  --arg commit "${GITHUB_SHA:-local}" \
  --argjson package_count "${package_count}" \
  --argjson total_bytes "${total_bytes}" \
  '{schema_version: 1, source: {url: $source_url, date: $source_date, inrelease_sha256: $source_digest}, validation: {package_count: $package_count, total_bytes: $total_bytes}, publication: {published_at: $published_at, repository: $repository, workflow_run: $workflow_run, commit: $commit}}' \
  >"${PUBLICATION_JSON}"

if [[ "${PUBLISH}" == true ]]; then
  s3_common=(--region "${AWS_REGION}" --sse aws:kms --sse-kms-key-id "${KMS_KEY_ID}" --only-show-errors)

  # Package objects are immutable and must be available before any metadata
  # that references them becomes visible to APT clients.
  aws s3 sync "${REPOSITORY}/pool/" "s3://${BUCKET}/pre-release/pool/" \
    "${s3_common[@]}" --cache-control 'public,max-age=31536000,immutable'

  # Upload unsigned/index metadata first. The signed Release files are promoted
  # one at a time, with InRelease last, so a failed run cannot advertise files
  # that have not already reached the bucket.
  aws s3 sync "${REPOSITORY}/dists/" "s3://${BUCKET}/pre-release/dists/" \
    "${s3_common[@]}" --cache-control 'no-cache,no-store,must-revalidate' \
    --exclude '*/InRelease' --exclude '*/Release' --exclude '*/Release.gpg'

  for metadata_name in Release Release.gpg InRelease; do
    metadata_path="${REPOSITORY}/dists/${SUITE}/${metadata_name}"
    if [[ -f "${metadata_path}" ]]; then
      aws s3 cp "${metadata_path}" \
        "s3://${BUCKET}/pre-release/dists/${SUITE}/${metadata_name}" \
        "${s3_common[@]}" --cache-control 'no-cache,no-store,must-revalidate'
    fi
  done

  aws s3 cp "${PUBLICATION_JSON}" \
    "s3://${BUCKET}/pre-release/.mirror/publication.json" \
    "${s3_common[@]}" --cache-control 'no-cache,no-store,must-revalidate' \
    --content-type application/json

  aws cloudfront create-invalidation \
    --region "${AWS_REGION}" \
    --distribution-id "${CLOUDFRONT_DISTRIBUTION_ID}" \
    --paths '/pre-release/dists/*' '/pre-release/.mirror/publication.json' \
    >/dev/null
  result="Published"
else
  result="Validated only"
fi

echo "${result}: ${package_count} packages, ${total_bytes} bytes, InRelease ${source_digest}"
if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo '## Debian mirror synchronization'
    echo
    echo "- Result: ${result}"
    echo "- Source date: ${source_date}"
    echo "- InRelease SHA256: \`${source_digest}\`"
    echo "- Unique packages: ${package_count}"
    echo "- Referenced bytes: ${total_bytes}"
  } >>"${GITHUB_STEP_SUMMARY}"
fi
