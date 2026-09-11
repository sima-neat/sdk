# Pre-release Debian mirror

The `Sync pre-release Debian mirror` workflow pulls the corporate repository at
`sw-web.eng.sima.ai/deb/daily` (suite `agate`, ARM64), validates it, and can publish it to the
production mirror at `https://debian.neat.sima.ai/daily`.

This is an operational mirror-transfer workflow only. It does not build or
modify the SDK container, SDK packages, or SDK installation behavior; the SDK
repository is only the home for the workflow and its synchronization utility.

The workflow runs every 30 minutes at 17 and 47 minutes past the hour and can also be started manually. Scheduled
runs publish after validation; manual runs expose an explicit `publish` switch
so the first production validation can download and verify without changing S3.
Package downloads use `apt-mirror2` with 16 asynchronous workers by default.
Manual runs can override `download_workers`; use a value from 1 through 64.
The dependency setup supports Ubuntu 22.04, 24.04, and 26.04 runners. It uses
Ubuntu's native `apt-mirror2` package when available and otherwise configures
the upstream signed Packagecloud repository after verifying its signing-key
fingerprint. The installer also normalizes Packagecloud's historical
`apt-mirror` executable name to `apt-mirror2` for the synchronization script.

## Platform 3.0 source

The source metadata is
`http://sw-web.eng.sima.ai/deb/daily/dists/agate/InRelease`. Agate advertises
only ARM64; the mirror also includes architecture-independent (`all`) packages
referenced by that index. Platform versions use the upstream
`3.0.0~git<timestamp>.<commit>-<build>` format and are copied without rewriting.

The daily source has its own public channel, `/daily`, with the new suite at
`/daily/dists/agate`. Existing `/pre-release/dists/bookworm` objects are retained but are no
longer synchronized by this workflow. Local downloads use
`${DEBIAN_MIRROR_WORK_ROOT}/agate/`, and publication state uses
`daily/.mirror/agate/`, so the first Agate publication seeds its indexes
independently of the previous Bookworm publication. The daily report includes
architecture-independent Palette packages when reporting platform versions.
The digest consumer accepts both legacy `~preN` and Agate `~git` versions,
uses Debian version ordering, and tracks additions, removals, and version
changes for both ARM64 and architecture-independent Palette packages.

SDK image consumers must separately select Agate and support the upstream
`~git` version format; changing this mirror does not update their APT settings
or platform resolver.

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
source is transported over the corporate network using HTTP. The workflow
retains its existing explicitly trusted mirror policy: it disables upstream
Release signature verification while
still verifying that every referenced package exists and matches the size and
SHA256 recorded in the downloaded package indexes.

Clients access the Vulcan mirror through HTTPS and must explicitly mark this
pre-release source as trusted:

```text
deb [trusted=yes] https://debian.neat.sima.ai/daily agate non-free
```

This configuration must not be reused for a production or publicly trusted
package channel. HTTPS protects transport from Vulcan to the client, but the
package-index checks do not establish the upstream publisher's identity.

## Infrastructure prerequisite

The Vulcan `envs/debian-production` publisher policy must allow `daily/*` in
addition to `pre-release/*` before a publishing run. Its CloudFront configuration
should include the daily pool and distribution paths. Apply the companion
Vulcan daily-prefix change before enabling this workflow on `main`.

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
under digest-addressed `.mirror/agate/inventories/` and `.mirror/agate/changes/` S3 keys.
Each run also uploads a three-day, machine-readable GitHub Actions artifact
containing its complete change report, platform version, and publication
provenance. This is the input to the daily reporting workflow.

## Daily change digest

The `Daily pre-release mirror summary` workflow runs once per day on the agent
summary runner using these labels:

```text
self-hosted, Linux, X64, issue-triage
```

It uses read-only GitHub Actions permission to enumerate successful mirror-sync
runs from the previous 24 hours and download their short-lived result artifacts.
It does not assume a Vulcan or AWS role. Scheduled runs post a concise digest to
`neat-sync-mirror-notification`; manual runs default to preview-only and can
replay a bounded window with an explicit UTC `as_of` timestamp.
Manual replay windows are limited to 72 hours to match the repository's maximum
GitHub Actions artifact retention. An historical `as_of` is accepted only when
the entire requested window remains inside that retention period.
Digest windows use `(since, as_of]` boundaries. A publication is assigned by
the later of its mirror publication time and workflow completion time, so a
publication whose result artifact becomes visible just after a cutoff is
reported once in the next window rather than dropped.

Configure the following GitHub settings:

- organization secret `SLACK_BOT_TOKEN`;
- variable `SLACK_MIRROR_NOTIFICATION_CHANNEL_ID` containing the Slack channel
  ID (not its display name).

Package counts, Debian version ordering, grouping, and report rendering use
deterministic Python logic. The workflow does not pass upstream package metadata
to an agent CLI because that would expose persistent-runner read tools and
credentials to prompt injection. The normalized context and rendered digest are
retained as short-lived workflow artifacts for auditing. A future model-assisted
wording step must use a tool-free API boundary. Jenkins correlation is not part
of this initial implementation.

"Removed" means no longer referenced by the published APT indexes. Old package
objects remain in the S3 pool during the initial rollout for safe rollback.

Package objects and immutable `by-hash` indexes are uploaded before repository
metadata. On the first publication, all ordinary index paths are also seeded,
including the nested `binary-*/Release` files. The suite-level `Release` is
replaced last and contains `Acquire-By-Hash: yes`, making that single S3 object
the publication boundary. Later runs retain the previous ordinary index paths
so clients holding an older `Release` continue to see a consistent generation.
The suite `Release` object also records the source digest and immutable inventory
key as S3 metadata. The next run uses that metadata as its authoritative change
baseline, so a failure while updating the later convenience manifest cannot
cause the following publication to compare against stale package state.

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

The production CloudFront endpoint allows public HTTPS reads. The S3 bucket
remains private behind CloudFront; clients must use the HTTPS mirror URL.

## No-change behavior

The workflow compares the upstream `InRelease` SHA256 with:

```text
s3://sima-neat-debian-production/daily/.mirror/agate/publication.json
```

An unchanged repository exits successfully without downloading or publishing.
Use the `force` input only when the local mirror must be rebuilt or revalidated.

## Rollback

The production bucket is versioned. To roll back, identify the last known-good
version of `daily/dists/agate/Release` and restore that object last.
The digest-addressed indexes and package-pool objects are immutable and must not
be deleted. Invalidate `/daily/dists/*` after restoration, then verify the
restored index and all referenced package checksums before reopening client
access.

## Daily platform images

The same synchronization job also mirrors Modalix platform images from
`https://artifacts.eng.sima.ai/artifactory/soc-images/elxr/bsp/modalix/` to
`s3://sima-neat-artifacts-production/daily-platform-images/`. For example,
`3.0.0_daily_develop_B1168/` becomes an identically named build directory.
This step runs every 30 minutes even when the Debian repository is unchanged,
and can run after a Debian sync failure. It uses the same `apt-mirror` runner,
production environment, OIDC role, and manual `publish` switch.

The runner’s provisioned `~/.netrc` supplies the login and password for
`artifacts.eng.sima.ai`, with read access to list and download `soc-images`.
No Artifactory GitHub secret is required. The file must be readable by the runner
service account and have owner-only permissions. Both Storage API requests and
image downloads use these credentials over trusted HTTPS. The script
uses the Artifactory Storage API, requires SHA256 metadata, and refuses
redirects. Missing authentication, an empty source listing, checksum errors, or altered
previously published builds fail the step without
replacing the index or pruning old builds.

Only directory names matching `3.0.0_daily_<channel>_B<number>` are eligible.
Completed builds are ordered by numeric build number, newest first (with directory
name as a deterministic tie breaker). The latest 7 completed builds are kept
across channels; pending uploads do not evict them.
Successfully mirrored builds remain eligible if Artifactory removes them.
Each directory must contain a `.wic`, `.img`, or `.iso` image; WIC/IMG gzip,
xz, and zstd variants are supported. All files in an eligible build directory,
including checksums and supporting assets, are mirrored preserving their paths.
Directories without a supported image or complete checksum metadata remain pending
and require a completed upload or an explicit format update before publication.

A newly discovered build is eligible immediately when every file is at least
30 minutes old according to Artifactory. The mirror uses the newest `created`,
`lastModified`, and (when present) `lastUpdated` timestamp across every image and
supporting file in the recursive inventory, rather than the build directory's
creation time. Recent files wait until that age threshold; future timestamps
also remain pending. This allows old daily builds to sync on the first run.

If a file lacks valid, timezone-aware creation/modification metadata, the mirror
falls back to observing an identical inventory (paths, byte sizes, SHA256 values,
and available file times) at least 30 minutes apart. Observations persist under
`$DEBIAN_MIRROR_WORK_ROOT/daily-image-readiness/`. Changes reset that timer; known
recent/future timestamps still block readiness even when another file's metadata
is unavailable. Preview runs may record observations but never publish.

All selected upstream inventories are checked again after transfer and before
any completion manifests or the index are written. A changed listing defers
publication, leaving the previous index intact. Newer pending build objects are
excluded from old-build retention. Source timestamps are used only for readiness
and verification; the published manifest/index schema remains unchanged.

File age is a quiet-period heuristic, not an upstream completion marker: an upload
that pauses more than 30 minutes can appear complete. If Artifactory gains an
authoritative completion signal, use it in place of this heuristic. Published
builds remain immutable, so later changes fail closed instead of silently
changing consumer-visible contents.

Downloads use disk space for one artifact at a time beneath
`DEBIAN_MIRROR_WORK_ROOT`, with a 1 GiB reserve. Each download must match the
source size and SHA256 before upload. Verified S3 objects are reused on retries;
completed builds have a `manifest.json`. Published build contents are immutable.
The image client uses refreshable GitHub OIDC credentials for the entire phase.
Before its one-hour STS session expires, Botocore requests a fresh GitHub identity
token and assumes the same publisher role again, including between multipart
upload requests. Static credentials exported by the workflow are not used by the
image client. The existing role duration and IAM permissions remain unchanged.
OIDC renewal requires the job's existing `id-token: write` permission. Outside
GitHub Actions, the script uses the normal Boto3 credential provider chain.
If renewal fails, the job reports an error; completed S3 files remain reusable
on the next run. The job's 720-minute timeout still bounds the whole workflow.

Without `publish`, the image step previews source metadata and selected builds;
it does not download image bodies, write S3, or delete objects. With `publish`,
it verifies/downloads/uploads files, publishes the index only after all selected
builds succeed, then permanently deletes **all object versions and delete markers**
for older matching build directories. It also removes abandoned partial uploads
that exist as completed S3 objects under older build directories. Other release
lines and bucket prefixes are untouched. Multipart uploads are aborted by the SDK
on ordinary transfer failures. Count retention is owned by this workflow, not
Vulcan's generic branch artifact cleanup.

A failed run can temporarily leave more than 7 directories in S3. The previous
index remains usable until the new index is published; a failure during pruning
leaves the new index usable and the next successful run retries cleanup.
Consumers should refresh the index when an old selection is no longer available.

### CLI index contract (schema version 1)

Read `s3://sima-neat-artifacts-production/daily-platform-images/index.json`.
The object is published with JSON content type and `no-cache, max-age=0`.
The index is unchanged on a no-op run and contains:

- `schema_version`: `1`.
- `generated_at`: UTC ISO 8601 publication timestamp.
- `platform`: `modalix`; `version_prefix`: `3.0.0_daily_`.
- `bucket`, `prefix`, and `retention_count` (`7`).
- `builds`: newest-first array, with at most 7 entries.
- Each build: `name`, numeric `build_number`, `source_url`, and `files`.
- Each file: relative `path`, S3 `key`, `s3_uri`, byte `size`, and `sha256`.

The same per-build entry is stored at `<build>/manifest.json`. A future sima-cli
selector can display build names and download the selected image via its S3 URI,
then verify its SHA256. No sima-cli behavior is changed by this workflow update.

Run the isolated S3/versioning regression tests with:

```bash
python -m pip install boto3 'moto[s3]' pytest PyYAML
python -m pytest -q tests/sdk/test-daily-platform-images.py
```

## New-version Slack notifications

Each publishing mirror run sends a compact event to the channel configured by
`SLACK_VULCAN_EVENT_CHANNEL_ID`, using the organization `SLACK_BOT_TOKEN` secret.
Make the secret available to the SDK repository and invite the bot to the event
channel. GitHub resolves the channel ID from the organization/repository or
production environment variable. This event is separate from the existing daily
APT package digest and does not use its channel setting.

The message summarizes actual APT package changes between the previous and current
validated inventories, device image build names, and a link to the GitHub Actions
run. It uses a native Slack Block Kit table with Package, Architecture, Removed
versions, and Added versions columns. Full version strings wrap within their cells.
The table shows up to 99 changes (plus its header), with an overflow count and a
link to the full workflow report for larger runs. It prioritizes entries
with added versions over removal-only entries and sorting each group alphabetically; unchanged retained
versions are omitted. A compact text fallback includes up to five changes for
notifications and accessibility. The workflow table lists removed and added versions instead
of repeating both full histories. Without a previous APT inventory, no package
change notification is sent because no reliable comparison is available. It is sent after publication, so
preview-only runs do not announce images or packages as available. Device image
notifications include only builds with artifacts successfully copied from
Artifactory to Vulcan during that run, after index publication. This also includes
builds copied by an earlier attempt that failed before publishing the index;
they are announced when a retry first publishes them. Existing builds
remain quiet even when notification history is missing or a different branch
runs the workflow. Package changes retain their originating run for retry and
deduplication. Device image versions are announced once per category.

Each daily device image version links to its Jenkins console, using the numeric
`B` suffix (for example, `3.0.0_daily_develop_B1295` links to
`https://jenkins.eng.sima.ai/job/soc-jobs/job/elxr-builder/1295/console`).
The GitHub workflow link is also retained.

Example:

```text
Mirror changes published
APT package changes: 16
Package | Architecture | Removed versions | Added versions
example | arm64        | 1.0              | 2.0
…remaining package rows (up to 99 changes)
Device images: 3.0.0_daily_develop_B1168
GitHub workflow run
```

Notification state and pending events live at
`$DEBIAN_MIRROR_WORK_ROOT/version-notifications/state.json` on the same persistent
runner volume as the mirror cache. Preserve that file across runs; replacing the
runner or clearing the volume resets deduplication. The existing workflow
concurrency group serializes access. A single run normally sends one combined
message; retries spanning multiple detecting runs send one message per original
run so links retain their provenance.

The final notification step runs even if one mirror phase fails. Only published
versions are eligible, including images whose index was published before a
retention failure. Slack errors fail the notification step but leave publication
intact and retain pending events for the next publishing run, including a no-change
run. Events are persisted before sending and acknowledged locally after Slack
success. An ambiguous network failure or a crash after Slack accepts a message
can cause a duplicate on retry; delivery is at least once rather than exactly once.

Regression coverage:

```bash
python -m pytest -q tests/sdk/test-daily-platform-images.py tests/sdk/test-mirror-version-notifications.py
```

## SWUpdate verification certificate

Every scheduled run also fetches the public build-signing certificate from
`http://sw-web.eng.sima.ai/deb/swupdate-signing-cert.pem` and mirrors it at
`https://debian.neat.sima.ai/daily/swupdate-signing-cert.pem` (S3 key
`daily/swupdate-signing-cert.pem`). This uses the existing publisher's `daily/*`
permissions and the distribution's caching-disabled default behavior.

The certificate step runs independently of the APT InRelease change check, so a
signing-key rotation is synchronized even when no packages changed. It validates
that the download contains exactly one parseable PEM certificate, compares its
bytes with S3, and replaces the object only when changed. Downloads or validation
failures preserve the published certificate and fail the step. The existing APT
and image phases can still run. Manual runs without `publish` validate the source
certificate without reading or writing S3. The job summary records the subject,
validity dates, SHA256 certificate fingerprint, and file digest.

On a board with `/data` mounted, fetch the mirrored certificate with:

```bash
curl -fsSL -o /data/swupdate-cert.pem \
  https://debian.neat.sima.ai/daily/swupdate-signing-cert.pem
openssl x509 -in /data/swupdate-cert.pem -noout -subject -fingerprint -sha256
```

Use `/data/swupdate-cert.pem` with SWUpdate's `-k` option. Gate device updates on
time synchronization: without an RTC, a certificate can appear not yet valid
until the device clock is stepped. The mirror validates certificate format but
does not enforce its validity dates, so it can distribute a future-dated rotated
certificate. This is the SiMa build-signing certificate, obtained over the same
corporate HTTP trust boundary as the internal package mirror. A production fleet
must distribute its own trusted verification certificate. No private key is
copied, and this workflow does not install the certificate onto boards.
