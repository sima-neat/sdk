#!/usr/bin/env bash

set -euo pipefail

usage() {
  cat <<'EOF'
Usage: insight-network-test [channel]

Check that the paired DevKit can reach Insight over TCP, then send a UDP
metadata probe and confirm that Insight received it. When no channel is given,
the test selects an inactive metadata channel to isolate the probe from normal
traffic.
EOF
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
esac

requested_channel="${1:-}"
if [[ -n "${requested_channel}" ]] && \
   { [[ ! "${requested_channel}" =~ ^[0-9]+$ ]] || \
     (( requested_channel < 0 || requested_channel > 79 )); }; then
  echo "Channel must be an integer from 0 through 79." >&2
  exit 2
fi

devkit_ip="${DEVKIT_SYNC_DEVKIT_IP:-}"
devkit_user="${DEVKIT_SYNC_DEVKIT_USER:-sima}"
devkit_ssh_port="${DEVKIT_SYNC_DEVKIT_PORT:-22}"
sdk_host_ip="${CONTAINER_HOST_IP:-}"
insight_url="${INSIGHT_BASE_URL:-https://127.0.0.1:${NEAT_INSIGHT_PORT:-9900}}"
metadata_port_start=9100
metadata_channel_count=80
insight_host_port="${INSIGHT_HOST_PORT:-9900}"
port_map="${INSIGHT_PORT_MAP_FILE:-${HOME}/.insight-config/neat-port-map.json}"

for command_name in curl python3 ssh; do
  if ! command -v "${command_name}" >/dev/null 2>&1; then
    echo "Required command not found: ${command_name}" >&2
    exit 2
  fi
done

if [[ -r "${port_map}" ]]; then
  mapfile -t mapped_ports < <(python3 - "${port_map}" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as stream:
    port_map = json.load(stream)

print(port_map.get("mainUI", {}).get("host", 9900))
print(port_map.get("metadataUDP", {}).get("hostStart", 9100))
print(port_map.get("metadataUDP", {}).get("hostEnd", 9179))
PY
  )
  insight_host_port="${mapped_ports[0]}"
  metadata_port_start="${mapped_ports[1]}"
  metadata_channel_count=$((mapped_ports[2] - mapped_ports[1] + 1))
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

select_probe_channel() {
  python3 - "${stats_file}" "${requested_channel}" "${metadata_channel_count}" <<'PY'
import json
import sys

path, requested, channel_count = sys.argv[1], sys.argv[2], int(sys.argv[3])
with open(path, encoding="utf-8") as stream:
    payload = json.load(stream)

channels = {item.get("channel"): item for item in payload.get("channels", [])}
if requested:
    channel = int(requested)
    if channel >= channel_count:
        raise SystemExit(
            f"Channel {channel} is not published by this SDK container; available channels are 0 through {channel_count - 1}"
        )
    item = channels.get(channel)
    if item is None:
        raise SystemExit(f"Insight did not report channel {channel}")
    if item.get("metadata", {}).get("active", False):
        raise SystemExit(
            f"Channel {channel} is receiving metadata; choose an inactive channel for an isolated probe"
        )
    print(channel)
    raise SystemExit(0)

for channel in range(channel_count - 1, -1, -1):
    item = channels.get(channel)
    if item is not None and not item.get("metadata", {}).get("active", False):
        print(channel)
        raise SystemExit(0)

raise SystemExit("Insight did not report an inactive metadata channel for the probe")
PY
}

metadata_messages_received() {
  python3 - "${stats_file}" "${channel}" <<'PY'
import json
import sys

path, channel = sys.argv[1], int(sys.argv[2])
with open(path, encoding="utf-8") as stream:
    payload = json.load(stream)

for item in payload.get("channels", []):
    if item.get("channel") == channel:
        print(item.get("metadata", {}).get("messages_received", 0))
        raise SystemExit(0)

raise SystemExit(f"Insight did not report channel {channel}")
PY
}

if ! curl -fsSk --connect-timeout 3 --max-time 5 \
  "${insight_url}/api/health" >/dev/null; then
  echo "Insight is not reachable at ${insight_url}." >&2
  exit 1
fi

echo "Checking reverse DevKit -> Insight network path..."

if ! ssh -T -p "${devkit_ssh_port}" \
  -o BatchMode=yes -o ConnectTimeout=8 \
  "${devkit_user}@${devkit_ip}" \
  python3 - "${sdk_host_ip}" "${insight_host_port}" <<'PY'
import json
import ssl
import sys
import urllib.request

host, tcp_port = sys.argv[1], int(sys.argv[2])
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
PY
then
  echo "Could not complete the reverse network test on ${devkit_user}@${devkit_ip}." >&2
  echo "Check SSH access and the Insight address shown above, then try again." >&2
  exit 1
fi

if ! fetch_stats; then
  echo "Could not read Insight ingest statistics." >&2
  exit 1
fi
if ! channel="$(select_probe_channel)"; then
  exit 1
fi
metadata_port=$((metadata_port_start + channel))
before="$(metadata_messages_received)"
probe_id="$(python3 - <<'PY'
import secrets
print(secrets.token_hex(16))
PY
)"

if ! ssh -T -p "${devkit_ssh_port}" \
  -o BatchMode=yes -o ConnectTimeout=8 \
  "${devkit_user}@${devkit_ip}" \
  python3 - "${sdk_host_ip}" "${metadata_port}" "${probe_id}" <<'PY'
import json
import socket
import sys

host, udp_port, probe_id = sys.argv[1], int(sys.argv[2]), sys.argv[3]

payload = json.dumps(
    {"type": "sima-udp-connectivity-test", "source": "sdk", "probe_id": probe_id},
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
    if (( after == before + 1 )); then
      echo "UDP PASS: Insight received the DevKit probe on port ${metadata_port} (${before} -> ${after} messages)."
      exit 0
    elif (( after > before + 1 )); then
      echo "UDP FAIL: Channel ${channel} received concurrent metadata; the DevKit probe could not be isolated." >&2
      echo "Retry without a channel to select another inactive metadata port." >&2
      exit 1
    fi
  fi
  sleep 1
done

echo "UDP FAIL: Insight did not observe the DevKit probe on port ${metadata_port}." >&2
echo "The DevKit can use SSH, but its UDP path to ${sdk_host_ip}:${metadata_port} is not working." >&2
exit 1
