#!/bin/bash
# Full custom image qualification on a native builder; never contacts a board.
set -euo pipefail
root="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
: "${PIB_IMAGE:?Set PIB_IMAGE to the image under test}"
output="${PIB_TEST_OUTPUT:-$root/test-output}"
mkdir -p "$output"
output="$(CDPATH='' cd -- "$output" && pwd)"
pib="$root/host/pib"
cd "$output"
"$pib" doctor
"$pib" init workspace --example custom-image
cd workspace
# Prove the installed example spec is the checked-in input, not a generated recipe.
cmp "$root/examples/custom-image/image.yaml" image.yaml
"$pib" keys init --cn 'PIB CI Test Only'
mkdir -m 700 ../secure
mv keys/ca.key ../secure/
"$pib" shell -c 'dpkg-deb --root-owner-group --build package-root custom-debs/pib-example-app_1.0.0_all.deb'
"$pib" sign-debs
"$pib" verify-debs
"$pib" build --sign --supplier 'PIB CI Test Only'
"$pib" verify
# Inspect the signed payload without mounting it or using devices.
docker run --rm --network none --entrypoint python3 \
    -v "$PWD:/workspace:ro" -v "$root/tests:/tests:ro" \
    -v "$root/examples/custom-image:/example:ro" \
    "$PIB_IMAGE" /tests/inspect-payload.py
printf 'PIB custom-image qualification passed; artifacts: %s/out\n' "$PWD"
