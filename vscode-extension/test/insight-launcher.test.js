const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const {
  readInsightLaunchUrl,
  resolveInsightLaunchUrl,
  validHttpUrl
} = require("../src/insight-launcher");

test("accepts HTTP and HTTPS launch URLs", () => {
  assert.equal(validHttpUrl("http://127.0.0.1:9900"), true);
  assert.equal(validHttpUrl("https://192.0.2.10:9900/viewer?src=0,1"), true);
});

test("rejects unsupported, malformed, and multi-line values", () => {
  assert.equal(validHttpUrl("file:///tmp/insight"), false);
  assert.equal(validHttpUrl("javascript:alert(1)"), false);
  assert.equal(validHttpUrl("not a URL"), false);
  assert.equal(validHttpUrl("https://example.test\nhttps://other.test"), false);
});

test("reads and trims a valid host-provided launch URL", async (t) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "neat-insight-launcher-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const filePath = path.join(directory, "launch-url");
  await fs.writeFile(filePath, "  https://192.0.2.10:9900/viewer?src=0  \n", "utf8");

  assert.equal(
    await readInsightLaunchUrl(filePath),
    "https://192.0.2.10:9900/viewer?src=0"
  );
});

test("returns an empty override for every fallback case", async (t) => {
  const directory = await fs.mkdtemp(path.join(os.tmpdir(), "neat-insight-launcher-"));
  t.after(() => fs.rm(directory, { recursive: true, force: true }));
  const filePath = path.join(directory, "launch-url");

  assert.equal(await readInsightLaunchUrl(filePath), "");
  await fs.writeFile(filePath, "  \n", "utf8");
  assert.equal(await readInsightLaunchUrl(filePath), "");
  await fs.writeFile(filePath, "not a URL\n", "utf8");
  assert.equal(await readInsightLaunchUrl(filePath), "");
  await fs.writeFile(filePath, "ftp://example.test/insight\n", "utf8");
  assert.equal(await readInsightLaunchUrl(filePath), "");
});

test("uses a valid override without resolving the default", async () => {
  let defaultCalls = 0;
  const url = await resolveInsightLaunchUrl(
    async () => {
      defaultCalls += 1;
      return "https://default.test:9900";
    },
    { readFile: async () => "https://override.test:9900/viewer" }
  );

  assert.equal(url, "https://override.test:9900/viewer");
  assert.equal(defaultCalls, 0);
});

test("falls back and re-reads the override for every resolution", async () => {
  let override = "";
  let defaultCalls = 0;
  const options = { readFile: async () => override };
  const resolveDefault = async () => {
    defaultCalls += 1;
    return "https://default.test:9900";
  };

  assert.equal(
    await resolveInsightLaunchUrl(resolveDefault, options),
    "https://default.test:9900"
  );
  override = "https://override.test:9900/viewer?src=1";
  assert.equal(
    await resolveInsightLaunchUrl(resolveDefault, options),
    "https://override.test:9900/viewer?src=1"
  );
  assert.equal(defaultCalls, 1);
});
