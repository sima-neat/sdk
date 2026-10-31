#!/usr/bin/env python3
"""Use the Neat extension icon as code-server's browser favicon."""
import argparse
import hashlib
from pathlib import Path
import re
import shutil

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--server-dir', type=Path, default=Path('/opt/code-server'))
parser.add_argument('--icon', type=Path, default=Path(__file__).resolve().parents[1] / 'vscode-extension/media/neat-logo.png')
args = parser.parse_args()
icon = args.icon.read_bytes()
if not icon.startswith(b'\x89PNG\r\n\x1a\n'):
    parser.error('--icon must be a PNG')
name = f'neat-favicon-{hashlib.sha256(icon).hexdigest()[:12]}.png'
media = args.server_dir / 'src/browser/media'
templates = [args.server_dir / p for p in (
    'src/browser/pages/login.html',
    'src/browser/pages/error.html',
    'lib/vscode/out/vs/code/browser/workbench/workbench.html',
)]
pattern = re.compile(r'<link\b[^>]*\brel="(?:alternate )?icon"[^>]*>', re.I)
asset = re.compile(r'(?P<prefix>/src/browser/media/)(?:favicon(?:-dark-support)?\.(?:svg|ico)|neat-favicon-[a-f0-9]+\.png)')
LOGIN_HEADER = """<div class="neat-brand"><img src="{{CS_STATIC_BASE}}/src/browser/media/NEAT_ICON" alt="" width="40" height="40" /><span>SiMa.ai <span class="neat-product">/ Palette SDK</span></span></div>
          <h1 class="main">Your development environment</h1>
          <div class="sub">Sign in to start building with SiMa Neat.</div>"""
LOGIN_HELP = """<section class="neat-help" aria-labelledby="neat-password-help">
            <h2 id="neat-password-help">Find your password</h2>
            <p>Your password is shown in the CLI output after SDK setup.</p>
            <p>Can’t find it? Run this command in a terminal on the SDK host:</p>
            <pre><code>sima-cli sdk neat printenv CODE_SERVER_PASSWORD</code></pre>
            <p>Paste the password above to sign in.</p>
          </section>"""
LOGIN_CSS = """
.card-box { max-width: 720px; width: calc(100% - 32px); }
.neat-brand { display:flex; align-items:center; gap:12px; font-weight:700; margin-bottom:32px; font-size:20px; }
.neat-product { font-weight:400; }
.card-box .main { font-size:clamp(24px, 4vw, 32px); line-height:1.2; }
.neat-help { margin-top:32px; border-top:1px solid light-dark(#d2d9e0,#465363); padding-top:24px; line-height:1.6; }
.neat-help h2 { font-size:18px; margin:0 0 12px; }
.neat-help p { margin:12px 0; }
.neat-help pre { padding:16px; background:light-dark(#eef2f6,#121e2b); overflow-wrap:anywhere; white-space:pre-wrap; font-size:14px; }
.login-form label { margin-bottom:8px; font-weight:600; }
.login-form .field { gap:12px; }
.login-form .field .password { min-width:0; }
.login-form .field .submit { margin-left:0; }
"""
FONT_CSS = "\n".join(
    f'@font-face {{ font-family:"{family}"; font-style:normal; font-weight:{weight}; font-display:swap; src:url("{slug}-latin-{weight}-normal.woff2") format("woff2"); }}'
    for family, slug in [('Roboto', 'roboto'), ('IBM Plex Mono', 'ibm-plex-mono')]
    for weight in [400, 500, 700]
)
LOGIN_CSS = FONT_CSS + LOGIN_CSS + """
:root { color-scheme:light dark; --neat-canvas:light-dark(#f5f5f7,#171a1d); --neat-surface:light-dark(#ffffff,#252a2e); --neat-ink:light-dark(#0b1220,#edf0ec); --neat-muted:light-dark(#5f6972,#adb7b8); --neat-line:light-dark(#dfe3e6,#323a3d); }
body { background:var(--neat-canvas); color:var(--neat-ink); font-family:Roboto,"Helvetica Neue",sans-serif; }
.card-box { background:var(--neat-surface); color:var(--neat-ink); border:1px solid var(--neat-line); box-shadow:none; }
.card-box .header { border-color:var(--neat-line); }
.card-box .sub { color:var(--neat-muted); }
input, button { font:inherit; }
.login-form .field .password { background:var(--neat-canvas); color:var(--neat-ink); border-color:var(--neat-line); }
.login-form .field .password:focus { outline:2px solid #5998DD; }
.login-form .field .submit { background:#5998DD; color:#0b1220; }
.login-form .field .submit:hover { background:#75abe5; }
.neat-help { border-color:var(--neat-line); }
.neat-help pre { background:var(--neat-canvas); }
.neat-help code { font-family:"IBM Plex Mono",monospace; }
"""
WORKBENCH_CSS = FONT_CSS + '\n.monaco-workbench { font-family:Roboto,"Helvetica Neue",sans-serif !important; }\n'
WORKBENCH_CSS += '\n.monaco-workbench .statusbar-item[id$=".simaNeat.brand"] > .statusbar-item-label::before { content:""; display:inline-block; width:69px; height:16px; margin-right:6px; background:transparent url("sima-logo.png?v=transparent") center / contain no-repeat; border-radius:2px; flex-shrink:0; }\n'
# Recolor only the wordmark at render time, preserving the multicolor symbol.
WORKBENCH_CSS += '\n.monaco-workbench .statusbar-item[id$=".simaNeat.brand"] > .statusbar-item-label { position:relative; }\n.monaco-workbench .statusbar-item[id$=".simaNeat.brand"] > .statusbar-item-label::after { content:""; position:absolute; left:5px; top:50%; transform:translateY(-50%); width:69px; height:16px; background:#fff; mask:url("sima-logo.png?v=transparent") center / contain no-repeat; clip-path:inset(0 0 0 29%); pointer-events:none; }\n'
logo = args.icon.parent / 'sima-logo.png'
if not logo.is_file():
    parser.error(f'Missing SiMa logo: {logo}')
font_dir = args.icon.parent / 'fonts'
font_files = list(font_dir.glob('*.woff2')) + list(font_dir.glob('*-LICENSE'))
if len(list(font_dir.glob('*.woff2'))) != 6:
    parser.error(f'Expected six bundled fonts in {font_dir}')
trust_assets = Path(__file__).resolve().parent / 'browser-trust'
trust_html = (trust_assets / 'help.html').read_text()
trust_js = (trust_assets / 'help.js').read_text()
trust_routes = (trust_assets / 'routes.cjs').read_text()
LOGIN_CSS += (trust_assets / 'help.css').read_text()
route_file = args.server_dir / 'out/node/routes/index.js'
route_source = route_file.read_text()
route_hook = 'app.router.disable("x-powered-by");'
route_import = 'require("./neat-browser-trust.cjs")(app.router);'
if route_import not in route_source:
    if route_source.count(route_hook) != 1:
        parser.error('Unsupported code-server route registration layout')
    route_source = route_source.replace(route_hook, route_hook + '\n    ' + route_import)
updates = [(route_file, route_source)]
# Validate all upstream templates before changing files; fail visibly on layout drift.
if not media.is_dir():
    parser.error(f'Missing code-server media directory: {media}')
for template in templates:
    original = template.read_text()
    count = [0]
    def replace(match):
        tag, replaced = asset.subn(lambda m: m['prefix'] + name, match[0])
        if replaced:
            count[0] += 1
            tag = re.sub(r'\s+type="[^"]*"', '', tag)
            tag = tag.replace('<link ', '<link type="image/png" ', 1)
        return tag
    updated = pattern.sub(replace, original)
    if count[0] != 2:
        parser.error(f'Expected two favicon links in {template}; found {count[0]}')
    if template == templates[0] and 'id="neat-password-help"' not in updated:
        replacements = {
            '<title>{{I18N_LOGIN_TITLE}}</title>': '<title>Sign in · SiMa Neat SDK</title>',
            '<h1 class="main">{{WELCOME_TEXT}}</h1>\n          <div class="sub">{{I18N_LOGIN_BELOW}} {{PASSWORD_MSG}}</div>': LOGIN_HEADER.replace('NEAT_ICON', name),
            '<div class="field">': '<label for="neat-password">Environment password</label>\n            <div class="field">',
            'class="password"': 'class="password" id="neat-password"',
            'value="{{I18N_SUBMIT}}"': 'value="Sign in"',
            '</form>': '</form>\n          ' + LOGIN_HELP,
            '</head>': '<link href="{{CS_STATIC_BASE}}/src/browser/media/neat-login.css" rel="stylesheet" />\n  </head>',
            'maximum-scale=1.0, minimum-scale=1.0, user-scalable=no': 'minimum-scale=1.0',
        }
        for old, new in replacements.items():
            if updated.count(old) != 1:
                parser.error(f'Unsupported login template: expected one {old!r}')
            updated = updated.replace(old, new, 1)
    if template == templates[0]:
        # Refresh existing branded pages too, including when the icon hash changes.
        updated, headers = re.subn(
            r'(<div class="neat-brand"><img src="[^"]*/src/browser/media/)(?:neat-favicon-[a-f0-9]+|sima-logo)\.png',
            lambda match: match[1] + "sima-logo.png", updated)
        if headers != 1:
            parser.error(f'Expected one branded header icon in {template}; found {headers}')
        updated = updated.replace('sima-logo.png" alt=""', 'sima-logo.png" alt="SiMa.ai"')
        updated = updated.replace('<span>SiMa.ai <span class="neat-product">', '<span><span class="neat-product">')

        updated, help_sections = re.subn(
            r'<section class="neat-help" aria-labelledby="neat-password-help">.*?</section>',
            lambda match: LOGIN_HELP, updated, flags=re.S)
        if help_sections != 1:
            parser.error(f'Expected one password help section in {template}; found {help_sections}')
        start, end = '<!-- neat-browser-trust -->', '<!-- /neat-browser-trust -->'
        block = start + trust_html + '<script src="{{CS_STATIC_BASE}}/src/browser/media/neat-certificate.js" data-base="{{BASE}}" defer></script>' + end
        if start in updated:
            updated = re.sub(re.escape(start) + '.*?' + re.escape(end), lambda _: block, updated, flags=re.S)
        else:
            updated = updated.replace('</body>', block + '\n</body>')
        # Place help inside the login content, immediately after password help.
        updated = updated.replace(block, '')
        updated = updated.replace(LOGIN_HELP, LOGIN_HELP + block)

    if template == templates[-1] and 'neat-workbench.css' not in updated:
        if updated.count('</head>') != 1:
            parser.error(f'Expected one head element in {template}')
        favicon_url = re.search(r'href="([^"]*' + re.escape(name) + r')"', updated)[1]
        css_url = favicon_url.rsplit('/', 1)[0] + '/neat-workbench.css'
        updated = updated.replace('</head>', f'<link rel="stylesheet" href="{css_url}" />\n</head>')
    updates.append((template, updated))
(media / "neat-certificate.js").write_text(trust_js)
(route_file.parent / "neat-browser-trust.cjs").write_text(trust_routes)
(media / "neat-login.css").write_text(LOGIN_CSS)
(media / "neat-workbench.css").write_text(WORKBENCH_CSS)
for font in font_files:
    shutil.copyfile(font, media / font.name)
    (media / font.name).chmod(0o644)
shutil.copyfile(logo, media / "sima-logo.png")
(media / "sima-logo.png").chmod(0o644)
shutil.copyfile(args.icon, media / name)
(media / name).chmod(0o644)
for template, updated in updates:
    template.write_text(updated)
print(f'Branded editor, login, and error favicons with {name}')
