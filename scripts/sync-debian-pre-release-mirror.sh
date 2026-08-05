#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

UPSTREAM_HOST="sw-web.eng.sima.ai"
UPSTREAM_ROOT="deb/pre-release"
UPSTREAM_BASE_URL="http://${UPSTREAM_HOST}/${UPSTREAM_ROOT}"
SUITE="bookworm"
COMPONENT="non-free"
ARCHITECTURES="arm64,arc,armhf,i386,amd64"
APT_MIRROR2_THREADS="${APT_MIRROR2_THREADS:-16}"

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

for command in apt-mirror2 aws cp curl find flock jq python3 sha256sum; do
  command -v "${command}" >/dev/null || {
    echo "Required command is unavailable: ${command}" >&2
    exit 1
  }
done

if ! [[ "${MINIMUM_FREE_GIB}" =~ ^[0-9]+$ ]]; then
  echo "--minimum-free-gib must be a non-negative integer" >&2
  exit 2
fi

if ! [[ "${APT_MIRROR2_THREADS}" =~ ^[0-9]+$ ]] || \
  ((APT_MIRROR2_THREADS < 1 || APT_MIRROR2_THREADS > 64)); then
  echo "APT_MIRROR2_THREADS must be an integer from 1 through 64" >&2
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
mkdir -p "${REPOSITORY}"
TEMP_DIR="$(mktemp -d "${WORK_ROOT}/run.XXXXXX")"
trap 'rm -rf -- "${TEMP_DIR}"' EXIT

INRELEASE="${TEMP_DIR}/InRelease"
VALIDATION_JSON="${TEMP_DIR}/validation.json"
CURRENT_INVENTORY_JSON="${TEMP_DIR}/inventory.json"
PREVIOUS_INVENTORY_JSON="${TEMP_DIR}/previous-inventory.json"
PREVIOUS_PUBLICATION_JSON="${TEMP_DIR}/previous-publication.json"
CHANGES_JSON="${TEMP_DIR}/changes.json"
PUBLICATION_JSON="${TEMP_DIR}/publication.json"
PUBLISH_DISTS="${TEMP_DIR}/publish-dists"
APT_MIRROR2_CONFIG="${TEMP_DIR}/apt-mirror2.list"

getent hosts "${UPSTREAM_HOST}" >/dev/null
curl --fail --silent --show-error --location --max-time 120 \
  --output "${INRELEASE}" "${UPSTREAM_BASE_URL}/dists/${SUITE}/InRelease"

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

previous_digest=""
previous_inventory_key=""
if aws s3 cp "s3://${BUCKET}/pre-release/.mirror/publication.json" \
  "${PREVIOUS_PUBLICATION_JSON}" --region "${AWS_REGION}" --only-show-errors 2>/dev/null; then
  previous_digest="$(jq -r '.source.inrelease_sha256 // empty' "${PREVIOUS_PUBLICATION_JSON}")"
  previous_inventory_key="$(jq -r '.publication.inventory_key // empty' "${PREVIOUS_PUBLICATION_JSON}")"
fi

if [[ "${FORCE}" != true && -n "${previous_digest}" && "${source_digest}" == "${previous_digest}" ]]; then
  echo "Upstream InRelease is unchanged (${source_digest}); nothing to publish."
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    {
      echo '## Debian mirror synchronization'
      echo
      echo "- Result: No change"
      echo "- InRelease SHA256: \`${source_digest}\`"
      echo "- Added package files: 0"
      echo "- Removed from package indexes: 0"
      echo "- Package version changes: 0"
    } >>"${GITHUB_STEP_SUMMARY}"
  fi
  exit 0
fi

available_kib="$(df -Pk "${WORK_ROOT}" | awk 'NR == 2 {print $4}')"
required_kib="$((MINIMUM_FREE_GIB * 1024 * 1024))"
if ((available_kib < required_kib)); then
  echo "Insufficient free space under ${WORK_ROOT}: require ${MINIMUM_FREE_GIB} GiB" >&2
  exit 1
fi

cat >"${APT_MIRROR2_CONFIG}" <<EOF
set base_path ${WORK_ROOT}/apt-mirror2
set mirror_path ${WORK_ROOT}
set skel_path ${WORK_ROOT}/apt-mirror2/skel
set var_path ${WORK_ROOT}/apt-mirror2/var
set nthreads ${APT_MIRROR2_THREADS}
set gpg_verify off
set write_file_lists off
set _autoclean 0
set use_dists_move 1

mirror_path ${UPSTREAM_BASE_URL} repository
deb [ arch=${ARCHITECTURES} by-hash=no ] ${UPSTREAM_BASE_URL} ${SUITE} ${COMPONENT}
EOF

echo "Mirroring with apt-mirror2 using ${APT_MIRROR2_THREADS} concurrent downloads"
apt-mirror2 "${APT_MIRROR2_CONFIG}"

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

# Publish a transformed unsigned Release with Acquire-By-Hash enabled. The
# upstream signature cannot be retained because --nosource removes source
# indexes and the Release file must describe only the mirrored content.
cp -a "${REPOSITORY}/dists" "${PUBLISH_DISTS}"
python3 "${SCRIPT_DIR}/prepare-debian-by-hash.py" \
  "${PUBLISH_DISTS}" \
  --suite "${SUITE}"

jq '{schema_version: 1, packages: .packages}' \
  "${VALIDATION_JSON}" >"${CURRENT_INVENTORY_JSON}"
previous_inventory_arguments=()
if [[ "${previous_inventory_key}" == pre-release/.mirror/inventories/*.json ]] && \
  aws s3 cp "s3://${BUCKET}/${previous_inventory_key}" "${PREVIOUS_INVENTORY_JSON}" \
    --region "${AWS_REGION}" --only-show-errors 2>/dev/null; then
  previous_inventory_arguments=(--previous "${PREVIOUS_INVENTORY_JSON}")
fi
if [[ "${PUBLISH}" == true && -n "${previous_digest}" && \
  ${#previous_inventory_arguments[@]} -eq 0 ]]; then
  echo "Previous publication inventory is unavailable; refusing publication" >&2
  exit 1
fi
python3 "${SCRIPT_DIR}/compare-debian-mirror-inventories.py" \
  "${previous_inventory_arguments[@]}" \
  --current "${CURRENT_INVENTORY_JSON}" \
  --output "${CHANGES_JSON}"

package_count="$(jq -r '.package_count' "${VALIDATION_JSON}")"
total_bytes="$(jq -r '.total_bytes' "${VALIDATION_JSON}")"
added_count="$(jq -r '.counts.added_files' "${CHANGES_JSON}")"
removed_count="$(jq -r '.counts.removed_files' "${CHANGES_JSON}")"
version_change_count="$(jq -r '.counts.version_changes' "${CHANGES_JSON}")"
reused_file_content_count="$(jq -r '.counts.reused_file_content' "${CHANGES_JSON}")"
if [[ "${PUBLISH}" == true && "${reused_file_content_count}" -gt 0 ]]; then
  echo "Upstream reused ${reused_file_content_count} pool filename(s) with different content; refusing publication" >&2
  jq -r '.reused_file_content[] | "- \(.filename): \(.previous_sha256) -> \(.current_sha256)"' \
    "${CHANGES_JSON}" >&2
  exit 1
fi
publication_time="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
inventory_key="pre-release/.mirror/inventories/${source_digest}.json"
changes_key="pre-release/.mirror/changes/${source_digest}.json"
jq -n \
  --arg source_url "${UPSTREAM_BASE_URL}" \
  --arg source_date "${source_date}" \
  --arg source_digest "${source_digest}" \
  --arg published_at "${publication_time}" \
  --arg repository "${GITHUB_REPOSITORY:-local}" \
  --arg workflow_run "${GITHUB_RUN_ID:-local}" \
  --arg commit "${GITHUB_SHA:-local}" \
  --arg inventory_key "${inventory_key}" \
  --arg changes_key "${changes_key}" \
  --argjson package_count "${package_count}" \
  --argjson total_bytes "${total_bytes}" \
  --slurpfile changes "${CHANGES_JSON}" \
  '{schema_version: 1, source: {url: $source_url, date: $source_date, inrelease_sha256: $source_digest}, validation: {package_count: $package_count, total_bytes: $total_bytes}, changes: $changes[0].counts, publication: {published_at: $published_at, repository: $repository, workflow_run: $workflow_run, commit: $commit, inventory_key: $inventory_key, changes_key: $changes_key, apt_release_mode: "unsigned-by-hash"}}' \
  >"${PUBLICATION_JSON}"

if [[ "${PUBLISH}" == true ]]; then
  s3_common=(--region "${AWS_REGION}" --sse aws:kms --sse-kms-key-id "${KMS_KEY_ID}" --only-show-errors)

  # Versioned inventory records are uploaded before publication and become
  # authoritative only when the final publication manifest references them.
  aws s3 cp "${CURRENT_INVENTORY_JSON}" "s3://${BUCKET}/${inventory_key}" \
    "${s3_common[@]}" --cache-control 'public,max-age=31536000,immutable' \
    --content-type application/json
  aws s3 cp "${CHANGES_JSON}" "s3://${BUCKET}/${changes_key}" \
    "${s3_common[@]}" --cache-control 'public,max-age=31536000,immutable' \
    --content-type application/json

  # Package objects are immutable and must be available before any metadata
  # that references them becomes visible to APT clients.
  aws s3 sync "${REPOSITORY}/pool/" "s3://${BUCKET}/pre-release/pool/" \
    "${s3_common[@]}" --cache-control 'public,max-age=31536000,immutable'

  # Upload immutable index objects before the Release file that advertises
  # them. APT fetches these digest-addressed paths after reading the new
  # Acquire-By-Hash Release, so an interrupted upload cannot create a mixed
  # generation of mutable Packages files.
  aws s3 sync "${PUBLISH_DISTS}/" "s3://${BUCKET}/pre-release/dists/" \
    "${s3_common[@]}" --cache-control 'public,max-age=31536000,immutable' \
    --exclude '*' --include '*/by-hash/SHA256/*'

  # Seed all ordinary index paths, including binary-*/Release, on the initial
  # publication. Keep these paths unchanged on later runs so a client holding
  # the previous Release can still fetch a consistent generation.
  if [[ -z "${previous_digest}" ]]; then
    aws s3 sync "${PUBLISH_DISTS}/" "s3://${BUCKET}/pre-release/dists/" \
      "${s3_common[@]}" --cache-control 'no-cache,no-store,must-revalidate' \
      --exclude '*/by-hash/SHA256/*' \
      --exclude "${SUITE}/Release"
  fi

  # Older publisher versions excluded every path named Release. Seed any
  # missing nested Release files without replacing a previous generation.
  while IFS= read -r -d '' nested_release; do
    relative_path="${nested_release#"${PUBLISH_DISTS}/"}"
    object_key="pre-release/dists/${relative_path}"
    if ! aws s3api head-object --bucket "${BUCKET}" --key "${object_key}" \
      --region "${AWS_REGION}" >/dev/null 2>&1; then
      aws s3 cp "${nested_release}" "s3://${BUCKET}/${object_key}" \
        "${s3_common[@]}" --cache-control 'no-cache,no-store,must-revalidate'
    fi
  done < <(find "${PUBLISH_DISTS}/${SUITE}" -mindepth 3 -type f \
    -name Release -print0)

  # The transformed Release is intentionally unsigned. Remove any previously
  # published source signatures before switching the suite Release.
  for signature_name in InRelease Release.gpg; do
    aws s3 rm "s3://${BUCKET}/pre-release/dists/${SUITE}/${signature_name}" \
      --region "${AWS_REGION}" --only-show-errors
  done

  # This single S3 object replacement is the publication boundary.
  aws s3 cp "${PUBLISH_DISTS}/${SUITE}/Release" \
    "s3://${BUCKET}/pre-release/dists/${SUITE}/Release" \
    "${s3_common[@]}" --cache-control 'no-cache,no-store,must-revalidate'

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
    echo "- Added package files: ${added_count}"
    echo "- Removed from package indexes: ${removed_count}"
    echo "- Package version changes: ${version_change_count}"
    if [[ "$(jq -r '.baseline_available' "${CHANGES_JSON}")" != true ]]; then
      echo "- Baseline: no previous inventory; all current package files are reported as added"
    fi
    echo
    echo '### Version changes (up to 50)'
    echo
    echo '| Package | Architecture | Previous | Current |'
    echo '|---|---|---|---|'
    jq -r '.version_changes[:50][] | "| `\(.package)` | `\(.architecture)` | `\(.previous_versions | join(", "))` | `\(.current_versions | join(", "))` |"' "${CHANGES_JSON}"
    echo
    echo '### Added package files (up to 50)'
    echo
    echo '| Package | Version | Architecture | File |'
    echo '|---|---|---|---|'
    jq -r '.added[:50][] | "| `\(.package)` | `\(.version)` | `\(.architecture)` | `\(.filename)` |"' "${CHANGES_JSON}"
    echo
    echo '### Removed from package indexes (up to 50)'
    echo
    echo '| Package | Version | Architecture | File |'
    echo '|---|---|---|---|'
    jq -r '.removed[:50][] | "| `\(.package)` | `\(.version)` | `\(.architecture)` | `\(.filename)` |"' "${CHANGES_JSON}"
    echo
    if [[ "${PUBLISH}" == true ]]; then
      echo "Full inventory: \`${inventory_key}\`"
      echo "Full change report: \`${changes_key}\`"
    else
      echo 'Full inventory and change report will be retained when publication is enabled.'
    fi
  } >>"${GITHUB_STEP_SUMMARY}"
fi
