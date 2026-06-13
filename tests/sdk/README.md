# SDK Smoke Tests

This directory contains CI smoke tests that validate a published Neat SDK
container after `sima-cli sdk setup -y -n` starts it.

## Layout

- `run-smoke-tests.sh` runs on the GitHub Actions runner. It finds the running
  SDK container for `IMAGE_REF`, copies this directory into the container, and
  invokes `run-in-container.sh`. It also runs host-side tests that need to
  validate Docker-published ports.
- `run-in-container.sh` runs inside the SDK container and acts as the index for
  individual SDK smoke tests.
- `neat-status/` validates the `neat --json` assembly/status contract.
- `insight-video-routing/` downloads a small H.264 video, streams it from the
  runner into the SDK container's published Insight video UDP port with
  `ffmpeg`, then verifies vf ingest through the Insight API.
- `hello-neat/` contains the minimal Hello Neat example from the public docs.

Additional SDK smoke suites should be added as sibling directories and invoked
from `run-in-container.sh` when they run inside the container, or from
`run-smoke-tests.sh` when they need host/container boundary coverage.
