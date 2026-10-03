const fs = require("fs");

const INSIGHT_LAUNCH_URL_FILE = "/home/docker/.insight-config/launch-url";

function validHttpUrl(value) {
  if (!value || /[\r\n]/.test(value)) {
    return false;
  }

  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

async function readInsightLaunchUrl(filePath = INSIGHT_LAUNCH_URL_FILE, readFile = fs.promises.readFile) {
  try {
    const value = (await readFile(filePath, "utf8")).trim();
    return validHttpUrl(value) ? value : "";
  } catch {
    return "";
  }
}

async function resolveInsightLaunchUrl(resolveDefault, options = {}) {
  const override = await readInsightLaunchUrl(options.filePath, options.readFile);
  if (override) {
    return override;
  }
  return resolveDefault();
}

module.exports = {
  INSIGHT_LAUNCH_URL_FILE,
  readInsightLaunchUrl,
  resolveInsightLaunchUrl,
  validHttpUrl
};
