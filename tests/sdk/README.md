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
from `run-in-container.sh`.
