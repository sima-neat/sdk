const manifest = require('./site-settings.cjs');
const {themes} = require('prism-react-renderer');

module.exports = {
  title: "Systems Builder Guide",
  tagline: 'Package device images and work with the system software stack',
  url: `https://${manifest.hostname}`,
  baseUrl: manifest.baseUrl,
  noIndex: manifest.preview,
  customFields: {installTarget: manifest.installTarget},
  organizationName: 'sima-neat',
  projectName: 'sdk',
  favicon: 'img/sima-favicon.png',
  trailingSlash: true,
  onBrokenLinks: 'throw',
  markdown: {hooks: {onBrokenMarkdownLinks: 'throw'}},
  i18n: {
    defaultLocale: 'en',
    locales: manifest.locales,
    path: '.generated-i18n',
    localeConfigs: {
      en: {label: 'English', htmlLang: 'en'},
      uk: {label: 'Українська', htmlLang: 'uk'},
      ja: {label: '日本語', htmlLang: 'ja'},
      ko: {label: '한국어', htmlLang: 'ko'},
      'zh-Hant': {label: '繁體中文', htmlLang: 'zh-Hant'},
    },
  },
  presets: [['classic', {
    docs: {
      path: '.generated-docs',
      routeBasePath: 'guides',
      sidebarPath: './sidebars.js',
      editUrl: ({locale, docPath}) => {
        const id = docPath.replace(/\.md$/, '');
        const document = manifest.documents.find(item => item.id === id);
        if (!document) return undefined;
        const source = locale === 'en' ? `docs/${document.source}` :
          `website/translations/${locale}/${document.source}`;
        return `https://github.com/sima-neat/sdk/edit/${manifest.sourceRef}/${source}`;
      },
    },
    blog: false,
    theme: {customCss: './src/css/custom.css'},
  }]],
  themeConfig: {
    announcementBar: {
      id: manifest.preview ? 'develop-preview' : 'content-verification-in-progress',
      content: manifest.preview
        ? '<strong>Develop preview</strong> — unreleased documentation. Use sdk/pib@develop for these instructions. <a href="https://sdk.neat.sima.ai/">Production guide</a>'
        : '<strong>Under construction</strong> — this content is still being verified. This banner will be removed once verification is complete. Please check back later.',
      backgroundColor: '#fff3cd',
      textColor: '#664d03',
      isCloseable: false,
    },
    colorMode: {defaultMode: 'light', respectPrefersColorScheme: true},
    navbar: {
      title: "Systems Builder Guide",
      logo: {alt: 'SiMa.ai', src: 'img/simaai-logo.png'},
      items: [
        {href: 'https://developer.sima.ai/software', label: 'Application development', position: 'right'},
        {href: 'https://github.com/sima-neat/sdk', label: 'GitHub', position: 'right'},
      ],
    },
    footer: {
      style: 'light',
      links: [{title: 'Resources', items: [
        {label: 'Developer documentation', href: 'https://developer.sima.ai/software'},
        {label: 'SDK source', href: 'https://github.com/sima-neat/sdk'},
      ]}],
      copyright: 'Copyright © 2026 SiMa.ai',
    },
    prism: {theme: themes.github, darkTheme: themes.dracula, additionalLanguages: ['bash', 'yaml', 'json', 'cmake']},
  },
};
