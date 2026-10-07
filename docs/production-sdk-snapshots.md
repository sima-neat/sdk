# Production SDK snapshots

The `Build production SDK snapshot` workflow creates an EBS-backed SDK cache
snapshot and proposes the corresponding Vulcan production configuration change.
It is intentionally a manual, protected production operation.

## Repository configuration

Configure these values on the SDK repository's protected `production`
environment:

- `VULCAN_SNAPSHOT_BUILDER_ROLE_ARN` environment variable: an AWS role that the
  SDK repository's GitHub OIDC identity can assume to run Vulcan's SDK snapshot
  builder in the production account.
- `VULCAN_AUTOMATION_APP_ID` and `VULCAN_AUTOMATION_APP_PRIVATE_KEY` environment
  secrets: credentials for a GitHub App installed on `sima-neat/vulcan` with
  Contents and Pull requests read/write permissions.
- `GHCR_READ_USERNAME` environment variable and `GHCR_READ_TOKEN` environment
  secret when the workflow's `GITHUB_TOKEN` cannot read the SDK packages. The
  token needs read-only package access.

Keep required reviewers enabled on the `production` environment. The workflow
does not receive AWS or Vulcan write credentials until that approval succeeds.

## Run the workflow

Open **Actions**, select **Build production SDK snapshot**, and choose **Run
workflow**. Supply:

- `sdk_branch`: the SDK source branch, such as `main` or `develop`.
- `snapshot_label`: the platform version and channel without the `sdk-` prefix,
  such as `2.1.3-develop` or `2.1.3-official`.

Production snapshots are always built in `us-west-2`.

The workflow resolves the branch head's GHCR image and pins the build to its
manifest digest. For example, `develop` first resolves
`ghcr.io/sima-neat/sdk-develop:<commit-sha>` and then builds from
`ghcr.io/sima-neat/sdk-develop@sha256:<digest>`. The image must already have been
published successfully by the SDK image workflow. The workflow also verifies
that the digest reported by the Vulcan builder matches the resolved digest.

The production builder executes from the reviewed `VULCAN_BUILDER_REF` commit
embedded in the workflow, never from mutable Vulcan `develop`. Updating the
builder requires reviewing and changing that pin in the SDK workflow. A separate
checkout of the current Vulcan `develop` branch is used only to prepare the
configuration pull request; no scripts from that checkout run with production
credentials.

After the EBS snapshot completes, the workflow creates a branch from Vulcan's
`develop` branch, updates `envs/production/variables.tf`, and opens a Vulcan pull
request. The Actions summary and PR body record the source branch and commit,
image and digest, new and previous snapshot IDs, and cache label.

Review and merge the Vulcan PR, then apply the production Terraform stack using
the approved Vulcan production process. Only delete the previous snapshot after
the rollout is validated and its retention window has expired. The SDK workflow
does not apply Terraform or remove a snapshot that production may still use.

If a run fails after creating a new snapshot but before opening the Vulcan PR,
the workflow deletes that snapshot, removes any pushed automation branch, and
uses the pinned Vulcan cleanup command to remove temporary builder resources
left by an interrupted build. If AWS cannot immediately delete the snapshot, it
marks the snapshot as failed and adds a seven-day `DeleteAfter` tag for
operational cleanup. An existing open PR—or an inability to verify PR
state—always prevents automatic snapshot deletion.
