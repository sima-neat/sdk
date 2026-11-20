#!/bin/bash
# Run inside the built container. Compose SDK code and fetched upstream inputs
# in a temporary tree so regression tests neither refetch nor modify the checkout.
set -euo pipefail
source_root="$(CDPATH='' cd -- "$(dirname "$0")/.." && pwd)"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT
tar -C "$source_root" --exclude='./test-output' --exclude='./workspace' \
    --exclude='./secure' --exclude='__pycache__' -cf - . | tar -C "$scratch" -xf -
for name in configs files scripts; do
    mkdir -p "$scratch/$name"
    cp -a "/usr/share/pib/$name/." "$scratch/$name/"
done
cd "$scratch"
python3 pib/test_cli.py
# This checkout's pib package, not the image's installed one, for every test module.
PYTHONPATH="$scratch/pib${PYTHONPATH:+:$PYTHONPATH}" python3 -m unittest discover -s tests -p 'test_*.py'
