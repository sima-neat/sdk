// @ts-check
(function () {
  // eslint-disable-next-line no-undef
  const vscode = acquireVsCodeApi();
  const $ = (id) => /** @type {any} */ (document.getElementById(id));
  let state;
  let versionRefs = '';
  let countdownTimer;
  const inputTimers = {};

  // ───────────────────────── helpers ─────────────────────────

  function setBadge(stepId, status) {
    document.querySelector(`#${stepId} .badge`).className = `badge ${status || ''}`;
  }

  function setDisabledStep(stepId, disabled) {
    $(stepId).classList.toggle('disabled', disabled);
  }

  // Renders text with `code` spans, without using innerHTML.
  function setRichText(el, value) {
    el.textContent = '';
    (value || '').split('`').forEach((part, i) => {
      if (i % 2) {
        const code = document.createElement('code');
        code.textContent = part;
        el.appendChild(code);
      } else {
        el.appendChild(document.createTextNode(part));
      }
    });
  }

  function post(message) {
    vscode.postMessage(message);
  }

  // ───────────────────────── steps ─────────────────────────

  function renderCli() {
    const { cli } = state;
    setBadge('step-cli', cli.found ? 'ok' : 'error');
    $('cli-detail').textContent = cli.found
      ? `sima-cli ${cli.version || ''} at ${cli.file}`
      : 'sima-cli is not installed. The SDK is installed and managed with it.';
    const button = $('cli-install');
    button.textContent = cli.found ? 'Update sima-cli' : 'Install sima-cli';
    button.classList.toggle('secondary', cli.found);
  }

  function renderLogin() {
    const { cli, login } = state;
    setDisabledStep('step-login', !cli.found);
    setBadge('step-login', !cli.found ? '' : login.loggedIn ? 'ok' : 'warn');
    $('login-detail').textContent = !cli.found
      ? 'Install sima-cli first.'
      : login.loggedIn
        ? `Logged in${login.user ? ` as ${login.user}` : ''}.`
        : 'Not logged in. Recommended: the Model Compiler and Model Zoo downloads need it.';
    $('login-button').hidden = login.loggedIn;
    $('logout-button').hidden = !login.loggedIn;
    $('login-button').disabled = !cli.found;
  }

  function renderPrereqs() {
    const { prereqs } = state;
    setBadge('step-prereqs', prereqs.status === 'checking' ? 'running' : prereqs.status);
    const list = $('prereq-list');
    list.textContent = '';
    if (prereqs.status === 'checking' && !prereqs.items.length) {
      const li = document.createElement('li');
      li.textContent = 'Checking…';
      list.appendChild(li);
    }
    for (const item of prereqs.items) {
      const li = document.createElement('li');
      const mark = document.createElement('span');
      mark.className = `mark ${item.status}`;
      mark.textContent = item.status === 'ok' ? '✓' : item.status === 'warn' ? '!' : '✕';
      const label = document.createElement('strong');
      label.textContent = item.label;
      const detail = document.createElement('span');
      detail.textContent = item.detail || '';
      li.append(mark, label, detail);
      if (item.hint) {
        const hint = document.createElement('span');
        hint.className = 'hint';
        setRichText(hint, item.hint);
        li.appendChild(hint);
      }
      list.appendChild(li);
    }
    $('prereq-recheck').disabled = prereqs.status === 'checking';
  }

  function renderVersionSelect() {
    const select = $('version');
    const refs = state.versions.items.map((i) => i.ref).join('|');
    if (refs !== versionRefs) {
      versionRefs = refs;
      select.textContent = '';
      for (const item of state.versions.items) {
        const option = document.createElement('option');
        option.value = item.ref;
        option.textContent = item.recommended ? `${item.label} (recommended)` : item.label;
        select.appendChild(option);
      }
    }
    if (state.selectedRef) {
      select.value = state.selectedRef;
    }
    const pulling = ['running', 'waiting'].includes(state.pull.state);
    select.disabled = state.versions.status === 'loading' || pulling;
  }

  function imageDetail() {
    const { versions, release, image, prereqs } = state;
    if (versions.status === 'loading') {
      return 'Loading versions…';
    }
    if (release.status === 'loading') {
      return `Looking up ${release.ref}…`;
    }
    if (release.status === 'error') {
      return `Couldn't look up ${release.ref}: ${release.error}`;
    }
    if (release.status !== 'ok') {
      return versions.warning || '';
    }
    const lines = [`Image: ${release.image}`];
    if (image.status === 'present') {
      lines.push(`On this computer: ${image.sizeGb} GB, created ${new Date(image.created).toLocaleString()}.`);
    } else if (image.status === 'missing') {
      lines.push('Not downloaded yet.');
    }
    if (!prereqs.dockerReady && prereqs.status !== 'checking') {
      lines.push('Fix Docker in step 3 before downloading.');
    }
    return lines.join('\n');
  }

  function pullStatusText(pull) {
    const { done, total } = pull.progress || { done: 0, total: 0 };
    const attempt = pull.maxAttempts > 1 ? ` · attempt ${pull.attempt} of ${pull.maxAttempts}` : '';
    if (pull.state === 'waiting') {
      const seconds = Math.max(0, Math.ceil((pull.retryAt - Date.now()) / 1000));
      return `Retrying in ${seconds}s (attempt ${pull.attempt + 1} of ${pull.maxAttempts}).`;
    }
    const layers = total ? `${done} of ${total} layers` : 'Preparing';
    return `${layers}${attempt}\n${pull.statusLine || ''}`;
  }

  function renderImage() {
    renderVersionSelect();
    const { cli, release, image, pull, prereqs } = state;
    const imageDetailEl = $('image-detail');
    imageDetailEl.textContent = imageDetail();
    imageDetailEl.style.whiteSpace = 'pre-line';

    const active = pull.state === 'running' || pull.state === 'waiting';
    const failed = pull.state === 'failed';
    let badge = '';
    if (active) {
      badge = 'running';
    } else if (failed) {
      badge = 'error';
    } else if (image.status === 'present') {
      badge = 'ok';
    } else if (pull.state === 'cancelled' || pull.state === 'interrupted') {
      badge = 'warn';
    }
    setBadge('step-image', badge);

    // Progress
    $('pull-progress').hidden = !active;
    if (active) {
      const { done, total } = pull.progress || { done: 0, total: 0 };
      $('bar-fill').style.width = total ? `${Math.round((done / total) * 100)}%` : '';
      document.querySelector('#pull-progress .bar').classList.toggle('indeterminate', !total);
      const status = $('pull-status');
      status.textContent = pullStatusText(pull);
      status.style.whiteSpace = 'pre-line';
    }

    // Errors and resume notes
    const errorBox = $('pull-error');
    const showError = (failed || pull.state === 'waiting') && pull.error;
    errorBox.hidden = !showError && pull.state !== 'cancelled' && pull.state !== 'interrupted';
    errorBox.className = `callout ${showError ? 'error' : 'warn'}`;
    if (showError) {
      $('pull-error-message').textContent = pull.error.message;
      setRichText($('pull-error-hint'), pull.error.hint);
    } else if (pull.state === 'cancelled') {
      $('pull-error-message').textContent = 'Download cancelled.';
      $('pull-error-hint').textContent = 'Layers already downloaded are kept. Resume to continue from there.';
    } else if (pull.state === 'interrupted') {
      $('pull-error-message').textContent = "A previous download didn't finish.";
      $('pull-error-hint').textContent = 'Layers already downloaded are kept. Resume to continue from there.';
    }

    // Buttons
    const canPull = cli.found && prereqs.dockerReady && release.status === 'ok';
    const pullButton = $('pull-button');
    pullButton.hidden = active;
    pullButton.disabled = !canPull;
    if (failed) {
      pullButton.textContent = 'Retry';
    } else if (pull.state === 'cancelled' || pull.state === 'interrupted') {
      pullButton.textContent = 'Resume download';
    } else if (image.status === 'present') {
      pullButton.textContent = 'Check for updates';
    } else {
      pullButton.textContent = 'Download';
    }
    pullButton.classList.toggle('secondary', image.status === 'present' && !failed);
    $('retry-button').hidden = pull.state !== 'waiting';
    $('cancel-button').hidden = !active;
    const terminalButton = $('terminal-button');
    terminalButton.hidden = !failed;
    terminalButton.disabled = !canPull;
    terminalButton.classList.toggle('secondary', !(pull.error && pull.error.needsTerminal));

    // Log
    const log = pull.log || [];
    $('pull-log-box').hidden = !log.length;
    const pre = $('pull-log');
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
    pre.textContent = log.join('\n');
    if (atBottom) {
      pre.scrollTop = pre.scrollHeight;
    }

    clearInterval(countdownTimer);
    if (pull.state === 'waiting') {
      countdownTimer = setInterval(() => {
        $('pull-status').textContent = pullStatusText(state.pull);
      }, 1000);
      $('pull-progress').hidden = false;
    }
  }

  function renderConfig() {
    const { config, configErrors } = state;
    for (const radio of document.querySelectorAll('input[name="devkitMode"]')) {
      radio.checked = radio.value === config.devkitMode;
    }
    for (const key of ['devkitIp', 'workspace', 'modelCompiler', 'codingAgents']) {
      const el = $(key);
      if (document.activeElement !== el && !inputTimers[key]) {
        el.value = config[key] || '';
      }
    }
    $('edgematicStudio').checked = Boolean(config.edgematicStudio);
    $('devkitIp').disabled = config.devkitMode !== 'pair';
    for (const key of ['devkitIp', 'workspace']) {
      $(`${key}-error`).textContent = configErrors[key] || '';
      $(key).classList.toggle('invalid', Boolean(configErrors[key]));
    }
    setBadge('step-config', Object.keys(configErrors).length ? '' : 'ok');
  }

  function renderSetup() {
    const { cli, release, image, configErrors, setup, containers, command } = state;
    const configOk = !Object.keys(configErrors).length;
    const ready = cli.found && release.status === 'ok' && image.status === 'present' && configOk;
    setDisabledStep('step-setup', !ready && setup.state !== 'running');

    let badge = '';
    let detail;
    if (setup.state === 'running' && setup.inTerminal) {
      badge = 'running';
      detail = 'Setup is running in the "Neat SDK setup" terminal. Press Enter there to close it when it finishes.';
    } else if (setup.state === 'running') {
      badge = 'running';
      detail = 'Setup is running. You can keep working; if it needs your sudo password, a box opens at the top of VS Code.';
    } else if (setup.state === 'failed') {
      badge = 'error';
      const code = setup.exitCode !== undefined && setup.exitCode !== 0 ? ` (exit code ${setup.exitCode})` : '';
      detail = setup.cancelled
        ? 'Setup was stopped. Run it again when you are ready.'
        : setup.containerRunning
          ? `Setup failed${code}, so the SDK container wasn't recreated: the one running is the previous one. The log below shows where it stopped.`
          : `Setup failed${code} and the SDK container isn't running. The log below shows where it stopped.`;
    } else if (image.status !== 'present') {
      detail = 'Download the SDK image first (step 4).';
    } else if (!configOk) {
      detail = 'Finish step 5 first.';
    } else {
      if (setup.state === 'done') {
        badge = 'ok';
      }
      detail = 'Runs here, with the answers above. It only asks for your sudo password, when it shares your workspace with a DevKit.';
    }
    setBadge('step-setup', badge);
    $('setup-detail').textContent = detail;

    // Only show a command that setup could actually run.
    $('setup-command').hidden = !command || !configOk;
    $('setup-command').textContent = command;
    $('copy-button').disabled = !command || !configOk;

    const warning = $('setup-warning');
    warning.hidden = !containers.length;
    if (containers.length) {
      const c = containers[0];
      warning.textContent = `An SDK container for this image already exists: ${c.name} (${c.status}). Setup recreates it. Your workspace folder is kept.`;
    }
    const running = setup.state === 'running';
    const log = setup.log || [];
    $('setup-status').hidden = !running || setup.inTerminal || !setup.status;
    $('setup-status').textContent = setup.status || '';
    $('setup-cancel').hidden = !running || Boolean(setup.inTerminal);
    $('setup-terminal').hidden = running;
    $('setup-terminal').disabled = !ready;
    $('setup-log-box').hidden = !log.length;
    const pre = $('setup-log');
    const atBottom = pre.scrollTop + pre.clientHeight >= pre.scrollHeight - 4;
    pre.textContent = log.join('\n');
    if (atBottom) {
      pre.scrollTop = pre.scrollHeight;
    }
    if (setup.state === 'failed' && log.length) {
      $('setup-log-box').open = true;
    }

    const button = $('setup-button');
    button.disabled = !ready || running;
    button.textContent = containers.length ? 'Run setup again' : 'Run setup';
  }

  function renderReady() {
    const { containers, ideAvailable, cli, devContainers } = state;
    const running = containers.find((c) => c.state === 'running');
    setDisabledStep('step-ready', !running);
    setBadge('step-ready', running ? 'ok' : '');
    const vsCodeNote = ' Open in VS Code switches this VS Code into the container, at /workspace.'
      + (devContainers ? '' : " It installs Microsoft's Dev Containers extension first.")
      + ' The first time, VS Code asks you to confirm that you trust the container: click Got It.';
    $('ready-detail').textContent = running
      ? `The SDK container ${running.name} is running (${running.status}).${vsCodeNote}`
      : containers.length
        ? `The SDK container ${containers[0].name} exists but is stopped (${containers[0].status}). Open in VS Code starts it again.`
        : 'Finish the steps above.';
    $('vscode-button').disabled = !containers.length;
    $('ide-button').disabled = !running || !ideAvailable;
    $('shell-button').disabled = !running;
    $('doctor-button').disabled = !cli.found;
  }

  // Defaults when the options open: remove what blocks a fresh setup, keep downloads and logins.
  const RESET_DEFAULTS = { containers: true, images: false, extensionState: true, logout: false, simaCli: false };
  let resetWasOpen = false;

  function renderReset() {
    const { reset } = state;
    const open = reset.status === 'open' || reset.status === 'running';
    $('reset-start').hidden = open || reset.status === 'loading';
    $('reset-loading').hidden = reset.status !== 'loading';
    $('reset-options').hidden = !open;
    if (open) {
      const { info } = reset;
      const boxes = /** @type {NodeListOf<HTMLInputElement>} */ (document.querySelectorAll('[data-reset]'));
      const running = reset.status === 'running';
      const available = {
        containers: info && info.containers.length > 0,
        images: info && info.images.length > 0,
        extensionState: true,
        logout: state.cli.found && state.login.loggedIn,
        simaCli: info && info.simaCliInstalled,
      };
      for (const box of boxes) {
        const key = box.dataset.reset;
        if (!resetWasOpen) {
          box.checked = RESET_DEFAULTS[key] && available[key];
        }
        box.disabled = running || !available[key];
        if (!available[key]) {
          box.checked = false;
        }
      }
      if (info) {
        $('reset-containers-label').textContent = info.containers.length
          ? `SDK containers: ${info.containers.map((c) => `${c.name}${c.state === 'running' ? ' (running)' : ''}`).join(', ')}`
          : 'SDK containers: none';
        $('reset-images-label').textContent = info.images.length
          ? `SDK images: ${info.images.map((i) => `${i.ref} (${i.size})`).join(', ')}. Step 4 downloads them again.`
          : 'SDK images: none';
        $('reset-simaCli-label').textContent = info.simaCliInstalled
          ? 'Uninstall sima-cli (removes ~/.sima-cli, including logins)'
          : 'Uninstall sima-cli: not installed';
        const attached = info.attachedTo && info.containers.some((c) => c.name === info.attachedTo);
        $('reset-attached').hidden = !attached;
        $('reset-attached').textContent = attached ? `This window is open in ${info.attachedTo}. Removing it disconnects this window.` : '';
      }
      $('reset-run').disabled = running || ![...boxes].some((b) => b.checked);
      $('reset-run').textContent = running ? 'Resetting…' : 'Reset…';
    }
    resetWasOpen = open;

    const list = $('reset-result');
    list.textContent = '';
    const result = reset.result;
    if (result) {
      for (const line of result.done) {
        const li = document.createElement('li');
        li.textContent = `✓ ${line}`;
        list.appendChild(li);
      }
      for (const line of result.failed) {
        const li = document.createElement('li');
        li.className = 'error';
        li.textContent = `✕ ${line}`;
        list.appendChild(li);
      }
    }
  }

  function render() {
    renderCli();
    renderLogin();
    renderPrereqs();
    renderImage();
    renderConfig();
    renderSetup();
    renderReady();
    renderReset();
  }

  // ───────────────────────── events ─────────────────────────

  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'state') {
      state = event.data.state;
      render();
    }
  });

  document.addEventListener('click', (event) => {
    const button = /** @type {HTMLElement} */ (event.target).closest('button[data-action]');
    if (button && !(/** @type {HTMLButtonElement} */ (button)).disabled) {
      post({ type: 'action', id: button.dataset.action, value: button.dataset.value });
    }
  });

  for (const box of document.querySelectorAll('[data-reset]')) {
    box.addEventListener('change', () => {
      $('reset-run').disabled = ![...document.querySelectorAll('[data-reset]')].some((b) => /** @type {HTMLInputElement} */ (b).checked);
    });
  }

  $('reset-run').addEventListener('click', () => {
    const choices = {};
    for (const box of /** @type {NodeListOf<HTMLInputElement>} */ (document.querySelectorAll('[data-reset]'))) {
      choices[box.dataset.reset] = box.checked;
    }
    post({ type: 'action', id: 'resetRun', value: choices });
  });

  $('version').addEventListener('change', (event) => {
    post({ type: 'action', id: 'selectVersion', value: event.target.value });
  });

  for (const el of document.querySelectorAll('[data-config]')) {
    const key = el.dataset.config;
    const read = () => (el.type === 'checkbox' ? el.checked : el.value);
    if (el.type === 'text') {
      el.addEventListener('input', () => {
        clearTimeout(inputTimers[key]);
        inputTimers[key] = setTimeout(() => {
          inputTimers[key] = undefined;
          post({ type: 'config', key, value: read() });
        }, 500);
      });
    }
    el.addEventListener('change', () => {
      clearTimeout(inputTimers[key]);
      inputTimers[key] = undefined;
      post({ type: 'config', key, value: read() });
    });
  }

  post({ type: 'ready' });
}());
