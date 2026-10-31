// A slow status source must not prevent the rest of the panel from rendering.
function withTimeout(probe, timeoutMs) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('Status check timed out')), timeoutMs);
    Promise.resolve().then(probe).then(resolve, reject).finally(() => clearTimeout(timer));
  });
}

async function loadStatuses(probes, update, timeoutMs = 10000) {
  await Promise.all(Object.entries(probes).map(async ([key, probe]) => {
    try {
      update(key, await withTimeout(probe, timeoutMs));
    } catch {
      update(key, {disabled: true, buttonLabel: 'Status unavailable',
        status: 'Could not check status. Refresh to try again.', detail: ''});
    }
  }));
}
module.exports = {loadStatuses};
