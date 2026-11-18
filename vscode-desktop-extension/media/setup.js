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
    const badge = document.querySelector(`#${stepId} .badge`);
    if (badge) {
      badge.className = `badge ${status || ''}`;
    }
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

  // "Show details" on the signed-in card; hidden by default.
  let signinDetails = false;

  function renderSignin() {
    const { cli, login, signin, cliLatest } = state;
    const signedIn = cli.found && login.loggedIn;
    const phase = signedIn && signin.phase !== 'pending' ? 'done' : signin.phase;
    $('si-done').hidden = phase !== 'done';
    $('si-details').hidden = phase !== 'done' || !signinDetails;
    $('si-details-toggle').textContent = signinDetails ? 'Hide details' : 'Show details';
    const who = $('si-who');
    who.textContent = 'Signed in as ';
    const strong = document.createElement('b');
    strong.textContent = login.name || login.email || login.user || 'you';
    who.appendChild(strong);
    if (login.name && login.email) {
      who.appendChild(document.createTextNode(` · ${login.email}`));
    }
    const newer = cliLatest && cli.version && cliLatest !== cli.version;
    $('si-cli').textContent = !cli.found ? 'not installed'
      : `${cli.version || 'unknown version'} · ${newer ? `update available (${cliLatest})` : cliLatest ? 'installed and up to date' : 'installed'}`;

    $('si-pending').hidden = phase !== 'pending' && phase !== 'installing';
    $('si-pending-text').textContent = phase === 'installing' ? 'Installing the SiMa command-line tools…' : 'Finish signing in in your browser…';
    $('si-error').hidden = phase !== 'error';
    $('si-error-reason').textContent = `Reason: ${signin.reason || 'Sign-in did not finish.'}`;

    const busy = phase === 'pending' || phase === 'installing';
    $('si-signin').hidden = !(phase === 'idle' || busy);
    $('si-signin').disabled = busy;
    $('si-cancel').hidden = !busy;
    $('si-retry').hidden = phase !== 'error';
    $('si-terminal').hidden = !(phase === 'error' && signin.needsTerminal);
    $('si-continue').hidden = phase !== 'done';
    $('si-signout').hidden = phase !== 'done';
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

  // Why each check matters: shown when hovering its status icon (texts from the design).
  const CHECK_TIPS = {
    os: 'Supported: Ubuntu 22.04+, macOS 14+ (Apple silicon), Windows 11 with WSL 2.',
    docker: 'The SDK runs as a Docker container. Needs Docker 24 or later.',
    daemon: 'Docker must be running to download and start the SDK.',
    disk: 'The SDK image and its data need about 20 GB.',
    ethtool: 'Used to find DevKits on your network automatically. Without it you can still enter the DevKit IP yourself.',
  };

  const CHECK_ROWS = [
    { id: 'os', label: 'Host OS', group: 'required' },
    { id: 'docker', label: 'Docker', group: 'required' },
    { id: 'daemon', label: 'Docker daemon', group: 'required' },
    { id: 'disk', label: 'Disk space', group: 'required' },
    { id: 'ethtool', label: 'ethtool', group: 'optional' },
  ];
  const CHECK_GROUPS = [
    { id: 'required', title: 'Required', sub: 'Setup can’t continue without these' },
    { id: 'optional', title: 'Optional', sub: 'Setup continues without it' },
  ];
  const CHECK_ICONS = { ok: 'pass', error: 'error', warn: 'warning', skip: 'circle-large-outline', busy: 'loading' };

  /** The rows to show: while checking, the host and Docker keep their last result and the rest spin. */
  function checkRows() {
    const { prereqs } = state;
    const items = prereqs.items || [];
    const byId = new Map(items.map((i) => [i.id, i]));
    const known = CHECK_ROWS.map((row) => byId.get(row.id) || row);
    const extra = items.filter((i) => !CHECK_ROWS.some((row) => row.id === i.id));
    const rows = [...known, ...extra];
    if (prereqs.status !== 'checking') {
      return rows.filter((r) => r.status);
    }
    return rows.map((r) => ((r.id === 'os' || r.id === 'docker') && r.status && r.status !== 'skip'
      ? r
      : { ...r, status: 'busy', detail: 'Checking…', fix: undefined }));
  }

  /** One problem at a time: the first required error, otherwise the first warning. */
  function checkFix(rows) {
    return rows.find((r) => r.status === 'error' && r.fix) || rows.find((r) => r.status === 'warn' && r.fix);
  }

  function renderPrereqs() {
    const { prereqs } = state;
    setBadge('step-prereqs', prereqs.status === 'checking' ? 'running' : prereqs.status);
    const rows = checkRows();
    const groups = $('prereq-groups');
    groups.textContent = '';
    for (const group of CHECK_GROUPS) {
      const groupRows = rows.filter((r) => (r.group || 'required') === group.id);
      if (!groupRows.length) {
        continue;
      }
      const box = document.createElement('div');
      box.className = 'ck-group';
      const head = document.createElement('div');
      head.className = 'ck-group-head';
      const title = document.createElement('span');
      title.className = 'ck-group-title';
      title.textContent = group.title;
      const sub = document.createElement('span');
      sub.className = 'ck-group-sub';
      sub.textContent = group.sub;
      head.append(title, sub);
      const list = document.createElement('div');
      list.className = 'ck-list';
      for (const row of groupRows) {
        const line = document.createElement('div');
        line.className = 'ck-row';
        line.dataset.check = row.id;
        const mark = document.createElement('span');
        mark.className = `ck-mark ${row.status}`;
        if (CHECK_TIPS[row.id]) {
          mark.title = CHECK_TIPS[row.id];
        }
        mark.appendChild(icon(CHECK_ICONS[row.status] || 'circle-large-outline', row.status === 'busy'));
        const label = document.createElement('span');
        label.className = 'ck-label';
        label.textContent = row.label;
        const value = document.createElement('span');
        value.className = `ck-value${row.status === 'error' || row.status === 'warn' ? ` ${row.status}` : ''}`;
        value.textContent = row.detail || '';
        line.append(mark, label, value);
        list.appendChild(line);
      }
      box.append(head, list);
      groups.appendChild(box);
    }

    const fix = prereqs.status === 'checking' ? undefined : checkFix(rows);
    $('prereq-fix').hidden = !fix;
    if (fix) {
      $('prereq-fix-icon').className = `codicon codicon-${fix.status === 'error' ? 'error' : 'warning'}`;
      setRichText($('prereq-fix-text'), fix.fix.text);
      const link = $('prereq-fix-link');
      link.hidden = !fix.fix.link;
      if (fix.fix.link) {
        $('prereq-fix-link-label').textContent = fix.fix.link.label;
        link.dataset.value = fix.fix.link.url;
      }
    }
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

  // ───────────────────────── step list and page frame ─────────────────────────

  const STEPS = [
    { id: 'signin', name: 'Sign in', title: 'Sign in to SiMa' },
    { id: 'check', name: 'Check this computer', title: 'Check this computer' },
    { id: 'download', name: 'Download SDK', title: 'Download the SDK' },
    { id: 'configure', name: 'Configure', title: 'Configure the SDK' },
    { id: 'start', name: 'Start Neat Studio', title: 'Start Neat Studio' },
  ];
  const saved = vscode.getState() || {};
  // The step the user opened from the list; undefined means "the current step".
  let viewing = saved.viewing;
  // The step on screen now; a button pressed on it keeps the page there.
  let shownStep;
  // Configure has no natural "done": it counts once the user continues past it.
  let configConfirmed = Boolean(saved.configConfirmed);
  // Check this computer counts as done once its checks pass and the user continues past it (frame A2a).
  let checkConfirmed = Boolean(saved.checkConfirmed);

  function saveView() {
    vscode.setState({ viewing, configConfirmed, checkConfirmed });
  }

  function pullPercent(pull) {
    const { done, total, bytesDone, bytesTotal } = (pull && pull.progress) || {};
    if (bytesTotal) {
      return Math.round((bytesDone / bytesTotal) * 100);
    }
    return total ? Math.round((done / total) * 100) : 0;
  }

  /** "4.2 of 10.1 GB", or '' while the layer sizes are unknown. */
  function pullGb(pull) {
    const { bytesDone, bytesTotal } = (pull && pull.progress) || {};
    if (!bytesTotal) {
      return '';
    }
    const gb = (n) => (n / 1e9).toFixed(1);
    return `${gb(bytesDone)} of ${gb(bytesTotal)} GB`;
  }

  function versionLabel() {
    const { release, selectedRef } = state;
    if (release && release.version) {
      return `v${String(release.version).replace(/^v/, '')}`;
    }
    return (release && release.ref) || selectedRef || '';
  }

  /** What each step looks like now: done, busy (downloading), failed, and its one-line summary. */
  function stepStatus() {
    const { cli, login, prereqs, image, pull, config, containers } = state;
    const items = prereqs.items || [];
    const pullBusy = pull.state === 'running' || pull.state === 'waiting';
    const pullFailed = pull.state === 'failed';
    const warnItem = items.find((i) => i.status === 'warn');
    const warnSummary = warnItem && (warnItem.group === 'optional'
      ? `Ready · ${warnItem.label} missing (optional)`
      : `Ready · ${warnItem.label}: ${warnItem.detail}`);
    const running = containers.some((c) => c.state === 'running');
    const status = {
      signin: {
        done: cli.found && login.loggedIn,
        summary: login.loggedIn ? `Signed in${login.name || login.user ? ` as ${login.name || login.user}` : ''}` : '',
      },
      check: {
        passed: prereqs.status !== 'checking' && items.length > 0 && !items.some((i) => i.status === 'error'),
        done: checkConfirmed && prereqs.status !== 'checking' && items.length > 0 && !items.some((i) => i.status === 'error'),
        summary: warnSummary || 'All required checks passed',
      },
      download: {
        done: image.status === 'present',
        busy: pullBusy,
        failed: pullFailed,
        pct: pullPercent(pull),
        summary: image.status === 'present'
          ? `${versionLabel()} · ${running ? 'already running' : 'downloaded'}`
          : pullBusy ? [versionLabel(), `${pullPercent(pull)}%`, pullGb(pull)].filter(Boolean).join(' · ')
            : pullFailed ? `Download failed at ${pullPercent(pull)}%` : '',
      },
      configure: {
        done: configConfirmed && !Object.keys(state.configErrors).length,
        summary: `${config.devkitMode === 'pair' ? (config.devkitIp || 'DevKit') : 'No DevKit'} · ${config.codingAgents === 'install' ? 'Claude Code and Codex' : 'No AI agent'}`,
      },
      start: { done: false, summary: '' },
    };
    return status;
  }

  /** The step setup is on: the first one not done. A running download counts as passed. */
  function activeStep(status) {
    if (!status.signin.done) return 'signin';
    if (!status.check.done) return 'check';
    if (!status.download.done && !status.download.busy) return 'download';
    if (!status.configure.done) return 'configure';
    return 'start';
  }

  function headingLead(id) {
    const { prereqs, image, pull, containers } = state;
    if (id === 'signin') {
      return 'One browser sign-in to the SiMa Developer Portal. It covers the SDK download, the Model Registry and Insight. The SiMa command-line tools are installed for you.';
    }
    if (id === 'check') {
      const items = prereqs.items || [];
      if (prereqs.status === 'checking') return 'Checking what the SDK needs…';
      if (items.some((i) => i.status === 'error')) return 'A required item needs your attention before setup can continue.';
      if (items.some((i) => i.status === 'warn' && i.group !== 'optional')) return 'Ready to continue. One item needs your attention.';
      if (items.some((i) => i.status === 'warn')) return 'Ready to continue. One optional item is missing.';
      return 'Everything the SDK needs is here. Hover a status icon to see why each item matters.';
    }
    if (id === 'download') {
      if (containers.some((c) => c.state === 'running')) return 'Neat Studio found an SDK on this computer.';
      if (pull.state === 'running' || pull.state === 'waiting') return 'Downloading in the background. Setup keeps going while you wait.';
      if (image.status === 'present') return 'Neat Studio found an SDK on this computer.';
      return 'The SDK is a Docker image with the toolchain, Neat and examples. Configure opens as soon as the download starts.';
    }
    if (id === 'configure') {
      return 'Choose what goes into your SDK. You can change any of this later.';
    }
    return containers.some((c) => c.state === 'running')
      ? 'Your SDK is already running. Open Neat Studio inside it.'
      : 'Neat Studio starts the SDK container with your choices, then reopens VS Code inside it.';
  }

  function icon(name, spin) {
    const i = document.createElement('i');
    i.className = `codicon codicon-${name}${spin ? ' codicon-modifier-spin' : ''}`;
    return i;
  }

  function renderFrame() {
    const status = stepStatus();
    const active = activeStep(status);
    const activeIndex = STEPS.findIndex((s) => s.id === active);
    // Once the user acts on a step (a button on it, the step list or Continue), stay on it
    // until they move on, so e.g. Check again shows its result instead of jumping ahead.
    // Without that, follow the current step. Fall back to it when the open step is no longer
    // reachable (e.g. after Start over).
    const reachable = (id) => {
      const i = STEPS.findIndex((st) => st.id === id);
      const st = status[id];
      return i >= 0 && (i <= activeIndex || (i === activeIndex + 1 && st.busy));
    };
    if (viewing && !reachable(viewing)) {
      viewing = undefined;
      saveView();
    }
    const view = viewing || active;
    shownStep = view;
    const viewIndex = STEPS.findIndex((s) => s.id === view);

    const list = $('rail-items');
    list.textContent = '';
    STEPS.forEach((step, i) => {
      // Steps after the current one show just their number, as in the design, even when
      // their check already passed in the background.
      const s = i > activeIndex ? { summary: '' } : status[step.id];
      const isView = step.id === view;
      const isActive = i === activeIndex && !s.done;
      const clickable = !isView && (s.done || s.busy || s.failed || i <= activeIndex);

      const item = document.createElement('div');
      item.className = `rail-item${clickable ? ' clickable' : ''}${isView ? ' viewing' : ''}`;
      if (clickable) {
        item.title = 'Open this step';
        item.addEventListener('click', () => {
          viewing = step.id;
          saveView();
          render();
        });
      }

      const row = document.createElement('div');
      row.className = 'rail-row';
      const dot = document.createElement('span');
      dot.className = `rail-dot${s.done ? ' done' : isActive ? ' active' : s.failed ? ' failed' : s.busy ? ' busy' : ''}`;
      if (s.done) {
        dot.appendChild(icon('check'));
      } else if (s.busy) {
        dot.appendChild(icon('loading', true));
      } else if (s.failed) {
        dot.appendChild(icon('warning'));
      } else {
        dot.textContent = String(i + 1);
      }
      const name = document.createElement('span');
      name.className = 'rail-name';
      name.textContent = step.name;
      row.append(dot, name);
      item.appendChild(row);

      if ((s.done || s.busy || s.failed) && s.summary) {
        const summary = document.createElement('span');
        summary.className = `rail-summary${s.failed ? ' failed' : ''}`;
        summary.textContent = s.summary;
        item.appendChild(summary);
      }
      if (s.busy) {
        const bar = document.createElement('div');
        bar.className = 'rail-bar';
        const fill = document.createElement('div');
        fill.style.width = `${s.pct}%`;
        bar.appendChild(fill);
        item.appendChild(bar);
      }
      list.appendChild(item);
    });

    $('step-count').textContent = `Step ${viewIndex + 1} of ${STEPS.length}`;
    $('heading-title').textContent = STEPS[viewIndex].title;
    $('heading-lead').textContent = headingLead(view);
    for (const pane of document.querySelectorAll('[data-pane]')) {
      pane.hidden = pane.dataset.pane !== view;
    }

    // Continue moves on once this step is done (or the download is running).
    const s = status[view];
    const next = STEPS[viewIndex + 1];
    // Sign in has its own button row (Continue · Sign out), as in the design.
    // Check this computer always shows Continue, disabled until the required items pass (as in the design).
    const canContinue = view !== 'signin' && Boolean(next) && (s.done || s.busy || view === 'configure' || view === 'check');
    const continueButton = $('continue-button');
    continueButton.hidden = !canContinue;

    continueButton.disabled = (view === 'configure' && Object.keys(state.configErrors).length > 0)
      || (view === 'check' && !s.passed);

    // Check again: on Check this computer once a check found something; not while checking or when all is fine.
    const { prereqs } = state;
    const checkProblem = prereqs.status !== 'checking' && (prereqs.items || []).some((i) => i.status === 'error' || i.status === 'warn');
    $('prereq-recheck').hidden = !(view === 'check' && checkProblem);
    const requiredFails = (prereqs.items || []).some((i) => i.status === 'error');
    $('nav-reason').hidden = !(view === 'check' && prereqs.status !== 'checking' && requiredFails);
    $('nav-reason-text').textContent = 'Fix the required item above, then Check again.';
    $('si-continue').onclick = () => {
      viewing = 'check';
      saveView();
      render();
    };
    continueButton.onclick = () => {
      if (view === 'configure') {
        configConfirmed = true;
      }
      if (view === 'check') {
        checkConfirmed = true;
      }
      viewing = next.id;
      saveView();
      render();
    };

    $('reset').hidden = view !== 'start';
    post({ type: 'hostStatus', value: { active: activeIndex + 1, total: STEPS.length } });
  }

  function render() {
    renderFrame();
    renderSignin();
    renderCli();
    renderLogin();
    renderPrereqs();
    renderImage();
    renderConfig();
    renderSetup();
    renderReady();
    renderReset();
    keepOnePrimary();
  }

  /** One primary button per step: Continue when shown, otherwise the step's first primary button. */
  function keepOnePrimary() {
    const pane = document.querySelector('[data-pane]:not([hidden])');
    if (!pane) {
      return;
    }
    const shown = (b) => !b.hidden && !b.closest('[hidden]');
    const continueShown = shown($('continue-button'));
    let primaryLeft = !continueShown;
    for (const button of pane.querySelectorAll('button')) {
      const wasPrimary = !button.classList.contains('secondary') || button.dataset.demoted === '1';
      if (!wasPrimary || button.classList.contains('danger') || button.classList.contains('link')) {
        continue;
      }
      const keep = primaryLeft && shown(button);
      if (keep) {
        primaryLeft = false;
      }
      button.classList.toggle('secondary', !keep);
      button.dataset.demoted = keep ? '' : '1';
    }
  }

  // ───────────────────────── events ─────────────────────────

  window.addEventListener('message', (event) => {
    if (event.data && event.data.type === 'state') {
      state = event.data.state;
      render();
    }
  });

  document.addEventListener('click', (event) => {
    if (/** @type {HTMLElement} */ (event.target).closest('#si-details-toggle')) {
      event.preventDefault();
      signinDetails = !signinDetails;
      renderSignin();
      return;
    }
    const link = /** @type {HTMLElement} */ (event.target).closest('[data-link-action]');
    if (link) {
      event.preventDefault();
      post(link.dataset.value === undefined
        ? { type: 'action', id: link.dataset.linkAction }
        : { type: 'action', id: link.dataset.linkAction, value: link.dataset.value });
      return;
    }
    const button = /** @type {HTMLElement} */ (event.target).closest('button[data-action]');
    if (button && !(/** @type {HTMLButtonElement} */ (button)).disabled) {
      if ((button.closest('[data-pane]') || button.hasAttribute('data-keep-step')) && shownStep && viewing !== shownStep) {
        viewing = shownStep;
        saveView();
      }
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
