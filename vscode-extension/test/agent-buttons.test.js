const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");

test("install acknowledges the click before dispatch and rejects a second click", () => {
  const element = () => ({ textContent: "", setAttribute() {}, classList: { toggle() {} } });
  const button = { ...element(), dataset: { provider: "codex" },
    addEventListener: (_, fn) => { button.click = fn; } };
  const fields = { ".install-agent": button, ".install-status": element(),
    ".agent-progress": element(), ".agent-next": element() };
  const card = { querySelector: key => fields[key] };
  let receive;
  const messages = [];
  const context = {
    document: {
      getElementById: () => null,
      querySelector: selector => selector.includes('"codex"') ? card : null,
      querySelectorAll: selector => selector === ".install-agent" ? [button] : [],
    },
    window: { addEventListener: (_, fn) => { if (!receive) receive = fn; } },
    vscode: { postMessage(message) {
      if (message.type === "agent") {
        assert.equal(button.disabled, true);
        assert.equal(button.textContent, "Installing…");
        assert.match(fields[".agent-progress"].textContent, /several minutes/);
      }
      messages.push(message);
    } },
  };
  const script = fs.readFileSync(require.resolve("../media/landing/landing.js"), "utf8");
  vm.runInNewContext(script.slice(script.indexOf("const agentNames =")), context);
  receive({ data: { type: "agents", value: { codex: { status: "available" } } } });
  button.click();
  button.click();
  assert.equal(messages.filter(message => message.type === "agent").length, 1);
  receive({ data: { type: "agents", value: { codex: { status: "available", error: "Please retry" } } } });
  assert.equal(button.disabled, false);
  assert.equal(fields[".agent-progress"].textContent, "Please retry");
});
