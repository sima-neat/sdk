/* Test the required browser capability, not a claimed certificate diagnosis. */
(() => {
  const script = document.currentScript;
  // _static is relative to code-server's external base, including path proxies.
  const base = new URL(script.dataset.base.replace(/\/?$/, '/'), location.href);
  const endpoint = name => new URL('_neat/' + name, base);
  const section = document.getElementById('neat-certificate');
  const details = document.getElementById('neat-certificate-details');
  const status = document.getElementById('neat-certificate-status');
  const os = document.getElementById('neat-browser-os');
  os.value = /Mac/i.test(navigator.platform) ? 'mac' : /Win/i.test(navigator.platform) ? 'windows' : 'linux';
  const showOS = () => document.querySelectorAll('[data-cert-os]').forEach(el => { el.hidden = el.dataset.certOs !== os.value; });
  os.addEventListener('change', showOS);
  showOS();
  document.getElementById('neat-ca-download').href = endpoint('ca-certificate').href;
  let userOpened = false;
  details.addEventListener('toggle', () => { if (details.open) userOpened = true; });
  let enabled = true;
  let caAvailable = false;
  let probeState = 'pending';
  function openHelpOnFailure() {
    if (probeState === 'failed' && enabled && caAvailable) details.open = true;
  }
  function hint() {
    if (!enabled) return;
    status.hidden = false;
    status.textContent = 'Having trouble loading extension panels? Certificate help is available below.';
  }
  async function probe() {
    if (!window.isSecureContext || !('serviceWorker' in navigator)) throw new Error('Unavailable');
    // Unique narrow scope isolates simultaneous tabs and any abandoned probe.
    const scope = endpoint('probe/check-' + crypto.randomUUID() + '/');
    const registration = await navigator.serviceWorker.register(endpoint('probe/service-worker.js').href, {
      scope: scope.href, updateViaCache: 'none',
    });
    await registration.unregister();
  }
  const timeout = setTimeout(() => {
    probeState = 'timeout';
    hint();
  }, 6000);
  probe().then(() => {
    clearTimeout(timeout);
    probeState = 'success';
    status.hidden = true;
    if (!userOpened) details.open = false;
  }).catch(() => {
    clearTimeout(timeout);
    // A late rejection must not unexpectedly expand help after a timeout.
    if (probeState === 'pending') probeState = 'failed';
    hint();
    openHelpOnFailure();
  });
  // Metadata is optional and never gates password submission or the probe.
  const controller = new AbortController();
  const infoTimeout = setTimeout(() => controller.abort(), 6000);
  fetch(endpoint('certificate-info'), { cache: 'no-store', signal: controller.signal }).then(r => {
    if (!r.ok) throw new Error('Unavailable');
    return r.json();
  }).then(info => {
    enabled = info.enabled !== false;
    caAvailable = info.available === true;
    section.hidden = !enabled;
    openHelpOnFailure();
    document.getElementById('neat-ca-available').hidden = !info.available;
    document.getElementById('neat-ca-unavailable').hidden = !!info.available;
  }).catch(() => {}).finally(() => clearTimeout(infoTimeout));
})();
