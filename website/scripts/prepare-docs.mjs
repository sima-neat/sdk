import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
import GithubSlugger from 'github-slugger';
import manifest from '../site-settings.cjs';

const site = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const repo = path.dirname(site);
const selectedIndex = process.argv.indexOf('--locale');
const selectedLocale = selectedIndex < 0 ? null : process.argv[selectedIndex + 1];
if (selectedLocale && !manifest.locales.includes(selectedLocale)) throw new Error('Unsupported preview locale');
const locales = selectedLocale ? [selectedLocale] : manifest.locales;
const sourceRoot = path.join(repo, 'docs');
const stages = ['.generated-docs', '.generated-i18n'];
for (const stage of stages) fs.rmSync(path.join(site, stage), {recursive: true, force: true});

export function headings(text) {
  let fence = null;
  return text.split('\n').flatMap((line, number) => {
    const mark = line.match(/^\s*(`{3,}|~{3,})/);
    if (mark) { fence = fence ? null : mark[1][0]; return []; }
    if (fence) return [];
    const match = line.match(/^(#{1,6})\s+(.+)$/);
    return match ? [{number, level: match[1].length, text: match[2]}] : [];
  });
}

export function fencedCode(text) {
  return [...text.matchAll(/^(`{3,}|~{3,})[^\n]*\n([\s\S]*?)^\1\s*$/gm)].map(match => match[2]);
}

function render(text, source, document, locale) {
  const original = headings(source);
  const localized = headings(text);
  if (localized.map(h => h.level).join() !== original.map(h => h.level).join()) {
    throw new Error(`${locale}/${document.source}: heading structure differs from English`);
  }
  if (JSON.stringify(fencedCode(source)) !== JSON.stringify(fencedCode(text))) {
    throw new Error(`${locale}/${document.source}: executable examples differ from English`);
  }
  const slugger = new GithubSlugger();
  const lines = text.split('\n');
  localized.forEach((heading, index) => {
    const slug = slugger.slug(original[index].text.replace(/`/g, ''));
    lines[heading.number] += ` {#${slug}}`;
  });
  let body = lines.join('\n');
  body = body.replace(/\]\(([^)]+)\)/g, (match, destination) => {
    if (/^(https?:|mailto:|#)/.test(destination)) return match;
    const [filename, anchor] = destination.split('#');
    const target = path.resolve(sourceRoot, path.dirname(document.source), filename);
    const asset = (manifest.assets || []).find(a => path.resolve(repo, a.source) === target);
    if (asset) {
      // Docusaurus adds the locale base to root-relative anchor links. Relative
      // asset URLs work for both <a> and <img> without duplicating that prefix.
      const route = path.posix.join(locale === 'en' ? '' : locale, 'guides', document.id);
      const relative = path.posix.relative(route, asset.path);
      return `](pathname://${relative}${anchor ? `#${anchor}` : ''})`;
    }
    const selected = manifest.documents.find(d => path.resolve(sourceRoot, d.source) === target);
    if (selected) return `](./${selected.id}.md${anchor ? `#${anchor}` : ''})`;
    if (target.startsWith(sourceRoot + path.sep)) {
      throw new Error(`Link to unpublished documentation: ${destination}`);
    }
    const relative = path.relative(repo, target).split(path.sep).join('/');
    return `](https://github.com/sima-neat/sdk/blob/${manifest.sourceRef}/${relative}${anchor ? `#${anchor}` : ''})`;
  });
  body = body.replaceAll('sima-cli neat install sdk/pib@develop', `sima-cli neat install ${manifest.installTarget}`);
  body = body.replaceAll('sima-cli neat install sdk/pib\n', `sima-cli neat install ${manifest.installTarget}\n`);
  return `---\nid: ${document.id}\nsidebar_position: ${document.position}\n---\n\n${body}`;
}

const hashesPath = path.join(site, 'translations/source-hashes.json');
const hashes = fs.existsSync(hashesPath) ? JSON.parse(fs.readFileSync(hashesPath)) : {};
for (const document of manifest.documents) {
  const absolute = path.resolve(sourceRoot, document.source);
  if (!absolute.startsWith(sourceRoot + path.sep)) throw new Error('Document escapes the publication root');
  const source = fs.readFileSync(absolute, 'utf8');
  const sourceHash = crypto.createHash('sha256').update(source).digest('hex');
  for (const locale of new Set(['en', ...locales])) {
    const text = locale === 'en' ? source : fs.readFileSync(path.join(site, 'translations', locale, document.source), 'utf8');
    if (locale !== 'en' && hashes[locale]?.[document.source] !== sourceHash) {
      throw new Error(`${locale}/${document.source}: translation is missing or stale`);
    }
    const output = locale === 'en' ? path.join(site, '.generated-docs') :
      path.join(site, '.generated-i18n', locale, 'docusaurus-plugin-content-docs/current');
    fs.mkdirSync(output, {recursive: true});
    fs.writeFileSync(path.join(output, `${document.id}.md`), render(text, source, document, locale));
  }
}
for (const locale of locales.filter(l => l !== 'en')) {
  const catalog = path.join(site, 'locales', locale);
  if (fs.existsSync(catalog)) fs.cpSync(catalog, path.join(site, '.generated-i18n', locale), {recursive: true});
}
fs.rmSync(path.join(site, 'static/img/diagrams'), {recursive: true, force: true});
for (const asset of manifest.assets || []) {
  const source = path.resolve(repo, asset.source);
  const destination = path.resolve(site, 'static', asset.path);
  if (!source.startsWith(path.join(repo, 'images') + path.sep) ||
      !destination.startsWith(path.join(site, 'static/img/diagrams') + path.sep)) {
    throw new Error('Diagram asset escapes the publication roots');
  }
  fs.mkdirSync(path.dirname(destination), {recursive: true});
  fs.copyFileSync(source, destination);
}
const images = path.join(site, 'static/img');
fs.mkdirSync(images, {recursive: true});
fs.copyFileSync(path.join(repo, 'images/simaai_logo.png'), path.join(images, 'simaai-logo.png'));
fs.writeFileSync(path.join(site, 'static/CNAME'), manifest.hostname + '\n');
// noIndex covers HTML pages; the root robots.txt also excludes the preview.
fs.writeFileSync(path.join(site, 'static/robots.txt'), 'User-agent: *\nDisallow: /staging-preview/\n');
console.log(`Prepared ${manifest.documents.length} allowed documents in ${locales.length} languages.`);
