# Develop and master platform synchronization

## Goal

Synchronize Modalix 3.0 develop (`3.0.0_daily_develop_B*`) and master
(`3.0.0_pre-release_master_B*`) firmware and their APT repositories every
scheduled cycle. Keep one shared pool of 21 completed image builds, ranked by
numeric build number. Either branch can occupy all slots. APT retention remains
upstream-index-driven, not coupled to the image limit.

## Implementation plan

1. Share build parsing between image discovery, readiness, notifications and
   source reports. Preserve existing image URLs and schema-v1 index compatibility.
   Include master in version pruning, retaining publication-before-deletion and
   stable-inventory/checksum safeguards.
2. Parameterize APT synchronization by `daily` or `pre-release`. Keep daily's
   existing cache/state paths. Give master a separate workspace and Agate
   publication state; publish `/pre-release/dists/agate` without changing retained
   Bookworm indexes. Run both channels even if one fails, and preserve per-channel
   reports and notification state.
3. Route firmware readiness to the matching repository and package format:
   develop uses `3.0.0~gitTIMESTAMP.COMMIT-BUILD`; master uses `3.0.0~preBUILD`.
   Report the limited scope of the anchor/exact-dependency check, especially for
   master's unpinned dependencies. Do not claim firmware/sysroot equivalence.
4. Extend SDK resolution and Agate sysroot handling to exact master versions,
   retaining develop defaults and keeping 2.x Bookworm behavior intact.
5. Test mixed retention, master publication/retries, repository isolation, version
   mapping, reporting and SDK selection. Dry-run against real metadata where
   available; do not publish production artifacts as part of implementation.

## Rollout

Review SDK changes and verify the production publisher policy permits the
pre-release pool, Agate distribution and state keys. Merge/deploy through normal
release workflow. First run preview-only, then publish and verify both image and
APT indexes plus a master SDK build. Full SDK build and device validation are
separate from unit/mock synchronization tests.

## Review notes

Tracking issue: https://github.com/sima-neat/sdk/issues/256.

B2254 was checked through the authenticated Artifactory storage API: all 43
artifacts have checksums and pass upload-age readiness. It has no
`manifestChanges.txt`; scheduled source-report generation must skip that build
without blocking develop reports. The production image publisher needs an
additional deletion grant for the master prefix:
https://github.com/sima-neat/vulcan/pull/271.

The implementation includes exact master SDK selection and whole-directory
sysroot transactions. Full master SDK image build and hardware validation remain
rollout checks; local tests do not establish those results.
