#!/usr/bin/env python3
"""Check the installed SDK's public login page, not a template fixture."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import urlopen
from urllib.parse import urljoin

BASE = 'http://127.0.0.1:9999/login'


def fetch(url):
    with urlopen(url, timeout=10) as response:
        assert response.status == 200, f'Unexpected response from {url}'
        return response.read()


class LoginPage(HTMLParser):
    def __init__(self):
        super().__init__()
        self.styles = []
        self.icons = []
        self.password = False
        self.post = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'stylesheet':
            self.styles.append(attrs.get('href', ''))
        if tag == 'img':
            self.icons.append(attrs.get('src', ''))
        if tag == 'input' and attrs.get('name') == 'password':
            self.password = attrs.get('type') == 'password'
        if tag == 'form' and attrs.get('method') == 'post':
            self.post = True


html = fetch(BASE).decode('utf-8')
assert 'SiMa.ai' in html and '/ Palette Neat SDK' in html, 'Missing SDK login branding'
assert 'sima-cli sdk neat printenv CODE_SERVER_PASSWORD' in html, 'Missing password guidance'
assert 'Welcome to code-server' not in html, 'Stock login page is still served'
page = LoginPage()
page.feed(html)
assert page.password and page.post, 'Missing password login form'
styles = [url for url in page.styles if url.endswith('/neat-login.css')]
assert len(styles) == 1, 'Missing login stylesheet'
assert b'.neat-brand' in fetch(urljoin(BASE, styles[0])), 'Login stylesheet not served'
icons = [url for url in page.icons if '/neat-favicon-' in url]
assert len(icons) == 1, 'Missing Neat logo'
assert fetch(urljoin(BASE, icons[0])) == Path('/opt/sima-neat/vscode-extension/media/neat-logo.png').read_bytes(), 'Served logo differs from bundled Neat icon'
print('Installed SDK serves the branded login page, password form, stylesheet, and Neat logo.')
