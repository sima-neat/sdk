// Ask code-server for a browser-facing loopback route to discover the SDK
// hostname. Only use its hostname: the HTTP proxy cannot serve HTTPS Insight.
async function resolveInsightBrowserUrl(vscode, value) {
  if (vscode.env.uiKind !== vscode.UIKind.Web) return value;
  const target = new URL(value);
  const route = await vscode.env.asExternalUri(
    vscode.Uri.parse(`http://127.0.0.1:${target.port || (target.protocol === "https:" ? 443 : 80)}/`)
  );
  const browser = new URL(route.toString());
  if (!["https:", "http:"].includes(browser.protocol)) {
    throw new Error("Unable to determine the SDK browser hostname");
  }
  target.hostname = browser.hostname;
  return target.href;
}

module.exports = { resolveInsightBrowserUrl };
