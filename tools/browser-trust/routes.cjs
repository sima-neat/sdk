// Public, fixed-path browser onboarding endpoints. No directory is served.
const fs = require('node:fs/promises');
const path = require('node:path');
const { X509Certificate } = require('node:crypto');

async function certificate() {
  if (process.env.SIMA_SDK_CERT_HELP === 'off') return null;
  const leafPath = process.env.CODE_SERVER_CERT || process.env.OPENVSCODE_SERVER_CERT || '/sdk-cert/neat-sdk.pem';
  const caPath = path.join(path.dirname(leafPath), 'sima-sdk-rootCA.pem');
  try {
    const [leafData, caData] = await Promise.all([fs.readFile(leafPath), fs.readFile(caPath)]);
    const leaf = new X509Certificate(leafData);
    const ca = new X509Certificate(caData);
    const now = Date.now();
    if (!ca.ca || !leaf.checkIssued(ca) || !leaf.verify(ca.publicKey) ||
        [leaf, ca].some(c => now < Date.parse(c.validFrom) || now > Date.parse(c.validTo))) return null;
    return ca.toString(); // Export one public certificate, never raw file contents.
  } catch { return null; }
}

module.exports = function registerBrowserTrust(router) {
  function headers(res) {
    res.set('Cache-Control', 'no-store');
    res.set('X-Content-Type-Options', 'nosniff');
  }
  router.get('/_neat/certificate-info', async (_req, res) => {
    headers(res);
    res.json({ available: !!(await certificate()), enabled: process.env.SIMA_SDK_CERT_HELP !== 'off' });
  });
  router.get('/_neat/ca-certificate', async (_req, res) => {
    headers(res);
    const pem = await certificate();
    if (!pem) return res.status(404).end();
    res.set('Content-Type', 'application/x-pem-file');
    res.set('Content-Disposition', 'attachment; filename="sima-sdk-rootCA.pem"');
    res.send(pem);
  });
  router.get('/_neat/probe/service-worker.js', (_req, res) => {
    headers(res);
    res.set('Content-Type', 'application/javascript');
    // No fetch handler, clients.claim(), or access to editor requests.
    res.send('self.addEventListener("install", () => self.skipWaiting());');
  });
};
