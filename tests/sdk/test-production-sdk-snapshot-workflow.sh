#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
workflow="${repo_root}/.github/workflows/production-sdk-snapshot.yml"

grep -Fq 'workflow_dispatch:' "${workflow}"
grep -Fq 'sdk_branch:' "${workflow}"
grep -Fq 'snapshot_label:' "${workflow}"
grep -Fq 'AWS_REGION: us-west-2' "${workflow}"
grep -Fq 'environment: production' "${workflow}"
grep -Fq 'cancel-in-progress: false' "${workflow}"
grep -Fq 'permission-contents: write' "${workflow}"
grep -Fq 'permission-pull-requests: write' "${workflow}"
grep -Eq 'VULCAN_BUILDER_REF: [0-9a-f]{40}$' "${workflow}"
grep -Fq 'persist-credentials: false' "${workflow}"
# These patterns intentionally match literal GitHub and shell expressions.
# shellcheck disable=SC2016
grep -Fq 'ref: ${{ env.VULCAN_BASE_BRANCH }}' "${workflow}"
# shellcheck disable=SC2016
grep -Fq 'SDK_IMAGE: ${{ steps.image.outputs.pinned_image_ref }}' "${workflow}"
# shellcheck disable=SC2016
grep -Fq 'SDK_REF: ${{ steps.image.outputs.pinned_sdk_ref }}' "${workflow}"
# shellcheck disable=SC2016
grep -Fq 'EXPECTED_IMAGE_DIGEST: ${{ steps.image.outputs.digest }}' "${workflow}"
# shellcheck disable=SC2016
grep -Fq 'builder_digest}" != "${EXPECTED_IMAGE_DIGEST}"' "${workflow}"
grep -Fq 'timeout-minutes: 150' "${workflow}"
grep -Fq 'scripts/build-sdk-cache-snapshot.sh build' "${workflow}"
# shellcheck disable=SC2016
grep -Fq -- '--base "${VULCAN_BASE_BRANCH}"' "${workflow}"
grep -Fq 'aws ec2 delete-snapshot' "${workflow}"
grep -Fq 'scripts/build-sdk-cache-snapshot.sh cleanup' "${workflow}"
grep -Fq 'Key=DeleteAfter' "${workflow}"
grep -Fq 'steps.pull-request.outputs.url == '\''' "${workflow}"
grep -Fq 'retained because Vulcan PR status could not be verified' "${workflow}"
grep -Fq 'Terraform apply | Deferred for manual approval' "${workflow}"

if grep -Fq 'aws_region:' "${workflow}"; then
  echo "Production snapshot workflow must use the fixed us-west-2 region." >&2
  exit 1
fi

if grep -Fq 'terraform apply' "${workflow}"; then
  echo "Production snapshot workflow must leave Terraform apply to manual review." >&2
  exit 1
fi

echo "Production SDK snapshot workflow checks passed"
