const fs = require("fs/promises");
const os = require("os");
const path = require("path");
const { execFile } = require("child_process");
const { promisify } = require("util");
const {
  resolveInsightLaunchUrl,
  normalizeHttpUrl,
} = require("./insight-launcher");
const run = async (file, args, options = {}) =>
  (
    await promisify(execFile)(file, args, {
      timeout: 8000,
      maxBuffer: 256 * 1024,
      ...options,
    })
  ).stdout;
const read = async (file, reader = fs.readFile) => {
  try {
    return await reader(file, "utf8");
  } catch {
    return "";
  }
};
function parseRelease(text) {
  return Object.fromEntries(
    text
      .split(/\r?\n/)
      .filter((line) => line.includes("="))
      .map((line) => {
        const i = line.indexOf("=");
        return [
          line.slice(0, i).trim(),
          line
            .slice(i + 1)
            .trim()
            .replace(/^["']|["']$/g, ""),
        ];
      }),
  );
}
function positive(value) {
  const n = Number(value);
  return Number.isFinite(n) && n > 0 ? n : null;
}
function cpuSetSize(text) {
  if (!/^\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*$/.test(text.trim())) return null;
  return (
    text
      .trim()
      .split(",")
      .reduce((sum, item) => {
        const [a, b = a] = item.split("-").map(Number);
        return sum + Math.max(0, b - a + 1);
      }, 0) || null
  );
}
// Walk visible cgroup ancestors too: the process's own group can be unlimited
// while its container or parent imposes a tighter limit.
async function cgroupDirectories(reader) {
  const [membership, mounts] = await Promise.all([
    read("/proc/self/cgroup", reader),
    read("/proc/self/mountinfo", reader),
  ]);
  const result = [];
  for (const line of mounts.split("\n")) {
    const [left, right] = line.split(" - ");
    if (!right) continue;
    const fields = left.split(" "),
      [type, , options = ""] = right.split(" ");
    if (!["cgroup", "cgroup2"].includes(type)) continue;
    const decode = (s) =>
      s.replace(/\\([0-7]{3})/g, (_, n) => String.fromCharCode(parseInt(n, 8)));
    const root = decode(fields[3]),
      mount = decode(fields[4]);
    const match = membership
      .split("\n")
      .map((l) => l.split(":"))
      .find(
        (parts) =>
          parts.length === 3 &&
          (type === "cgroup2"
            ? parts[0] === "0"
            : parts[1].split(",").some((c) => options.split(",").includes(c))),
      );
    if (!match) continue;
    const member = match[2];
    const relative =
      member === root
        ? ""
        : member.startsWith(root === "/" ? "/" : root + "/")
          ? member.slice(root === "/" ? 1 : root.length + 1)
          : "";
    let dir = path.join(mount, relative);
    while (dir === mount || dir.startsWith(mount + "/")) {
      result.push({ dir, type });
      if (dir === mount) break;
      dir = path.dirname(dir);
    }
  }
  return result;
}
async function readResources(reader = fs.readFile, system = os) {
  const info = await read("/proc/meminfo", reader);
  const mem = (name) =>
    positive(new RegExp(`^${name}:\\s+(\\d+)`, "m").exec(info)?.[1]) * 1024;
  let total = mem("MemTotal") || system.totalmem();
  const availableMatch = /^MemAvailable:\s+(\d+)/m.exec(info);
  let available = availableMatch
    ? Number(availableMatch[1]) * 1024
    : system.platform() === "linux"
      ? null
      : system.freemem();
  let cores = system.availableParallelism
    ? system.availableParallelism()
    : system.cpus().length;
  for (const { dir, type } of await cgroupDirectories(reader)) {
    const v2 = type === "cgroup2";
    const [limitText, usedText, quotaText, periodText, setText] =
      await Promise.all([
        read(
          path.join(dir, v2 ? "memory.max" : "memory.limit_in_bytes"),
          reader,
        ),
        read(
          path.join(dir, v2 ? "memory.current" : "memory.usage_in_bytes"),
          reader,
        ),
        read(path.join(dir, v2 ? "cpu.max" : "cpu.cfs_quota_us"), reader),
        v2 ? "" : read(path.join(dir, "cpu.cfs_period_us"), reader),
        read(
          path.join(dir, v2 ? "cpuset.cpus.effective" : "cpuset.cpus"),
          reader,
        ),
      ]);
    const limit = positive(limitText);
    if (limit && limit < total) total = limit;
    if (
      limit &&
      usedText.trim() !== "" &&
      Number.isFinite(Number(usedText)) &&
      Number(usedText) >= 0
    ) {
      const headroom = Math.max(0, limit - Number(usedText));
      available = available === null ? headroom : Math.min(available, headroom);
    }
    const [quota, period] = v2
      ? quotaText.trim().split(/\s+/)
      : [quotaText, periodText];
    if (positive(quota) && positive(period))
      cores = Math.min(cores, Number(quota) / Number(period));
    const count = cpuSetSize(setText);
    if (count) cores = Math.min(cores, count);
  }
  return {
    cores: cores || null,
    total,
    available:
      available === null ? null : Math.max(0, Math.min(total, available)),
  };
}
async function readNeatStatus(execute = run) {
  try {
    return JSON.parse(await execute("neat", ["--json", "--offline"]));
  } catch {
    return {};
  }
}
async function getInsightUrl(
  status,
  { reader = fs.readFile, env = process.env } = {},
) {
  return resolveInsightLaunchUrl(
    async () => {
      const fromStatus = normalizeHttpUrl(status?.insight?.webUiUrl);
      if (fromStatus) return fromStatus;
      // Platform-only SDK images have Insight but do not necessarily bundle Core's neat CLI.
      const host = (env.CONTAINER_HOST_IP || "").trim();
      if (!/^(?:[a-zA-Z0-9][a-zA-Z0-9._-]*|[a-fA-F0-9:]+)$/.test(host))
        return "";
      try {
        const ports = JSON.parse(
          await read(
            env.NEAT_PORT_MAP_FILE ||
              "/home/docker/.insight-config/neat-port-map.json",
            reader,
          ),
        );
        const port = Number(ports.mainUI?.host);
        if (!Number.isInteger(port) || port < 1 || port > 65535) return "";
        const scheme = ports.mainUI?.scheme || "https";
        return normalizeHttpUrl(
          `${scheme}://${host.includes(":") ? "[" + host + "]" : host}:${port}`,
        );
      } catch {
        return "";
      }
    },
    { readFile: reader },
  );
}
async function readInsight(
  status,
  { execute = run, reader = fs.readFile, env = process.env } = {},
) {
  let version = status?.components?.insight?.version || "";
  if (!version) {
    const python = path.join(
      env.NEAT_INSIGHT_VENV_DIR || "/opt/neat-insight/venv",
      "bin/python",
    );
    try {
      version = (
        await execute(python, [
          "-c",
          'import importlib.metadata; print(importlib.metadata.version("neat-insight"))',
        ])
      ).trim();
    } catch {}
  }
  return { version, url: await getInsightUrl(status, { reader, env }) };
}
const DEVICE_COMMAND =
  "printf '__MODEL__\\n'; cat /proc/device-tree/model 2>/dev/null; printf '\\n__BUILD__\\n'; cat /etc/build /etc/buildinfo 2>/dev/null; printf '\\n__END__\\n'";
function parseDevice(text) {
  const model =
    /__MODEL__\n([\s\S]*?)\n__BUILD__/
      .exec(text)?.[1]
      .replace(/\0/g, "")
      .trim()
      .replace(/^SiMa\.ai\s+/, "")
      .replace(/\s+Board$/, "") || "";
  const build = parseRelease(
    text.split("__BUILD__\n")[1]?.split("__END__")[0] || "",
  );
  return { model, version: build.SIMA_BUILD_VERSION || "" };
}
async function readDevkit(config, { execute = run } = {}) {
  const { host = "", user = "sima", port = "22" } = config || {};
  if (!host) return { state: "absent", host: "" };
  if (
    !/^[A-Za-z0-9][A-Za-z0-9_.:-]*$/.test(host) ||
    !/^[A-Za-z_][A-Za-z0-9_-]*$/.test(user) ||
    !/^\d+$/.test(port) ||
    Number(port) < 1 ||
    Number(port) > 65535
  )
    return { state: "invalid", host };
  const args = [
    "-p",
    String(port),
    "-o",
    "ConnectTimeout=3",
    "-o",
    "ConnectionAttempts=1",
    "-o",
    "StrictHostKeyChecking=accept-new",
    `${user}@${host}`,
    DEVICE_COMMAND,
  ];
  try {
    let output;
    try {
      output = await execute("ssh", ["-o", "BatchMode=yes", ...args], {
        timeout: 5000,
      });
    } catch {
      output = await execute("sshpass", ["-e", "ssh", ...args], {
        timeout: 5000,
        env: { ...process.env, SSHPASS: "edgeai" },
      });
    }
    if (!output.includes("__END__")) throw Error("Incomplete metadata");
    return { state: "connected", host, port, ...parseDevice(output) };
  } catch {
    return { state: "unreachable", host, port };
  }
}
async function loadLandingData(getDevkitConfig, options = {}) {
  const reader = options.reader || fs.readFile;
  const [release, resources, devkit, status] = await Promise.all([
    read("/etc/sdk-release", reader),
    readResources(reader),
    Promise.resolve()
      .then(getDevkitConfig)
      .then((config) => readDevkit(config, options))
      .catch(() => ({ state: "unreachable", host: "" })),
    readNeatStatus(options.execute),
  ]);
  const metadata = parseRelease(release);
  return {
    sdk: {
      version: metadata["SDK Version"] || "",
      release: metadata["SDK Release"] || "",
      platform: metadata["Platform Version"] || "",
      ...resources,
    },
    devkit,
    insight: await readInsight(status, options),
    updatedAt: new Date().toISOString(),
  };
}
module.exports = {
  parseRelease,
  cpuSetSize,
  cgroupDirectories,
  readResources,
  readNeatStatus,
  getInsightUrl,
  readInsight,
  parseDevice,
  readDevkit,
  loadLandingData,
};
