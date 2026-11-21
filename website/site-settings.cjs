const manifest = require('./docs-manifest.json');

const channel = process.env.DOCS_CHANNEL || 'production';
if (!['production', 'preview'].includes(channel)) throw new Error(`Unknown documentation channel: ${channel}`);
const preview = channel === 'preview';

module.exports = {
  ...manifest,
  preview,
  baseUrl: preview ? '/staging-preview/' : '/',
  sourceRef: preview ? 'develop' : 'main',
  installTarget: preview ? 'sdk/pib@develop' : 'sdk/pib',
};
