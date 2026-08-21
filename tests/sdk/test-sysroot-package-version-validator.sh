#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VALIDATOR="${ROOT_DIR}/scripts/validate-sysroot-package-versions.sh"
WORK_DIR="$(mktemp -d)"
trap 'rm -rf "${WORK_DIR}"' EXIT

mkdir -p "${WORK_DIR}/bin" "${WORK_DIR}/debs"
touch "${WORK_DIR}/debs/bzip2-amd64.deb" "${WORK_DIR}/debs/bzip2-arm64.deb"

cat > "${WORK_DIR}/bin/dpkg-deb" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

deb="$2"
field="$3"
filename="$(basename "${deb}")"

case "${field}" in
  Package) echo bzip2 ;;
  Architecture)
    case "${filename}" in
      *-amd64.deb) echo amd64 ;;
      *-arm64.deb) echo arm64 ;;
      *) exit 1 ;;
    esac
    ;;
  Version)
    case "${filename}" in
      *-amd64.deb) echo 1.0.8-5.1build0.1 ;;
      *-arm64.deb) echo 1.0.8-5+b1 ;;
      *) exit 1 ;;
    esac
    ;;
  *) exit 1 ;;
esac
EOF
chmod +x "${WORK_DIR}/bin/dpkg-deb"

cat > "${WORK_DIR}/debs/expected-package-versions.tsv" <<'EOF'
bzip2	amd64	1.0.8-5.1build0.1
bzip2	arm64	1.0.8-5+b1
EOF

PATH="${WORK_DIR}/bin:${PATH}" "${VALIDATOR}" 2.1.3~pre4617 "${WORK_DIR}/debs"

cat > "${WORK_DIR}/debs/expected-package-versions.tsv" <<'EOF'
bzip2	amd64	1.0.8-5.1build0.1
bzip2	arm64	incorrect-version
EOF

if PATH="${WORK_DIR}/bin:${PATH}" \
  "${VALIDATOR}" 2.1.3~pre4617 "${WORK_DIR}/debs" 2>/dev/null; then
  echo "Validator accepted an incorrect architecture-specific package version." >&2
  exit 1
fi

rm "${WORK_DIR}/debs/bzip2-arm64.deb"
cat > "${WORK_DIR}/debs/expected-package-versions.tsv" <<'EOF'
bzip2	1.0.8-5.1build0.1
EOF

PATH="${WORK_DIR}/bin:${PATH}" "${VALIDATOR}" 2.1.3~pre4617 "${WORK_DIR}/debs"

echo "Sysroot package version validator tests passed."
