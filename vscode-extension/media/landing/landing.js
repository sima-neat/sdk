const vscode = acquireVsCodeApi();
const $ = (id) => document.getElementById(id);
const text = (id, value) => {
  $(id).textContent = value;
};
const tabs = [...document.querySelectorAll('[role="tab"]')];
function selectTab(tab, focus = false) {
  tabs.forEach((t) => {
    const active = t === tab;
    t.setAttribute("aria-selected", String(active));
    t.tabIndex = active ? 0 : -1;
    $(t.getAttribute("aria-controls")).hidden = !active;
  });
  vscode.setState({ tab: tab.id });
  if (focus) tab.focus();
}
tabs.forEach((tab, i) => {
  tab.addEventListener("click", () => selectTab(tab));
  tab.addEventListener("keydown", (e) => {
    const next = {
      ArrowRight: (i + 1) % tabs.length,
      ArrowLeft: (i + tabs.length - 1) % tabs.length,
      Home: 0,
      End: tabs.length - 1,
    }[e.key];
    if (next !== undefined) {
      e.preventDefault();
      selectTab(tabs[next], true);
    }
  });
});
const saved = vscode.getState();
if (saved?.tab && tabs.some((t) => t.id === saved.tab)) selectTab($(saved.tab));
document.querySelectorAll("[data-action]").forEach((button) =>
  button.addEventListener("click", (e) => {
    e.preventDefault();
    vscode.postMessage({ type: "action", action: button.dataset.action });
  }),
);
$("refresh").addEventListener("click", () => {
  $("refresh").disabled = true;
  text("load-status", "Refreshing environment details…");
  vscode.postMessage({ type: "refresh" });
});
const gib = (n) =>
  typeof n === "number" && Number.isFinite(n)
    ? (n / 1024 ** 3).toLocaleString(undefined, { maximumFractionDigits: 1 })
    : "Unknown";
window.addEventListener("message", ({ data }) => {
  if (data.type === "error") {
    text("load-status", "Unable to refresh environment details. Try Refresh.");
    $("refresh").disabled = false;
    return;
  }
  if (data.type !== "data") return;
  const { sdk, devkit, insight, modelsEnabled, updatedAt } = data.value;
  text("sdk-version", sdk.release || sdk.version || "Unavailable");
  $("sdk-version").title = sdk.version || "";
  text("sdk-platform", sdk.platform || "Unknown");
  text("sdk-status", sdk.version ? "Running" : "SDK not detected");
  text(
    "sdk-cores",
    sdk.cores === null
      ? "Unknown"
      : Number(sdk.cores.toFixed(2)).toLocaleString(),
  );
  text("sdk-memory", `${gib(sdk.available)} / ${gib(sdk.total)} GiB`);
  const connected = devkit.state === "connected";
  $("topology").classList.toggle("unavailable", !connected);
  text(
    "status",
    connected
      ? "Connected"
      : devkit.state === "absent"
        ? "Not configured"
        : devkit.state === "invalid"
          ? "Invalid configuration"
          : "Unreachable",
  );
  text("model", connected ? devkit.model || "Unknown" : "—");
  text("version", connected ? devkit.version || "Unknown" : "—");
  text("address", devkit.host || "—");
  text(
    "connection",
    connected
      ? `SSH connected · port ${devkit.port}`
      : devkit.state === "absent"
        ? "DevKit optional"
        : "Connection unavailable",
  );
  text("wireicon", connected ? "↔" : "–");
  text(
    "hint",
    connected
      ? "Ready to receive your models and applications."
      : devkit.state === "absent"
        ? "You can build and compile without a DevKit. Connect one when you’re ready to deploy."
        : devkit.state === "invalid"
          ? "Check the DevKit Sync host, user, and port settings."
          : "Unable to read the configured device over SSH. Check power, network, and SSH access.",
  );
  text(
    "insight-version",
    `Insight · ${insight.version || "Version unavailable"}`,
  );
  text("insight-url", insight.url || "");
  text(
    "insight-note",
    insight.url
      ? "Same launch destination as the Neat panel."
      : "No launch URL detected. Configure Insight access, then refresh.",
  );
  $("launch-insight").disabled = !insight.url;
  $("insight-url").disabled = !insight.url;
  $("browse-models").disabled = !modelsEnabled;
  text(
    "model-availability",
    modelsEnabled ? "" : "Model Registry requires SDK 3.0 or newer.",
  );
  text(
    "load-status",
    `Updated ${new Date(updatedAt).toLocaleTimeString()} · Refresh to read the latest environment details.`,
  );
  $("refresh").disabled = false;
});
vscode.postMessage({ type: "ready" });
