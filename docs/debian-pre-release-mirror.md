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

The repository pins the public key currently advertised by the private mirror.
If the mirror owner rotates its signing key, place the approved public key on
the runner and set both `DEBIAN_MIRROR_SIGNING_KEY_PATH` and
`DEBIAN_MIRROR_SIGNING_KEY_FINGERPRINT` in the protected `production`
environment. The workflow fails closed if the configured key fingerprint or
the upstream signature does not match.

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

Package objects are uploaded before repository metadata. `Release`,
`Release.gpg`, and `InRelease` are promoted last, with `InRelease` last of all.
Old package-pool objects are not deleted by the initial implementation.

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
versions under `pre-release/dists/`, restore all referenced metadata, and restore
`InRelease` last. Do not delete package-pool objects. Invalidate
`/pre-release/dists/*` after restoration, then verify the restored signature and
all referenced package checksums before reopening client access.
