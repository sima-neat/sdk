# SDK Smoke Tests

This directory contains CI smoke tests that validate a published Neat SDK
container after `sima-cli sdk setup -y -n` starts it.

## Layout

- `run-smoke-tests.sh` runs on the GitHub Actions runner. It finds the running
  SDK container for `IMAGE_REF`, copies this directory into the container, and
  invokes `run-in-container.sh`. It also runs host-side tests that need to
  validate Docker-published ports.
- `run-in-container.sh` runs inside the SDK container and acts as the index for
  individual SDK smoke tests. For a `platform-cross` image it validates release
  metadata, absence of bundled Core resources, the Modalix cross toolchain, and
  the sysroot overlay without running Core-dependent examples.
- `test-resolve-platform-config.sh`, `test-write-sdk-release.sh`, and
  `test-devkit-platform-profile.sh` cover pre-release selection, image
  provenance, protected release refs, and intentional Core-sync skipping.
- `test-install-neat-resources.sh` covers bundled Core, unpublished and
  incompatible Core skips, explicit platform-only builds, and unexpected fatal
  installer failures.
- `test-sysroot-update.sh` covers interactive safety, exact and latest
  pre-release resolution, Platform Base enforcement, dry-run validation,
  overlay provenance, idempotence, and the shell prompt overlay marker.
- `test-sysroot-unprivileged-dry-run.sh` verifies that an ordinary user can
  resolve overlay package aliases without writing under the system APT paths.
- `test-sysroot-progress.py` verifies package download/cache and extraction
  progress summaries used by `sysroot update`.
- `test-retarget-release-line-metadata.py` verifies that tagged SDK releases
  retarget both canonical and offline-bundle release-line image resources.
- `neat-status/` validates the `neat --json` assembly/status contract.
- `insight-video-routing/` downloads a small H.264 video, streams it from the
  runner into the SDK container's published Insight video UDP port with
  `ffmpeg`, then verifies vf ingest through the Insight API.
- `hello-neat/` contains the minimal Hello Neat example from the public docs.
- `representative-builds/internals/` builds a tiny CMake target that consumes
  `NeatInternals` and its transitive sysroot dependencies.
- `representative-builds/core-api/` builds a tiny public Core API target that
  consumes the `core/develop` public API shape through `SimaNeat`, tensor
  contracts, graph headers, model headers, and policy defaults without building
  the core repository.
- `representative-builds/llima-python-extension/` builds a tiny Python C API
  extension using a host-runnable Python interpreter plus target sysroot Python
  headers/library, matching the llima cross-build shape without building llima.
- `run-in-container.sh` also exercises a temporary sysroot overlay install with
  packages representative of the llima dependency overlay.

Additional SDK smoke suites should be added as sibling directories and invoked
from `run-in-container.sh` when they run inside the container, or from
`run-smoke-tests.sh` when they need host/container boundary coverage.
