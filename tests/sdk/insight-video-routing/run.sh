#!/usr/bin/env bash
set -euo pipefail

CONTAINER_ID="${1:-}"
ASSET_URL="${NEAT_SDK_INSIGHT_VIDEO_ASSET_URL:-https://artifacts.sima-neat.com/assets/videos/480p30/video02.mp4}"
ASSET_FALLBACK_URL="${NEAT_SDK_INSIGHT_VIDEO_ASSET_FALLBACK_URL:-https://artifacts.sima-neat.com/assets/videos/720p16/video01.mp4}"
CHANNEL="${NEAT_SDK_INSIGHT_VIDEO_CHANNEL:-0}"
CONTAINER_VIDEO_UDP_PORT=$((9000 + CHANNEL))
CONTAINER_MAIN_UI_PORT=9900
WORK_DIR="${NEAT_SDK_INSIGHT_VIDEO_WORK_DIR:-/tmp/neat-sdk-insight-video-routing}"
VIDEO_FILE="${WORK_DIR}/insight-smoke-video.mp4"
FFMPEG_LOG="${WORK_DIR}/ffmpeg.log"
VALIDATION_LOG="${WORK_DIR}/validation.log"
FFMPEG_PID=""

if [[ -z "${CONTAINER_ID}" ]]; then
  echo "Usage: $(basename "$0") CONTAINER_ID" >&2
  exit 2
fi

cleanup() {
  if [[ -n "${FFMPEG_PID}" ]] && kill -0 "${FFMPEG_PID}" 2>/dev/null; then
    kill "${FFMPEG_PID}" 2>/dev/null || true
    wait "${FFMPEG_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

require_cmd() {
  local cmd="$1"
  if ! command -v "${cmd}" >/dev/null 2>&1; then
    echo "Required command not found on smoke-test host: ${cmd}" >&2
    exit 1
  fi
}

download_video_asset() {
  local output_file="$1"
  local -a urls=("${ASSET_URL}")

  if [[ -n "${ASSET_FALLBACK_URL}" && "${ASSET_FALLBACK_URL}" != "${ASSET_URL}" ]]; then
    urls+=("${ASSET_FALLBACK_URL}")
  fi

  local url
  for url in "${urls[@]}"; do
    echo "Downloading Insight smoke video: ${url}"
    if curl -fL --retry 3 --retry-delay 2 "${url}" -o "${output_file}.tmp"; then
      mv "${output_file}.tmp" "${output_file}"
      return 0
    fi
    rm -f "${output_file}.tmp"
    echo "Failed to download ${url}" >&2
  done

  echo "Failed to download any Insight smoke video asset." >&2
  return 1
}

docker_host_port() {
  local container_id="$1"
  local container_port="$2"
  local protocol="$3"

  python3 - "${container_id}" "${container_port}" "${protocol}" <<'PY'
import json
import subprocess
import sys

container_id = sys.argv[1]
container_port = sys.argv[2]
protocol = sys.argv[3]
key = f"{container_port}/{protocol}"
data = json.loads(subprocess.check_output(["docker", "inspect", container_id], text=True))
ports = (data[0].get("NetworkSettings", {}) or {}).get("Ports", {}) or {}
entries = ports.get(key) or []
for entry in entries:
    host_port = str(entry.get("HostPort", "")).strip()
    if host_port:
        print(host_port)
        raise SystemExit(0)
raise SystemExit(1)
PY
}

port_map_path() {
  local container_id="$1"

  python3 - "${container_id}" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

container_id = sys.argv[1]
data = json.loads(subprocess.check_output(["docker", "inspect", container_id], text=True))
for mount in data[0].get("Mounts", []):
    destination = str(mount.get("Destination", ""))
    source = str(mount.get("Source", ""))
    if destination.endswith("/.insight-config") and source:
        candidate = Path(source) / "neat-port-map.json"
        if candidate.is_file():
            print(candidate)
            raise SystemExit(0)
raise SystemExit(1)
PY
}

host_port_from_map() {
  local map_path="$1"
  local section="$2"
  local container_port="$3"

  python3 - "${map_path}" "${section}" "${container_port}" <<'PY'
import json
import sys

path, section, container_port_s = sys.argv[1:4]
container_port = int(container_port_s)
with open(path, encoding="utf-8") as f:
    data = json.load(f)

entry = data.get(section) or {}
if "host" in entry and int(entry.get("container", -1)) == container_port:
    print(int(entry["host"]))
    raise SystemExit(0)

container_start = int(entry.get("containerStart", -1))
container_end = int(entry.get("containerEnd", -1))
host_start = int(entry.get("hostStart", -1))
host_end = int(entry.get("hostEnd", -1))
if container_start <= container_port <= container_end:
    host_port = host_start + (container_port - container_start)
    if host_start <= host_port <= host_end:
        print(host_port)
        raise SystemExit(0)

raise SystemExit(1)
PY
}

resolve_host_port() {
  local container_id="$1"
  local section="$2"
  local container_port="$3"
  local protocol="$4"
  local map_path=""

  if map_path="$(port_map_path "${container_id}")"; then
    if host_port_from_map "${map_path}" "${section}" "${container_port}"; then
      return 0
    fi
  fi

  docker_host_port "${container_id}" "${container_port}" "${protocol}"
}

wait_for_insight_health() {
  local base_url="$1"
  local deadline=$((SECONDS + 30))

  while (( SECONDS < deadline )); do
    if curl -fsSk "${base_url}/api/health" >/dev/null; then
      return 0
    fi
    sleep 2
  done

  echo "Insight health endpoint did not become ready: ${base_url}/api/health" >&2
  return 1
}

ingest_packets() {
  local stats_file="$1"
  local channel="$2"

  python3 - "${stats_file}" "${channel}" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as f:
    data = json.load(f)
channel = int(sys.argv[2])
for item in data.get("channels", []):
    if int(item.get("channel", -1)) == channel:
        print(int((item.get("rtp") or {}).get("packets_received") or 0))
        raise SystemExit(0)
print(0)
PY
}

validate_ingest_stats() {
  local stats_file="$1"
  local channel="$2"
  local baseline_packets="$3"

  python3 - "${stats_file}" "${channel}" "${baseline_packets}" <<'PY'
import json
import sys

path = sys.argv[1]
expected_channel = int(sys.argv[2])
baseline_packets = int(sys.argv[3])

with open(path, encoding="utf-8") as f:
    data = json.load(f)

for item in data.get("channels", []):
    if int(item.get("channel", -1)) != expected_channel:
        continue
    rtp = item.get("rtp") or {}
    media = item.get("media") or {}
    packets = int(rtp.get("packets_received") or 0)
    errors = []
    if not item.get("active"):
        errors.append("channel is not active")
    if packets <= baseline_packets:
        errors.append(f"packets did not increase: baseline={baseline_packets}, current={packets}")
    if int(rtp.get("bitrate_bps") or 0) <= 0:
        errors.append("rtp.bitrate_bps is zero")
    if not media.get("seen_sps"):
        errors.append("media.seen_sps is false")
    if not media.get("seen_pps"):
        errors.append("media.seen_pps is false")
    if int(media.get("idr_count") or 0) <= 0:
        errors.append("media.idr_count is zero")
    if errors:
        print("; ".join(errors), file=sys.stderr)
        raise SystemExit(1)
    print(
        "Insight ingest ok: "
        f"channel={expected_channel} packets={packets} "
        f"bitrate_bps={rtp.get('bitrate_bps')} idr_count={media.get('idr_count')}"
    )
    raise SystemExit(0)

print(f"channel {expected_channel} not found in ingest stats", file=sys.stderr)
raise SystemExit(1)
PY
}

collect_failure_diagnostics() {
  local base_url="$1"
  local stats_file="$2"

  {
    echo "::group::Insight video routing diagnostics"
    echo "Container: ${CONTAINER_ID}"
    docker port "${CONTAINER_ID}" || true
    echo
    echo "Insight health:"
    curl -sk "${base_url}/api/health" || true
    echo
    echo
    echo "Insight ingest stats:"
    if [[ -f "${stats_file}" ]]; then
      cat "${stats_file}"
    else
      curl -sk "${base_url}/api/ingest/stats?all=1&verbose=1" || true
    fi
    echo
    echo
    echo "ffmpeg log:"
    tail -120 "${FFMPEG_LOG}" 2>/dev/null || true
    echo
    echo "Insight supervisor status:"
    docker exec "${CONTAINER_ID}" insight-admin status || true
    echo
    echo "Insight logs:"
    docker exec "${CONTAINER_ID}" insight-admin logs 160 || true
    echo "::endgroup::"
  } >&2
}

require_cmd docker
require_cmd curl
require_cmd ffmpeg
require_cmd python3

mkdir -p "${WORK_DIR}"

MAIN_UI_HOST_PORT="$(resolve_host_port "${CONTAINER_ID}" mainUI "${CONTAINER_MAIN_UI_PORT}" tcp)"
VIDEO_UDP_HOST_PORT="$(resolve_host_port "${CONTAINER_ID}" videoUDP "${CONTAINER_VIDEO_UDP_PORT}" udp)"
INSIGHT_BASE_URL="https://127.0.0.1:${MAIN_UI_HOST_PORT}"
BASELINE_STATS="${WORK_DIR}/ingest-baseline.json"
CURRENT_STATS="${WORK_DIR}/ingest-current.json"

echo "Insight API: ${INSIGHT_BASE_URL}"
echo "Insight video UDP channel ${CHANNEL}: host ${VIDEO_UDP_HOST_PORT}/udp -> container ${CONTAINER_VIDEO_UDP_PORT}/udp"

wait_for_insight_health "${INSIGHT_BASE_URL}"

curl -fsSk "${INSIGHT_BASE_URL}/api/ingest/stats?all=1&verbose=1" -o "${BASELINE_STATS}"
BASELINE_PACKETS="$(ingest_packets "${BASELINE_STATS}" "${CHANNEL}")"

if [[ ! -s "${VIDEO_FILE}" ]]; then
  download_video_asset "${VIDEO_FILE}"
fi

: > "${FFMPEG_LOG}"
ffmpeg -nostdin -hide_banner -loglevel warning -re -stream_loop -1 -i "${VIDEO_FILE}" \
  -an -c:v copy -bsf:v h264_mp4toannexb \
  -f rtp "rtp://127.0.0.1:${VIDEO_UDP_HOST_PORT}?pkt_size=1200" \
  >"${FFMPEG_LOG}" 2>&1 &
FFMPEG_PID="$!"

deadline=$((SECONDS + 45))
while (( SECONDS < deadline )); do
  if ! kill -0 "${FFMPEG_PID}" 2>/dev/null; then
    echo "ffmpeg exited before Insight observed video ingest." >&2
    collect_failure_diagnostics "${INSIGHT_BASE_URL}" "${CURRENT_STATS}"
    exit 1
  fi

  if curl -fsSk "${INSIGHT_BASE_URL}/api/ingest/stats?all=1&verbose=1" -o "${CURRENT_STATS}" &&
     validate_ingest_stats "${CURRENT_STATS}" "${CHANNEL}" "${BASELINE_PACKETS}" 2>"${VALIDATION_LOG}"; then
    exit 0
  fi
  sleep 2
done

echo "Timed out waiting for Insight to observe RTP/H264 ingest on channel ${CHANNEL}." >&2
if [[ -s "${VALIDATION_LOG}" ]]; then
  cat "${VALIDATION_LOG}" >&2
fi
collect_failure_diagnostics "${INSIGHT_BASE_URL}" "${CURRENT_STATS}"
exit 1
