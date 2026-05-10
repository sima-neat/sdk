# SDK Smoke Tests

This directory contains CI smoke tests that validate a published Neat SDK
container after `sima-cli sdk setup -y -n` starts it.

## Layout

- `run-smoke-tests.sh` runs on the GitHub Actions runner. It finds the running
  SDK container for `IMAGE_REF`, copies this directory into the container, and
  invokes `run-in-container.sh`.
- `run-in-container.sh` runs inside the SDK container and acts as the index for
  individual SDK smoke tests.
- `neat-status/` validates the `neat --json` assembly/status contract.
- `hello-neat/` contains the minimal Hello Neat example from the public docs.

Additional SDK smoke suites should be added as sibling directories and invoked
from `run-in-container.sh`.
