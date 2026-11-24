"""pib package: build SiMa.ai packages with sbp (SiMa Build Package) into this workspace's custom-debs/.

Runs as root like every pib command, after sbp/setup.sh (the entrypoint runs it first) has prepared
sbp's local repo, apt sources and git's URL maps (and exported sbp's settings for this process only).
The launcher gives it the workspace read-only except custom-debs/, and of keys/ only the kernel
FIT key pair. For now it builds the kernel and the kernel-module packages palette images carry.
The kernel source is the user's to choose: SiMa.ai's public repository by default, a fork
(PIB_KERNEL_URL) or a repository on the host (PIB_KERNEL_SRC).
"""
import argparse
import fnmatch
import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from pib import cli

SOURCES = Path("/usr/share/pib/sbp/sources.json")  # default sources (sbp/sources.json)
# sbp and its package configs from the swsoc-simaai-elxr-doc commit deps/artifacts.json pins, when it
# carries them (deps/fetch-artifacts.py --sbp, with the files below and a SOURCE line naming it)
BAKED_SRC = Path("/usr/share/pib/sbp-src")
SBP_FILES = ("pkgbuild/sbp/cli.py", "configs/packages/packages.yaml")
ARM64_LOADER = "/lib/ld-linux-aarch64.so.1"
UAPI = ("usr/include/linux/media/simaai/", "usr/include/linux/simaai/")
COMMIT = re.compile(r"[0-9a-f]{40}")
REF = re.compile(r"[A-Za-z0-9._/-]+")               # a branch name or a full commit
# An https URL of a git repository: no user or token in it (the container fetches it without
# credentials, and the URL is written into sbp's config and logs), and none of the characters
# OmegaConf interpolates ($ { }), as sbp resolves that config. host/pib checks the same pattern.
HTTPS_URL = re.compile(r"https://[A-Za-z0-9.-]+(?::[0-9]+)?/[A-Za-z0-9._~%+/-]+")
# Forms OmegaConf (sbp's config loader) reads as floats, which PyYAML reads as strings: 1e5, 1.5e3
OMEGACONF_FLOAT = re.compile(r"[-+]?[0-9]+(?:_[0-9]+)*(?:\.[0-9_]*)?[eE][-+]?[0-9]+")
BRANCH_LINE = re.compile(r"^ +branch: .*\n", re.M)  # in a pinned config: only carries sbp's clone
# -p entries pib package accepts -> component. sbp matches -p as a substring of package names, so
# pib package passes sbp the full config name instead of the user's text.
ALIASES = {"linux": "linux", "kernel": "linux", "smifb": "smifb", "lttng": "lttng",
           "lttng-modules": "lttng"}
MODULES = ("smifb", "lttng")  # out-of-tree kernel modules: built against the kernel's headers
WITH_MODULES = ("palette",)   # flavors whose images carry them (simaai-palette-<target>)
USAGE = """\
usage: pib package -p PACKAGES [-t TASKS] [--dry-run] [--debug] [--no-ccache]
                   [--kernel-url URL] [--kernel-ref REF] [--no-modules]
       pib package --list [--debug]

Build SiMa.ai packages with sbp, SiMa.ai's package builder, and put the .debs in custom-debs/;
then run pib sign-debs and pib build. The kernel FIT is signed with keys/fit-signing.key: make
it once with pib keys fit.

PACKAGES   comma-separated: linux (the kernel), smifb, lttng (kernel-module packages, built
           against that kernel; palette workspaces get them with linux, always rebuilt
           when the kernel changes)
--list     list the packages sbp's package configs define and their build state; builds nothing
-t TASKS   sbp tasks for the kernel, e.g. clean+ (default: what has not run yet)
--kernel-url URL
           https URL of the kernel's git repository, e.g. your fork of SiMa.ai's (default:
           https://github.com/SiMa-ai/simaai-linux.git, sbp/sources.json). The volume keeps a
           copy of it: the first build downloads all of it, later ones only what is new
--kernel-ref REF
           branch or full commit of the kernel to build (default: master, or the branch
           checked out in PIB_KERNEL_SRC). A branch is built at its tip of the moment:
           each run looks the tip up again, and a branch that moved is rebuilt. A commit
           must be on a branch or tag of the repository
--no-modules
           build the kernel alone; module packages pib package built for an older kernel
           leave custom-debs/, so the image falls back to SiMa.ai's

Environment (set on the host; the launcher passes them):
  PIB_PKGBUILD_SRC     a checkout of swsoc-simaai-elxr-doc or swsoc-elxr with pkgbuild/ (sbp)
                       and configs/packages/, used instead of the image's own while it is set;
                       needed while the image carries none
  PIB_KERNEL_SRC       your kernel: a git repository on the host (a checkout or a bare one),
                       for a private repository or commits not pushed anywhere (the container
                       gets no credentials). Only its git directory is mounted, read-only; it
                       must be a complete clone (not --filter, --shared or a worktree) without
                       credentials in its git config. A commit of it is built, never uncommitted
                       changes
  PIB_KERNEL_URL       --kernel-url for every run (not with PIB_KERNEL_SRC)
  PIB_KERNEL_REF       --kernel-ref for every run
  PIB_GIT_MIRRORS      directory of bare git mirrors (<name>.git), read-only; each stands in for
                       SiMa.ai's private repository of that name on Bitbucket (the container
                       gets no credentials). GitHub repositories are always fetched from GitHub
  PIB_PACKAGE_JOBS     parallel jobs (default: CPUs, fewer when memory is short)
  PIB_CCACHE_SIZE      ccache size on the volume (default 5G)
  PIB_PACKAGE_VOLUME   Docker volume for sbp's work tree, local repo and ccache (default
                       pib-package-<uid>)"""


def work():
    return Path(os.environ.get("SBP_WORKSPACE", "/var/tmp/pib-package"))


def repo_dir():
    return Path(os.environ.get("REPO_ROOT", "/var/tmp/pib-package/repo/")) / os.environ.get("BUILD_TYPE", "custom")


def parse(argv):
    if any(x in ("-h", "--help") for x in argv):  # the full text, not argparse's option list
        print(USAGE)
        raise SystemExit(0)
    p = argparse.ArgumentParser(prog="pib package", usage=USAGE.split("\n\n")[0][7:], add_help=False)
    mode = p.add_mutually_exclusive_group(required=True)  # neither -p nor --list: a usage error
    mode.add_argument("-p", "--packages")
    mode.add_argument("--list", action="store_true")
    p.add_argument("-t", "--tasks")
    p.add_argument("-g", "--group")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--no-ccache", action="store_true")
    p.add_argument("--kernel-ref")
    p.add_argument("--kernel-url")
    p.add_argument("--no-modules", action="store_true")
    a = p.parse_args(argv)
    if a.list:  # builds nothing: of the options only --debug, which sbp list takes too, applies
        for flag, value in (("-t", a.tasks), ("-g", a.group), ("--dry-run", a.dry_run),
                            ("--no-ccache", a.no_ccache), ("--kernel-url", a.kernel_url),
                            ("--kernel-ref", a.kernel_ref), ("--no-modules", a.no_modules)):
            if value not in (None, False):
                cli.die(f"{flag} is for a build (-p), not --list")
        return a
    if a.group not in (None, "all"):
        cli.die("pib package always builds with -g all: other groups make sbp import SiMa.ai's prebuilt "
                "packages from a mirror instead of building them")
    picked = []
    for entry in a.packages.split(","):
        entry = entry.strip()
        if entry.endswith("+"):
            cli.die(f"{entry}: '+' would also rebuild every package that depends on it; "
                    "name the packages instead")
        name = ALIASES.get(re.sub(r"-modalix$", "", entry))
        if not name:
            cli.die(f"pib package builds linux, smifb and lttng for now, not {entry!r}")
        if name not in picked:
            picked.append(name)
    a.picked = picked
    if a.tasks is not None and "linux" not in picked:
        cli.die("-t is for the kernel (-p linux); smifb and lttng-modules are always rebuilt from scratch")
    for flag, value in (("--kernel-url", a.kernel_url), ("--kernel-ref", a.kernel_ref)):
        if value is not None and "linux" not in picked:
            cli.die(f"{flag} is for the kernel (-p linux)")
    if a.kernel_ref is not None:
        check_ref("--kernel-ref", a.kernel_ref)
    if a.kernel_url is not None:
        check_url("--kernel-url", a.kernel_url)
    return a


def check_ref(what, ref):
    if not ref or ref.startswith("-") or not REF.fullmatch(ref):
        cli.die(f"{what} {ref!r} is not a branch name or commit")


def shown(url):
    """url for messages: never its user, password or token."""
    return re.sub(r"(?<=://)[^/@\s]*@", "<credentials>@", url).split("?")[0].split("#")[0]


def check_url(what, url):
    if not HTTPS_URL.fullmatch(url):
        cli.die(f"{what} {shown(url)!r} must be the https URL of a git repository, with no user or "
                "token in it: the container fetches it without credentials. For a private "
                "repository, clone it on the host and set PIB_KERNEL_SRC to the clone")


def baked():
    """Where this image's own sbp and package configs come from (BAKED_SRC/SOURCE: the repository
    and commit), or None when the image carries none."""
    if not all((BAKED_SRC / f).is_file() for f in SBP_FILES):
        return None
    source = (BAKED_SRC / "SOURCE").read_text().split() if (BAKED_SRC / "SOURCE").is_file() else []
    return f"{source[0]} @ {source[1]}" if len(source) == 2 else str(BAKED_SRC)


def source_tree():
    """The tree with sbp and configs/packages, and what to call it: the checkout PIB_PKGBUILD_SRC
    names when it is set, else this image's own (BAKED_SRC), which the image carries when the
    swsoc-simaai-elxr-doc commit it was built from has them."""
    named, own = os.environ.get("PIB_PKGBUILD_SRC"), baked()
    if named:
        named = os.path.abspath(named)  # sbp itself runs in the volume's tree, not here
        missing = [f for f in SBP_FILES if not (Path(named) / f).is_file()]
        if missing:
            cli.die(f"PIB_PKGBUILD_SRC: {named}/{missing[0]} not found: PIB_PKGBUILD_SRC must be a checkout "
                    "of swsoc-simaai-elxr-doc or swsoc-elxr that carries sbp and its package configs"
                    + (f", or unset it to use this image's own ({own})" if own else ""))
        return Path(named), f"PIB_PKGBUILD_SRC ({named})" + (", not this image's own" if own else "")
    if not own:
        cli.die("this image does not carry sbp yet: the swsoc-simaai-elxr-doc commit it was built from "
                "has no pkgbuild/ and configs/packages/. Set PIB_PKGBUILD_SRC to a checkout with both "
                "(swsoc-simaai-elxr-doc or swsoc-elxr)")
    return BAKED_SRC, f"this image's, from {own}"


def config_names(target):
    return {"linux": f"linux-{target}", "smifb": f"smifb-{target}", "lttng": f"lttng-modules-{target}"}


# Each component's sbp config, relative to configs/packages/ (its directory is its recipe).
CONFIGS = {"linux": "kernel/linux.yaml", "smifb": "smifb/smifb.yaml",
           "lttng": "lttng-modules/lttng-modules.yaml"}


def scalar(value):
    """value as YAML that sbp reads back as this same string: a branch named 1.10 must not become
    the number 1.1, nor one named no a boolean, nor 1e5 OmegaConf's float."""
    try:
        same = yaml.safe_load(value) == value and not OMEGACONF_FLOAT.fullmatch(value)
    except yaml.YAMLError:
        same = False
    return value if same else json.dumps(value)


def set_source(path, name, target, branch, commit, url=None):
    """Point the sbp config of package name at branch (and commit, or none) and, given one, at
    url, by line edits like SiMa.ai's scripts/changeBranch.py's; the rest of the file stays byte
    for byte. Nothing OmegaConf would interpolate (${...}) is written: sbp resolves the config."""
    if any("$" in v for v in (branch, commit, url) if v):
        cli.die(f"{path}: refusing to pin {name} to a value with '$' in it")
    text = path.read_text()
    m = re.search(r"^( +)branch: *\S+ *$", text, re.M)
    if not m:
        cli.die(f"{path}: no 'branch:' option to pin")
    indent = m[1]
    text = text[:m.start()] + f"{indent}branch: {scalar(branch)}" + text[m.end():]
    text = re.sub(r"^ +commit-id: *\S+ *\n", "", text, flags=re.M)
    if commit:
        text = re.sub(r"^( +branch: .*\n)", lambda b: f"{b[1]}{indent}commit-id: {scalar(commit)}\n", text,
                      count=1, flags=re.M)
    if url:
        u = re.search(r"^( +)url: *\S+ *$", text, re.M)
        if not u:
            cli.die(f"{path}: no 'url:' option to point at {url}")
        text = text[:u.start()] + f"{u[1]}url: {scalar(url)}" + text[u.end():]
    path.write_text(text)
    opts = (cli.read_yaml(path).get("options") or {})
    if str(opts.get("name", "")).replace("${platform}", target) != name or \
            opts.get("branch") != branch or opts.get("commit-id") != commit or \
            (url and opts.get("url") != url):
        cli.die(f"{path}: could not pin {name} to {' '.join(filter(None, (url, branch, commit)))}")


def prepare_tree(src, target):
    """A writable copy of configs/packages on the volume, with the sources of sbp/sources.json
    pinned (for the kernel its repository and branch: pib package then pins the commit it
    builds, resolve_kernel); sbp runs from it (its paths are relative to the tree root) and uses
    the tool in src."""
    sources = json.loads(SOURCES.read_text())
    if (sources["release"], sources["codename"]) != (cli.container_release(), cli.container_codename()):
        cli.die(f"sbp/sources.json pins sources for {sources['release']} {sources['codename']}, "
                f"not this image's {cli.container_release()} {cli.container_codename()}")
    tree = work() / "tree"
    shutil.rmtree(tree, ignore_errors=True)
    shutil.copytree(src / "configs/packages", tree / "configs/packages", symlinks=True)
    pk = tree / "configs/packages"
    codename = (pk / "simaai-palette/codename").read_text().strip()
    if codename != cli.container_codename():
        cli.die(f"{src} builds for suite {codename!r}; this image is for {cli.container_codename()!r}")
    for name, pin in sources["packages"].items():
        set_source(pk / pin["config"], name, target, pin["branch"], pin.get("commit-id"), pin.get("url"))
    return tree, sources


BITBUCKET = re.compile(r"bitbucket\.org[:/]sima-ai/")  # SiMa.ai's, private: through a mirror only
GITHUB = re.compile(r"github\.com[:/]", re.IGNORECASE)  # serves any commit by id: asked before a clone


def git_env():
    """git on the kernel's repositories never prompts (nobody could answer), and never fetches a
    partial clone's missing objects from its remote."""
    return dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_NO_LAZY_FETCH="1")


def git_url(url):
    """url as git fetches it: with sbp/setup.sh's url.<mirror>.insteadOf applied (no network)."""
    r = subprocess.run(["git", "ls-remote", "--get-url", url], capture_output=True, text=True)
    return r.stdout.strip() if not r.returncode and r.stdout.strip() else url


def ask_git(url, *argv):
    """git ls-remote argv, about url: (exit code, output), 2 being git's "no such ref". Dies when
    url cannot be asked. git applies sbp/setup.sh's URL maps (mirrors, PIB_KERNEL_SRC)."""
    try:
        r = subprocess.run(["git", "ls-remote", *argv], capture_output=True, text=True,
                           env=git_env(), timeout=120)
    except subprocess.TimeoutExpired:
        cli.die(f"could not reach {url} (timed out)")
    if r.returncode not in (0, 2):
        cli.die(f"could not reach {url}: {r.stderr.strip() or f'git exit {r.returncode}'}")
    return r.returncode, r.stdout


def branch_tip(url, branch):
    """The commit at the tip of url's branch now, or None when url has no such branch."""
    rc, out = ask_git(url, "--exit-code", url, f"refs/heads/{branch}")
    tips = [ln.split("\t")[0] for ln in out.splitlines() if ln.split("\t")[1:] == [f"refs/heads/{branch}"]]
    return tips[0] if not rc and tips else None


def default_branch(url):
    """The branch url's HEAD names (the one a plain clone of it checks out), or None. A name that
    is not a plain branch name is ignored: it would go into sbp's config, which sbp interpolates."""
    _, out = ask_git(url, "--symref", url, "HEAD")
    m = re.search(r"^ref: refs/heads/(\S+)\tHEAD$", out, re.M)
    return m[1] if m and not m[1].startswith("-") and REF.fullmatch(m[1]) else None


def remote_lacks(url, branch, commit):
    """What url lacks of branch and commit, or None: asked without cloning (its refs, then that one
    commit object, without trees or blobs). Dies when url cannot be asked."""
    env = git_env()
    try:
        r = subprocess.run(["git", "ls-remote", "--exit-code", url, f"refs/heads/{branch}"],
                           capture_output=True, text=True, env=env, timeout=120)
        if r.returncode == 2:  # reachable, no such branch
            return f"branch {branch}"
        if not r.returncode and commit:
            with tempfile.TemporaryDirectory() as tmp:
                subprocess.run(["git", "init", "-q", "--bare", tmp], check=True, capture_output=True, env=env)
                r = subprocess.run(["git", "-C", tmp, "fetch", "-q", "--depth=1", "--filter=tree:0", url, commit],
                                   capture_output=True, text=True, env=env, timeout=120)
            if r.returncode and "not our ref" in r.stderr:
                return f"commit {commit}"
    except subprocess.TimeoutExpired:
        cli.die(f"could not reach {url} (timed out)")
    if r.returncode:
        cli.die(f"could not reach {url}: {r.stderr.strip() or f'git exit {r.returncode}'}")
    return None


def check_mirror(url):
    """SiMa.ai's Bitbucket repositories are private and the container has no credentials: they
    are served by a mirror on the host (PIB_GIT_MIRRORS), into which sbp/setup.sh rewrites
    their URLs, or not at all. Checked before anything asks Bitbucket. Returns the mirror, or None
    for any other URL (GitHub URLs are never rewritten)."""
    if not BITBUCKET.search(url):
        return None
    name = re.split(r"[/:]", url.rstrip("/"))[-1]
    if not name.endswith(".git"):
        cli.die(f"{url}: pib package finds the mirror of a SiMa.ai repository by its <name>.git; "
                "write the url with .git")
    mirrors = os.environ.get("PIB_GIT_MIRRORS")
    fetched = git_url(url)
    if not mirrors or Path(fetched).parent != Path(mirrors):
        cli.die(f"{url} is private: set PIB_GIT_MIRRORS to a directory holding {name}, made on "
                f"the host with: git clone --mirror {url} <mirrors>/{name}")
    if not Path(fetched).is_dir():  # rewritten into the mirrors directory, which lacks it
        cli.die(f"no mirror {name} in PIB_GIT_MIRRORS; make one on the host: "
                f"git clone --mirror {url} <mirrors>/{name}")
    return fetched


def local_git(repo, *argv):
    return subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True, env=git_env())


def head_branch(repo, what):
    """The branch repo's HEAD names, or None when it is detached. Dies when git cannot read repo."""
    r = local_git(repo, "symbolic-ref", "-q", "HEAD")
    head = r.stdout.strip()
    if r.returncode not in (0, 1):
        cli.die(f"cannot read {what}: {r.stderr.strip() or f'git exit {r.returncode}'}")
    return head[len("refs/heads/"):] if not r.returncode and head.startswith("refs/heads/") else None


def resolve_in(repo, what, ref, preferred, hint=""):
    """(branch, commit) of ref in a repository on this machine (PIB_KERNEL_SRC, a mirror, or
    the volume's copy of a remote repository), whose branches and tags are what sbp's clone of it
    holds. A branch resolves to its tip. A commit must be on a branch or tag (sbp's clone holds
    those only); sbp clones a branch and then checks the commit out, so it goes with preferred
    (the repository's default branch) when that holds it, else with another branch that does."""
    def refs(*argv):
        r = local_git(repo, "for-each-ref", "--format=%(refname:lstrip=2)", *argv)
        if r.returncode:
            cli.die(f"cannot read {what}: {r.stderr.strip() or f'git exit {r.returncode}'}")
        return r.stdout.split()
    r = local_git(repo, "rev-parse", "--git-dir")  # git's own reason when it cannot read it at all
    if r.returncode:
        cli.die(f"cannot read {what}: {r.stderr.strip() or f'git exit {r.returncode}'}")
    if not COMMIT.fullmatch(ref):
        r = local_git(repo, "rev-parse", "-q", "--verify", f"refs/heads/{ref}^{{commit}}")
        if r.returncode:
            cli.die(f"{what} has no branch {ref}{hint}")
        return ref, r.stdout.strip()
    r = local_git(repo, "cat-file", "-e", f"{ref}^{{commit}}")
    if r.returncode:
        why = f" ({r.stderr.strip()})" if r.stderr.strip() else ""
        cli.die(f"{what} has no commit {ref}{why}{hint}")
    holders = refs("--contains", ref, "refs/heads")
    if not holders:
        if not refs("--count=1", "--contains", ref, "refs/tags"):
            cli.die(f"commit {ref} is on no branch or tag of {what}, so sbp's clone would not hold "
                    f"it: name a branch or tag that holds it, or push one{hint}")
        holders = refs("refs/heads")  # a clone takes every tag: any branch can carry it
        if not holders:
            cli.die(f"{what} has no branch for sbp to clone")
    return (preferred if preferred in holders else holders[0]), ref


def kernel_repo(url):
    """The volume's copy of url's repository: path of the copy of url's branches and tags."""
    return work() / "kernel-repo" / (hashlib.sha256(url.encode()).hexdigest()[:16] + ".git")


def fetch_kernel_repo(url):
    """The volume's copy of url's branches and tags, fetched now: all of them the first time, then
    only what is new. sbp clones the kernel from it, locally, so no build from scratch downloads
    the repository again; and a commit it lacks is on no branch or tag of url, which sbp's clone
    would not hold. A copy of another repository is removed: one repository's worth of disk."""
    repo = kernel_repo(url)
    repo.parent.mkdir(parents=True, exist_ok=True)
    for other in repo.parent.iterdir():
        if other != repo:
            shutil.rmtree(other, ignore_errors=True)
    if not (repo / "HEAD").is_file():
        shutil.rmtree(repo, ignore_errors=True)
        cli.run(["git", "init", "-q", "--bare", repo])
        cli.run(["git", "-C", repo, "config", "gc.auto", "0"])
        print(f"pib: fetching {url}: the whole repository this once; later builds fetch what is new", flush=True)
    else:
        print(f"pib: fetching what is new in {url}", flush=True)
    r = subprocess.run(["git", "-C", str(repo), "fetch", "--progress" if sys.stderr.isatty() else "-q",
                        "--prune", "--no-tags", url, "+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*"],
                       env=git_env())
    if r.returncode:
        cli.die(f"could not fetch {url} (git exit {r.returncode}, see above)")
    return repo


def git_map(env, url, path):
    """Make git in env fetch url from path (sbp's clone of the kernel): GIT_CONFIG_* variables,
    for sbp's processes only; pib's own fetch of url keeps going to url."""
    n = int(env.get("GIT_CONFIG_COUNT") or 0)
    env.update({f"GIT_CONFIG_KEY_{n}": f"url.{path}.insteadOf", f"GIT_CONFIG_VALUE_{n}": url,
                "GIT_CONFIG_COUNT": str(n + 1)})


def kernel_choice(a, pin, config):
    """The kernel source asked for: (URL for sbp's config, branch or commit or None, the repository
    on the host or None). SiMa.ai's repository by default (sbp/sources.json, else the config's own
    URL); --kernel-url or PIB_KERNEL_URL name another, PIB_KERNEL_SRC one on the host (the
    launcher mounts its git directory read-only and sbp/setup.sh maps the URL
    PIB_KERNEL_SRC_URL to it), and --kernel-ref or PIB_KERNEL_REF a branch or commit.
    The flags win over the variables."""
    url, ref = a.kernel_url, a.kernel_ref
    if url is None and os.environ.get("PIB_KERNEL_URL"):
        url = os.environ["PIB_KERNEL_URL"]
        check_url("PIB_KERNEL_URL", url)
    if ref is None and os.environ.get("PIB_KERNEL_REF"):
        ref = os.environ["PIB_KERNEL_REF"]
        check_ref("PIB_KERNEL_REF", ref)
    local = os.environ.get("PIB_KERNEL_SRC")
    if not local:
        return url or pin.get("url") or str((cli.read_yaml(config).get("options") or {}).get("url", "")), ref, None
    if url:
        cli.die("PIB_KERNEL_SRC and a kernel URL (--kernel-url, PIB_KERNEL_URL) exclude each "
                "other: unset one")
    mapped = os.environ.get("PIB_KERNEL_SRC_URL")
    if not mapped:
        cli.die("PIB_KERNEL_SRC is set, but sbp/setup.sh did not map it (PIB_KERNEL_SRC_URL)")
    return mapped, ref, local


def uncommitted_word(commit):
    """Uncommitted changes in the checkout at PIB_KERNEL_SRC are not built: a word when they sit
    on the commit being built, where they are easy to take for part of it. The launcher counted
    them on the host, with git running as the user (PIB_KERNEL_SRC_HEAD and _CHANGES)."""
    changes = os.environ.get("PIB_KERNEL_SRC_CHANGES", "0")
    if os.environ.get("PIB_KERNEL_SRC_HEAD") == commit and changes not in ("", "0"):
        print(f"pib: WARNING: PIB_KERNEL_SRC has uncommitted changes to {changes} tracked files: "
              f"they are not built, only commit {commit[:12]}; commit them to build them", flush=True)


def resolve_kernel(a, tree, sources, names, target):
    """Pin the kernel's sbp config to its source and to the one commit this run builds. Returns
    (branch, commit, how messages name the source, (url, path sbp must clone it from) or None). A
    branch is looked up now and built at its tip, so a branch that moved since the last build is
    a new source (built from scratch, build_kernel). Each source is resolved in a repository on
    this machine: PIB_KERNEL_SRC, SiMa.ai's Bitbucket mirror, or the volume's copy of a remote
    repository; a dry run asks the remote instead of fetching it."""
    pin = sources["packages"][names["linux"]]
    config = tree / "configs/packages" / pin["config"]
    url, ref, local = kernel_choice(a, pin, config)
    clone_from = None
    if local:
        what = "PIB_KERNEL_SRC"
        head = head_branch(local, what)
        if ref is None:
            if head is None:
                cli.die("PIB_KERNEL_SRC has no branch checked out (its HEAD is detached): check "
                        "one out, or name a branch or commit with --kernel-ref or PIB_KERNEL_REF")
            check_ref("the branch checked out in PIB_KERNEL_SRC", head)
            ref = head
        branch, commit = resolve_in(local, what, ref, head or pin["branch"])
        uncommitted_word(commit)
    else:
        what = url
        ref = ref or pin["branch"]
        mirror = check_mirror(url)
        if mirror:
            name = Path(mirror).name
            origin = local_git(mirror, "config", "remote.origin.url").stdout.strip()
            hint = (f"; refresh the mirror on the host: git -C <mirrors>/{name} remote update"
                    + (f" (its origin is {origin})" if origin else ""))
            branch, commit = resolve_in(mirror, f"the mirror {name}", ref,
                                        head_branch(mirror, f"the mirror {name}") or pin["branch"], hint)
        elif a.dry_run:
            branch, commit = ask_remote(url, ref, pin["branch"])
        else:
            clone_from = fetch_kernel_repo(url)
            branch, commit = resolve_in(clone_from, url, ref, default_branch(url) or pin["branch"])
    set_source(config, names["linux"], target, branch, commit, url)
    return branch, commit, what, ((url, str(clone_from)) if clone_from else None)


def ask_remote(url, ref, fallback):
    """resolve_in for a dry run, which fetches nothing: (branch, commit) asked of url. A commit
    goes with url's default branch, and GitHub is asked whether it has the commit at all."""
    if not COMMIT.fullmatch(ref):
        commit = branch_tip(url, ref)
        if not commit:
            cli.die(f"{url} has no branch {ref}")
        return ref, commit
    branch = default_branch(url) or fallback
    if not branch_tip(url, branch):
        cli.die(f"{url} has no branch {branch} to clone commit {ref} with: name a branch that holds it")
    if GITHUB.search(url):
        lacks = remote_lacks(url, branch, ref)
        if lacks:
            cli.die(f"{url} has no {lacks}: name a branch, or a commit it has; a commit that only "
                    "a copy of your own holds is built from that copy (PIB_KERNEL_SRC)")
    return branch, ref


def fit_key(ws):
    """The kernel FIT signing key, keys/fit-signing.{key,crt} (pib keys fit), presented to sbp as
    FIT_SIGN_KEYDIR/FIT_SIGN_KEYNAME: an RSA-2048 key, as linux.yaml signs with sha256,rsa2048."""
    key, crt = ws / "keys/fit-signing.key", ws / "keys/fit-signing.crt"
    if not key.is_file() or not crt.is_file():
        cli.die("the kernel FIT signing key keys/fit-signing.key (and .crt) is missing: "
                "run pib keys fit in this workspace first")
    if "Public-Key: (2048 bit)" not in cli.run(["openssl", "x509", "-in", crt, "-noout", "-text"]):
        cli.die("keys/fit-signing.crt must be an RSA-2048 certificate (the kernel FIT uses sha256,rsa2048)")
    if cli.run(["openssl", "x509", "-in", crt, "-noout", "-pubkey"]) != \
            cli.run(["openssl", "pkey", "-in", key, "-pubout"]):
        cli.die("keys/fit-signing.crt is not the certificate of keys/fit-signing.key")
    keydir = work() / "fit-key"  # the name sbp's kernel build signs with: pib (never SiMa.ai's dev)
    shutil.rmtree(keydir, ignore_errors=True)
    keydir.mkdir(parents=True)
    (keydir / "pib.key").symlink_to(key.resolve())
    (keydir / "pib.crt").symlink_to(crt.resolve())
    return {"FIT_SIGN_KEYDIR": str(keydir), "FIT_SIGN_KEYNAME": "pib"}


def jobs():
    """PIB_PACKAGE_JOBS, else the CPUs, fewer when memory is short (sbp runs make -j<CPUs>)."""
    want = os.environ.get("PIB_PACKAGE_JOBS")
    if want:
        if not want.isdigit() or int(want) < 1:
            cli.die(f"PIB_PACKAGE_JOBS must be a positive number, not {want!r}")
        return int(want)
    cpus = os.cpu_count() or 1
    try:
        avail = next(int(ln.split()[1]) for ln in Path("/proc/meminfo").read_text().splitlines()
                     if ln.startswith("MemAvailable:"))
    except (OSError, StopIteration, ValueError):
        return cpus
    return max(1, min(cpus, avail // (768 * 1024)))  # about 768 MiB per compiler job


def packages_index():
    """[{field: value}] of sbp's local repo (arm64), from reprepro's exported index."""
    dist = repo_dir() / "dists" / cli.container_codename() / "non-free/binary-arm64"
    if (dist / "Packages").is_file():
        text = (dist / "Packages").read_text()
    elif (dist / "Packages.gz").is_file():
        text = gzip.decompress((dist / "Packages.gz").read_bytes()).decode()
    else:
        return []
    out = []
    for stanza in text.split("\n\n"):
        f = dict(ln.split(": ", 1) for ln in stanza.splitlines() if ": " in ln and not ln.startswith(" "))
        if f.get("Package"):
            out.append(f)
    return out


def revision(version):
    m = re.search(r"-(\d+)$", version)
    return int(m[1]) if m else 0


def is_kernel(package, target):
    return re.fullmatch(rf"linux-image-.*-{re.escape(target)}", package) is not None


def next_kernel_build(index, target):
    """The kernel's Debian revision for a build from scratch: one above every kernel already in
    sbp's repo. The kernel counts its own builds from there (populate_build.sh seeds .version
    from BUILD); reprepro silently keeps a higher version over a lower one, so it must never go back."""
    return 1 + max((revision(f["Version"]) for f in index if is_kernel(f["Package"], target)), default=0)


def kernel_glob(ws, target):
    """The kernel package the image installs, e.g. linux-image-6.18.3-modalix* (image-params.yaml)."""
    params = (ws / "configs/images/image-params.yaml").read_text()
    m = re.search(r"(linux-image-[^\s,\]]*)", params)
    if not m:
        cli.die("configs/images/image-params.yaml names no linux-image package")
    return m[1].replace("${platform}", target)


def recipe(tree, config, skip=None):
    """A digest of a package's config directory in the build tree (its yaml as pinned, patches,
    scripts): a changed recipe must rebuild the package like a changed source. skip: lines left
    out of the config file itself (the kernel's pinned branch, which only carries sbp's clone)."""
    path = tree / "configs/packages" / config
    d = path.parent
    h = hashlib.sha256()
    for f in sorted(p for p in d.rglob("*") if p.is_file()):
        data = f.read_bytes()
        if skip is not None and f == path:
            data = skip.sub("", data.decode()).encode()
        h.update(str(f.relative_to(d)).encode() + b"\0" + data + b"\0")
    return h.hexdigest()[:16]


def stamp(name):
    return work() / "stamps" / name


def write_stamp(name, text):
    stamp(name).parent.mkdir(parents=True, exist_ok=True)
    stamp(name).write_text(text)


def run_sbp(tree, env, args):
    print("pib: sbp " + " ".join(args), flush=True)
    r = subprocess.run(["sbp", *args], cwd=tree, env=env)
    if r.returncode:
        cli.die(f"sbp failed (exit {r.returncode}); task logs: {work()}/packages/<package>/tmp/log "
                f"on the pib-package volume")


def built_kernel(index, ws, target):
    """The linux-image package in sbp's repo; it must be the one the image installs."""
    images = [f for f in index if is_kernel(f["Package"], target)]
    if len(images) != 1:
        cli.die(f"sbp's repo holds {len(images)} kernel packages, not 1 "
                f"({', '.join(sorted(f['Package'] + ' ' + f['Version'] for f in images))}): rebuild the "
                "kernel from scratch (pib package -p linux -t clean+), or start a new volume "
                "(set PIB_PACKAGE_VOLUME to a new name, or docker volume rm the old one)")
    glob = kernel_glob(ws, target)
    if not fnmatch.fnmatchcase(images[0]["Package"], glob):
        cli.die(f"the kernel package is {images[0]['Package']}, but the image installs {glob}: "
                "this kernel would be left out of the image")
    return images[0]


def headers_of(index, kernel):
    name = kernel["Package"].replace("linux-image-", "linux-headers-", 1)
    return next((f for f in index if f["Package"] == name and f["Version"] == kernel["Version"]), None)


def headers_id(index, kernel):
    """What a module build is stamped with: the kernel headers package it compiled against."""
    heads = headers_of(index, kernel) if kernel else None
    return heads and f"{heads['Package']} {heads['Version']} {heads.get('SHA256', '')}"


def wanted(index, picked, target, kernel):
    """The repo entries of what was asked for: the kernel set, smifb, lttng; never -dbg."""
    names = config_names(target)
    out = []
    for f in index:
        p = f["Package"]
        if p.endswith("-dbg"):
            continue
        if "linux" in picked and kernel and f["Version"] == kernel["Version"] and (
                p in (kernel["Package"], kernel["Package"].replace("linux-image-", "linux-headers-", 1))
                or p == "linux-libc-dev"):
            out.append(f)
        elif any(p == names[m] for m in picked if m in MODULES):
            out.append(f)
    return out


def root_owned(deb):
    """Every entry of the .deb's data belongs to root (sbp's dpkg-deb runs without --root-owner-group)."""
    bad = [ln for ln in cli.run(["dpkg-deb", "-c", deb]).splitlines() if ln.split()[1] != "root/root"]
    if bad:
        cli.die(f"{deb.name} has files not owned by root, e.g. {bad[0]}")


def deb_package(deb):
    return cli.run(["dpkg-deb", "-f", deb, "Package"]).strip()


def copy_debs(ws, entries, drop=()):
    """Put the repo's .debs in custom-debs/, replacing every .deb (and .sig) of the same packages,
    and of the packages in drop. Everything is checked before custom-debs/ changes."""
    debs = ws / cli.DEBS
    new = []
    for f in sorted(entries, key=lambda f: f["Package"]):
        src = repo_dir() / f["Filename"]
        if f.get("Architecture") not in ("arm64", "all"):
            cli.die(f"{src.name} is for {f.get('Architecture')}, not arm64")
        root_owned(src)
        new.append(src)
    gone = {f["Package"] for f in entries} | set(drop)
    old = [d for d in sorted(debs.glob("*.deb")) if deb_package(d) in gone]
    tmp = []
    try:
        for src in new:  # next to their final names: each rename below replaces atomically
            t = debs / f".{src.name}.pib-package"
            shutil.copyfile(src, t)
            tmp.append(t)
        out = []
        for src, t in zip(new, tmp):
            dst = debs / src.name
            if dst.is_file() and cli.sha256(dst) == cli.sha256(t):
                out.append(dst)  # the same build: it and its signature stay
                print(f"pib: {cli.DEBS}/{dst.name} (unchanged)")
                continue
            t.replace(dst)
            Path(f"{dst}.sig").unlink(missing_ok=True)  # a .sig of an older build of this file
            cli.chown(dst)
            out.append(dst)
            print(f"pib: {cli.DEBS}/{dst.name}")
        for d in old:  # only now: an interruption above leaves the old packages in place
            if d not in out:
                d.unlink()
                Path(f"{d}.sig").unlink(missing_ok=True)
                print(f"pib: removed {cli.DEBS}/{d.name}")
        return out
    finally:
        for t in tmp:
            t.unlink(missing_ok=True)


def uapi_report(cfg, ours):
    """Compare the SiMa.ai uapi headers (ISP calibration, MLA, ...) of the built linux-libc-dev
    with the release's: SiMa.ai's userspace (libcamera's ISP, simaai-mlart) is built against those."""
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        try:
            theirs = cli.release_deb("linux-libc-dev", cfg, d / "apt")
        except SystemExit as e:
            print(f"pib: note: could not fetch SiMa.ai's linux-libc-dev to compare uapi headers ({e})")
            return
        trees = {}
        for label, deb in (("ours", ours), ("theirs", theirs)):
            (d / label).mkdir()
            cli.run(["dpkg-deb", "-x", deb, d / label])
            trees[label] = {str(p.relative_to(d / label)): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (d / label).rglob("*") if p.is_file() and
                            str(p.relative_to(d / label)).startswith(UAPI)}
        differ = sorted(n for n in set(trees["ours"]) | set(trees["theirs"])
                        if trees["ours"].get(n) != trees["theirs"].get(n))
        if differ:
            print("pib: WARNING: this kernel's SiMa.ai uapi headers differ from the release's "
                  f"({len(differ)} files, e.g. {differ[0]}): SiMa.ai's prebuilt userspace (libcamera's "
                  "ISP, simaai-mlart) may refuse it", flush=True)
        else:
            print(f"pib: SiMa.ai uapi headers match the release ({len(trees['ours'])} files)")


def fit_report(copied):
    """A word when the kernel package carries no FIT (boot/fitImage), whose signature U-Boot
    checks: without one, pasha's simaai.bootloader installs the kernel's vmlinuz-* as Image,
    booted unsigned. SiMa.ai's kernel source packs and signs one (scripts/package/builddeb, with
    FIT_SIGN_KEYDIR); a kernel source that does not, such as an older release, makes none."""
    image = next((d for d in copied if d.name.startswith("linux-image-")), None)
    if image and not any(ln.split()[5:6] == ["./boot/fitImage"]
                         for ln in cli.run(["dpkg-deb", "-c", image]).splitlines()):
        print("pib: WARNING: the kernel package has no FIT (boot/fitImage): its source makes none, "
              "so the image boots this kernel unsigned, as Image", flush=True)


def check_arm64():
    try:
        ok = subprocess.run([ARM64_LOADER, "--version"], capture_output=True).returncode == 0
    except OSError:  # ENOEXEC without a binfmt handler, ENOENT without libc6:arm64
        ok = False
    if not ok:
        cli.die("this Docker host cannot run arm64 programs, which smifb and lttng-modules need "
                "(the kernel's headers carry arm64 build tools): run 'pib doctor' once, or use --no-modules")


def kernel_set(package, target):
    """The packages of one kernel build: its image and headers (and -dbg), and linux-libc-dev."""
    return package == "linux-libc-dev" or \
        re.fullmatch(rf"linux-(image|headers)-.+-{re.escape(target)}(-dbg)?", package) is not None


def drop_kernels(index, target):
    """Before a kernel build from scratch, take every kernel's packages out of sbp's repo. The repo
    keeps every package name it is given, so a kernel of another version (another release, or a
    fork's LOCALVERSION) would stay next to the new one and stop every later run (built_kernel),
    and it never takes a lower linux-libc-dev than it holds."""
    names = sorted({f["Package"] for f in index if kernel_set(f["Package"], target)})
    if names:
        cli.run(["reprepro", "-b", repo_dir(), "remove", cli.container_codename(), *names])


def build_kernel(a, tree, env, flags, index, target, names, commit, fit_crt, config):
    """Run sbp for the kernel. Its work tree is rebuilt from scratch whenever the source (the
    commit), its recipe or the FIT key changed: sbp's done markers follow none of them, and only a
    full rebuild re-fetches and re-signs. The pinned branch only carries sbp's clone and is not
    part of the source. The stamp names what the work tree holds, so it is written only once sbp
    succeeded."""
    st = stamp(names["linux"])
    source = " ".join((commit, "recipe:" + recipe(tree, config, skip=BRANCH_LINE),
                       "fit:" + cli.sha256(fit_crt)[:16]))
    tasks = a.tasks
    if (work() / "packages" / names["linux"]).exists() and (not st.exists() or st.read_text() != source):
        if tasks not in (None, "clean+"):
            cli.die(f"the kernel source, recipe or FIT key changed ({source}): it is built from scratch, "
                    f"so -t {tasks} does not apply; drop it")
        tasks = "clean+"
        print(f"pib: the kernel source, recipe or FIT key changed ({source}): building it from scratch")
        if not a.dry_run:
            st.unlink(missing_ok=True)
    elif not a.dry_run and not st.exists():
        write_stamp(names["linux"], source)  # a first build: its work tree comes from this source
    env["BUILD"] = str(next_kernel_build(index, target))  # counted first: numbers only go up
    scratch = tasks == "clean+" or not (work() / "packages" / names["linux"]).exists()
    if scratch and not a.dry_run:
        drop_kernels(index, target)
    run_sbp(tree, env, ["package", "-p", names["linux"], *(["-t", tasks] if tasks else []), *flags])
    if not a.dry_run:
        write_stamp(names["linux"], source)


def module_id(index, kernel, tree, configs, m):
    """What a module's stamp holds: the kernel headers it compiled against, and its recipe."""
    heads = headers_id(index, kernel)
    return heads and f"{heads} recipe:{recipe(tree, configs[m])}"


def build_modules(a, tree, env, flags, index, modules, names, kernel, explicit, configs):
    """Rebuild each module that is not built against this kernel's headers and its own recipe yet
    (or that was asked for by name), from scratch: sbp's done markers follow neither, and only a
    full rebuild takes the headers just published. One stamp per module."""
    current = {m: module_id(index, kernel, tree, configs, m) for m in modules}
    have = {f["Package"] for f in index}
    stale = [m for m in modules if explicit or not current[m] or names[m] not in have or
             not stamp(names[m]).exists() or stamp(names[m]).read_text() != current[m]]
    for m in modules:
        if m not in stale:
            print(f"pib: {names[m]} is already built against this kernel")
    if not stale:
        return
    # REPO set: sbp takes the kernel headers from its repo and never adds an unbuilt kernel to
    # this run (unsigned, BUILD unset); REPO_PULL, not REPO, names the apt source (setup.sh).
    run_sbp(tree, dict(env, REPO="http://localhost"),
            ["package", "-p", ",".join(names[m] for m in stale), "-t", "clean+", *flags])
    if not a.dry_run:
        for m in stale:
            write_stamp(names[m], current[m] or "")


def cmd_package(argv):
    a = parse(argv)
    if os.environ.get("PIB_PACKAGE_SETUP") != "1":  # exported by sbp/setup.sh
        cli.die("pib package needs its set-up (sbp/setup.sh), which the image runs when the pib "
                "launcher starts pib package: run it on the host, not inside pib shell")
    ws = Path.cwd()
    if a.list and not (ws / "image.yaml").is_file():
        cfg = {"target": "modalix", "base": None}  # listing needs no workspace
    else:
        cfg = cli.load_config(ws)
    target = cfg["target"]
    if not a.list and cfg["base"] == "securepalette":
        cli.die("securepalette images check the kernel FIT against SiMa.ai's U-Boot key, which a "
                "kernel built here is not signed with; use minimal or palette")
    src, src_name = source_tree()
    tree, sources = prepare_tree(src, target)
    # sbp gets the environment without pib's own kernel settings: they are in the kernel's config.
    env = {k: v for k, v in os.environ.items() if not k.startswith("PIB_KERNEL_")}
    env["PIB_PKGBUILD_SRC"] = str(src)  # for the sbp wrapper (sbp/sbp)
    if a.list:
        print(f"pib: sbp and its package configs: {src_name}")
        run_sbp(tree, env, ["list", *(["--debug"] if a.debug else [])])
        return
    names = config_names(target)
    picked = list(a.picked)
    if "linux" in picked and cfg["base"] in WITH_MODULES and not a.no_modules:
        added = [m for m in MODULES if m not in picked]
        if added:
            picked += added
            print(f"pib: {cfg['base']} images carry the kernel modules smifb and lttng-modules: "
                  "they follow this kernel (--no-modules builds the kernel alone)")
    modules = [m for m in MODULES if m in picked]
    print(f"pib: sbp and its package configs: {src_name}")
    commit = None
    if "linux" in picked:
        branch, commit, where, clone_from = resolve_kernel(a, tree, sources, names, target)
        print(f"pib: kernel: {where} {branch} @ {commit}")
        if clone_from:  # (url, the volume's copy of it): sbp clones the kernel from the copy
            git_map(env, *clone_from)
        env.update(fit_key(ws))  # only the kernel signs anything
    env["PYTHON_CPU_COUNT"] = str(jobs())  # sbp's -j and git --jobs come from os.cpu_count()
    print(f"pib: {env['PYTHON_CPU_COUNT']} parallel jobs (PIB_PACKAGE_JOBS)")
    if modules:
        check_arm64()
    flags = ["-g", "all", *(["--dry-run"] if a.dry_run else []), *(["--debug"] if a.debug else []),
             *(["--no-ccache"] if a.no_ccache else [])]
    index = packages_index()
    if "linux" in picked:
        build_kernel(a, tree, env, flags, index, target, names, commit, ws / "keys/fit-signing.crt",
                     CONFIGS["linux"])
        if not a.dry_run:
            index = packages_index()
    kernel = None
    if not a.dry_run:
        if any(is_kernel(f["Package"], target) for f in index):
            kernel = built_kernel(index, ws, target)
        if modules and not kernel:
            cli.die("build the kernel first: pib package -p linux")
    if modules:
        build_modules(a, tree, env, flags, index, modules, names, kernel, explicit="linux" not in picked,
                      configs=CONFIGS)
        if not a.dry_run:
            index = packages_index()
    if a.dry_run:
        print("pib: dry run: nothing copied to custom-debs/")
        return
    entries = wanted(index, picked, target, kernel)
    missing = [p for p in picked if p in MODULES and not any(f["Package"] == names[p] for f in entries)]
    if missing or ("linux" in picked and not kernel):
        cli.die(f"sbp's repo lacks {', '.join(names[m] for m in missing) or 'the kernel'} after the build")
    # A module package not built against this kernel must not stay next to it: dropped, so the
    # image takes SiMa.ai's (--no-modules) or the user rebuilds it (pib package -p <module>).
    drop = []
    if "linux" in picked:
        for m in MODULES:
            current = module_id(index, kernel, tree, CONFIGS, m)
            if m not in picked and (not stamp(names[m]).exists() or stamp(names[m]).read_text() != current):
                drop.append(names[m])
    copied = copy_debs(ws, entries, drop)
    fit_report(copied)
    libc = next((d for d in copied if d.name.startswith("linux-libc-dev_")), None)
    if libc:
        uapi_report(cfg, libc)
    print(f"pib: {len(copied)} packages in {cli.DEBS}/; next: pib sign-debs, then pib build")
