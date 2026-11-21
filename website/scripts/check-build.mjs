import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import settings from '../site-settings.cjs';

const build = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../build');
for (const locale of settings.locales) {
  const directory = path.join(build, locale === 'en' ? '' : locale);
  const home = fs.readFileSync(path.join(directory, 'index.html'), 'utf8');
  assert(home.includes(settings.installTarget), `${locale}: wrong homepage install target`);
  for (const id of settings.documents.map(document => document.id)) {
    const html = fs.readFileSync(path.join(directory, 'guides', id, 'index.html'), 'utf8');
    assert(html.includes(`/edit/${settings.sourceRef}/`), `${locale}/${id}: wrong source links`);
    if (settings.preview) {
      assert(/name="robots"[^>]*content="noindex/.test(html), `${locale}/${id}: preview must be noindex`);
      assert(!html.includes('https://github.com/sima-neat/sdk/blob/main/'), `${locale}/${id}: production link in preview`);
    }
    for (const [page, route] of [[home, ''], [html, `guides/${id}/`]]) {
      const pageUrl = `https://${settings.hostname}${settings.baseUrl}${locale === 'en' ? '' : `${locale}/`}${route}`;
      for (const [, destination] of page.matchAll(/(?:href|src)="([^\"]*)"/g)) {
        if (!destination || /^(?:[a-z]+:|\/\/|#)/i.test(destination)) continue;
        const pathname = new URL(destination, pageUrl).pathname;
        assert(pathname.startsWith(settings.baseUrl), `${locale}/${id}: path escapes channel: ${destination}`);
        const target = path.join(build, decodeURIComponent(pathname.slice(settings.baseUrl.length)));
        assert(fs.existsSync(target), `${locale}/${id}: missing asset or route: ${destination}`);
      }
    }
  }
}
console.log(`Checked ${settings.preview ? 'preview' : 'production'} routes, assets, source links, and install targets in all locales.`);
