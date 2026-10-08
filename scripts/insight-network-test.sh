#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: insight-network-test [channel]

Check that the paired DevKit can reach Insight over TCP, then send a UDP
metadata probe and confirm that Insight received it. The default channel is 0.
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

channel="${1:-0}"
if [[ ! "${channel}" =~ ^[0-9]+$ ]] || (( channel < 0 || channel > 79 )); then
  echo "Channel must be an integer from 0 through 79." >&2
  exit 2
fi

devkit_ip="${DEVKIT_SYNC_DEVKIT_IP:-}"
devkit_user="${DEVKIT_SYNC_DEVKIT_USER:-sima}"
devkit_ssh_port="${DEVKIT_SYNC_DEVKIT_PORT:-22}"
sdk_host_ip="${CONTAINER_HOST_IP:-}"
insight_url="${INSIGHT_BASE_URL:-https://127.0.0.1:${NEAT_INSIGHT_PORT:-9900}}"
metadata_port=$((9100 + channel))
insight_host_port="${INSIGHT_HOST_PORT:-9900}"
port_map="${INSIGHT_PORT_MAP_FILE:-${HOME}/.insight-config/neat-port-map.json}"

for command_name in curl python3 ssh; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command not found: ${command_name}" >&2
    exit 2
  fi
done

if [[ -r "${port_map}" ]]; then
  mapfile -t mapped_ports < <(python3 - "${port_map}" "${channel}" <<'PY'
import json
import sys

path, channel = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as stream:
    port_map = json.load(stream)

print(port_map.get("mainUI", {}).get("host", 9900))
print(port_map.get("metadataUDP", {}).get("hostStart", 9100) + channel)
PY
  )
  insight_host_port="${mapped_ports[0]}"
  metadata_port="${mapped_ports[1]}"
fi

if [[ -z "${devkit_ip}" || -z "${sdk_host_ip}" ]]; then
  echo "No paired DevKit network configuration was found." >&2
  echo "Run SDK setup with a DevKit, open a new SDK shell, and try again." >&2
  exit 2
fi

work_dir="$(mktemp -d)"
trap 'rm -rf "${work_dir}"' EXIT
stats_file="${work_dir}/ingest-stats.json"

fetch_stats() {
  curl -fsSk --connect-timeout 3 --max-time 5 \
    "${insight_url}/api/ingest/stats?all=1&verbose=1" \
    -o "${stats_file}"
}

metadata_messages_received() {
  python3 - "${stats_file}" "${channel}" <<'PY'
import json
import sys

path, requested_channel = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as stream:
    payload = json.load(stream)

for item in payload.get("channels", []):
    if item.get("channel") == requested_channel:
        print(item.get("metadata", {}).get("messages_received", 0))
        break
else:
    raise SystemExit(f"Insight did not report channel {requested_channel}")
PY
}

if ! curl -fsSk --connect-timeout 3 --max-time 5 \
  "${insight_url}/api/health" >/dev/null; then
  echo "Insight is not reachable at ${insight_url}." >&2
  exit 1
fi

if ! fetch_stats; then
  echo "Could not read Insight ingest statistics." >&2
  exit 1
fi
before="$(metadata_messages_received)"

echo "Checking reverse DevKit -> Insight network path..."

if ! ssh -T -p "${devkit_ssh_port}" \
  -o BatchMode=yes -o ConnectTimeout=8 \
  "${devkit_user}@${devkit_ip}" \
  python3 - "${sdk_host_ip}" "${insight_host_port}" "${metadata_port}" <<'PY'
import json
import socket
import ssl
import sys
import urllib.request

host, tcp_port, udp_port = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
health_url = f"https://{host}:{tcp_port}/api/health"
context = ssl._create_unverified_context()

try:
    with urllib.request.urlopen(health_url, context=context, timeout=5) as response:
        health = json.load(response)
    if health.get("status") != "ok":
        raise RuntimeError(f"unexpected health response: {health!r}")
except Exception as error:
    print(f"TCP FAIL: DevKit could not reach Insight at {health_url}: {error}", file=sys.stderr)
    raise SystemExit(1)

print(f"TCP PASS: DevKit reached Insight at {health_url}.", flush=True)

payload = json.dumps(
    {"type": "sima-udp-connectivity-test", "source": "sdk"},
    separators=(",", ":"),
).encode("utf-8")

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
try:
    sock.sendto(payload, (host, udp_port))
finally:
    sock.close()
PY
then
  echo "Could not complete the reverse network test on ${devkit_user}@${devkit_ip}." >&2
  echo "Check SSH access and the Insight address shown above, then try again." >&2
  exit 1
fi

deadline=$((SECONDS + 5))
while (( SECONDS <= deadline )); do
  if fetch_stats; then
    after="$(metadata_messages_received)"
    if (( after > before )); then
      echo "UDP PASS: Insight received the DevKit probe on port ${metadata_port} (${before} -> ${after} messages)."
      exit 0
    fi
  fi
  sleep 1
done

echo "UDP FAIL: Insight did not observe the DevKit probe on port ${metadata_port}." >&2
echo "The DevKit can use SSH, but its UDP path to ${sdk_host_ip}:${metadata_port} is not working." >&2
exit 1
