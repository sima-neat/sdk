# Pre-release Debian mirror

The `Sync pre-release Debian mirror` workflow pulls the corporate repository at
`sw-web.eng.sima.ai/deb/pre-release`, validates it, and can publish it to the
production mirror at `https://debian.neat.sima.ai/pre-release`.

This is an operational mirror-transfer workflow only. It does not build or
modify the SDK container, SDK packages, or SDK installation behavior; the SDK
repository is only the home for the workflow and its synchronization utility.

The workflow runs every 30 minutes at 17 and 47 minutes past the hour and can also be started manually. Scheduled
runs publish after validation; manual runs expose an explicit `publish` switch
so the first production validation can download and verify without changing S3.
Package downloads use `apt-mirror2` with 16 asynchronous workers by default.
Manual runs can override `download_workers`; use a value from 1 through 64.

## Private runner

Use a corporate-network Linux x86_64 runner with these labels:

```text
self-hosted, Linux, X64, apt-mirror
```

Restrict the runner group to `sima-neat/sdk`. The host must resolve and reach
`sw-web.eng.sima.ai`, allow passwordless `sudo` for package installation and
workspace creation, and provide at least 150 GiB of persistent storage. The
workflow stores incremental mirror state outside the Actions checkout at:

```text
/var/lib/sima-neat/debian-mirror
```

Set the protected SDK `production` environment variable
`DEBIAN_MIRROR_WORK_ROOT` if the persistent volume is mounted elsewhere.

## Pre-release trust model

This mirror is limited to controlled internal pre-release testing. The private
source is transported over the corporate network using HTTP, and its current
repository signature cannot be verified with the public key it advertises.
The synchronization therefore disables upstream Release signature verification while
still verifying that every referenced package exists and matches the size and
SHA256 recorded in the downloaded package indexes.

Clients access the Vulcan mirror through HTTPS and must explicitly mark this
pre-release source as trusted:

```text
deb [trusted=yes] https://debian.neat.sima.ai/pre-release bookworm non-free
```

This configuration must not be reused for a production or publicly trusted
package channel. HTTPS protects transport from Vulcan to the client, but the
package-index checks do not establish the upstream publisher's identity.

## First manual run

1. Open **Actions → Sync pre-release Debian mirror → Run workflow**.
2. Select `main`.
3. Leave `publish` disabled for the first run. This downloads and validates
   every referenced package without changing S3.
4. Review the job summary and confirm the package count, byte count, source
   date, and `InRelease` digest.
5. Run it again with `publish` enabled. The persistent mirror makes this run
   incremental.

After rollout, the scheduled run executes every 30 minutes, performs the same
validation, and enables publication automatically. It exits successfully
without uploading when the upstream `InRelease` digest has not changed.

Each changed run compares the validated package indexes with the inventory from
the last successful publication. The Actions summary reports package files
added to the indexes, package files removed from the indexes, and correlated
version changes by package and architecture. It shows up to 50 entries in each
category and records the complete machine-readable inventory and change report
under digest-addressed `.mirror/inventories/` and `.mirror/changes/` S3 keys.
Each run also uploads a three-day, machine-readable GitHub Actions artifact
containing its complete change report, platform version, and publication
provenance. This is the input to the daily reporting workflow.

## Daily change digest

The `Daily pre-release mirror summary` workflow runs once per day on the
corporate Alice reporting runner using these labels:

```text
self-hosted, Linux, X64, issue-triage
```

It uses read-only GitHub Actions permission to enumerate successful mirror-sync
runs from the previous 24 hours and download their short-lived result artifacts.
It does not assume a Vulcan or AWS role. Scheduled runs post a concise digest to
`neat-sync-mirror-notification`; manual runs default to preview-only and can
replay a bounded window with an explicit UTC `as_of` timestamp.

Configure the following GitHub settings:

- organization secret `SLACK_BOT_TOKEN`;
- variable `SLACK_MIRROR_NOTIFICATION_CHANNEL_ID` containing the Slack channel
  ID (not its display name).

The report generator follows the same Codex-on-Alice pattern as the process
repository. Package counts, version ordering, grouping, and the fallback report
are deterministic Python logic; Codex is used only to tighten the wording. The
normalized context, prompt, and rendered digest are retained as short-lived
workflow artifacts for auditing. Jenkins correlation is not part of this
initial implementation.

"Removed" means no longer referenced by the published APT indexes. Old package
objects remain in the S3 pool during the initial rollout for safe rollback.

Package objects and immutable `by-hash` indexes are uploaded before repository
metadata. On the first publication, all ordinary index paths are also seeded,
including the nested `binary-*/Release` files. The suite-level `Release` is
replaced last and contains `Acquire-By-Hash: yes`, making that single S3 object
the publication boundary. Later runs retain the previous ordinary index paths
so clients holding an older `Release` continue to see a consistent generation.

apt-mirror2 may retrieve only compressed `Packages.gz` indexes. Before
publication, the workflow reconstructs each logical `Packages` index and
verifies its size and checksums against the upstream Release metadata. Both
forms and every advertised by-hash algorithm are published so APT clients can
discover and fetch the package index normally.

Because the destination `Release` is transformed to describe the binary-only
mirror and enable by-hash, the upstream `InRelease` and `Release.gpg` signatures
are not published. This is consistent with the explicitly trusted pre-release
client configuration above. Old package-pool objects are not deleted by the
initial implementation.

The production CloudFront endpoint is currently blocked by WAF. Publishing can
be validated through S3, but `apt update` requires a separately approved public
or corporate/VPN CIDR access policy.

## No-change behavior

The workflow compares the upstream `InRelease` SHA256 with:

```text
s3://sima-neat-debian-production/pre-release/.mirror/publication.json
```

An unchanged repository exits successfully without downloading or publishing.
Use the `force` input only when the local mirror must be rebuilt or revalidated.

## Rollback

The production bucket is versioned. To roll back, identify the last known-good
version of `pre-release/dists/bookworm/Release` and restore that object last.
The digest-addressed indexes and package-pool objects are immutable and must not
be deleted. Invalidate `/pre-release/dists/*` after restoration, then verify the
restored index and all referenced package checksums before reopening client
access.
