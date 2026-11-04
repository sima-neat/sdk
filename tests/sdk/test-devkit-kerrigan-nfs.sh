#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DEVKIT_SH_FUNCTIONS_ONLY=1 source "${ROOT_DIR}/scripts/devkit.sh"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
export TEST_NFS_STATE="$tmpdir/state" TEST_NFS_CALLS="$tmpdir/calls"
export TEST_HELPER_PATH=/workspace TEST_PROBE=0 TEST_MOUNT_FAIL=0
# Execute the actual remote shell program, replacing only SSH and privileged IO.
timeout() { shift 2; "$@"; }
ssh() {
  local command="${!#}"
  if [[ "$command" == *'helper=/usr/local/sbin/kerrigan-sdk-nfs;'* ]]; then
    return "$TEST_PROBE"
  fi
  if [[ "$command" == 'bash -s -- '* ]]; then
    bash -c "$command"
  else
    # The unmanaged flow sends bash, -s and its arguments separately.
    cat > /dev/null
    touch "${TEST_NFS_STATE}.unmanaged"
  fi
}
sudo() {
  printf '%s\n' "$*" >> "$TEST_NFS_CALLS"
  [[ "$1" == -n && "$2" == /usr/local/sbin/kerrigan-sdk-nfs ]] || return 99
  case "$3" in
    mount)
      [[ "$TEST_MOUNT_FAIL" == 0 ]] || return 1
      [[ "$4" == --source && "$6" == --version && "$7" =~ ^[34]$ ]] || return 98
      printf '%s' "$5" > "$TEST_NFS_STATE" ;;
    status)
      python3 - <<'PY'
import json,os,pathlib
p=pathlib.Path(os.environ['TEST_NFS_STATE']); target=os.environ['TEST_HELPER_PATH']
print(json.dumps({'mount_point':target,'managed':p.exists(), 'mount':
 {'source':p.read_text(),'fstype':'nfs','target':target} if p.exists() else None}))
PY
      ;;
    *) return 97 ;;
  esac
}
git() { return 0; }
export -f ssh sudo git
check_remote_kerrigan_nfs sima example 22
TEST_PROBE=44; rc=0; check_remote_kerrigan_nfs sima example 22 || rc=$?
[[ $rc == 1 ]]
for TEST_PROBE in 45 255 124; do
  rc=0; check_remote_kerrigan_nfs sima example 22 || rc=$?
  [[ $rc == 2 ]]
done
TEST_PROBE=0
mount_kerrigan_sdk_workspace sima example 22 10.252.1.1 /export 3
[[ "$(cat "$TEST_NFS_STATE")" == 10.252.1.1:/export ]]
rm "$TEST_NFS_STATE"
TEST_HELPER_PATH=/mnt/kerrigan-sdk
if mount_kerrigan_sdk_workspace sima example 22 10.252.1.1 /export 4; then
  echo 'old helper path was accepted' >&2; exit 1
fi
[[ ! -f "$TEST_NFS_STATE" ]]
TEST_HELPER_PATH=/workspace; TEST_MOUNT_FAIL=1
if mount_kerrigan_sdk_workspace sima example 22 10.252.1.1 /export 4; then
  echo 'helper rejection was ignored' >&2; exit 1
fi
[[ ! -f "$TEST_NFS_STATE" ]]
# Export strings must remain a single argument through SSH's shell boundary.
TEST_MOUNT_FAIL=0
mount_kerrigan_sdk_workspace sima example 22 10.252.1.1 '/export;touch INJECTION' 4
[[ "$(cat "$TEST_NFS_STATE")" == '10.252.1.1:/export;touch INJECTION' ]]
[[ ! -f INJECTION ]]
# Exercise the production pairing decision block too: only a genuinely absent
# helper may reach the existing general-sudo / Neat / unmanaged-NFS path.
python3 - "$ROOT_DIR/scripts/devkit.sh" "$tmpdir/pairing.sh" <<'PYBLOCK'
from pathlib import Path
import sys
source=Path(sys.argv[1]).read_text()
start=source.index('_KERRIGAN_NFS=0\n')
end=source.index('_SYNC_METHOD="none"',start)
Path(sys.argv[2]).write_text(source[start:end])
PYBLOCK
check_remote_passwordless_sudo() { touch "${TEST_NFS_STATE}.sudo"; return 0; }
sync_neat_framework_to_devkit() { touch "${TEST_NFS_STATE}.neat"; return 0; }
_DEVKIT_USER=sima _DEVKIT_IP=example _DEVKIT_PORT=22
_HOST_IP=10.252.1.1 _HOST_EXPORT_PATH=/export _HOST_PLATFORM=darwin
_NFS_OPTS=vers=3 _c_error='' _c_reset='' _DEFAULT_MOUNT_PATH=/custom
devkit_sync_noninteractive() { return 0; }
for TEST_PROBE in 0 44 45 255 124; do
  rm -f "$TEST_NFS_STATE" "${TEST_NFS_STATE}.sudo" "${TEST_NFS_STATE}.neat" "${TEST_NFS_STATE}.unmanaged"
  TEST_HELPER_PATH=/workspace TEST_MOUNT_FAIL=0 _MOUNT_POINT=/custom
  rc=0
  (source "$tmpdir/pairing.sh"; exit $?) > "$tmpdir/pairing.log" 2>&1 || rc=$?
  case "$TEST_PROBE" in
    0)
      [[ $rc == 0 && -f "$TEST_NFS_STATE" ]]
      [[ ! -e "${TEST_NFS_STATE}.sudo" && ! -e "${TEST_NFS_STATE}.neat" && ! -e "${TEST_NFS_STATE}.unmanaged" ]]
      ;;
    44)
      [[ $rc == 0 && ! -e "$TEST_NFS_STATE" ]]
      [[ -e "${TEST_NFS_STATE}.sudo" && -e "${TEST_NFS_STATE}.neat" && -e "${TEST_NFS_STATE}.unmanaged" ]]
      ;;
    *)
      [[ $rc != 0 && ! -e "$TEST_NFS_STATE" ]]
      [[ ! -e "${TEST_NFS_STATE}.sudo" && ! -e "${TEST_NFS_STATE}.neat" && ! -e "${TEST_NFS_STATE}.unmanaged" ]]
      ;;
  esac
done
TEST_PROBE=0 TEST_MOUNT_FAIL=1
rc=0
(source "$tmpdir/pairing.sh"; exit $?) > "$tmpdir/pairing.log" 2>&1 || rc=$?
[[ $rc != 0 ]]
[[ ! -e "${TEST_NFS_STATE}.sudo" && ! -e "${TEST_NFS_STATE}.neat" && ! -e "${TEST_NFS_STATE}.unmanaged" ]]
echo 'Kerrigan managed and unmanaged pairing tests passed'
