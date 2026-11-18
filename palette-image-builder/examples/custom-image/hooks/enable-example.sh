#!/bin/sh
set -eu
systemctl --root="$1" enable pib-example.service
printf 'PIB example post-install hook\n' > "$1/etc/pib-example-build"
