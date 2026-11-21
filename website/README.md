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
The existing repository wordmark is copied during preparation for the navigation.
The favicon is the square SiMa brand mark from
<https://developer.sima.ai/img/sima-logo.png>, stored at
`static/img/sima-favicon.png`.

The manifest records the hostname and publication allowlist. `site-settings.cjs`
selects the channel: production uses `sdk/pib` with source links to `main`;
`DOCS_CHANNEL=preview` uses `sdk/pib@develop` with source links to `develop`
and serves the site under `/staging-preview/`. To preview that layout locally:

```sh
DOCS_CHANNEL=preview npm run build
npm run serve -- --host 127.0.0.1 --port 3040 --no-open
# Open http://127.0.0.1:3040/staging-preview/
```

Preview pages carry an unreleased banner and noindex metadata. The GitHub
Pages hostname is `sdk.neat.sima.ai`; building this site does not configure
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
requests and `sdk-docs-*` tags without publishing. Pushes or manual dispatches on
`main` and `develop` publish a combined artifact through `github-pages`:

- `/` is built only from current `main`.
- `/staging-preview/` is built only from current `develop`.

Publication runs are serialized without cancelling active deployments. The
publisher checks out both current branch heads after acquiring that workflow
slot and records their commits in `publication.json`; an older queued event
therefore cannot restore older branch content. Both subtrees are rebuilt and
shipped together so neither deployment erases the other. If `main` does not yet
contain this new site, the root displays a release-pending landing page while
the develop preview remains available. Build failures preserve the deployed site.
This workflow does not publish PIB packages: preview installation requires a
qualified `sdk/pib@develop` package from the separate image workflow.

Repository Pages settings and environment rules must permit deployments from
both `main` and `develop`; DNS is managed separately in Vulcan. Feature-branch
pushes and manual dispatches on other refs do not publish.

## Reader paths

The published menu contains four pages, in order: Palette SDK System Stack,
Custom Image Workflow, Example Image, and Palette Image Builder Reference.
The workflow explains the general lifecycle; the example owns the runnable sample
recipe; the reference owns technical rules and troubleshooting. The lower-level
system-software draft remains in the repository but is excluded from publication.

The system-stack diagram uses reviewable light/dark SVG sources under `../images/`.
Diagram assets are explicitly listed in `docs-manifest.json` and copied during
preparation. Markdown uses GitHub's theme fragments; site CSS follows the guide's
manual light/dark selection. Select the diagram to open its full-size SVG.
