const test = require("node:test");
const assert = require("node:assert/strict");
const {
  parseRelease,
  readResources,
  parseDevice,
  readDevkit,
  readInsight,
  getInsightUrl,
} = require("../src/landing-data");
const reader = (files) => async (p) => {
  if (!(p in files)) throw Error("missing");
  return files[p];
};
const system = {
  availableParallelism: () => 16,
  totalmem: () => 64 * 1024 ** 3,
  freemem: () => 30 * 1024 ** 3,
  platform: () => "linux",
};
test("SDK metadata preserves full versions, including equals in values", () => {
  assert.equal(
    parseRelease("SDK Version = 3.0.0_Palette_SDK_develop_hash\nOther=a=b")[
      "SDK Version"
    ],
    "3.0.0_Palette_SDK_develop_hash",
  );
  assert.equal(parseRelease("Other=a=b").Other, "a=b");
});
test("cgroup v2 ancestor limits and CPU quota constrain visible host resources", async () => {
  const f = {
    "/proc/meminfo": "MemTotal: 67108864 kB\nMemAvailable: 40000000 kB",
    "/proc/self/cgroup": "0::/container/task",
    "/proc/self/mountinfo": "1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw",
    "/sys/fs/cgroup/container/task/cpu.max": "max 100000",
    "/sys/fs/cgroup/container/cpu.max": "150000 100000",
    "/sys/fs/cgroup/container/memory.max": String(8 * 1024 ** 3),
    "/sys/fs/cgroup/container/memory.current": String(3 * 1024 ** 3),
  };
  const result = await readResources(reader(f), system);
  assert.equal(result.cores, 1.5);
  assert.equal(result.total, 8 * 1024 ** 3);
  assert.equal(result.available, 5 * 1024 ** 3);
});
test("cgroup v1 limits and cpusets are honored; missing MemAvailable stays unknown", async () => {
  const f = {
    "/proc/self/cgroup": "2:cpu,cpuacct:/\n3:memory:/\n4:cpuset:/",
    "/proc/self/mountinfo":
      "1 0 0:1 / /cg/cpu rw - cgroup cgroup rw,cpu,cpuacct\n2 0 0:2 / /cg/mem rw - cgroup cgroup rw,memory\n3 0 0:3 / /cg/set rw - cgroup cgroup rw,cpuset",
    "/cg/cpu/cpu.cfs_quota_us": "-1",
    "/cg/cpu/cpu.cfs_period_us": "100000",
    "/cg/set/cpuset.cpus": "0-1,5",
    "/cg/mem/memory.limit_in_bytes": String(4 * 1024 ** 3),
    "/cg/mem/memory.usage_in_bytes": String(4 * 1024 ** 3),
  };
  const result = await readResources(reader(f), system);
  assert.equal(result.cores, 3);
  assert.equal(result.available, 0);
  assert.equal(result.total, 4 * 1024 ** 3);
  assert.equal((await readResources(reader({}), system)).available, null);
});
test("device-tree NULs and quoted firmware values are normalized", () => {
  assert.deepEqual(
    parseDevice(
      '__MODEL__\nSiMa.ai Modalix SoM Board\0\n__BUILD__\nSIMA_BUILD_VERSION = "3.0.0_develop_B2264"\n__END__\n',
    ),
    { model: "Modalix SoM", version: "3.0.0_develop_B2264" },
  );
});
test("device probing distinguishes absent, bad config, failed SSH, and actual metadata", async () => {
  const fail = async () => {
    throw Error("unreachable");
  };
  assert.equal((await readDevkit({}, { execute: fail })).state, "absent");
  assert.equal(
    (await readDevkit({ host: "-oProxyCommand=bad" }, { execute: fail })).state,
    "invalid",
  );
  assert.equal(
    (await readDevkit({ host: "192.0.2.2" }, { execute: fail })).state,
    "unreachable",
  );
  const calls = [];
  const execute = async (file, args) => {
    calls.push([file, args]);
    return "__MODEL__\nSiMa.ai Modalix DVT Board\0\n__BUILD__\nSIMA_BUILD_VERSION=3.0.0\n__END__\n";
  };
  const data = await readDevkit({ host: "192.0.2.2" }, { execute });
  assert.equal(data.state, "connected");
  assert.equal(data.model, "Modalix DVT");
  assert.equal(calls[0][0], "ssh");
  assert.ok(calls[0][1].includes("StrictHostKeyChecking=accept-new"));
});
test("Insight launch override wins over status and platform-only port mapping", async () => {
  const status = { insight: { webUiUrl: "https://status.test:9900" } };
  assert.equal(
    await getInsightUrl(status, {
      reader: reader({
        "/home/docker/.insight-config/launch-url":
          "https://gateway.test/insight/",
      }),
      env: {},
    }),
    "https://gateway.test/insight/",
  );
  assert.equal(
    await getInsightUrl(status, { reader: reader({}), env: {} }),
    "https://status.test:9900/",
  );
  const ports = reader({
    "/home/docker/.insight-config/neat-port-map.json": JSON.stringify({
      mainUI: { host: 28705 },
    }),
  });
  assert.equal(
    await getInsightUrl(
      {},
      { reader: ports, env: { CONTAINER_HOST_IP: "192.0.2.10" } },
    ),
    "https://192.0.2.10:28705/",
  );
  assert.equal(await getInsightUrl({}, { reader: ports, env: {} }), "");
});
test("Insight version uses installed package when Core is absent", async () => {
  const value = await readInsight(
    {},
    {
      reader: reader({}),
      env: {},
      execute: async (file, args) => {
        assert.equal(file, "/opt/neat-insight/venv/bin/python");
        assert.match(args[1], /importlib.metadata/);
        return "0.0.8\n";
      },
    },
  );
  assert.equal(value.version, "0.0.8");
  assert.equal(value.url, "");
});
