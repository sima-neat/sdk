# Pre-release Debian mirror

The `Sync pre-release Debian mirror` workflow pulls the corporate repository at
`sw-web.eng.sima.ai/deb/pre-release`, validates it, and can publish it to the
production mirror at `https://debian.neat.sima.ai/pre-release`.

This is an operational mirror-transfer workflow only. It does not build or
modify the SDK container, SDK packages, or SDK installation behavior; the SDK
repository is only the home for the workflow and its synchronization utility.

The workflow runs daily at 09:27 UTC and can also be started manually. Scheduled
runs publish after validation; manual runs expose an explicit `publish` switch
so the first production validation can download and verify without changing S3.

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
The synchronization therefore ignores the upstream Release signature while
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

After rollout, the daily scheduled run performs the same validation and enables
publication automatically. It exits successfully without uploading when the
upstream `InRelease` digest has not changed.

Each changed run compares the validated package indexes with the inventory from
the last successful publication. The Actions summary reports package files
added to the indexes, package files removed from the indexes, and correlated
version changes by package and architecture. It shows up to 50 entries in each
category and records the complete machine-readable inventory and change report
under digest-addressed `.mirror/inventories/` and `.mirror/changes/` S3 keys.

"Removed" means no longer referenced by the published APT indexes. Old package
objects remain in the S3 pool during the initial rollout for safe rollback.

Package objects and immutable `by-hash` indexes are uploaded before repository
metadata. On the first publication, all ordinary index paths are also seeded,
including the nested `binary-*/Release` files. The suite-level `Release` is
replaced last and contains `Acquire-By-Hash: yes`, making that single S3 object
the publication boundary. Later runs retain the previous ordinary index paths
so clients holding an older `Release` continue to see a consistent generation.

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
