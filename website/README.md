# Systems Builder Guide

Standalone Docusaurus documentation for system engineers creating custom Modalix
images with Palette Image Builder, a companion to Palette SDK. Application
workflows belong at <https://developer.sima.ai/software>.

## Local preview

Use Node.js 24 and npm:

```sh
cd website
npm ci
npm start -- --host 127.0.0.1 --port 3040 --no-open
```

The development preview prepares English documentation. To build and preview all
five languages:

```sh
npm run build
npm run serve -- --host 127.0.0.1 --port 3040 --no-open
```

## Curated documentation

`docs-manifest.json` is the publication allowlist. Only those documents from
`../docs/` are copied into the generated site. Links to unpublished documents
inside `docs/` fail preparation. Other repository references link to GitHub.
Generated content, installed dependencies, and build output are excluded from Git.
The existing repository logo is copied during preparation and used as the favicon.

The manifest records the hostname, source branch, and install target. Preview
examples currently use the published PIB feature-branch package; update the
install target when promoting the package to a release branch. The intended
GitHub Pages hostname is `sdk.neat.sima.ai`; building this site does not configure
GitHub Pages or DNS.

## Translations

English sources live in `../docs/`. Ukrainian, Japanese, Korean, and Traditional
Chinese sources live in `translations/`. The navigation has no language dropdown;
localized builds remain available at `/uk/`, `/ja/`, `/ko/`, and `/zh-Hant/`.
Homepage copy for every locale lives in `src/content/site-copy.json`.

After changing an English document, review and update each translation. Preserve
heading levels, command blocks, file paths, and link destinations. Record the
reviewed English source's SHA256 in `translations/source-hashes.json` for each
locale and document. Preparation rejects stale source hashes, different heading
structures, or changed executable examples. Localized headings retain English
anchor IDs so cross-document links work in every language.

Before pushing, run `npm run build` to check every locale and its internal links.

## GitHub Pages workflow

`.github/workflows/docs-pages.yml` builds all languages for documentation pull
requests. Updates on `main` or `develop`, `sdk-docs-*` tags, and manual dispatches
publish the validated artifact through the `github-pages` environment. Repository
Pages settings and environment rules must permit that deployment; DNS is managed
separately in Vulcan. A feature-branch push alone does not publish the site.
