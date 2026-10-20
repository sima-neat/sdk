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
LOGIN_HEADER = """<div class="neat-brand"><img src="{{CS_STATIC_BASE}}/src/browser/media/NEAT_ICON" alt="" width="40" height="40" /><span>SiMa.ai <span class="neat-product">/ Palette Neat SDK</span></span></div>
          <h1 class="main">Your development environment</h1>
          <div class="sub">Sign in to start building with SiMa Neat.</div>"""
LOGIN_HELP = """<section class="neat-help" aria-labelledby="neat-password-help">
            <h2 id="neat-password-help">Find your password</h2>
            <p>For a local SDK, run this in a terminal on the computer running Docker:</p>
            <pre><code>sima-cli sdk neat printenv CODE_SERVER_PASSWORD</code></pre>
            <p>Copy the printed password into the field above. If you have several SDK containers, select the one for this environment.</p>
            <p class="neat-hosted">Using a hosted environment? Use the password supplied by your environment provider, or contact your administrator.</p>
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
.neat-hosted { font-size:14px; }
.login-form label { margin-bottom:8px; font-weight:600; }
.login-form .field { gap:12px; }
.login-form .field .password { min-width:0; }
.login-form .field .submit { margin-left:0; }
"""
updates = []
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
    updates.append((template, updated))
(media / "neat-login.css").write_text(LOGIN_CSS)
shutil.copyfile(args.icon, media / name)
(media / name).chmod(0o644)
for template, updated in updates:
    template.write_text(updated)
print(f'Branded editor, login, and error favicons with {name}')
