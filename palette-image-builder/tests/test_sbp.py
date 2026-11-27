"""pib package: the launcher verb, the image layout and the build orchestration, with a fake sbp.

No network, no SiMa.ai sources: a stand-in sbp publishes small .debs into the layout reprepro
gives sbp's local repo, keeping a kernel build counter the way the real kernel build does.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pib'))
from pib import cli  # noqa: E402
from pib import sbp  # noqa: E402

# This checkout's pib, not one installed in the image: run-unit-tests.sh puts it first on PYTHONPATH,
# as another test module may import pib before this one does.
assert Path(sbp.__file__).resolve().is_relative_to(ROOT), f'testing {sbp.__file__}, not {ROOT}'

LINUX_YAML = """\
---
name: "Package Linux Kernel for ${platform}"
module: simaai.makefile
options:
  name: linux-${platform}
  codename: ${include:simaai-palette/codename}
  url: ssh://git@ssh.bitbucket.org/sima-ai/simaai-linux.git
  branch: develop
  patches:
  - kernel/0001-HACK-do-not-put-commit-hash-in-version-string.patch
  extra_makeflags: KBUILD_DEFCONFIG=simaai_${platform}_defconfig ARCH=arm64
    FIT_SIGN_KEYDIR=${oc.env:FIT_SIGN_KEYDIR,/opt/secure-boot-keys/fit-signing}
  debfiles:
  - linux-headers
  - linux-image
  - linux-libc-dev
"""
LTTNG_YAML = """\
---
name: "Lttng Kernel Modules for ${platform}"
module: simaai.makefile
options:
  name: lttng-modules-${platform}
  url: https://git.lttng.org/lttng-modules.git
  branch: stable-2.14
  source: .
"""
SMIFB_YAML = """\
---
name: "smifb for ${platform}"
module: simaai.makedeb
options:
  name: smifb-${platform}
  url: https://github.com/teddywlq/smifb4.0.git
  branch: v4.6.0
  commit-id: 3a2a5616157a22895a55a1c4cf0474a431e6fa58
"""
PARAMS = """\
# boot firmware
pboot_common:
- linux-image-6.18.3-${platform}* u-boot-${platform} atf-${platform}
"""
KERNEL_URL = 'https://git.example/simaai-linux.git'  # tests map it to a local repository
SOURCES = {"release": "3.0.0", "codename": "agate", "packages": {
    "linux-modalix": {"config": "kernel/linux.yaml", "url": KERNEL_URL, "branch": "master"},
    "lttng-modules-modalix": {"config": "lttng-modules/lttng-modules.yaml", "branch": "stable-2.14",
                              "commit-id": "5f23d6ea07a1b965c9f805c1dd5aab0a213b455b"}}}
LOCAL_URL = 'https://pib.invalid/PIB_KERNEL_SRC.git'  # sbp/setup.sh's PIB_KERNEL_SRC_URL
# The variables the launcher passes pib package alone (host/pib package_arguments), by prefix
PACKAGE_VARIABLES = ('PIB_PKGBUILD_SRC', 'PIB_PACKAGE_', 'PIB_KERNEL_', 'PIB_GIT_MIRRORS', 'PIB_CCACHE_SIZE')


def script(path):
    """A script of this checkout (ci/, deps/) as a module."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(path.stem.replace('-', '_'), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

# A stand-in for sbp: logs each call, then publishes .debs the way sbp + reprepro leave them.
FAKE_SBP = r'''#!/usr/bin/env python3
import hashlib, json, os, subprocess, sys, tempfile
from pathlib import Path
args = sys.argv[1:]
log = {"args": args, "cwd": os.getcwd(), "BUILD": os.environ.get("BUILD"),
       "jobs": os.environ.get("PYTHON_CPU_COUNT"), "src": os.environ.get("PIB_PKGBUILD_SRC"),
       "keydir": os.environ.get("FIT_SIGN_KEYDIR"), "keyname": os.environ.get("FIT_SIGN_KEYNAME"),
       "REPO": os.environ.get("REPO"),
       "git_map": [(os.environ.get(f"GIT_CONFIG_KEY_{i}"), os.environ.get(f"GIT_CONFIG_VALUE_{i}"))
                   for i in range(int(os.environ.get("GIT_CONFIG_COUNT") or 0))],
       "pib_kernel_vars": sorted(k for k in os.environ if k.startswith("PIB_KERNEL_"))}
with open(os.environ["FAKE_SBP_LOG"], "a") as f:
    f.write(json.dumps(log) + "\n")
assert Path("configs/packages/packages.yaml").is_file(), "sbp runs from the tree root"
if os.environ.get("FAKE_SBP_FAIL"):
    sys.exit(3)
if args[0] != "package" or "--dry-run" in args:
    sys.exit(0)
pick = args[args.index("-p") + 1].split(",")
tasks = args[args.index("-t") + 1] if "-t" in args else ""
ws = Path(os.environ["SBP_WORKSPACE"])
repo = Path(os.environ["REPO_ROOT"]) / os.environ["BUILD_TYPE"]
index = repo / "dists/agate/non-free/binary-arm64/Packages"
entries = {}
if index.is_file():
    for st in index.read_text().split("\n\n"):
        f = dict(l.split(": ", 1) for l in st.splitlines() if ": " in l)
        if f: entries[f["Package"]] = f
def vkey(v):
    return [int(x) if x.isdigit() else x for x in v.replace("~", ".~.").replace("-", ".").split(".")]
def publish(pkg, ver, files):
    old = entries.get(pkg)
    if old and old["Version"] != ver and subprocess.run(
            ["dpkg", "--compare-versions", ver, "lt", old["Version"]]).returncode == 0:
        print(f"Skipping inclusion of '{pkg}' '{ver}', as it has already '{old['Version']}'.")
        return  # reprepro keeps the higher version and still exits 0
    with tempfile.TemporaryDirectory() as t:
        t = Path(t); (t / "DEBIAN").mkdir()
        (t / "DEBIAN/control").write_text(f"Package: {pkg}\nVersion: {ver}\nArchitecture: arm64\n"
                                          "Maintainer: t <t@t>\nDescription: t\n")
        for name, text in files.items():
            (t / name).parent.mkdir(parents=True, exist_ok=True); (t / name).write_text(text)
        out = repo / "pool/non-free" / pkg[0] / f"{pkg}_{ver}_arm64.deb"
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["dpkg-deb", "--root-owner-group", "-Zgzip", "-b", t, out],
                       check=True, capture_output=True)
    if old and old["Filename"] != str(out.relative_to(repo)):
        (repo / old["Filename"]).unlink(missing_ok=True)
    entries[pkg] = {"Package": pkg, "Version": ver, "Architecture": "arm64",
                    "Filename": str(out.relative_to(repo)),
                    "SHA256": hashlib.sha256(out.read_bytes()).hexdigest()}
def counter(name):
    return ws / "packages" / name / "built"
if "linux-modalix" in pick:
    built = counter("linux-modalix")
    if tasks.startswith("clean") or not built.exists():
        rev = int(os.environ["BUILD"])  # populate_build.sh: a fresh build counts from BUILD
    elif tasks:
        rev = int(built.read_text()) + 1  # a rebuild in the same tree: the kernel's own counter
    else:
        rev = None  # every task done: sbp publishes nothing
    if rev is not None:
        built.parent.mkdir(parents=True, exist_ok=True); built.write_text(str(rev))
        kv = os.environ.get("FAKE_KV", "6.18.3")  # the kernel release the source makes
        ver = f"{kv}-{rev}"
        uapi = os.environ.get("FAKE_UAPI", "#define MODALIX_ISP_CALIB_TOTAL_SIZE 137\n")
        boot = {f"boot/vmlinuz-{kv}-modalix": "k"} if os.environ.get("FAKE_NO_FIT") else {"boot/fitImage": "fit"}
        publish(f"linux-image-{kv}-modalix", ver, boot)
        publish(f"linux-headers-{kv}-modalix", ver, {"usr/src/x": "h"})
        publish("linux-libc-dev", ver, {"usr/include/linux/media/simaai/modalix_isp_calib.h": uapi})
for name, deb, ver in (("smifb-modalix", "smifb-modalix", "4.6.0~git{n}-0"),
                       ("lttng-modules-modalix", "lttng-modules-modalix", "2.14-1~git{n}-0")):
    if name in pick:
        assert any(p.startswith("linux-headers-") for p in entries), "modules need the kernel's headers"
        built = counter(name)
        n = int(built.read_text()) + 1 if built.exists() else 1
        if tasks.startswith("clean") or not built.exists():
            built.parent.mkdir(parents=True, exist_ok=True); built.write_text(str(n))
            publish(deb, ver.format(n=f"20261119{n:04d}"), {"lib/modules/6.18.3-modalix/extra/m.ko": deb})
index.parent.mkdir(parents=True, exist_ok=True)
index.write_text("\n".join("".join(f"{k}: {v}\n" for k, v in e.items()) for e in entries.values()))
'''

# A stand-in for reprepro's "remove": drops packages from the stand-in repo's index.
FAKE_REPREPRO = r'''#!/usr/bin/env python3
import sys
from pathlib import Path
args = sys.argv[1:]
assert args[0] == "-b" and args[2] == "remove", args
index = Path(args[1]) / "dists" / args[3] / "non-free/binary-arm64/Packages"
stanzas = [s for s in index.read_text().split("\n\n") if s.strip()]
keep = [s.strip("\n") + "\n" for s in stanzas
        if dict(l.split(": ", 1) for l in s.splitlines() if ": " in l).get("Package") not in args[4:]]
index.write_text("\n".join(keep))
'''


def dies(fn, *a, **k):
    try:
        fn(*a, **k)
    except SystemExit as e:
        return str(e.code)
    raise AssertionError('did not die')


def write(path, text):
    path.write_text(text)
    return path


def git(*a):
    return subprocess.run(['git', *a], check=True, capture_output=True, text=True).stdout.strip()


def add_commit(repo, branch, text):
    """A new commit on branch of the git checkout repo, made (with the branch) if need be: a
    stand-in kernel repository. Returns the commit."""
    if not (repo / '.git').is_dir():
        git('init', '-q', '-b', branch, str(repo))
    elif branch in git('-C', str(repo), 'branch', '--format=%(refname:short)').split():
        git('-C', str(repo), 'checkout', '-q', branch)
    else:
        git('-C', str(repo), 'checkout', '-q', '-b', branch)
    (repo / 'f').write_text(text)
    git('-C', str(repo), 'add', 'f')
    git('-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', '-c', 'commit.gpgsign=false',
        'commit', '-q', '-m', text)
    return git('-C', str(repo), 'rev-parse', 'HEAD')


def url_map(config, url, repo):
    """What sbp/setup.sh does in the container: git fetches url from repo (a system config file)."""
    git('config', '--file', str(config), '--add', f'url.{repo}.insteadOf', url)


def fake_tree(base):
    src = base / 'swsoc-elxr'
    for rel, text in (('pkgbuild/sbp/cli.py', ''), ('configs/packages/packages.yaml', ''),
                      ('configs/packages/kernel/linux.yaml', LINUX_YAML),
                      ('configs/packages/lttng-modules/lttng-modules.yaml', LTTNG_YAML),
                      ('configs/packages/smifb/smifb.yaml', SMIFB_YAML),
                      ('configs/packages/simaai-palette/codename', 'agate\n')):
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_text(text)
    return src


def workspace(base, flavor='palette'):
    ws = base / 'ws'
    (ws / 'configs/images').mkdir(parents=True)
    (ws / 'configs/images/image-params.yaml').write_text(PARAMS)
    (ws / 'custom-debs').mkdir()
    (ws / 'keys').mkdir()
    (ws / 'image.yaml').write_text(f'base: {flavor}\ntarget: modalix\nrelease: 3.0.0\nversion: 3.0.0.1\n')
    with patch('sys.stdout'):
        cli.gen_fit_key(ws / 'keys')
    return ws


def deb(path, pkg, ver, owner=None):
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'DEBIAN').mkdir()
        (t / 'DEBIAN/control').write_text(f'Package: {pkg}\nVersion: {ver}\nArchitecture: arm64\n'
                                          'Maintainer: t <t@t>\nDescription: t\n')
        (t / 'usr/share').mkdir(parents=True)
        (t / 'usr/share/f').write_text('x')
        flags = ['--root-owner-group']
        if owner is not None:
            flags = []
            if os.getuid() == 0:
                for p in [t, *t.rglob('*')]:
                    os.chown(p, owner, owner)
        subprocess.run(['dpkg-deb', *flags, '-b', t, path], check=True, capture_output=True)
    return path


class Launcher(unittest.TestCase):
    """host/pib package: unprivileged, a read-only workspace, the customer keys hidden."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'bin').mkdir()
        (self.root / 'bin/docker').write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n')
        (self.root / 'bin/docker').chmod(0o755)
        self.ws = self.root / 'ws'
        (self.ws / 'keys').mkdir(parents=True)
        (self.ws / 'image.yaml').write_text('base: palette\n')
        for name in ('ca.key', 'swu-signing.key', 'debs-signing.secret.asc', 'fit-signing.key', 'fit-signing.crt'):
            (self.ws / 'keys' / name).write_text('secret ' + name)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(('PIB_', 'SWU_'))}
        self.env.update(PATH=f'{self.root}/bin:{os.environ["PATH"]}', PIB_IMAGE='reg/x:7')

    def tearDown(self):
        self.tmp.cleanup()

    def run_pib(self, *args, check=True, cwd=None, **env):
        r = subprocess.run([str(ROOT / 'host/pib'), *args], cwd=cwd or self.ws, capture_output=True,
                           text=True, env={**self.env, **env})
        if check:
            self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_unprivileged_read_only_workspace_and_hidden_keys(self):
        args = self.run_pib('package', '-p', 'linux').stdout.splitlines()
        uid = os.getuid()
        self.assertEqual(args[-5:], ['reg/x:7', 'pib', 'package', '-p', 'linux'], 'the image every pib command runs')
        self.assertNotIn('--privileged', args)
        self.assertNotIn('/dev:/dev', args)
        self.assertIn(f'pib-package-{uid}:/var/tmp/pib-package', args)
        self.assertEqual(args[args.index('--name') + 1], f'pib-package-{uid}')
        self.assertIn(f'{self.ws}:/workspace:ro', args)
        self.assertNotIn(f'{self.ws}:/workspace', args)
        self.assertIn(f'{self.ws}/custom-debs:/workspace/custom-debs', args)
        self.assertTrue((self.ws / 'custom-debs').is_dir(), 'made for a workspace')
        self.assertIn('type=tmpfs,destination=/workspace/keys', args)
        mounts = [a for a in args if ':/workspace/keys/' in a]
        self.assertEqual(mounts, [f'{self.ws}/keys/fit-signing.key:/workspace/keys/fit-signing.key:ro',
                                  f'{self.ws}/keys/fit-signing.crt:/workspace/keys/fit-signing.crt:ro'])
        self.assertFalse(any('secret' in a for a in args))
        # the other verbs keep the read-write workspace and know nothing of pib package's settings
        args = self.run_pib('verify', PIB_PKGBUILD_SRC=str(self.root), PIB_PACKAGE_JOBS='3').stdout.splitlines()
        self.assertIn(f'{self.ws}:/workspace', args)
        self.assertFalse(any('pib-package' in a or a.startswith((*PACKAGE_VARIABLES, 'type=tmpfs'))
                             for a in args), args)

    def test_outside_a_workspace_nothing_is_created(self):
        bare = self.root / 'bare'
        bare.mkdir()
        args = self.run_pib('package', '--list', cwd=bare).stdout.splitlines()
        self.assertFalse((bare / 'custom-debs').exists())
        self.assertFalse(any('custom-debs' in a or a.startswith('type=tmpfs') for a in args), args)

    def test_the_image_every_pib_command_runs(self):
        """pib package has no image of its own: PIB_IMAGE, else the launcher's DEFAULT_IMAGE, also
        when that is a digest."""
        def image(r):  # the argument before the command ('pib ...')
            args = r.stdout.splitlines()
            return args[len(args) - 2 - args[::-1].index('pib')]
        digest = 'reg/x@sha256:' + 'a' * 64
        for env, want in (({}, 'reg/x:7'), ({'PIB_IMAGE': digest}, digest),
                          ({'PIB_IMAGE': ''}, 'ghcr.io/sima-neat/palette-image-builder:latest')):
            for argv in (('package', '--list'), ('package', '-p', 'linux'), ('verify',)):
                self.assertEqual(image(self.run_pib(*argv, **env)), want, (argv, env))
        # an installed launcher: the installer binds its DEFAULT_IMAGE to the published digest
        copy = self.root / 'installed-pib'
        copy.write_text((ROOT / 'host/pib').read_text().replace(
            'DEFAULT_IMAGE = "ghcr.io/sima-neat/palette-image-builder:latest"', f'DEFAULT_IMAGE = "{digest}"'))
        copy.chmod(0o755)
        r = subprocess.run([str(copy), 'package', '--list'], cwd=self.ws, capture_output=True, text=True,
                           env={**self.env, 'PIB_IMAGE': ''})
        self.assertEqual(image(r), digest, r.stderr)

    def test_source_and_mirrors_are_read_only_and_partial(self):
        src = self.root / 'swsoc-elxr'
        for d in ('pkgbuild/sbp', 'configs/packages', 'keys/rot-key'):
            (src / d).mkdir(parents=True)
        (self.root / 'mirrors').mkdir()
        args = self.run_pib('package', '--list', PIB_PKGBUILD_SRC=str(src), PIB_GIT_MIRRORS=str(self.root / 'mirrors'),
                            PIB_PACKAGE_JOBS='3', PIB_CCACHE_SIZE='2G', PIB_PACKAGE_VOLUME='my-vol').stdout.splitlines()
        self.assertIn('PIB_CCACHE_SIZE=2G', args)
        self.assertEqual(args[args.index('--name') + 1], 'pib-package-my-vol', 'one run per volume, not per user')
        self.assertIn(f'{src}/pkgbuild:/src/pkgbuild:ro', args)
        self.assertIn(f'{src}/configs/packages:/src/configs/packages:ro', args)
        self.assertFalse(any(a.startswith(f'{src}:') or '/keys/rot-key' in a for a in args), 'not the checkout keys')
        self.assertIn('PIB_PKGBUILD_SRC=/src', args)
        self.assertIn(f'{self.root}/mirrors:/mirrors:ro', args)
        self.assertIn('PIB_GIT_MIRRORS=/mirrors', args)
        self.assertIn('PIB_PACKAGE_JOBS=3', args)
        self.assertIn('my-vol:/var/tmp/pib-package', args)
        for env, msg in (({'PIB_PKGBUILD_SRC': 'missing'}, 'PIB_PKGBUILD_SRC: missing is not a directory'),
                         ({'PIB_PKGBUILD_SRC': str(self.root / 'mirrors')}, 'has no pkgbuild/'),
                         ({'PIB_PACKAGE_VOLUME': '/abs/path'}, 'is not a Docker volume name')):
            r = self.run_pib('package', '--list', check=False, **env)
            self.assertEqual((r.returncode, r.stdout), (1, ''), r)
            self.assertIn(msg, r.stderr)

    def test_the_kernel_repository_is_read_only_and_whole(self):
        repo = self.root / 'simaai-linux'
        head = add_commit(repo, 'master', 'k')
        git('-C', str(repo), 'config', 'uploadpack.allowFilter', 'true')  # for the partial clone below
        (repo / 'f').write_text('changed, not committed')
        (repo / 'signing_key.pem').write_text('untracked: never mounted, not counted')
        args = self.run_pib('package', '-p', 'linux', PIB_KERNEL_SRC=str(repo),
                            PIB_KERNEL_REF='my-branch').stdout.splitlines()
        self.assertIn(f'{repo}/.git:/kernel-src:ro', args, 'its git directory, not the working tree')
        self.assertFalse(any(a.startswith(f'{repo}:') for a in args))
        self.assertIn('PIB_KERNEL_SRC=/kernel-src', args)
        self.assertIn('PIB_KERNEL_REF=my-branch', args)
        self.assertIn(f'PIB_KERNEL_SRC_HEAD={head}', args, 'counted on the host')
        self.assertIn('PIB_KERNEL_SRC_CHANGES=1', args)
        bare = self.root / 'bare.git'
        git('clone', '-q', '--bare', str(repo), str(bare))
        args = self.run_pib('package', '-p', 'linux', PIB_KERNEL_SRC=str(bare)).stdout.splitlines()
        self.assertIn(f'{bare}:/kernel-src:ro', args)
        self.assertFalse(any(a.startswith('PIB_KERNEL_SRC_') for a in args), 'a bare one has no changes')
        args = self.run_pib('package', '-p', 'linux',
                            PIB_KERNEL_URL='https://github.com/me/simaai-linux.git').stdout.splitlines()
        self.assertIn('PIB_KERNEL_URL=https://github.com/me/simaai-linux.git', args)
        self.assertFalse(any('/kernel-src' in a for a in args))
        git('-C', str(repo), 'worktree', 'add', '-q', str(self.root / 'wt'))
        borrower = self.root / 'borrower'
        git('clone', '-q', '--shared', str(repo), str(borrower))
        partial = self.root / 'partial'
        git('clone', '-q', '--filter=blob:none', 'file://' + str(repo), str(partial))
        creds = self.root / 'creds'
        git('clone', '-q', str(repo), str(creds))
        git('-C', str(creds), 'remote', 'set-url', 'origin', 'https://me:s3cr3t@example.com/linux.git')
        linked = self.root / 'linked'
        linked.mkdir()
        (linked / '.git').symlink_to(repo / '.git')
        (self.root / 'plain').mkdir()
        for path, msg in ((self.root / 'wt', 'is not a directory (a worktree'),
                          (linked, 'is not a directory (a worktree'),
                          (borrower, 'borrows objects from another repository'),
                          (partial, 'is a partial clone'),
                          (creds, 'holds credentials'),
                          (self.root / 'plain', 'is not a git repository'),
                          (self.root / 'missing', 'is not a directory')):
            r = self.run_pib('package', '-p', 'linux', check=False, PIB_KERNEL_SRC=str(path))
            self.assertEqual((r.returncode, r.stdout), (1, ''), r)
            self.assertIn(msg, r.stderr)
            self.assertNotIn('s3cr3t', r.stderr)
        for env, msg in (({'PIB_KERNEL_URL': 'https://me:s3cr3t@github.com/me/x.git'}, 'PIB_KERNEL_URL must'),
                         ({'PIB_KERNEL_URL': 'https://github.com/me/${oc.env:HOME}.git'}, 'PIB_KERNEL_URL must'),
                         ({'PIB_KERNEL_REF': 'a b'}, 'PIB_KERNEL_REF must')):
            r = self.run_pib('package', '-p', 'linux', check=False, **env)
            self.assertEqual((r.returncode, r.stdout), (1, ''), r)
            self.assertIn(msg, r.stderr)
            self.assertNotIn('s3cr3t', r.stderr, 'the token is never echoed')
        # PIB_CONFIGS mounts its parent directory: never for pib package, which must not see the keys
        (self.ws / 'configs').mkdir()
        args = self.run_pib('package', '-p', 'linux', PIB_CONFIGS=str(self.ws / 'configs')).stdout.splitlines()
        self.assertFalse(any(':/pib-src' in a or a.startswith('PIB_CONFIGS=') for a in args), args)
        args = self.run_pib('init', 'x', PIB_CONFIGS=str(self.ws / 'configs')).stdout.splitlines()
        self.assertIn(f'{self.ws}:/pib-src:ro', args, 'other verbs keep it')

    def test_signing_material_never_reaches_sbp(self):
        args = self.run_pib('package', '--list', SWU_SIGNING_KEY=str(self.ws / 'keys/swu-signing.key'),
                            PIB_CREDENTIALS=str(self.ws / 'keys/ca.key'), SSH_AUTH_SOCK=str(self.root / 'agent')).stdout.splitlines()
        self.assertFalse(any(a.startswith(('SWU_', 'PIB_CREDENTIALS', 'SSH_AUTH_SOCK')) or ':/keys/' in a
                             for a in args), args)


class Layout(unittest.TestCase):
    """One image: PIB with pib package's tools and sbp; sbp's settings never become image ENV."""

    def test_dockerfile_stages(self):
        text = (ROOT / 'Dockerfile').read_text()
        stages = re.findall(r'^FROM\s+(\S+)(?:\s+AS\s+(\S+))?', text, re.M)
        self.assertEqual(stages[0][1], 'pib-deps')
        self.assertEqual(stages[1:], [('pib-deps', 'pib-package-tools'), ('pib-package-tools', 'pib')])
        self.assertEqual(stages[-1][1], 'pib', 'a plain build must give PIB, with the package tools')
        # The per-commit build identity comes last, so the dependency and toolchain layers before
        # it are cached across commits.
        body = dict(zip([s[1] for s in stages], re.split(r'^FROM\s+.*$', text, flags=re.M)[1:]))
        identity = re.compile(r'PIB_VERSION|PIB_GIT_SHA|PIB_DEFAULT_IMAGE')
        for stage in ('pib-deps', 'pib-package-tools'):
            self.assertNotRegex(body[stage], identity, stage)
        self.assertRegex(body['pib'], identity)
        # pib package's toolchain is installed before every per-commit input, so its large layer
        # stays cached across commits and image updates do not download it again.
        deps = body['pib-deps']
        toolchain = deps.index('gcc-aarch64-linux-gnu')
        for per_commit in ('COPY RELEASE', '--mount=type=bind,source=deps', '--mount=type=bind,source=pib'):
            self.assertLess(toolchain, deps.index(per_commit), per_commit)
        self.assertNotIn('apt-get', body['pib-package-tools'])
        # Every PIB image runs pib package: no marker tells one image from another.
        for path in (ROOT / 'Dockerfile', Path(sbp.__file__)):
            self.assertNotIn('/etc/pib-sbp', path.read_text(), path)
        env = ' '.join(re.findall(r'^ENV\s+(.*(?:\\\n.*)*)', text, re.M))
        for name in ('BUILD', 'BUILD_TYPE', 'KEY_PATH', 'REPO', 'REPO_ROOT', 'REPO_PUSH', 'REPO_PULL', 'DAILY_MIRROR'):
            self.assertNotRegex(env, rf'(^|\s){name}=', f'{name} would leak into pib build')
        self.assertIn('!sbp/', (ROOT / '.dockerignore').read_text().splitlines())

    def test_sbp_comes_with_the_pinned_commit(self):
        """pib-package-tools fetches sbp and its package configs from the commit deps/artifacts.json
        pins, into the tree pib package and the sbp wrapper look in, and checks them and the tools;
        PIB's own image configs, which pib init copies into workspaces, never hold configs/packages."""
        text = (ROOT / 'Dockerfile').read_text()
        names = [m[1] for m in re.findall(r'^FROM\s+(\S+)(?:\s+AS\s+(\S+))?', text, re.M)]
        body = dict(zip(names, re.split(r'^FROM\s+.*$', text, flags=re.M)[1:]))
        tools = body['pib-package-tools']
        self.assertIn(f'python3 /tmp/deps/fetch-artifacts.py --sbp {sbp.BAKED_SRC}\n', tools)
        # The entrypoint runs pib package's set-up only when it is there, so the image must have it
        # where the entrypoint looks.
        self.assertIn('COPY --chmod=755 sbp/setup.sh /usr/local/lib/pib/sbp-setup\n', tools)
        self.assertIn('[ -x /usr/local/lib/pib/sbp-setup ]', (ROOT / 'entrypoint.sh').read_text())
        self.assertIn('COPY --chmod=755 sbp/sbp /usr/local/bin/sbp\n', tools)
        self.assertIn('command -v "$tool"', tools, 'the tools pib package builds with are checked')
        check = tools.split(f'if [ -d {sbp.BAKED_SRC} ]; then', 1)
        self.assertEqual(len(check), 2, 'the fetched sbp is checked')
        self.assertIn('sbp --help', check[1], 'it must start')
        self.assertIn('pkgutil.walk_packages(sbp.__path__', check[1], 'and all of its modules must import')
        self.assertNotIn('--sbp', body['pib-deps'])
        self.assertIn('rm -rf /tmp/pib-artifacts /usr/share/pib/configs/packages', body['pib-deps'])
        self.assertIn(f'src="${{PIB_PKGBUILD_SRC:-{sbp.BAKED_SRC}}}"', (ROOT / 'sbp/sbp').read_text())
        fetcher = script(ROOT / 'deps/fetch-artifacts.py')
        self.assertEqual(fetcher.SBP_FILES, sbp.SBP_FILES, 'what the fetch checks is what pib package needs')
        self.assertIn(f'for part in {fetcher.SBP_PARTS!r}:', (ROOT / 'host/pib').read_text(),
                      'PIB_PKGBUILD_SRC mounts the same two parts')
        # run-unit-tests.sh copies the image's configs here: PIB's image has none to copy
        self.assertFalse((ROOT / 'configs/packages').exists())

    def test_launcher_has_no_unpublished_default(self):
        text = (ROOT / 'host/pib').read_text()
        # the Dockerfile rewrites the default tag in the launcher it ships: only DEFAULT_IMAGE has it
        sed = re.search(r's\|(ghcr\.io/[^|]+)\|\$\{PIB_DEFAULT_IMAGE\}\|g', (ROOT / 'Dockerfile').read_text())
        self.assertEqual(sed[1], 'ghcr.io/sima-neat/palette-image-builder:latest')
        self.assertEqual(text.count(sed[1]), 1)

    def test_setup_keeps_sbp_away_from_pib_builds_repo(self):
        setup = (ROOT / 'sbp/setup.sh').read_text()
        # sbp's work and repo go on the volume, which the launcher mounts here
        self.assertRegex(setup, r'(?m)^export SBP_WORKSPACE=/var/tmp/pib-package$')
        self.assertIn('export REPO_ROOT=/var/tmp/pib-package/repo/', setup)
        self.assertRegex(setup, r'(?m)^export REPO_PUSH=http://localhost\s')
        self.assertRegex(setup, r'(?m)^export BUILD_TYPE=custom\s')
        self.assertIn('rm -f /etc/nginx/sites-enabled/*', setup)
        pins = json.loads((ROOT / 'sbp/sources.json').read_text())
        kernel = pins['packages']['linux-modalix']
        self.assertEqual(kernel, {'config': 'kernel/linux.yaml', 'url': 'https://github.com/SiMa-ai/simaai-linux.git',
                                  'branch': 'master'}, 'the public repository, its branch followed')
        self.assertRegex(pins['packages']['lttng-modules-modalix']['commit-id'], r'^[0-9a-f]{40}$')
        self.assertIn(f'export PIB_KERNEL_SRC_URL={LOCAL_URL}\n', setup)
        self.assertRegex(setup, r'(?m)^export GIT_TERMINAL_PROMPT=0$')
        # the launcher checks PIB_KERNEL_URL and _REF as pib package does
        launcher = (ROOT / 'host/pib').read_text()
        self.assertIn(f"HTTPS_URL = re.compile(r'{sbp.HTTPS_URL.pattern}')", launcher)
        self.assertEqual(pins['codename'], (ROOT / 'CODENAME').read_text().strip())
        self.assertEqual(pins['release'], (ROOT / 'RELEASE').read_text().strip(), 'update with RELEASE')
        self.assertIn('sbp/sources.json', (ROOT / 'README.md').read_text())


class GitMirrors(unittest.TestCase):
    """setup.sh's git block: Bitbucket URLs reach the mirrors, and the kernel's placeholder URL the
    user's kernel repository, also when another user owns them; a Bitbucket repository without a
    mirror fails locally; GitHub URLs are never rewritten, even with a mirror of that name."""

    def test_clone_through_a_mirror_and_from_the_users_kernel(self):
        setup = (ROOT / 'sbp/setup.sh').read_text()
        block = setup[setup.index('# --- git:'):setup.index('cd /workspace')]
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            env = {'PATH': os.environ['PATH'], 'HOME': str(t), 'GIT_CONFIG_GLOBAL': '/dev/null',
                   'GIT_CONFIG_SYSTEM': str(t / 'gitconfig'), 'PIB_GIT_MIRRORS': str(t / 'mirrors'),
                   'PIB_KERNEL_SRC': str(t / 'linux/.git'),  # the launcher mounts the git directory
                   'GIT_ALLOW_PROTOCOL': 'file', 'GIT_TERMINAL_PROMPT': '0'}  # a broken map fails, offline
            git = lambda *a, **k: subprocess.run(['git', *a], env=env, check=True, capture_output=True, **k)  # noqa: E731
            git('init', '-q', '-b', 'master', str(t / 'work'))
            (t / 'work/f').write_text('x')
            git('-C', str(t / 'work'), 'add', 'f')
            git('-C', str(t / 'work'), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-m', 'm')
            git('clone', '-q', '--mirror', str(t / 'work'), str(t / 'mirrors/demo.git'))
            git('clone', '-q', '--mirror', str(t / 'work'), str(t / 'mirrors/simaai-linux.git'))
            git('clone', '-q', '-b', 'master', str(t / 'work'), str(t / 'linux'))   # the user's kernel
            git('-C', str(t / 'linux'), 'checkout', '-q', '-b', 'mine')
            (t / 'linux/f').write_text('mine')
            git('-C', str(t / 'linux'), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit', '-q', '-am', 'mine')
            if os.getuid() == 0:  # root reading repositories the host user owns, as in the container
                for top in (t / 'mirrors', t / 'linux'):
                    for p in [top, *top.rglob('*')]:
                        os.chown(p, 1000, 1000)
            r = subprocess.run(['bash', '-c', 'set -euo pipefail\ndie() { echo "$*" >&2; exit 1; }\n' + block +
                                '\necho "$PIB_KERNEL_SRC_URL"'], env=env, check=True, capture_output=True, text=True)
            self.assertEqual(r.stdout.strip(), LOCAL_URL, 'pib package reads the placeholder from the environment')
            for url in ('ssh://git@ssh.bitbucket.org/sima-ai/demo.git', 'git@bitbucket.org:sima-ai/demo.git'):
                dest = t / ('clone-' + str(abs(hash(url))))
                git('clone', '-q', '-b', 'master', url, str(dest))  # as sbp's Fetch runs it
                self.assertEqual((dest / 'f').read_text(), 'x')
            git('clone', '-q', '-b', 'mine', LOCAL_URL, str(t / 'clone-kernel'))
            self.assertEqual((t / 'clone-kernel/f').read_text(), 'mine')
            # pib package's own look at it: as root on a repository another user owns, in the container
            with patch.dict(os.environ, {k: env[k] for k in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM')}):
                kernel = env['PIB_KERNEL_SRC']
                self.assertEqual(sbp.head_branch(kernel, 'K'), 'mine')
                tip = sbp.resolve_in(kernel, 'K', 'mine', 'master')[1]
                self.assertEqual(sbp.resolve_in(kernel, 'K', tip, 'master'), ('mine', tip))
                self.assertEqual(sbp.branch_tip(LOCAL_URL, 'mine'), tip)
                self.assertEqual(sbp.default_branch(LOCAL_URL), 'mine')
            self.assertIn('master', git('ls-remote', 'ssh://git@ssh.bitbucket.org/sima-ai/demo.git',
                                        text=True).stdout)
            get_url = lambda u: git('ls-remote', '--get-url', u, text=True).stdout.strip()  # noqa: E731
            for form in ('ssh://git@ssh.bitbucket.org/sima-ai/', 'ssh://git@bitbucket.org/sima-ai/',
                         'git@bitbucket.org:sima-ai/', 'https://bitbucket.org/sima-ai/'):
                self.assertEqual(get_url(form + 'demo.git'), str(t / 'mirrors/demo.git'), form)
            self.assertEqual(get_url('ssh://git@ssh.bitbucket.org/sima-ai/other.git'), str(t / 'mirrors/other.git'))
            for url in ('https://github.com/SiMa-ai/simaai-linux.git', 'https://github.com/SiMa-ai/other.git',
                        'git@github.com:SiMa-ai/simaai-linux.git', 'ssh://git@github.com/SiMa-ai/simaai-linux.git'):
                self.assertEqual(get_url(url), url, 'GitHub is never rewritten')
            self.assertEqual(get_url(LOCAL_URL), str(t / 'linux/.git'))


class Parsing(unittest.TestCase):
    def test_packages_map_to_components(self):
        a = sbp.parse(['-p', 'linux,smifb-modalix,lttng-modules'])
        self.assertEqual((a.picked, a.list), (['linux', 'smifb', 'lttng'], False))
        self.assertEqual(sbp.parse(['-p', 'kernel,linux']).picked, ['linux'])
        a = sbp.parse(['--list', '--debug'])
        self.assertEqual((a.list, a.debug), (True, True))

    def test_refusals(self):
        for argv, msg in ((['-p', 'linux+'], "'+'"),
                          (['-p', 'u-boot'], 'not \'u-boot\''),
                          (['-p', 'linux', '-g', 'frequent'], 'always builds with -g all'),
                          (['-p', 'linux', '--kernel-ref', 'a b'], 'is not a branch name'),
                          (['-p', 'linux', '--kernel-ref=-x'], 'is not a branch name'),
                          (['-p', 'smifb', '-t', 'build+'], '-t is for the kernel'),
                          (['-p', 'smifb', '--kernel-ref', 'x'], '--kernel-ref is for the kernel'),
                          (['-p', 'lttng', '--kernel-url', 'https://h/x.git'], '--kernel-url is for the kernel'),
                          # --list builds nothing: the build options do not apply
                          (['--list', '-t', 'clean+'], '-t is for a build (-p), not --list'),
                          (['--list', '--dry-run'], '--dry-run is for a build (-p), not --list'),
                          (['--list', '--kernel-ref', 'x'], '--kernel-ref is for a build (-p), not --list')):
            with self.assertRaises(SystemExit) as e:
                sbp.parse(argv)
            self.assertIn(msg, str(e.exception.code), argv)
        # neither -p nor --list, or both: a usage error
        for argv, msg in (([], 'one of the arguments -p/--packages --list is required'),
                          (['list'], 'one of the arguments -p/--packages --list is required'),
                          (['--list', '-p', 'linux'], 'not allowed with')):
            with self.assertRaises(SystemExit) as e, patch('sys.stderr', new_callable=io.StringIO) as err:
                sbp.parse(argv)
            self.assertEqual(e.exception.code, 2, argv)
            self.assertIn(msg, err.getvalue(), argv)
        for url in ('http://github.com/me/simaai-linux.git', 'git@github.com:me/simaai-linux.git',
                    'ssh://git@github.com/me/simaai-linux.git', 'https://me:token@github.com/me/simaai-linux.git',
                    'https://github.com', 'https://github.com/', 'https://github.com/me/x y.git',
                    '/home/me/simaai-linux', 'ssh://github.com/me/x.git', 'file:///home/me/linux',
                    'https://github.com/me/${oc.env:HOME}.git', 'https://github.com/me/x.git?token=t'):
            with self.assertRaises(SystemExit) as e:
                sbp.parse(['-p', 'linux', '--kernel-url', url])
            self.assertIn('must be the https URL of a git repository', str(e.exception.code), url)
            self.assertNotIn('token', str(e.exception.code).replace('or token', ''), 'never echoed')
        for argv in (['--help'], ['-h'], ['-p', 'linux', '-h'], ['--list', '--help']):  # the full text
            with self.assertRaises(SystemExit) as e, patch('builtins.print') as out:
                sbp.parse(argv)
            self.assertEqual(e.exception.code, 0, argv)
            self.assertIn('PIB_KERNEL_SRC', out.call_args.args[0])
            self.assertNotRegex(out.call_args.args[0], r'pib[ -]sbp|PIB_SBP_|-sbp\b', 'no separate image any more')
        self.assertRegex(cli.parser().format_help(), r'\bpackage\s+build\s+SiMa\.ai\s+packages', 'pib --help lists it')
        a = sbp.parse(['-p', 'linux', '--kernel-url', 'https://github.com/me/simaai-linux.git',
                       '--kernel-ref', 'feature/isp-fix'])
        self.assertEqual((a.kernel_url, a.kernel_ref), ('https://github.com/me/simaai-linux.git', 'feature/isp-fix'))


class Pieces(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_source_pins_like_change_branch(self):
        f = self.root / 'linux.yaml'
        f.write_text(LINUX_YAML)
        sbp.set_source(f, 'linux-modalix', 'modalix', 'master', 'af18d01975c6bd1ec1f36082cf962717145ed152')
        text = f.read_text()
        self.assertIn('  branch: master\n  commit-id: af18d01975c6bd1ec1f36082cf962717145ed152\n  patches:', text)
        self.assertEqual(text.replace('  commit-id: af18d01975c6bd1ec1f36082cf962717145ed152\n', '')
                         .replace('branch: master', 'branch: develop'), LINUX_YAML)
        sbp.set_source(f, 'linux-modalix', 'modalix', 'develop', None)  # a branch: the commit goes
        self.assertEqual(f.read_text(), LINUX_YAML)
        with self.assertRaises(SystemExit):
            sbp.set_source(f, 'lttng-modules-modalix', 'modalix', 'master', None)  # the wrong file
        # another repository, and branch names YAML would read as a number or a boolean
        for branch, line in (('1.10', '  branch: "1.10"\n'), ('no', '  branch: "no"\n'),
                             ('1e5', '  branch: "1e5"\n'),  # a string to PyYAML, a float to OmegaConf
                             ('feature/isp', '  branch: feature/isp\n')):
            sbp.set_source(f, 'linux-modalix', 'modalix', branch, 'f' * 40, 'https://github.com/me/simaai-linux.git')
            text = f.read_text()
            self.assertIn(line + '  commit-id: ' + 'f' * 40 + '\n', text)
            self.assertIn('  url: https://github.com/me/simaai-linux.git\n', text)
            self.assertEqual((cli.read_yaml(f)['options']['branch'], cli.read_yaml(f)['options']['url']),
                             (branch, 'https://github.com/me/simaai-linux.git'))
        self.assertEqual(text.count('url:'), 1)
        self.assertIn("'$'", dies(sbp.set_source, f, 'linux-modalix', 'modalix', 'x${oc.env:HOME}', None))

    def test_kernel_build_numbers_never_go_back(self):
        idx = [{'Package': 'linux-image-6.18.3-modalix', 'Version': '6.18.3-7'},
               {'Package': 'linux-headers-6.18.3-modalix', 'Version': '6.18.3-9'},
               {'Package': 'linux-image-6.18.3-other', 'Version': '6.18.3-99'}]
        self.assertEqual(sbp.next_kernel_build(idx, 'modalix'), 8)
        self.assertEqual(sbp.next_kernel_build([], 'modalix'), 1)

    def test_kernel_glob_and_selection(self):
        ws = workspace(self.root)
        self.assertEqual(sbp.kernel_glob(ws, 'modalix'), 'linux-image-6.18.3-modalix*')
        k = {'Package': 'linux-image-6.18.3-modalix', 'Version': '6.18.3-2'}
        idx = [k, {'Package': 'linux-headers-6.18.3-modalix', 'Version': '6.18.3-2'},
               {'Package': 'linux-libc-dev', 'Version': '6.18.3-2'},
               {'Package': 'linux-image-6.18.3-modalix-dbg', 'Version': '6.18.3-2'},
               {'Package': 'smifb-modalix', 'Version': '4.6.0'}, {'Package': 'u-boot-modalix', 'Version': '1'}]
        self.assertEqual([f['Package'] for f in sbp.wanted(idx, ['linux'], 'modalix', k)],
                         ['linux-image-6.18.3-modalix', 'linux-headers-6.18.3-modalix', 'linux-libc-dev'])
        self.assertEqual([f['Package'] for f in sbp.wanted(idx, ['smifb'], 'modalix', k)], ['smifb-modalix'])
        with self.assertRaises(SystemExit) as e:
            sbp.built_kernel([{'Package': 'linux-image-6.19.0-modalix', 'Version': '6.19.0-1'}], ws, 'modalix')
        self.assertIn('would be left out of the image', str(e.exception.code))

    def test_root_ownership_is_required(self):
        good = deb(self.root / 'good.deb', 'p', '1')
        sbp.root_owned(good)
        bad = deb(self.root / 'bad.deb', 'p', '1', owner=1000)
        if 'root/root' not in cli.run(['dpkg-deb', '-c', bad]):
            with self.assertRaises(SystemExit) as e:
                sbp.root_owned(bad)
            self.assertIn('not owned by root', str(e.exception.code))

    def test_fit_key_comes_from_pib_keys_fit(self):
        out = self.root / 'keys'
        with patch('sys.stdout'):
            cli.cmd_keys_fit(cli.parser().parse_args(['keys', 'fit', '--out', str(out)]))
        self.assertEqual(oct((out / 'fit-signing.key').stat().st_mode & 0o777), '0o600')
        self.assertIn('Public-Key: (2048 bit)', cli.run(['openssl', 'x509', '-in', out / 'fit-signing.crt', '-noout', '-text']))
        self.assertIn('refusing to overwrite', dies(cli.gen_fit_key, out))
        ws = self.root / 'ws'
        (ws / 'keys').mkdir(parents=True)
        with patch.object(sbp, 'work', return_value=self.root / 'vol'):
            self.assertIn('run pib keys fit', dies(sbp.fit_key, ws))
            for name in ('fit-signing.key', 'fit-signing.crt'):
                shutil.copy(out / name, ws / 'keys' / name)
            env = sbp.fit_key(ws)
            self.assertEqual(env['FIT_SIGN_KEYNAME'], 'pib')
            self.assertEqual(Path(env['FIT_SIGN_KEYDIR'], 'pib.key').resolve(), (ws / 'keys/fit-signing.key').resolve())
            cli.run(['openssl', 'req', '-batch', '-new', '-x509', '-newkey', 'rsa:2048', '-nodes',
                     '-keyout', self.root / 'other.key', '-subj', '/CN=o', '-out', ws / 'keys/fit-signing.crt'])
            self.assertIn('is not the certificate of', dies(sbp.fit_key, ws))

    def test_check_mirror(self):
        """SiMa.ai's Bitbucket repositories come from a mirror or not at all, decided before
        anything asks Bitbucket; other URLs are not its business."""
        work = self.root / 'work'
        add_commit(work, 'master', 'x')
        mirrors = self.root / 'mirrors'
        git('clone', '-q', '--mirror', str(work), str(mirrors / 'simaai-linux.git'))
        setup = (ROOT / 'sbp/setup.sh').read_text()
        block = setup[setup.index('# --- git:'):setup.index('cd /workspace')]

        def mapped(directory):
            """os.environ as in the container: setup.sh's git config for this mirrors directory."""
            conf = self.root / f'gitconfig-{abs(hash(str(directory)))}'
            env = {'PATH': os.environ['PATH'], 'HOME': str(self.root), 'GIT_CONFIG_GLOBAL': '/dev/null',
                   'GIT_CONFIG_SYSTEM': str(conf), 'PIB_GIT_MIRRORS': str(directory)}
            subprocess.run(['bash', '-c', 'set -euo pipefail\ndie() { echo "$*" >&2; exit 1; }\n' + block],
                           env=env, check=True, capture_output=True)
            return {k: env[k] for k in ('GIT_CONFIG_GLOBAL', 'GIT_CONFIG_SYSTEM', 'PIB_GIT_MIRRORS')}

        bb = 'ssh://git@ssh.bitbucket.org/sima-ai/simaai-linux.git'
        with patch.dict(os.environ, mapped(mirrors)):
            self.assertEqual(sbp.check_mirror(bb), str(mirrors / 'simaai-linux.git'))
            self.assertEqual(sbp.check_mirror('https://bitbucket.org/sima-ai/simaai-linux.git'),
                             str(mirrors / 'simaai-linux.git'))
            self.assertIsNone(sbp.check_mirror('https://github.com/SiMa-ai/simaai-linux.git'), 'never mirrored')
        (self.root / 'empty').mkdir()
        with patch.dict(os.environ, mapped(self.root / 'empty')):
            self.assertIn('no mirror simaai-linux.git', dies(sbp.check_mirror, bb))
        with patch.dict(os.environ, {'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_CONFIG_SYSTEM': '/dev/null'}):
            os.environ.pop('PIB_GIT_MIRRORS', None)
            self.assertIn('is private', dies(sbp.check_mirror, bb))
            self.assertIn('with .git', dies(sbp.check_mirror, bb[:-4]))
            self.assertIsNone(sbp.check_mirror(KERNEL_URL))

    def test_resolve_in(self):
        """A branch resolves to its tip; a commit must be on a branch or tag, and goes with the
        preferred branch when that holds it, else with a branch that does."""
        repo = self.root / 'repo'
        base = add_commit(repo, 'master', 'a')
        mine = add_commit(repo, 'mine', 'b')
        git('-C', str(repo), 'checkout', '-q', 'master')
        tagged = git('-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit-tree', '-m', 't',
                     f'{base}^{{tree}}')
        git('-C', str(repo), 'tag', 'v1', tagged)
        orphan = git('-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit-tree', '-m', 'o',
                     f'{base}^{{tree}}')
        r = lambda ref, preferred='master': sbp.resolve_in(repo, 'R', ref, preferred, ' (hint)')  # noqa: E731
        self.assertEqual(r('mine'), ('mine', mine))
        self.assertEqual(r(base), ('master', base), 'the preferred branch holds it')
        self.assertEqual(r(mine), ('mine', mine), 'master does not: a branch that does')
        self.assertEqual(r(base, 'mine'), ('mine', base))
        self.assertEqual(r(tagged), ('master', tagged), 'on a tag only: any branch carries the clone')
        self.assertIn('is on no branch or tag of R', dies(r, orphan))
        self.assertIn('R has no commit ' + 'e' * 40, dies(r, 'e' * 40))
        self.assertIn('R has no branch nope (hint)', dies(r, 'nope'))
        self.assertIn('R has no branch abc1234', dies(r, 'abc1234'), 'a short commit is not one')
        self.assertIn('cannot read R', dies(sbp.resolve_in, self.root / 'nothing', 'R', base, 'master'))
        self.assertIn('cannot read R', dies(sbp.head_branch, self.root / 'nothing', 'R'))
        git('-C', str(repo), 'tag', 'mine')                      # a tag named like the branch
        git('-C', str(repo), 'checkout', '-q', 'mine')
        self.assertEqual(sbp.head_branch(repo, 'R'), 'mine', 'not heads/mine')
        git('-C', str(repo), 'checkout', '-q', '--detach')
        self.assertIsNone(sbp.head_branch(repo, 'R'))

    def test_ask_remote(self):
        """A dry run asks the remote instead of fetching it."""
        repo = self.root / 'srv'
        first = add_commit(repo, 'master', 'a')
        dev = add_commit(repo, 'feature/x', 'b')
        git('-C', str(repo), 'checkout', '-q', 'master')
        url = 'file://' + str(repo)
        self.assertEqual(sbp.ask_remote(url, 'feature/x', 'master'), ('feature/x', dev))
        self.assertIn('has no branch nope', dies(sbp.ask_remote, url, 'nope', 'master'))
        self.assertEqual(sbp.ask_remote(url, first, 'main'), ('master', first), "the remote's default branch")
        asked = []
        with patch.object(sbp, 'GITHUB', re.compile('file:')), \
                patch.object(sbp, 'remote_lacks', lambda u, b, c: asked.append((b, c)) or (None if c == first else f'commit {c}')):
            self.assertEqual(sbp.ask_remote(url, first, 'main'), ('master', first))
            self.assertIn(f'has no commit {"f" * 40}', dies(sbp.ask_remote, url, 'f' * 40, 'main'))
        self.assertEqual(asked, [('master', first), ('master', 'f' * 40)], 'GitHub is asked for the commit')
        git('-C', str(repo), 'symbolic-ref', 'HEAD', 'refs/heads/gone')   # an unborn default branch
        self.assertIn('has no branch main to clone commit', dies(sbp.ask_remote, url, first, 'main'),
                      'the fallback branch must be there too')

    def test_branch_tip_and_default_branch(self):
        repo = self.root / 'srv'
        first = add_commit(repo, 'master', 'a')
        dev = add_commit(repo, 'feature/x', 'b')
        git('-C', str(repo), 'checkout', '-q', 'master')
        git('-C', str(repo), 'update-ref', 'refs/tags/refs/heads/x', dev)  # ls-remote tail-matches refs/heads/x
        url = 'file://' + str(repo)
        self.assertEqual(sbp.branch_tip(url, 'master'), first)
        self.assertEqual(sbp.branch_tip(url, 'feature/x'), dev)
        self.assertIsNone(sbp.branch_tip(url, 'x'), 'refs/tags/refs/heads/x is not branch x')
        self.assertIsNone(sbp.branch_tip(url, 'nope'))
        self.assertEqual(sbp.default_branch(url), 'master')
        self.assertEqual(add_commit(repo, 'master', 'c'), sbp.branch_tip(url, 'master'), 'the tip of the moment')
        self.assertIn('could not reach', dies(sbp.branch_tip, 'file://' + str(self.root / 'nothing'), 'master'))
        # a server's HEAD name goes into sbp's config only if it is a plain branch name
        with patch.object(sbp, 'ask_git', return_value=(0, 'ref: refs/heads/${oc.env:X}\tHEAD\n' + first + '\tHEAD\n')):
            self.assertIsNone(sbp.default_branch(url))

    def test_remote_lacks(self):
        """GitHub is asked without a clone: its refs, then the one pinned commit (here a local
        'server' that, like GitHub, serves reachable commits by id)."""
        work = self.root / 'srv.git'
        head = add_commit(self.root / 'w', 'master', 'x')
        git('clone', '-q', '--bare', str(self.root / 'w'), str(work))
        for key in ('uploadpack.allowFilter', 'uploadpack.allowReachableSHA1InWant'):
            git('-C', str(work), 'config', key, 'true')
        url = 'file://' + str(work)
        self.assertIsNone(sbp.remote_lacks(url, 'master', head))
        self.assertIsNone(sbp.remote_lacks(url, 'master', None))
        self.assertEqual(sbp.remote_lacks(url, 'master', 'f' * 40), 'commit ' + 'f' * 40)
        self.assertEqual(sbp.remote_lacks(url, 'develop', head), 'branch develop')
        self.assertIn('could not reach', dies(sbp.remote_lacks, 'file://' + str(self.root / 'nothing'), 'master', head))

    def test_jobs(self):
        with patch.dict(os.environ, {'PIB_PACKAGE_JOBS': '3'}):
            self.assertEqual(sbp.jobs(), 3)
        with patch.dict(os.environ, {'PIB_PACKAGE_JOBS': 'x'}), self.assertRaises(SystemExit):
            sbp.jobs()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('PIB_PACKAGE_JOBS', None)
            self.assertGreaterEqual(sbp.jobs(), 1)


class Orchestration(unittest.TestCase):
    """cmd_package end to end with the stand-in sbp."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.base = base
        self.src = fake_tree(base)
        (base / 'bin').mkdir()
        (base / 'bin/sbp').write_text(FAKE_SBP)
        (base / 'bin/sbp').chmod(0o755)
        (base / 'bin/reprepro').write_text(FAKE_REPREPRO)
        (base / 'bin/reprepro').chmod(0o755)
        (base / 'sources.json').write_text(json.dumps(SOURCES))
        (base / 'release').write_text('3.0.0\n')
        (base / 'codename').write_text('agate\n')
        self.log = base / 'sbp.log'
        # SiMa.ai's kernel repository, as git sees it in the container: KERNEL_URL mapped to a
        # local stand-in with the branches master and develop.
        self.kernel = base / 'simaai-linux'
        self.tips = {b: add_commit(self.kernel, b, b) for b in ('master', 'develop')}
        git('-C', str(self.kernel), 'checkout', '-q', 'master')
        self.gitconfig = base / 'gitconfig'
        url_map(self.gitconfig, KERNEL_URL, self.kernel)
        self.env = {'PATH': f'{base}/bin:{os.environ["PATH"]}', 'PIB_PKGBUILD_SRC': str(self.src),
                    'SBP_WORKSPACE': str(base / 'vol'), 'REPO_ROOT': str(base / 'vol/repo') + '/',
                    'BUILD_TYPE': 'custom', 'PIB_PACKAGE_JOBS': '2', 'FAKE_SBP_LOG': str(self.log),
                    'GIT_CONFIG_SYSTEM': str(self.gitconfig), 'GIT_CONFIG_GLOBAL': '/dev/null',
                    'PIB_KERNEL_SRC_URL': LOCAL_URL, 'PIB_PACKAGE_SETUP': '1'}
        self.patches = [patch.dict(os.environ, self.env),
                        patch.object(sbp, 'SOURCES', base / 'sources.json'),
                        patch.object(sbp, 'BAKED_SRC', base / 'baked'),  # the image's own: none
                        patch.object(sbp, 'ARM64_LOADER', shutil.which('true')),
                        patch.object(cli, 'RELEASE_FILE', base / 'release'),
                        patch.object(cli, 'CODENAME_FILE', base / 'codename'),
                        patch.object(cli, 'release_deb', side_effect=SystemExit('offline'))]
        for p in self.patches:
            p.start()
        # nothing from the developer's environment: sbp's settings come from setup.sh in the container
        for name in ('PIB_GIT_MIRRORS', 'PIB_KERNEL_SRC', 'PIB_KERNEL_URL', 'PIB_KERNEL_REF',
                     'PIB_KERNEL_SRC_HEAD', 'PIB_KERNEL_SRC_CHANGES', 'FAKE_NO_FIT', 'FAKE_UAPI',
                     'FAKE_SBP_FAIL', 'FAKE_KV', 'REPO', 'REPO_PUSH', 'REPO_PULL', 'FIT_SIGN_KEYDIR',
                     'FIT_SIGN_KEYNAME', 'BUILD', 'DAILY_MIRROR', 'KEY_PATH', 'GIT_CONFIG_COUNT'):
            os.environ.pop(name, None)
        self.cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self.cwd)
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def pib_package(self, ws, *argv):
        """pib package argv in ws: the sbp calls it made."""
        os.chdir(ws)
        before = self.log.read_text().splitlines() if self.log.exists() else []
        with patch('sys.stdout'):
            cli.main(['package', *argv])
        return [json.loads(ln) for ln in self.log.read_text().splitlines()[len(before):]]

    def printed(self, ws, *argv):
        """What pib package prints, and the sbp calls it made."""
        out = []
        os.chdir(ws)
        before = self.log.read_text().splitlines() if self.log.exists() else []
        with patch('builtins.print', side_effect=lambda *a, **k: out.append(' '.join(map(str, a)))):
            cli.main(['package', *argv])
        calls = [json.loads(ln) for ln in self.log.read_text().splitlines()[len(before):]] if self.log.exists() else []
        return out, calls

    def kernel_yaml(self):
        return (self.base / 'vol/tree/configs/packages/kernel/linux.yaml').read_text()

    @staticmethod
    def debs(ws):
        return sorted(p.name for p in (ws / 'custom-debs').glob('*.deb'))

    def test_refuses_to_run_without_its_setup(self):
        """Inside pib shell, or anywhere sbp/setup.sh did not run, sbp would use its own defaults and
        publish into PIB's own local repo: pib package stops before it reads a workspace or sbp."""
        ws = workspace(self.base)
        os.chdir(ws)
        with patch.dict(os.environ):
            del os.environ['PIB_PACKAGE_SETUP']
            for argv in (['-p', 'linux'], ['--list']):
                with self.assertRaisesRegex(SystemExit, 'needs its set-up'):
                    cli.main(['package', *argv])
        self.assertFalse(self.log.exists(), 'sbp must not run')
        self.assertIn('export PIB_PACKAGE_SETUP=1\n', (ROOT / 'sbp/setup.sh').read_text())

    def test_palette_kernel_then_modules_then_a_new_source(self):
        ws = workspace(self.base)
        deb(ws / 'custom-debs/linux-image-6.18.3-modalix_6.18.3-1_arm64.deb', 'linux-image-6.18.3-modalix', '6.18.3-1')
        (ws / 'custom-debs/linux-image-6.18.3-modalix_6.18.3-1_arm64.deb.sig').write_text('old')
        deb(ws / 'custom-debs/app_1_arm64.deb', 'app', '1')
        calls = self.pib_package(ws, '-p', 'linux')
        self.assertEqual([c['args'] for c in calls], [
            ['package', '-p', 'linux-modalix', '-g', 'all'],
            ['package', '-p', 'smifb-modalix,lttng-modules-modalix', '-t', 'clean+', '-g', 'all']])
        self.assertEqual(calls[0]['BUILD'], '1')
        self.assertEqual([c['REPO'] for c in calls], [None, 'http://localhost'], 'modules never pull a kernel in')
        self.assertEqual(calls[0]['jobs'], '2')
        self.assertEqual(calls[0]['keyname'], 'pib')
        self.assertEqual(calls[0]['src'], str(self.src))
        self.assertEqual(Path(calls[0]['cwd']), self.base / 'vol/tree')
        self.assertEqual(calls[0]['git_map'], [[f'url.{sbp.kernel_repo(KERNEL_URL)}.insteadOf', KERNEL_URL]],
                         "sbp clones the kernel from the volume's copy of its repository")
        self.assertEqual(calls[0]['pib_kernel_vars'], [], "pib's own kernel settings never reach sbp")
        tree_yaml = self.kernel_yaml()
        self.assertIn(f'branch: master\n  commit-id: {self.tips["master"]}\n', tree_yaml, 'the tip, looked up')
        self.assertIn(f'  url: {KERNEL_URL}\n', tree_yaml, "sources.json's repository, not the config's own")
        self.assertIn('commit-id: 5f23d6ea07a1b965c9f805c1dd5aab0a213b455b',
                      (self.base / 'vol/tree/configs/packages/lttng-modules/lttng-modules.yaml').read_text())
        self.assertEqual((self.src / 'configs/packages/kernel/linux.yaml').read_text(), LINUX_YAML, 'source untouched')
        first = self.debs(ws)
        self.assertEqual(first, ['app_1_arm64.deb', 'linux-headers-6.18.3-modalix_6.18.3-1_arm64.deb',
                                 'linux-image-6.18.3-modalix_6.18.3-1_arm64.deb', 'linux-libc-dev_6.18.3-1_arm64.deb',
                                 'lttng-modules-modalix_2.14-1~git202611190001-0_arm64.deb',
                                 'smifb-modalix_4.6.0~git202611190001-0_arm64.deb'])
        self.assertFalse((ws / 'custom-debs/linux-image-6.18.3-modalix_6.18.3-1_arm64.deb.sig').exists(), 'stale .sig')
        self.assertTrue((ws / 'keys/fit-signing.key').is_file())
        # nothing changed: the kernel run publishes nothing and the modules are current
        calls = self.pib_package(ws, '-p', 'linux')
        self.assertEqual([c['args'] for c in calls], [['package', '-p', 'linux-modalix', '-g', 'all']])
        self.assertEqual(self.debs(ws), first)
        # another kernel source: rebuilt from scratch with a higher build number, modules follow
        calls = self.pib_package(ws, '-p', 'linux', '--kernel-ref', 'develop')
        self.assertEqual(calls[0]['args'], ['package', '-p', 'linux-modalix', '-t', 'clean+', '-g', 'all'])
        self.assertEqual(calls[0]['BUILD'], '2')
        self.assertEqual(calls[1]['args'][2:4], ['smifb-modalix,lttng-modules-modalix', '-t'])
        self.assertIn(f'  branch: develop\n  commit-id: {self.tips["develop"]}\n  patches:', self.kernel_yaml())
        now = self.debs(ws)
        self.assertIn('linux-image-6.18.3-modalix_6.18.3-2_arm64.deb', now)
        self.assertEqual([n for n in now if n.startswith('linux-image-')], ['linux-image-6.18.3-modalix_6.18.3-2_arm64.deb'])
        self.assertEqual(len([n for n in now if n.startswith('smifb-')]), 1)
        # back to master: from scratch again, and the number still goes up
        calls = self.pib_package(ws, '-p', 'linux')
        self.assertEqual((calls[0]['args'][3:5], calls[0]['BUILD']), (['-t', 'clean+'], '3'))

    def test_a_branch_that_moved_is_rebuilt(self):
        ws = workspace(self.base)
        stamp = self.base / 'vol/stamps/linux-modalix'
        out, calls = self.printed(ws, '-p', 'linux')
        self.assertIn(f'pib: kernel: {KERNEL_URL} master @ {self.tips["master"]}', out)
        self.assertTrue(any('the whole repository this once' in o for o in out), out)
        out, calls = self.printed(ws, '-p', 'linux')
        self.assertEqual([c['args'] for c in calls], [['package', '-p', 'linux-modalix', '-g', 'all']], 'unmoved')
        self.assertTrue(any('fetching what is new' in o for o in out), 'the copy is kept: no new download')
        tip = add_commit(self.kernel, 'master', 'a new commit on master')
        out, calls = self.printed(ws, '-p', 'linux')
        self.assertIn(f'pib: kernel: {KERNEL_URL} master @ {tip}', out)
        self.assertEqual((calls[0]['args'][3:5], calls[0]['BUILD']), (['-t', 'clean+'], '2'), 'the new tip, from scratch')
        self.assertEqual(calls[1]['args'][2], 'smifb-modalix,lttng-modules-modalix', 'the modules follow')
        self.assertIn(f'commit-id: {tip}\n', self.kernel_yaml())
        self.assertTrue(stamp.read_text().startswith(tip + ' '))
        # a dry run looks the new tip up too, and changes nothing: not the stamp, not custom-debs/
        newest = add_commit(self.kernel, 'master', 'one more')
        out, calls = self.printed(ws, '-p', 'linux', '--dry-run')
        self.assertIn(f'pib: kernel: {KERNEL_URL} master @ {newest}', out)
        self.assertTrue(any('building it from scratch' in o for o in out), out)
        self.assertTrue(stamp.read_text().startswith(tip + ' '), 'a dry run stamps nothing')
        self.assertIn('linux-image-6.18.3-modalix_6.18.3-2_arm64.deb', self.debs(ws))
        calls = self.pib_package(ws, '-p', 'linux')
        self.assertEqual((calls[0]['args'][3:5], calls[0]['BUILD']), (['-t', 'clean+'], '3'))
        self.assertIn('linux-image-6.18.3-modalix_6.18.3-3_arm64.deb', self.debs(ws))
        # the same commit through another branch is not a new source: the branch only carries the clone
        git('-C', str(self.kernel), 'branch', 'other', newest)
        calls = self.pib_package(ws, '-p', 'linux', '--kernel-ref', 'other')
        self.assertNotIn('-t', calls[0]['args'])
        calls = self.pib_package(ws, '-p', 'linux', '--kernel-ref', newest)
        self.assertNotIn('-t', calls[0]['args'])

    def test_your_own_kernel_from_a_url_or_a_commit(self):
        ws = workspace(self.base, 'minimal')
        fork = self.base / 'fork'
        git('clone', '-q', str(self.kernel), str(fork))
        mine = add_commit(fork, 'mine', 'my change')
        git('-C', str(fork), 'checkout', '-q', 'master')       # its default branch
        url = 'https://github.com/me/simaai-linux.git'
        url_map(self.gitconfig, url, fork)
        with patch.dict(os.environ, {'PIB_KERNEL_URL': url, 'PIB_KERNEL_REF': 'mine'}):
            out, calls = self.printed(ws, '-p', 'linux')
            self.assertIn(f'pib: kernel: {url} mine @ {mine}', out)
            self.assertIn(f'  url: {url}\n  branch: mine\n  commit-id: {mine}\n', self.kernel_yaml())
            self.assertEqual(calls[0]['git_map'], [[f'url.{sbp.kernel_repo(url)}.insteadOf', url]])
            # the flags win over the variables
            out, calls = self.printed(ws, '-p', 'linux', '--kernel-url', KERNEL_URL,
                                      '--kernel-ref', 'develop')
            self.assertIn(f'pib: kernel: {KERNEL_URL} develop @ {self.tips["develop"]}', out)
            self.assertFalse(sbp.kernel_repo(url).exists(), "one repository's copy on the volume")
        # a commit by itself: the branch that holds it carries sbp's clone, as master does not
        out, calls = self.printed(ws, '-p', 'linux', '--kernel-url', url, '--kernel-ref', mine)
        self.assertIn(f'pib: kernel: {url} mine @ {mine}', out)
        # a commit the remote serves by id but holds on no branch or tag (a pull request's head):
        # sbp's clone would not have it, so it is refused before sbp runs
        pull = git('-C', str(fork), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit-tree', '-p', mine,
                   '-m', 'pull request', f'{mine}^{{tree}}')
        git('-C', str(fork), 'update-ref', 'refs/pull/1/head', pull)
        before = self.log.read_text()
        self.assertIn(f'{url} has no commit {pull}', dies(self.pib_package, ws, '-p', 'linux',
                                                          '--kernel-url', url, '--kernel-ref', pull))
        self.assertEqual(self.log.read_text(), before, 'sbp never ran')
        # a dry run fetches nothing: it asks the remote, and GitHub whether it has the commit
        with patch.object(sbp, 'remote_lacks', return_value=None) as asked:
            out, calls = self.printed(ws, '-p', 'linux', '--kernel-url', url, '--kernel-ref', mine,
                                      '--dry-run')
        self.assertIn(f'pib: kernel: {url} master @ {mine}', out)
        self.assertEqual(asked.call_args.args, (url, 'master', mine))
        self.assertIn(f'{KERNEL_URL} has no branch nope', dies(self.pib_package, ws, '-p', 'linux',
                                                               '--kernel-ref', 'nope'))
        with patch.dict(os.environ, {'PIB_KERNEL_REF': 'a b'}):
            self.assertIn('PIB_KERNEL_REF', dies(self.pib_package, ws, '-p', 'linux'))
        with patch.dict(os.environ, {'PIB_KERNEL_URL': 'git@github.com:me/x.git'}):
            self.assertIn('must be the https URL', dies(self.pib_package, ws, '-p', 'linux'))
            calls = self.pib_package(ws, '-p', 'smifb')     # a module alone: the kernel is not asked
            self.assertEqual(calls[0]['args'][2], 'smifb-modalix')

    def test_your_own_kernel_from_a_repository_on_the_host(self):
        ws = workspace(self.base, 'minimal')
        repo = self.base / 'my-linux'
        git('clone', '-q', str(self.kernel), str(repo))
        git('-C', str(repo), 'branch', '-q', 'develop', 'origin/develop')
        mine = add_commit(repo, 'mine', 'my change')
        kernel = repo / '.git'                         # what the launcher mounts
        url_map(self.gitconfig, LOCAL_URL, kernel)     # sbp/setup.sh's map, for PIB_KERNEL_SRC
        with patch.dict(os.environ, {'PIB_KERNEL_SRC': str(kernel)}):
            out, calls = self.printed(ws, '-p', 'linux')
            self.assertIn(f'pib: kernel: PIB_KERNEL_SRC mine @ {mine}', out, 'its checked-out branch')
            self.assertIn(f'  url: {LOCAL_URL}\n  branch: mine\n  commit-id: {mine}\n', self.kernel_yaml())
            self.assertEqual(calls[0]['git_map'], [], 'sbp/setup.sh maps it')
            self.assertFalse(any('uncommitted' in o for o in out))
            # the launcher counted uncommitted changes on the host
            with patch.dict(os.environ, {'PIB_KERNEL_SRC_HEAD': mine, 'PIB_KERNEL_SRC_CHANGES': '2'}):
                out, calls = self.printed(ws, '-p', 'linux')
                self.assertTrue(any('uncommitted changes to 2 tracked files' in o for o in out), out)
                out, calls = self.printed(ws, '-p', 'linux', '--kernel-ref', 'develop')
                self.assertFalse(any('uncommitted' in o for o in out), 'not the commit those changes sit on')
            git('-C', str(repo), 'checkout', '-q', '--detach')
            self.assertIn('detached', dies(self.pib_package, ws, '-p', 'linux'))
            out, calls = self.printed(ws, '-p', 'linux', '--kernel-ref', mine)
            self.assertIn(f'pib: kernel: PIB_KERNEL_SRC mine @ {mine}', out, 'the branch that holds it')
            tagged = git('-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit-tree',
                         '-m', 'on a tag only', f'{mine}^{{tree}}')
            git('-C', str(repo), 'tag', 'v1', tagged)
            out, calls = self.printed(ws, '-p', 'linux', '--kernel-ref', tagged)
            self.assertIn(f'pib: kernel: PIB_KERNEL_SRC master @ {tagged}', out, 'a clone takes the tags')
            orphan = git('-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@t', 'commit-tree',
                         '-m', 'on no branch', f'{mine}^{{tree}}')
            self.assertIn('is on no branch or tag', dies(self.pib_package, ws, '-p', 'linux',
                                                         '--kernel-ref', orphan))
            self.assertIn('has no commit', dies(self.pib_package, ws, '-p', 'linux', '--kernel-ref', 'e' * 40))
            self.assertIn('exclude each other', dies(self.pib_package, ws, '-p', 'linux',
                                                     '--kernel-url', 'https://github.com/me/x.git'))
            with patch.dict(os.environ, {'PIB_KERNEL_URL': 'https://github.com/me/x.git'}):
                self.assertIn('exclude each other', dies(self.pib_package, ws, '-p', 'linux'))
            with patch.dict(os.environ, {'PIB_KERNEL_SRC_URL': ''}):
                self.assertIn('did not map it', dies(self.pib_package, ws, '-p', 'linux'))
            git('-C', str(repo), 'checkout', '-q', '-b', 'feat+x')
            self.assertIn('is not a branch name or commit', dies(self.pib_package, ws, '-p', 'linux'))

    def test_another_kernel_version_never_wedges_the_volume(self):
        """sbp's repo keeps every package name it is given: before a build from scratch the old
        kernels leave it, or a kernel of another version would stay next to the next one."""
        ws = workspace(self.base, 'minimal')
        self.pib_package(ws, '-p', 'linux')                                        # 6.18.3-1
        with patch.dict(os.environ, {'FAKE_KV': '6.19.0'}):
            msg = dies(self.pib_package, ws, '-p', 'linux', '--kernel-ref', 'develop')
        self.assertIn('would be left out of the image', msg, 'the image installs 6.18.3 kernels only')
        kernels = lambda: sorted((f['Package'], f['Version']) for f in sbp.packages_index()  # noqa: E731
                                 if sbp.kernel_set(f['Package'], 'modalix'))
        self.assertEqual(kernels(), [('linux-headers-6.19.0-modalix', '6.19.0-2'),
                                     ('linux-image-6.19.0-modalix', '6.19.0-2'), ('linux-libc-dev', '6.19.0-2')])
        calls = self.pib_package(ws, '-p', 'linux')               # back to SiMa.ai's: it works again
        self.assertEqual((calls[0]['args'][3:5], calls[0]['BUILD']), (['-t', 'clean+'], '3'))
        self.assertEqual(kernels(), [('linux-headers-6.18.3-modalix', '6.18.3-3'),
                                     ('linux-image-6.18.3-modalix', '6.18.3-3'), ('linux-libc-dev', '6.18.3-3')],
                         'and linux-libc-dev went back below 6.19.0')
        self.assertIn('linux-image-6.18.3-modalix_6.18.3-3_arm64.deb', self.debs(ws))
        with patch.object(sbp, 'kernel_glob', return_value='linux-image-*'):  # two kernels in a repo: the way out
            msg = dies(sbp.built_kernel, [{'Package': 'linux-image-6.18.3-modalix', 'Version': '6.18.3-1'},
                                          {'Package': 'linux-image-6.19.0-modalix', 'Version': '6.19.0-2'}],
                       ws, 'modalix')
        self.assertIn('-t clean+', msg)
        self.assertIn('PIB_PACKAGE_VOLUME', msg)

    def test_a_kernel_without_a_fit_is_said_so(self):
        ws = workspace(self.base, 'minimal')
        out, _ = self.printed(ws, '-p', 'linux')
        self.assertFalse(any('FIT' in o for o in out), out)
        with patch.dict(os.environ, {'FAKE_NO_FIT': '1'}):
            out, _ = self.printed(ws, '-p', 'linux', '-t', 'clean+')
        self.assertTrue(any('WARNING: the kernel package has no FIT' in o for o in out), out)

    def test_minimal_kernel_only_and_opt_outs(self):
        ws = workspace(self.base, 'minimal')
        calls = self.pib_package(ws, '-p', 'linux')
        self.assertEqual(len(calls), 1, 'no modules in minimal images')
        self.assertEqual([n.split('_')[0] for n in self.debs(ws)],
                         ['linux-headers-6.18.3-modalix', 'linux-image-6.18.3-modalix', 'linux-libc-dev'])
        # modules on their own, against the kernel already built
        calls = self.pib_package(ws, '-p', 'lttng')
        self.assertEqual([c['args'] for c in calls], [['package', '-p', 'lttng-modules-modalix', '-t', 'clean+', '-g', 'all']])

    def test_palette_no_modules_dry_run_and_order(self):
        ws = workspace(self.base)
        calls = self.pib_package(ws, '-p', 'linux', '--no-modules', '--dry-run')
        self.assertEqual([c['args'] for c in calls], [['package', '-p', 'linux-modalix', '-g', 'all', '--dry-run']])
        self.assertEqual(self.debs(ws), [])
        with self.assertRaises(SystemExit) as e:
            self.pib_package(ws, '-p', 'smifb')
        self.assertIn('build the kernel first', str(e.exception.code))

    def test_needs_a_workspace(self):
        (self.base / 'empty').mkdir()
        with self.assertRaises(SystemExit) as e:
            self.pib_package(self.base / 'empty', '-p', 'linux')
        self.assertIn("run 'pib init' first", str(e.exception.code))

    def test_the_images_own_sbp_unless_pib_packages_src_names_another(self):
        ws = workspace(self.base, 'minimal')
        not_yet = script(ROOT / 'ci/check-sbp-start.py').NOT_YET
        del os.environ['PIB_PKGBUILD_SRC']
        msg = dies(self.pib_package, ws, '-p', 'linux')    # neither: stops before sbp runs
        self.assertIn(not_yet, msg, 'what CI looks for in the start check')
        self.assertIn('Set PIB_PKGBUILD_SRC', msg)
        self.assertFalse(self.log.exists(), 'sbp never ran')
        # the tree the image fetched from the pinned commit (deps/fetch-artifacts.py --sbp)
        shutil.copytree(self.src, self.base / 'baked')
        pin = 'https://github.com/SiMa-ai/swsoc-simaai-elxr-doc.git ' + 'c' * 40
        (self.base / 'baked/SOURCE').write_text(pin + '\n')
        out, calls = self.printed(ws, '-p', 'linux', '--dry-run')
        self.assertIn("pib: sbp and its package configs: this image's, from " + pin.replace(' ', ' @ '), out)
        self.assertEqual({c['src'] for c in calls}, {str(self.base / 'baked')}, 'sbp runs from it too')
        out, calls = self.printed(ws, '--list')
        self.assertIn("pib: sbp and its package configs: this image's, from " + pin.replace(' ', ' @ '), out,
                      'list names it too')
        self.assertEqual([c['src'] for c in calls], [str(self.base / 'baked')])
        # PIB_PKGBUILD_SRC replaces it
        os.environ['PIB_PKGBUILD_SRC'] = str(self.src)
        label = f"pib: sbp and its package configs: PIB_PKGBUILD_SRC ({self.src}), not this image's own"
        out, calls = self.printed(ws, '-p', 'linux', '--dry-run')
        self.assertIn(label, out)
        self.assertEqual({c['src'] for c in calls}, {str(self.src)})
        out, calls = self.printed(ws, '--list')
        self.assertIn(label, out)
        self.assertEqual([c['src'] for c in calls], [str(self.src)])
        # and one without sbp stops, rather than being passed over for the image's
        (self.src / 'pkgbuild/sbp/cli.py').unlink()
        msg = dies(self.pib_package, ws, '-p', 'linux')
        self.assertIn(f'PIB_PKGBUILD_SRC: {self.src}/pkgbuild/sbp/cli.py not found', msg)
        self.assertIn("or unset it to use this image's own (" + pin.replace(' ', ' @ ') + ")", msg)
        self.assertNotIn(not_yet, msg)
        # without the image's own, PIB_PKGBUILD_SRC alone is named; a relative one is taken from here,
        # and sbp, which runs in the volume's tree, gets it absolute
        shutil.rmtree(self.base / 'baked')
        shutil.copytree(self.base / 'swsoc-elxr', self.base / 'other')
        (self.base / 'other/pkgbuild/sbp/cli.py').write_text('')
        os.environ['PIB_PKGBUILD_SRC'] = os.path.relpath(self.base / 'other', ws)
        other = Path(os.path.realpath(self.base)) / 'other'
        out, calls = self.printed(ws, '-p', 'linux', '--dry-run')
        self.assertIn(f"pib: sbp and its package configs: PIB_PKGBUILD_SRC ({other})", out)
        self.assertEqual({c['src'] for c in calls}, {str(other)})

    def test_a_changed_source_is_never_stamped_before_it_is_built(self):
        ws = workspace(self.base)
        self.pib_package(ws, '-p', 'linux', '--no-modules')
        # with a source change only a build from scratch is right: other -t values are refused
        self.assertIn('does not apply', dies(self.pib_package, ws, '-p', 'linux', '--kernel-ref', 'develop',
                                             '-t', 'build+', '--no-modules'))
        with patch.dict(os.environ, {'FAKE_SBP_FAIL': '1'}):
            self.assertIn('sbp failed', dies(self.pib_package, ws, '-p', 'linux', '--kernel-ref', 'develop',
                                             '--no-modules'))
        calls = self.pib_package(ws, '-p', 'linux', '--kernel-ref', 'develop', '--no-modules')
        self.assertEqual(calls[0]['args'][3:5], ['-t', 'clean+'], 'the failed run left no stamp for develop')
        calls = self.pib_package(ws, '-p', 'linux', '--kernel-ref', 'develop', '--no-modules')
        self.assertNotIn('-t', calls[0]['args'], 'built: develop is stamped now')

    def test_a_new_fit_key_rebuilds_the_kernel(self):
        ws = workspace(self.base, 'minimal')
        self.pib_package(ws, '-p', 'linux')
        for name in ('fit-signing.key', 'fit-signing.crt'):
            (ws / 'keys' / name).unlink()
        with patch('sys.stdout'):
            cli.gen_fit_key(ws / 'keys')
        calls = self.pib_package(ws, '-p', 'linux')
        self.assertEqual((calls[0]['args'][3:5], calls[0]['BUILD']), (['-t', 'clean+'], '2'))

    def test_each_module_follows_its_own_kernel(self):
        ws = workspace(self.base)
        self.pib_package(ws, '-p', 'linux')                                   # K1, modules on K1
        calls = self.pib_package(ws, '-p', 'linux', '--kernel-ref', 'develop', '--no-modules')  # K2
        self.assertEqual(len(calls), 1)
        self.assertFalse([n for n in self.debs(ws) if n.startswith(('smifb-', 'lttng-'))],
                         'module packages built for K1 must not stay next to K2')
        calls = self.pib_package(ws, '-p', 'smifb')                          # asked for: rebuilt on K2
        self.assertEqual([c['args'][2] for c in calls], ['smifb-modalix'])
        calls = self.pib_package(ws, '-p', 'linux', '--kernel-ref', 'develop')
        self.assertEqual([c['args'][2] for c in calls], ['linux-modalix', 'lttng-modules-modalix'],
                         'smifb is current on K2, lttng still on K1')
        self.assertEqual(len([n for n in self.debs(ws) if n.startswith(('smifb-', 'lttng-'))]), 2)

    def test_a_changed_recipe_rebuilds(self):
        ws = workspace(self.base)
        self.pib_package(ws, '-p', 'linux')
        patch_file = self.src / 'configs/packages/kernel/0001-HACK-do-not-put-commit-hash-in-version-string.patch'
        patch_file.write_text('a new patch\n')                            # the checkout moved on
        calls = self.pib_package(ws, '-p', 'linux')
        self.assertEqual(calls[0]['args'][3:5], ['-t', 'clean+'], 'a new kernel recipe is a new kernel')
        self.assertEqual(calls[1]['args'][2], 'smifb-modalix,lttng-modules-modalix', 'and new headers')
        (self.src / 'configs/packages/smifb/smifb.yaml').write_text(SMIFB_YAML + '  # changed\n')
        calls = self.pib_package(ws, '-p', 'linux')
        self.assertEqual([c['args'][2] for c in calls], ['linux-modalix', 'smifb-modalix'], 'only smifb')

    def test_unchanged_packages_keep_their_signatures(self):
        ws = workspace(self.base, 'minimal')
        self.pib_package(ws, '-p', 'linux')
        sigs = []
        for d in (ws / 'custom-debs').glob('*.deb'):
            Path(f'{d}.sig').write_text('signed')
            sigs.append(Path(f'{d}.sig'))
        self.pib_package(ws, '-p', 'linux')                     # nothing new
        self.assertTrue(all(s.read_text() == 'signed' for s in sigs), 'no re-sign needed')

    def test_modules_alone_need_no_fit_key_and_list_needs_no_workspace(self):
        ws = workspace(self.base, 'minimal')
        self.pib_package(ws, '-p', 'linux')
        for name in ('fit-signing.key', 'fit-signing.crt'):
            (ws / 'keys' / name).unlink()
        calls = self.pib_package(ws, '-p', 'smifb')
        self.assertEqual(calls[0]['args'][2], 'smifb-modalix')
        self.assertIsNone(calls[0]['keyname'])
        self.assertIn('run pib keys fit', dies(self.pib_package, ws, '-p', 'linux'))
        (self.base / 'elsewhere').mkdir()
        calls = self.pib_package(self.base / 'elsewhere', '--list')
        self.assertEqual(calls[0]['args'], ['list'])
        calls = self.pib_package(self.base / 'elsewhere', '--list', '--debug')
        self.assertEqual(calls[0]['args'], ['list', '--debug'], 'sbp list takes --debug too')

    def test_module_packages_built_for_this_kernel_stay(self):
        ws = workspace(self.base, 'minimal')
        self.pib_package(ws, '-p', 'linux')
        self.pib_package(ws, '-p', 'smifb')                  # built against this kernel
        smifb = [n for n in self.debs(ws) if n.startswith('smifb-')]
        self.assertEqual(len(smifb), 1)
        self.pib_package(ws, '-p', 'linux')                  # nothing changed: it stays
        self.assertEqual([n for n in self.debs(ws) if n.startswith('smifb-')], smifb)
        self.pib_package(ws, '-p', 'linux', '-t', 'clean+')  # a new kernel: it goes
        self.assertEqual([n for n in self.debs(ws) if n.startswith('smifb-')], [])

    def test_refusals_before_any_build(self):
        ws = workspace(self.base, 'securepalette')
        self.assertIn('securepalette', dies(self.pib_package, ws, '-p', 'linux'))
        ws2 = self.base / 'ws2'
        shutil.copytree(ws, ws2)
        (ws2 / 'image.yaml').write_text('base: palette\ntarget: modalix\nrelease: 3.0.0\nversion: 3.0.0.1\n')
        (self.base / 'sources.json').write_text(json.dumps({**SOURCES, 'release': '3.0.1'}))
        self.assertIn('pins sources for 3.0.1', dies(self.pib_package, ws2, '-p', 'linux'))
        self.assertFalse(self.log.exists(), 'sbp never ran')

    def test_custom_debs_change_only_when_everything_checks_out(self):
        ws = workspace(self.base, 'minimal')
        self.pib_package(ws, '-p', 'linux')
        before = self.debs(ws)
        (ws / 'custom-debs/zz-broken.deb').write_bytes(b'not a deb')
        self.assertIn('dpkg-deb failed', dies(self.pib_package, ws, '-p', 'linux', '-t', 'clean+'))
        self.assertEqual(self.debs(ws), sorted(before + ['zz-broken.deb']), 'the old kernel is still there')
        self.assertFalse(list((ws / 'custom-debs').glob('.*.pib-package')), 'no temporary files left')

    def test_uapi_report(self):
        ws = workspace(self.base, 'minimal')
        theirs = deb(self.base / 'theirs.deb', 'linux-libc-dev', '6.18.3-2796')
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            (t / 'DEBIAN').mkdir()
            (t / 'DEBIAN/control').write_text('Package: linux-libc-dev\nVersion: 6.18.3-2796\nArchitecture: arm64\n'
                                              'Maintainer: t <t@t>\nDescription: t\n')
            (t / 'usr/include/linux/media/simaai').mkdir(parents=True)
            (t / 'usr/include/linux/media/simaai/modalix_isp_calib.h').write_text('#define MODALIX_ISP_CALIB_TOTAL_SIZE 137\n')
            subprocess.run(['dpkg-deb', '--root-owner-group', '-b', t, theirs], check=True, capture_output=True)
        for uapi, want in (('#define MODALIX_ISP_CALIB_TOTAL_SIZE 137\n', 'match the release'),
                           ('#define MODALIX_ISP_CALIB_TOTAL_SIZE 102\n', 'WARNING')):
            out = []
            with patch.dict(os.environ, {'FAKE_UAPI': uapi}), \
                    patch.object(cli, 'release_deb', return_value=theirs), \
                    patch('builtins.print', side_effect=lambda *a, **k: out.append(' '.join(map(str, a)))):
                os.chdir(ws)
                cli.main(['package', '-p', 'linux', '-t', 'clean+'])
            self.assertTrue(any(want in o for o in out), out)


class StartCheck(unittest.TestCase):
    """ci/check-sbp-start.py passes CI only when pib package --list ran the image's own sbp, from the
    commit deps/artifacts.json pins: not an image without sbp, nor a listing from PIB_PKGBUILD_SRC."""

    def check(self, code, stdout, stderr=''):
        start = script(ROOT / 'ci/check-sbp-start.py')
        launcher = [sys.executable, '-c', 'import sys; sys.stdout.write(sys.argv[1]); '
                    'sys.stderr.write(sys.argv[2]); sys.exit(int(sys.argv[3]))', stdout, stderr, str(code)]
        with patch('sys.stdout', new_callable=io.StringIO), patch('sys.stderr', new_callable=io.StringIO) as err:
            return start.check(launcher), err.getvalue()

    def test_only_the_images_own_sbp_from_the_pinned_commit_passes(self):
        pin = json.loads((ROOT / 'deps/artifacts.json').read_text())['upstream']
        own = f"pib: sbp and its package configs: this image's, from {pin['repository']} @ {pin['commit']}"
        start = script(ROOT / 'ci/check-sbp-start.py')
        self.assertEqual(start.OWN, own, 'the line sbp.cmd_package prints for the SOURCE fetch-artifacts writes')
        self.assertEqual(self.check(0, own + '\npib: sbp list\n')[0], 0)
        rc, err = self.check(0, own.replace(pin['commit'], 'c' * 40) + '\n')
        self.assertEqual(rc, 1)
        self.assertIn("not with the image's own sbp", err)
        rc, err = self.check(0, 'pib: sbp and its package configs: PIB_PKGBUILD_SRC (/src)\n')
        self.assertEqual(rc, 1, 'a checkout named by PIB_PKGBUILD_SRC does not prove the image')
        rc, err = self.check(1, '', f'pib: {start.NOT_YET}: the swsoc-simaai-elxr-doc commit ...\n')
        self.assertEqual(rc, 1)
        self.assertIn('the image carries no sbp', err)
        rc, err = self.check(2, '', 'usage: pib ...\n')
        self.assertEqual(rc, 1)
        self.assertIn('did not start (exit 2)', err)


if __name__ == '__main__':
    unittest.main()
