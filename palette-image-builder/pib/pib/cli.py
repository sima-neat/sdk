"""pib: SiMa.ai Palette Image Builder. Runs inside the PIB container."""
import argparse
import contextlib
import hashlib
import gzip
import json
import lzma
import os
import re
import secrets
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from pib import __version__

DEBS = "custom-debs"
BAKED_CONFIGS = Path("/usr/share/pib/configs")  # the image configs shipped in the container
RELEASE_FILE = Path("/etc/pib-release")  # the release this container builds (from RELEASE)
CODENAME_FILE = Path("/etc/pib-codename")  # its eLxr suite (from CODENAME)
VERSION_RE = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)")  # use fullmatch
# image.yaml fields and the type each must have (release/version/slots may be numbers).
FIELDS = {"base": str, "target": str, "release": (str, int, float), "version": (str, int, float),
          "slots": (str, int, float), "packages": dict, "overlay": str, "hooks": list,
          "signing": dict, "debs": dict, "vendor": (str, int, float), "swu": dict,
          "sources": list, "sima_source": str, "encryption": dict}
AES_KEY_RE = re.compile(r"[0-9a-f]{64} [0-9a-f]{32}")  # swupdate -K file: <key> <ivt>
ENCRYPTED = ("rootfs.ext4.gz", "boot.vfat.gz")  # the payloads pib sign --encrypt covers
SAFE_PATH = re.compile(r"^[A-Za-z0-9_./+-]+$")  # paths that go into YAML and a shell command line
# Repo-root items the image hooks reach through CURRENT_DIR or symlinks.
REPO_ITEMS = ("elxr-config", "scripts/build_scripts/prepare_buildinfo.sh",
              "scripts/extract_licenses.py")
TEMPLATE = """\
base: {flavor}            # minimal | palette | securepalette
target: {target}
slots: ab                   # ab = rootfs.A + rootfs.B | a = single slot
release: {release}        # SiMa.ai release; must match the container
version: {release}.1      # <release>.<build>, build 1..65535
packages:
  add: []
  remove: []
overlay: overlay/         # copied over / after SiMa.ai's overlays
hooks: []                 # run after SiMa.ai's customize hooks
signing:
  cert: keys/swu-signing.crt
  key: keys/swu-signing.key   # pib sign also takes --pkcs11 <uri>
  ca: keys/ca.crt             # boards trust it: /etc/swupdate/swupdate.crt
debs:
  key: keys/debs-signing.asc  # custom-debs/*.deb need a <name>.deb.sig by this key
# encryption: {{key: keys/payload.key}}   # pib keys payload; for pib sign --encrypt
# vendor: Acme              # written to /etc/buildinfo
# swu: {{description: swu/sw-description, script: swu/update.sh}}
# sources: ["deb http://mirror.corp/debian trixie main"]   # replaces the Debian/eLxr lines
# sima_source: "deb [signed-by=...] http://mirror.corp/sima agate non-free"
"""


GITIGNORE = """\
# written by pib init: secrets and build output stay out of git
keys/*.key
keys/*.secret.asc
keys/.pib-renew-*/
out/
build/
"""


UPDATE_WRAPPER = """\
#!/bin/sh
# Install a .swu, trusting only this image's own certificate (see /etc/swupdate.cfg).
[ $# -ge 1 ] || { echo "usage: simaai-update <bundle> [swupdate options]" >&2; exit 2; }
bundle=$1
shift
exec swupdate -f /etc/swupdate.cfg -i "$bundle" "$@"
"""


def die(msg):
    sys.exit(f"pib: {msg}")


def run(cmd, **kw):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True, **kw)
    if r.returncode:
        die(f"{cmd[0]} failed: {r.stderr.strip()}")
    return r.stdout


def chown(*paths):
    """Hand root-made files back to the host user (PIB_UID/PIB_GID from the shim)."""
    uid, gid = os.environ.get("PIB_UID"), os.environ.get("PIB_GID")
    if uid and gid:
        for root in map(Path, paths):
            for p in [root, *(root.rglob("*") if root.is_dir() else [])]:
                st = p.lstat()  # chown clears setuid/setgid even to the same owner
                if (st.st_uid, st.st_gid) != (int(uid), int(gid)):
                    os.chown(p, int(uid), int(gid), follow_symlinks=False)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- keys -------------------------------------------------------------------

def newkey(algo):
    return ["rsa:4096"] if algo == "rsa4096" else \
        ["ec", "-pkeyopt", "ec_paramgen_curve:secp384r1"]


def subj(cn, role):
    if any(ch in cn for ch in "/\\+"):  # RDN separators in openssl -subj
        die("--cn must not contain /, \\ or +")
    return f"/CN={cn} {role}"


RENEW_TMP = ".pib-renew-"  # work dir in keys/; holds a key copy while the pair is swapped


@contextlib.contextmanager
def clean_on_signal():
    """Turn SIGTERM and SIGHUP into an exit, so the with-blocks below delete their key copies."""
    def stop(sig, frame):
        sys.exit(128 + sig)
    old = {s: signal.signal(s, stop) for s in (signal.SIGTERM, signal.SIGHUP)}
    try:
        yield
    finally:
        for s, h in old.items():
            signal.signal(s, h)


def gen_leaf(out, algo, cn):
    """Write swu-signing.{key,crt}, issued by ca.{key,crt} in out, over any old pair."""
    for stale in out.glob(RENEW_TMP + "*"):  # left by a run that was killed (SIGKILL)
        shutil.rmtree(stale, ignore_errors=True)
    with clean_on_signal(), tempfile.TemporaryDirectory(prefix=RENEW_TMP, dir=out) as d:
        d = Path(d)
        run(["openssl", "req", "-newkey", *newkey(algo), "-nodes",
             "-keyout", d / "swu-signing.key", "-out", d / "leaf.csr",
             "-subj", subj(cn, "SWU signing")])
        (d / "leaf.ext").write_text(
            "basicConstraints=CA:FALSE\nkeyUsage=critical,digitalSignature\n"
            "extendedKeyUsage=codeSigning,emailProtection\n")
        run(["openssl", "x509", "-req", "-in", d / "leaf.csr",
             "-CA", out / "ca.crt", "-CAkey", out / "ca.key",
             "-CAserial", d / "ca.srl", "-CAcreateserial",
             "-out", d / "swu-signing.crt", "-days", "825",
             "-extfile", d / "leaf.ext"])
        (d / "swu-signing.key").chmod(0o600)
        # An expired or non-CA ca.crt signs without error; stop before the old pair goes.
        check_issued(d / "swu-signing.crt", out / "ca.crt")
        # If the certificate swap fails, the old key goes back so the pair still matches.
        old = out / "swu-signing.key"
        if old.exists():
            shutil.copy2(old, d / "old.key")
        os.replace(d / "swu-signing.key", old)
        try:
            os.replace(d / "swu-signing.crt", out / "swu-signing.crt")
        except BaseException:
            if (d / "old.key").exists() and (d / "swu-signing.crt").exists():
                os.replace(d / "old.key", old)
            raise


def gen_keys(out, algo="rsa4096", cn="Customer"):
    """Write ca.{key,crt} and a CA-issued swu-signing.{key,crt} into out."""
    out, ca_subj = Path(out), subj(cn, "SWU CA")  # reject a bad cn before mkdir
    out.mkdir(parents=True, exist_ok=True)
    if (out / "ca.key").exists():
        die(f"{out}/ca.key exists; refusing to overwrite keys")
    run(["openssl", "req", "-x509", "-newkey", *newkey(algo), "-nodes",
         "-keyout", out / "ca.key", "-out", out / "ca.crt",
         "-subj", ca_subj, "-days", "3650",
         "-addext", "basicConstraints=critical,CA:TRUE",
         "-addext", "keyUsage=critical,keyCertSign,cRLSign"])
    (out / "ca.key").chmod(0o600)
    gen_leaf(out, algo, cn)


def gpg(home, *args):
    return run(["gpg", "--batch", "--homedir", home, *args])


@contextlib.contextmanager
def gpg_home():
    with tempfile.TemporaryDirectory() as h:
        try:
            yield h
        finally:
            subprocess.run(["gpgconf", "--homedir", h, "--kill", "all"],
                           capture_output=True)


def gen_deb_key(out, cn="Customer"):
    """Write debs-signing.asc (public) and debs-signing.secret.asc."""
    out = Path(out)
    with gpg_home() as h:
        gpg(h, "--passphrase", "", "--pinentry-mode", "loopback",
            "--quick-gen-key", f"{cn} deb signing", "ed25519", "sign", "never")
        (out / "debs-signing.asc").write_text(gpg(h, "--armor", "--export"))
        (out / "debs-signing.secret.asc").touch(mode=0o600)  # before the key goes in
        (out / "debs-signing.secret.asc").write_text(
            gpg(h, "--armor", "--export-secret-keys"))


def key_fingerprint(keyfile):
    for ln in run(["gpg", "--show-keys", "--with-colons", keyfile]).splitlines():
        if ln.startswith("fpr:"):
            return ln.split(":")[9]
    die(f"{keyfile} holds no OpenPGP key")


def cmd_sign_debs(a):
    debs = sorted((Path.cwd() / DEBS).glob("*.deb"))
    if not debs:
        die(f"no .debs in {DEBS}/")
    with gpg_home() as h:
        gpg(h, "--import", a.key)
        for deb in debs:
            gpg(h, "--yes", "--detach-sign", "--output", f"{deb}.sig", deb)
            chown(f"{deb}.sig")
            print(f"pib: wrote {DEBS}/{deb.name}.sig")


def cmd_keys_init(a):
    for name in ("ca.key", "ca.crt", "swu-signing.key", "swu-signing.crt",
                 "debs-signing.asc", "debs-signing.secret.asc"):
        if (Path(a.out) / name).exists():
            die(f"{Path(a.out)}/{name} exists; refusing to overwrite keys")
    gen_keys(a.out, a.algo, a.cn)
    gen_deb_key(a.out, a.cn)
    chown(a.out)
    print(f"pib: keys written to {a.out}; keep ca.key offline")


def gen_payload_key(out):
    """Write payload.key: '<AES-256 key> <ivt>' in hex, the file swupdate -K reads."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    f = out / "payload.key"
    if f.exists():
        die(f"{f} exists; refusing to overwrite the payload key")
    with os.fdopen(os.open(f, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as h:
        h.write(f"{secrets.token_hex(32)} {secrets.token_hex(16)}\n")


def cmd_keys_payload(a):
    gen_payload_key(a.out)
    chown(a.out)
    print(f"pib: payload key written to {a.out}/payload.key; set encryption.key in "
          "image.yaml so the image holds it, and keep it secret")


def gen_fit_key(out, cn="Customer"):
    """Write fit-signing.{key,crt}: the RSA-2048 key a kernel built by pib sbp signs its FIT
    with (the kernel's FIT_SIGN_ALGO is sha256,rsa2048), and its certificate."""
    out, cn_subj = Path(out), subj(cn, "kernel FIT")
    out.mkdir(parents=True, exist_ok=True)
    key, crt = out / "fit-signing.key", out / "fit-signing.crt"
    if key.exists() or crt.exists():
        die(f"{out}/fit-signing.key or .crt exists; refusing to overwrite keys")
    run(["openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:2048", "-out", key])
    key.chmod(0o600)
    run(["openssl", "req", "-batch", "-new", "-x509", "-days", "3650", "-key", key,
         "-subj", cn_subj, "-out", crt])


def cmd_keys_fit(a):
    gen_fit_key(a.out, a.cn)
    chown(a.out)
    print(f"pib: kernel FIT signing key written to {a.out}/fit-signing.key (keep it secret) "
          "and .crt, for pib sbp")


def read_aes_key(path):
    """The hex AES key of a payload key file."""
    f = Path(path)
    if not f.is_file():
        die(f"{f} not found (pib keys payload creates it)")
    text = f.read_text().strip()
    if not AES_KEY_RE.fullmatch(text):
        die(f"{f} must hold '<64 hex key> <32 hex ivt>' on one line")
    return text.split()[0]


def cmd_keys_renew(a):
    out = Path(a.out)
    for name in ("ca.key", "ca.crt"):
        if not (out / name).is_file():
            die(f"{out}/{name} not found; a new signing leaf needs the CA")
    try:
        gen_leaf(out, a.algo, a.cn)
    except OSError as e:
        die(f"cannot write the new signing leaf: {e}")
    chown(out / "swu-signing.key", out / "swu-signing.crt")
    print(f"pib: new signing leaf written to {out}; keep ca.key offline")


# ---- workspace --------------------------------------------------------------

def container_release():
    """The container's release; SIMA_RELEASE stands in for it outside the container."""
    return RELEASE_FILE.read_text().strip() if RELEASE_FILE.exists() else os.environ.get("SIMA_RELEASE")


def container_codename():
    """The container's eLxr suite; PIB_CODENAME stands in for it outside the container."""
    return CODENAME_FILE.read_text().strip() if CODENAME_FILE.exists() else os.environ.get("PIB_CODENAME")


def sima_release_line(cfg):
    """The SiMa.ai apt line: image.yaml sima_source, else this container's release repo and suite."""
    if cfg.get("sima_source"):
        return str(cfg["sima_source"])
    url, codename = os.environ.get("PIB_SIMA_APT_URL"), container_codename()
    if not (url and codename):
        die("PIB_SIMA_APT_URL or /etc/pib-codename is missing; run inside the PIB container")
    return f"deb [signed-by=/usr/share/keyrings/simaai-public.gpg] {url} {codename} non-free"


def cmd_init(a):
    example = getattr(a, "example", None)
    if example:
        a.flavor = "minimal"
        example_dir = BAKED_CONFIGS.parent / "examples" / example
        if not (example_dir / "image.yaml").is_file():
            die(f"example {example!r} is not shipped in this container")
    ws = Path(a.dir)
    if (ws / "image.yaml").exists():
        die(f"{ws}/image.yaml exists")
    configs = Path(a.configs or os.environ.get("PIB_CONFIGS")
                   or ("configs" if Path("configs").is_dir() else BAKED_CONFIGS))
    ref = configs / "images" / f"image-{a.flavor}-{a.target}.yaml"
    if not ref.is_file():
        die(f"reference config {ref} not found (see --configs)")
    release = a.release or container_release()
    if not release:
        die("--release or SIMA_RELEASE is required")
    if not re.fullmatch(r"\d+\.\d+\.\d+", release):
        die(f"release {release!r} must be numeric <major>.<minor>.<patch>")
    if example:
        sample = read_yaml(example_dir / "image.yaml")
        if str(sample.get("release")) != release:
            die(f"example release {sample.get('release')} != requested release {release}")
    ws.mkdir(parents=True, exist_ok=True)
    repo = configs.resolve().parent
    for rel in ("configs", *REPO_ITEMS):
        src, dst = (configs if rel == "configs" else repo / rel), ws / rel
        if not src.exists():  # e.g. elxr-config, which only the container carries
            src = BAKED_CONFIGS.parent / rel
        if not src.exists():
            print(f"pib: warning: {src} not found; the build may fail",
                  file=sys.stderr)
        elif src.resolve() != dst.resolve():
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst, symlinks=True, dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)
    for d in (DEBS, "overlay", "hooks", "keys"):
        (ws / d).mkdir(exist_ok=True)
    (ws / "image.yaml").write_text(TEMPLATE.format(
        flavor=a.flavor, target=a.target, release=release))
    if example:
        shutil.copytree(example_dir, ws, symlinks=True, dirs_exist_ok=True)
    if not (ws / ".gitignore").exists():
        (ws / ".gitignore").write_text(GITIGNORE)
    chown(ws)
    print(f"pib: workspace ready in {ws}")


def read_yaml(f):
    try:
        cfg = yaml.safe_load(f.read_text()) or {}
    except yaml.YAMLError as ex:
        die(f"{f} is not valid YAML: {ex}")
    if not isinstance(cfg, dict):
        die(f"{f} must hold a mapping of fields")
    return cfg


def load_config(ws):
    f = ws / "image.yaml"
    if not f.is_file():
        die(f"{f} not found; run 'pib init' first")
    cfg = read_yaml(f)
    missing = [k for k in ("base", "target", "release", "version")
               if k not in cfg]
    if missing:
        die(f"image.yaml lacks {', '.join(missing)}")
    unknown = sorted(set(cfg) - FIELDS.keys())
    if unknown:
        die(f"image.yaml: unknown field {', '.join(unknown)}")
    for key, kind in FIELDS.items():
        if key in cfg and cfg[key] is not None and not isinstance(cfg[key], kind):
            want = {list: "a list", dict: "a mapping", str: "text"}.get(kind, "text or a number")
            die(f"image.yaml: {key} must be {want}")
    if not all(isinstance(h, str) for h in cfg.get("hooks") or []):
        die("image.yaml: hooks must be a list of script file names")
    cfg["release"], cfg["version"] = str(cfg["release"]), str(cfg["version"])
    m = VERSION_RE.fullmatch(cfg["version"])
    if not m or cfg["version"].rsplit(".", 1)[0] != cfg["release"] or \
            any(int(x) > 65535 for x in m.groups()) or int(m[4]) < 1:
        die(f"version {cfg['version']} must be {cfg['release']}.<build>, "
            "numeric, with build 1..65535")
    env = container_release()
    if env and env != cfg["release"]:
        die(f"image.yaml release {cfg['release']} != container release {env}")
    return cfg


def check_deb_signature(debs, keyfile):
    """Die unless each deb has a valid detached <deb>.sig from the key in keyfile."""
    fpr = key_fingerprint(keyfile)
    with gpg_home() as h:
        gpg(h, "--import", keyfile)
        for deb in debs:
            sig = Path(f"{deb}.sig")
            if not sig.is_file():
                die(f"{deb.name} is not signed: {sig.name} not found")
            r = subprocess.run(["gpg", "--batch", "--homedir", h, "--status-fd", "1",
                                "--verify", str(sig), str(deb)],
                               capture_output=True, text=True)
            valid = [ln.split() for ln in r.stdout.splitlines()
                     if ln.startswith("[GNUPG:] VALIDSIG")]
            good = any(ln.startswith("[GNUPG:] GOODSIG") for ln in r.stdout.splitlines())
            if r.returncode or not good or len(valid) != 1 or valid[0][-1].upper() != fpr.upper():
                die(f"{deb.name} is not signed by the customer key {fpr}")


ROOTS = (("troot-", "tRoot"), ("atf-", "ATF"))  # roots of trust: only SiMa.ai's repo supplies them


def boot_chain(target):
    """(label, package-name pattern) of what the image must hold exactly once."""
    t = re.escape(target)
    return (("kernel", rf"^linux-image-\d.*-{t}$"), ("U-Boot", f"^u-boot-{t}$"),
            ("ATF", f"^atf-{t}$"))


def check_unique_debs(debs):
    """Reject ambiguous local repositories before reprepro can discard a version."""
    records = []
    seen = {}
    for deb in debs:
        f = dict(ln.split(": ", 1) for ln in run(["dpkg-deb", "-f", deb, "Package", "Version",
                                                  "Architecture"]).splitlines() if ": " in ln)
        pkg = f.get("Package", "")
        ver = f.get("Version", "")
        if pkg in seen:
            previous, previous_version = seen[pkg]
            die(f"duplicate custom package {pkg}: {previous.name} ({previous_version}) and "
                f"{deb.name} ({ver}); keep only one .deb per package in {DEBS}/")
        seen[pkg] = (deb, ver)
        records.append((deb, f))
    return records


def check_debs(ws, cfg):
    """Return [(package, version)] for custom-debs/: signed by the customer
    key and arm64 or all."""
    debs = sorted((ws / DEBS).glob("*.deb"))
    keyfile = (cfg.get("debs") or {}).get("key")
    if debs:
        if not keyfile:
            die("custom .debs must be signed: set debs.key in image.yaml")
        check_deb_signature(debs, ws / keyfile)
    found = []
    for deb, f in check_unique_debs(debs):
        arch, pkg = f.get("Architecture", ""), f.get("Package", "")
        if arch not in ("arm64", "all"):
            die(f"{deb.name} is for {arch}, not arm64")
        for pre, what in ROOTS:
            if pkg.startswith(pre):
                die(f"{pkg}: {what} comes from SiMa.ai's repo and cannot be replaced")
        if pkg == f"u-boot-{cfg['target']}":
            die(f"{pkg}: the board runs the U-Boot inside fip.bin from SiMa.ai's ATF package, "
                "so a custom U-Boot would be refused at the end of the build")
        found.append((pkg, f.get("Version", "")))
    for label, pat in boot_chain(cfg["target"]):
        same = [p for p, _ in found if re.match(pat, p)]
        if len(same) > 1:
            die(f"custom-debs/ holds more than one {label} package: {', '.join(same)}")
    return found


def check_repo(debs):
    """Every custom .deb must be in the signed local repo the entrypoint built."""
    repo = Path(os.environ.get("PIB_REPO_DIR", "/var/www/html/deb/custom"))
    codename = container_codename()
    if not codename:
        die("/etc/pib-codename is missing; run inside the PIB container")
    dist = repo / "dists" / codename
    if not (dist / "Release").is_file():
        die(f"local repo {dist} is not published; start via the entrypoint")
    index = dist / "non-free/binary-arm64/Packages"
    have = set()
    for stanza in (index.read_text() if index.is_file() else "").split("\n\n"):
        f = dict(ln.split(": ", 1) for ln in stanza.splitlines() if ": " in ln)
        have.add((f.get("Package"), f.get("Version")))
    for pkg, ver in debs:
        if (pkg, ver) not in have:
            die(f"{pkg} {ver} is missing from the local repo; restart the "
                "container after changing custom-debs/")


def sub1(text, pattern, repl, what):
    new, n = re.subn(pattern, repl, text, flags=re.M)
    if n != 1:
        die(f"reference config changed: {what} matched {n} times, expected 1")
    return new


def check_description(text, members):
    """Die unless a customer sw-description can be stamped and installed."""
    plain = strip_comments(text)
    for ph in ("@@VERSION@@", "@@HW_COMPAT@@"):
        if ph not in plain:
            die(f"swu.description lacks {ph}")
    arts = list(artifacts(text))
    for name, digest in arts:
        if name not in members:
            die(f"swu.description installs {name}, which the bundle does not carry")
        if digest != f"@@{name}@@".lower():
            die(f"swu.description: sha256 of {name} must be @@{name}@@")
    for need in ("boot0.be", "sbom.cdx.json"):
        if need not in dict(arts):
            die(f"swu.description must list {need}")


def write_effective(ws, cfg, version, trust, debs, aes_key, supplier):
    """Write pib-* copies of the reference flavor, params and stages.

    trust is installed in the rootfs as /etc/swupdate/swupdate.crt
    with an /etc/swupdate.cfg that uses it and refuses older versions; debs
    (package, version) are pinned so apt leaves them in place; aes_key (a key
    file) is installed for swupdate to decrypt encrypted bundles; supplier
    names the SBOM's distro supplier.
    """
    img = ws / "configs/images"
    base = cfg["base"]
    flavor_f = img / f"image-{base}-{cfg['target']}.yaml"
    if not flavor_f.is_file():
        die(f"reference config {flavor_f} not found")
    pk = cfg.get("packages") or {}
    adds, removes = pk.get("add") or [], pk.get("remove") or []
    if not all(isinstance(p, str) for p in [*adds, *removes]) or \
            isinstance(pk.get("add"), str) or isinstance(pk.get("remove"), str):
        die("packages.add/remove must be lists of package names")
    extra = [json.dumps(p) for p in [*adds, *(f"{p}-" for p in removes)]]

    flavor = sub1(flavor_f.read_text(), r"^version: .*$",
                  lambda m: f"version: {version}", "version line")
    flavor = sub1(flavor, r"package:image-params\.yaml",
                  lambda m: "package:pib-params.yaml", "params reference")
    flavor = sub1(flavor, r"package:image-stages\.yaml",
                  lambda m: "package:pib-stages.yaml", "stages reference")

    params = (img / "image-params.yaml").read_text()
    if extra:
        params = sub1(
            params, rf"^(packages_{re.escape(base)}): (.*)$",
            lambda m: f"{m[1]}: ${{concat:{m[2]},[{','.join(extra)}]}}",
            "package list")

    stages = sub1((img / "image-stages.yaml").read_text(), r"--distro-supplier SiMa\.ai$",
                  lambda m: f"--distro-supplier={shlex.quote(supplier)}", "SBOM supplier")
    rel = str(cfg.get("overlay", "overlay") or "")
    overlay = ws / rel
    if ws.resolve() not in overlay.resolve().parents:
        die(f"image.yaml: overlay must be a folder inside the workspace, not {rel!r}")
    # pib init writes the default "overlay/"; git drops that folder while empty.
    if Path(rel) != Path("overlay") and not overlay.is_dir():
        die(f"overlay folder {overlay} not found")
    syncs = [img / "overlay/elxr", img / "overlay/simaai"]
    if overlay.is_dir() and any(overlay.iterdir()):
        syncs.append(overlay.resolve())
    tdir = ws / "build/trust"
    shutil.rmtree(tdir, ignore_errors=True)
    (tdir / "etc/swupdate").mkdir(parents=True)
    syncs.append(tdir.resolve())
    shutil.copy(trust, tdir / "etc/swupdate/swupdate.crt")
    (tdir / "etc/swupdate.cfg").write_text(
        'globals :\n{\n\tpublic-key-file = "/etc/swupdate/swupdate.crt";\n'
        + ('\taes-key-file = "/etc/swupdate/aes.key";\n' if aes_key else "")
        + f'\tno-downgrading = "{version}";\n}};\n')
    (tdir / "usr/bin").mkdir(parents=True)
    (tdir / "usr/bin/simaai-update").write_text(UPDATE_WRAPPER)
    (tdir / "usr/bin/simaai-update").chmod(0o755)
    if aes_key:
        (tdir / "etc/swupdate/aes.key").touch(mode=0o600)
        (tdir / "etc/swupdate/aes.key").write_text(Path(aes_key).read_text())
    if debs:
        (tdir / "etc/apt/preferences.d").mkdir(parents=True)
        (tdir / "etc/apt/preferences.d/99pib-custom").write_text("".join(
            f"Package: {p}\nPin: version {v}\nPin-Priority: 1001\n\n"
            for p, v in debs))
    # sync-in keeps each file's on-disk owner, the host user after pib init, so
    # every overlay goes in as a tar whose members are all root:root instead.
    sdir = ws / "build/sync"
    shutil.rmtree(sdir, ignore_errors=True)
    sdir.mkdir(mode=0o700, parents=True)
    for i, d in enumerate(syncs):
        run(["tar", "-C", d, "--owner=0", "--group=0", "--xattrs",
             "-cf", sdir / f"{i}.tar", "."])
    stages = sub1(
        stages, r"^( *)- 'sync-in overlay/elxr/ /'\n\1- 'sync-in overlay/simaai/ /'$",
        lambda m: "\n".join(f"{m[1]}- 'tar-in {sdir.resolve()}/{i}.tar /'"
                            for i in range(len(syncs))),
        "overlay sync")
    hooks = [ws / h for h in cfg.get("hooks") or []]
    for h in hooks:
        if not h.is_file():
            die(f"hook {h} not found")
    for h in [*hooks, ws / "build"]:
        if not SAFE_PATH.fullmatch(str(h.resolve())):
            die(f"{h.resolve()}: paths used in hooks may only hold letters, "
                "digits and _ . / + -")
    vendor = str(cfg.get("vendor") or "")
    if re.search(r"[\x00-\x1f\x7f]", vendor):
        die("vendor must be a single line of text")
    if not re.fullmatch(r"[a-z0-9_]+", cfg["target"]):
        die(f"target {cfg['target']!r} has unsupported characters")
    # Runs last: tags package origins, checks one boot chain, adds the vendor.
    finish = f"pib _finish $1 {(ws / 'build').resolve()}"
    items = ",".join(json.dumps(x) for x in
                     [*(f"sh {h.resolve()} $1" for h in hooks), finish])
    stages = sub1(
        stages,
        r"^( *customize_hooks: )(\$\{oc\.select:params\.hooks_\$\{flavor\}\})$",
        lambda m: f"{m[1]}${{concat:{m[2]},[{items}]}}", "customize hooks")

    def member(path, what):
        f = ws / str(path)
        if not f.is_file() or not f.stat().st_size:
            die(f"{what} {f} not found or empty")
        if "${" in str(f.resolve()):
            die(f"{what} path must not contain '${{'")
        return f.resolve()

    swu = cfg.get("swu") or {}
    (ws / "build/policy.json").write_text(json.dumps({
        "base": base, "dev": version.endswith("-dev"), "target": cfg["target"], "vendor": vendor,
        "own_sources": bool(cfg.get("sima_source") or cfg.get("sources"))}))
    script = "update_modalix.sh"
    if swu.get("script"):
        sc = member(swu["script"], "swu.script")
        script = sc.name
        if script != "update_modalix.sh" and not swu.get("description"):
            die(f"swu.script {script} needs swu.description to install it")
        stages = sub1(
            stages, r"^( *- )\$\{oc\.env:CURRENT_DIR\}/configs/images/files/update_modalix\.sh$",
            lambda m: f"{m[1]}{json.dumps(str(sc))}", "update script")
    if swu.get("description"):
        d = member(swu["description"], "swu.description")
        check_description(d.read_text(), {"rootfs.ext4.gz", "boot.vfat.gz",
                                          "boot0.be", "swu-os-marker", "sbom.cdx.json", script})
        stages = sub1(stages, r"^( *description: ).*$",
                      lambda m: f"{m[1]}{json.dumps(str(d))}", "description")
    src = cfg.get("sources")
    if src is not None:
        if not isinstance(src, list) or not src or \
                not all(isinstance(x, str) and "${" not in x and "\n" not in x for x in src):
            die("sources must be a list of apt source lines")
        stages = sub1(
            stages, r"^( *)- deb http://deb\.debian\.org[^\n]*\n(?:\1- deb [^\n]*\n){3}",
            lambda m: "".join(f"{m[1]}- {json.dumps(x)}\n" for x in src), "apt sources")

    target = img / f"pib-{base}-{cfg['target']}.yaml"
    target.write_text(flavor)
    (img / "pib-params.yaml").write_text(params)
    (img / "pib-stages.yaml").write_text(stages)
    shutil.copy(target, ws / "build/effective.yaml")
    return target


def check_issued(cert, ca):
    for f in (cert, ca):
        if not Path(f).is_file():
            die(f"{f} not found")
    if subprocess.run(["openssl", "verify", "-no-CApath", "-no-CAstore",
                       "-CAfile", ca, cert], capture_output=True).returncode:
        die(f"{cert} is not issued by {ca}; the board would reject the bundle")


def build_signing(ws, cfg, dev):
    """(key, cert, trust): the swu stage gets a throwaway key; pib sign signs."""
    if not dev:
        ca = ws / ((cfg.get("signing") or {}).get("ca") or "keys/ca.crt")
        if not ca.is_file():
            die(f"{ca} not found (pib keys init creates it); without it the "
                "image would trust no key")
    d = ws / "build/dev-keys"
    shutil.rmtree(d, ignore_errors=True)
    gen_keys(d, cn="PIB dev")
    if dev:
        print("pib: WARNING: --dev uses a throwaway key; do not ship this image",
              file=sys.stderr)
    return d / "swu-signing.key", d / "swu-signing.crt", d / "ca.crt" if dev else ca.resolve()


CRED_LINE = re.compile(r"(root|sima):\$[0-9a-z]+\$\S+")  # a crypt(3) hash, never a plain password


def check_credentials():
    """The optional PIB_CREDENTIALS file: one root:<hash> and one sima:<hash> line, as chpasswd -e reads it."""
    path = os.environ.get("PIB_CREDENTIALS")
    if not path:
        print("pib: no PIB_CREDENTIALS: root and sima are locked; boards with a rootfs overlay keep "
              "their passwords, a fresh flash or clean-overlay update needs an SSH key in overlay/", file=sys.stderr)
        return
    if not SAFE_PATH.fullmatch(path):  # the path goes into a hook command line
        die(f"PIB_CREDENTIALS {path!r}: paths used in hooks may only hold letters, digits and _ . / + -")
    f = Path(path)
    if not f.is_file():
        die(f"PIB_CREDENTIALS {f} not found")
    users = []
    for n, ln in enumerate(f.read_text().splitlines(), 1):
        if not CRED_LINE.fullmatch(ln):
            die(f"{f}:{n} must be root:<hash> or sima:<hash> with a $id$ crypt hash, not a password")
        users.append(ln.split(":")[0])
    if sorted(users) != ["root", "sima"]:
        die(f"{f} must hold exactly one root and one sima line")


def cmd_build(a):
    if getattr(a, "sign", False) and a.dev:
        die("--sign cannot be combined with --dev; use your own test signing identity")
    supplier = a.supplier or "SiMa.ai"
    if not supplier.strip() or len(supplier) > 256 or "${" in supplier or not supplier.isprintable():
        die("--supplier must be one non-blank line of up to 256 characters, without '${'")
    ws = Path.cwd()
    cfg = load_config(ws)
    check_credentials()
    debs = check_debs(ws, cfg)
    check_repo(debs)
    version = cfg["version"] + ("-dev" if a.dev else "")
    stem = f"elxr-{cfg['base']}-{cfg['target']}-{version}-"  # this image's out/ files
    slots = str(cfg.get("slots", "ab"))
    if slots not in ("a", "ab"):
        die(f"slots must be 'a' or 'ab', not {slots!r}")
    aes = (cfg.get("encryption") or {}).get("key")
    if aes:
        read_aes_key(ws / aes)
    out = ws / "out"
    try:  # from here on the throwaway CA key and root-owned files are cleaned up
        key, cert, ca = build_signing(ws, cfg, a.dev)
        config = write_effective(ws, cfg, version, ca, debs, aes and ws / aes, supplier)
        out.mkdir(exist_ok=True)
        env = dict(os.environ, CURRENT_DIR=str(ws), OUTPUT_DIR=str(out),
                   ROOTFS_SLOTS=slots, SWU_SIGNING_KEY=str(key), SWU_SIGNING_CERT=str(cert))
        env["MIRROR_1"] = sima_release_line(cfg)
        log = ws / "configs/images/mmdebstrap.log"  # a pib _finish refusal ends up there
        log.unlink(missing_ok=True)
        r = subprocess.run(["rs", "build", "--config",
                            str(config.relative_to(ws))], cwd=ws, env=env)
        if r.returncode:
            discard(out, stem)
            why = [ln[5:] for ln in log.read_text().splitlines() if ln.startswith("pib: ")] \
                if log.is_file() else []
            die("\n".join([*why, f"rs build failed with exit code {r.returncode}; "
                             f"out/{stem}* removed"]))
        try:
            write_manifest(ws, out, cfg, version, stem, supplier)
        except BaseException:
            discard(out, stem)
            raise
        if not a.dev:
            for swu in built(out, stem, r"\.swu"):
                unsign(swu)
        write_sums(out)
    finally:
        shutil.rmtree(ws / "build/dev-keys", ignore_errors=True)
        chown(ws)  # rs leaves root-owned logs and installer files outside out/
    print(f"pib: artifacts in {out}")
    if getattr(a, "sign", False):
        cmd_sign(argparse.Namespace(swu=None, key=None, cert=None, pkcs11=None,
                                   dev=False, encrypt=False, aes_key=None, out=None))
        cmd_verify(argparse.Namespace(swu=None, ca=None, manifest=None))


def unsign(swu):
    """Replace swu with <name>.unsigned.swu, minus its throwaway signature."""
    with tempfile.TemporaryDirectory() as t:
        names = [n for n in read_swu(swu, t) if n != "sw-description.sig"]
        write_swu(names, t, swu.with_name(swu.name[:-4] + ".unsigned.swu"))
    swu.unlink()
    print(f"pib: {swu.name[:-4]}.unsigned.swu is unsigned; run pib sign")


def write_sums(out):
    sums = out / "SHA256SUMS"
    files = sorted(p for p in out.iterdir() if p.is_file() and p != sums)
    sums.write_text("".join(f"{sha256(p)}  {p.name}\n" for p in files))


def cmd_verify_debs(a):
    ws = Path.cwd()
    debs = check_debs(ws, load_config(ws))
    print(f"pib: {len(debs)} custom .debs verified")


# ---- .swu -------------------------------------------------------------------

def built(out, stem, suffix=r"(-boot0?\.[^-]+|\.[^-]+)"):
    """Files in out/ named <stem><codename>-<arch><suffix> (a regex), so outputs
    of other images or versions, -dev included, in the same out/ are left alone."""
    pat = re.compile(rf"^{re.escape(stem)}[^-]+-[^-.]+{suffix}$")
    return sorted(p for p in out.iterdir() if pat.match(p.name) and p.is_file())


def discard(out, stem):
    """Remove this image's files from out/: a failed build leaves no mix of old and new."""
    for p in built(out, stem):
        p.unlink()
    if (out / "SHA256SUMS").is_file():
        write_sums(out)


def release_deb(spec, cfg, d):
    """Download a package (spec: name or name=version) from the SiMa.ai apt line the image
    installs from (nothing else) into the new directory d, and return the .deb."""
    d = Path(d)
    (d / "lists/partial").mkdir(parents=True)
    (d / "cache/archives/partial").mkdir(parents=True)
    (d / "src.list").write_text(sima_release_line(cfg) + "\n")
    opt = [f"-o{k}={v}" for k, v in (
        ("Dir::Etc::sourcelist", d / "src.list"), ("Dir::Etc::sourceparts", "/dev/null"),
        ("Dir::State", d), ("Dir::Cache", d / "cache"), ("Dir::State::status", "/dev/null"),
        ("APT::Architecture", "arm64"), ("APT::Architectures", "arm64"),
        ("Debug::NoLocking", "1"))]
    run(["apt-get", *opt, "update"])
    run(["apt-get", *opt, "download", spec], cwd=d)
    return next(d.glob(f"{spec.partition('=')[0]}_*.deb"))


def release_boot0_md5(spec, cfg):
    """md5 of boot/Release/boot0.be in a tRoot package (spec: name or name=version) of the
    SiMa.ai apt line the image installs from (nothing else), read from the package's own md5sums."""
    with tempfile.TemporaryDirectory() as d:
        for ln in run(["dpkg-deb", "-I", release_deb(spec, cfg, d), "md5sums"]).splitlines():
            md5, _, name = ln.partition("  ")
            if name == "boot/Release/boot0.be":
                return md5
    die(f"{spec} md5sums has no boot/Release/boot0.be")


def write_manifest(ws, out, cfg, version, stem, supplier):
    """<image>.manifest.json: every package with its origin, and the tRoot source. Dies,
    writing nothing, when boot0.be is not the one in SiMa's release package."""
    boots, pkgs_f = built(out, stem, r"-boot0\.be"), ws / "build/packages.json"
    if not pkgs_f.is_file() or len(boots) != 1:
        die("the build left no package list or boot0.be to check")
    pkgs = json.loads(pkgs_f.read_text())
    # The secure flavor installs troot-modalix-secure, which carries a different boot0.be.
    t = [p for p in pkgs if p["name"].startswith("troot-")]
    if len(t) > 1:
        die(f"the image holds more than one tRoot package: {', '.join(p['name'] for p in t)}")
    name = t[0]["name"] if t else "troot-modalix"
    want = release_boot0_md5(f"{name}={t[0]['version']}" if t else name, cfg)
    got = hashlib.md5(boots[0].read_bytes()).hexdigest()
    if got != want:
        die(f"md5 check failed for boot0.be: bundle {got}, SiMa release {name} {want}")
    src = {"source": "package", "package": " ".join(
        [t[0]["name"], t[0]["version"], f"({t[0]['origin']})"]) if t else "unknown"}
    stem = boots[0].name[:-len("-boot0.be")]
    (out / f"{stem}.manifest.json").write_text(json.dumps({
        "image": stem, "version": version, "release": cfg["release"],
        "vendor": cfg.get("vendor"), "supplier": supplier,
        "boot0": {**src, "sha256": sha256(boots[0])}, "packages": pkgs},
        indent=1) + "\n")


def read_swu(swu, dest):
    """Extract a .swu into dest and return its member names in order."""
    def cpio(*args):
        with open(swu, "rb") as f:
            # newc only: a tar-format member can be a hard link to any file
            r = subprocess.run(["cpio", *args, "-H", "newc", "--quiet"], stdin=f, cwd=dest,
                               capture_output=True, text=True)
        if r.returncode:
            die(f"cpio failed on {swu}: {r.stderr.strip()}")
        return r.stdout
    names = cpio("-it").splitlines()
    if not names or names[0] != "sw-description":
        die(f"{swu} is not a .swu: sw-description must be the first member")
    for n in names:
        # pib sign re-packs by name: a path would pull in the signer's own files
        if "/" in n or n in ("", ".", "..") or names.count(n) > 1:
            die(f"{swu}: member name {n!r} is not a plain, unique file name")
    cpio("-idm", "--no-absolute-filenames")
    for p in (Path(dest, n) for n in names):
        # sign and verify write and read members by name, through any link
        if p.is_symlink() or not p.is_file() or p.stat().st_nlink > 1:
            die(f"{swu}: member {p.name!r} is a link or not a regular file")
    return names


def write_swu(names, src, out):
    members = "\n".join(names).encode() + b"\n"
    with open(out, "wb") as f:
        r = subprocess.run(["cpio", "-o", "-H", "newc", "--reproducible",
                            "--quiet"], cwd=src, input=members, stdout=f,
                           stderr=subprocess.PIPE)
    if r.returncode:
        die(f"cpio failed: {r.stderr.decode().strip()}")


def one_in_out(what, *globs):
    found = next((f for g in globs if (f := sorted(Path("out").glob(g)))), [])
    if len(found) != 1:
        die(f"{what} (out/ holds {len(found)})")
    return found[0]


def ws_yaml():
    f = Path("image.yaml")
    return read_yaml(f) if f.is_file() else {}


def cmd_sign(a):
    y = ws_yaml()  # out/ keeps earlier builds: default to the image.yaml version's bundle
    stem = f"elxr-{y.get('base', '*')}-{y.get('target', '*')}-{y['version']}-" if y.get("version") else ""
    swu = Path(a.swu) if a.swu else one_in_out("name the .swu to sign", f"{stem}*.unsigned.swu", f"{stem}*.swu")
    if not swu.is_file():
        die(f"{swu} not found")
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        if a.dev:
            gen_keys(d / "keys", cn="PIB dev")
            cert, key, pkcs11 = (d / "keys/swu-signing.crt",
                                 d / "keys/swu-signing.key", None)
            print("pib: WARNING: --dev signs with a throwaway key; the board "
                  "will not trust it", file=sys.stderr)
        else:
            s = ws_yaml().get("signing") or {}
            cert = a.cert or os.environ.get("SWU_SIGNING_CERT") or s.get("cert")
            key = a.key or os.environ.get("SWU_SIGNING_KEY") or s.get("key")
            pkcs11 = a.pkcs11 or (key if str(key).startswith("pkcs11:") else None)
            if not cert or not (pkcs11 or key):
                die("need --cert and --key (or --pkcs11), or --dev")
            key = None if pkcs11 else key
            ca = Path(s.get("ca") or "keys/ca.crt")
            if ca.is_file() or s.get("ca"):  # check_issued dies when a named CA is missing
                check_issued(cert, ca)
            else:
                print(f"pib: warning: {ca} not found; not checking that the "
                      "leaf is issued by your CA", file=sys.stderr)
        names = [n for n in read_swu(swu, d) if n != "sw-description.sig"]
        desc = (d / "sw-description").read_text()
        if not a.dev and re.search(r'version\s*=\s*"[^"]*-dev"', desc):
            die(f"{swu} was built with --dev: its image trusts a throwaway CA; "
                "rebuild without --dev")
        if a.dev:
            desc = re.sub(r'(version\s*=\s*")([^"]*)(")',
                          lambda m: m[1] + m[2].removesuffix("-dev") + "-dev" + m[3], desc, count=1)
        if a.encrypt:
            aes = a.aes_key or (ws_yaml().get("encryption") or {}).get("key")
            if not aes:
                die("--encrypt needs --aes-key or encryption.key in image.yaml")
            desc = encrypt_payloads(d, names, desc, read_aes_key(aes))
        (d / "sw-description").write_text(desc)
        cmd = ["openssl", "cms", "-sign", "-binary", "-noattr",
               "-in", d / "sw-description", "-out", d / "sw-description.sig",
               "-signer", cert, "-outform", "DER", "-nosmimecap"]
        cmd += ["-engine", "pkcs11", "-keyform", "engine", "-inkey", pkcs11] \
            if pkcs11 else ["-inkey", key]
        run(cmd)
        out = Path(a.out) if a.out else \
            swu.with_name(swu.name.replace(".unsigned.swu", ".swu"))
        tmp = out.with_name(out.name + ".tmp")
        write_swu([names[0], "sw-description.sig", *names[1:]], d, tmp)
        tmp.replace(out)
    sums = out.parent / "SHA256SUMS"
    if sums.is_file():
        write_sums(out.parent)
    chown(out, *([sums] if sums.is_file() else []))
    print(f"pib: signed {out}")


def strip_comments(text):
    """Drop /* */, // and # comments; quoted strings are kept as they are."""
    return re.sub(r'("(?:[^"\\]|\\.)*")|/\*.*?\*/|(?://|#)[^\n]*',
                  lambda m: m[1] or "", text, flags=re.S)


def encrypt_payloads(d, names, desc, key):
    """Encrypt the payload members in d (AES-256-CBC, a fresh ivt each) and mark them in
    the description with their new sha256. Returns the new description."""
    if re.search(r"\bencrypted\s*=\s*true", strip_comments(desc)):
        die("the bundle is already encrypted")
    todo = [n for n in ENCRYPTED if n in names]
    if not todo:
        die(f"the bundle has none of {', '.join(ENCRYPTED)} to encrypt")
    for n in todo:
        ivt = secrets.token_hex(16)
        # openssl takes the key only as an argument; this runs in the signing container
        run(["openssl", "enc", "-aes-256-cbc", "-K", key, "-iv", ivt,
             "-in", d / n, "-out", d / (n + ".enc")])
        os.replace(d / (n + ".enc"), d / n)
        digest = sha256(d / n)

        def block(m):
            if not re.search(rf'filename\s*=\s*"{re.escape(n)}"', m[0]):
                return m[0]
            b = re.sub(r'(sha256\s*=\s*")[^"]*(")', lambda x: x[1] + digest + x[2], m[0])
            return re.sub(r'([ \t]*)(filename\s*=\s*"[^"]*";)',
                          lambda x: f'{x[1]}{x[2]}\n{x[1]}encrypted = true;\n{x[1]}ivt = "{ivt}";',
                          b, count=1)
        new = re.sub(r"\{[^{}]*\}", block, desc)
        if new == desc:
            die(f"cannot find the sw-description entry of {n} to mark it encrypted")
        desc = new
    return desc


def artifacts(text):
    """(filename, sha256) of every artifact block in a sw-description."""
    text = strip_comments(text)
    stack, cur, pos = [], "", 0
    for m in re.finditer(r"[{}]", text):
        cur += text[pos:m.start()]
        pos = m.end()
        if m[0] == "{":
            stack.append(cur)
            cur = ""
            continue
        name = re.search(r'filename\s*=\s*"([^"]+)"', cur)
        if name:
            digest = re.search(r'sha256\s*=\s*"([^"]*)"', cur)
            yield name[1], digest and digest[1].lower()
        cur = stack.pop() if stack else ""


def cmd_verify(a):
    # Resolve the current project version, rather than asking users to parse YAML/globs.
    cfg = ws_yaml()
    if not a.swu:
        stem = f"elxr-{cfg.get('base', '*')}-{cfg.get('target', '*')}-{cfg['version']}-" if cfg.get("version") else ""
        found = sorted(p for p in Path("out").glob(f"{stem}*.swu")
                       if not p.name.endswith(".unsigned.swu")
                       and not p.name.startswith(f"{stem}dev-"))
        if len(found) != 1:
            die(f"name the signed .swu to verify (out/ holds {len(found)})")
        a.swu = str(found[0])
    if not a.ca:
        a.ca = (cfg.get("signing") or {}).get("ca") or "keys/ca.crt"
    if not a.manifest:
        manifest = Path(a.swu).with_suffix(".manifest.json")
        if manifest.is_file():
            a.manifest = str(manifest)
    with tempfile.TemporaryDirectory() as t:
        d = Path(t)
        names = read_swu(a.swu, d)
        if names[1:2] != ["sw-description.sig"]:
            die("sw-description.sig must be the second member")
        r = subprocess.run(
            ["openssl", "cms", "-verify", "-binary", "-inform", "DER",
             "-in", d / "sw-description.sig", "-content", d / "sw-description",
             "-CAfile", a.ca, "-no-CApath", "-no-CAstore", "-purpose", "any",
             "-out", os.devnull],
            capture_output=True, text=True)
        if r.returncode:
            die(f"signature does not verify against {a.ca}: "
                f"{r.stderr.strip()}")
        text = (d / "sw-description").read_text()
        plain = strip_comments(text)
        compat = re.search(r"hardware-compatibility\s*[:=]\s*\[([^\]]*)\]", plain)
        ver = re.search(r'version\s*=\s*"([^"]*)"', plain)
        if not ver or not VERSION_RE.fullmatch(ver[1].removesuffix("-dev")):
            die(f"version {ver and ver[1]!r} is not numeric <release>.<build>")
        if not compat or not compat[1].strip():
            die("hardware-compatibility is missing or empty")
        arts = list(artifacts(text))
        if not arts:
            die("sw-description lists no artifacts")
        for name, digest in arts:
            if not (d / name).is_file():
                die(f"{name} is referenced but not in the bundle")
            if digest is None:
                die(f"{name} has no sha256 in the signed description")
            if sha256(d / name) != digest:
                die(f"{name} does not match its signed sha256")
        if a.manifest:
            try:
                m = json.loads(Path(a.manifest).read_text())
                want, mver = m["boot0"]["sha256"], m["version"]
            except (OSError, ValueError, KeyError, TypeError) as ex:
                die(f"{a.manifest} is not a pib manifest: {ex}")
            if mver != ver[1]:
                die(f"the manifest describes version {mver}, the bundle is {ver[1]}")
            if not (d / "boot0.be").is_file() or sha256(d / "boot0.be") != want:
                die("boot0.be does not match the manifest")
    print(f"pib: {a.swu} OK ({len(arts)} artifacts verified)")


# ---- kernel FIT signature (securepalette) -----------------------------------

FDT_MAGIC = b"\xd0\x0d\xfe\xed"
FIT_EXC = ("data", "data-size", "data-position", "data-offset")  # never part of the signed hash
SHA256_DER = bytes.fromhex("3031300d060960864801650304020105000420")  # PKCS#1 DigestInfo prefix


def fdt_parse(b):
    """(nodes, tags, struct offset, strings offset, total size) of a device tree blob:
    nodes is {path: {property: bytes}}, tags [(tag, offset, next, name)] in the struct block."""
    magic, total, off_struct, off_strings, _, _, _, _, _, size_struct = struct.unpack(">10I", b[:40])
    if magic != 0xd00dfeed or total > len(b):
        raise ValueError("not a device tree")
    s = b[off_struct:off_struct + size_struct]
    nodes, tags, path, o = {}, [], [], 0
    while True:
        tag, n, name = int.from_bytes(s[o:o + 4], "big"), o + 4, None
        if tag == 1:    # begin node: name, NUL, padded to 4 bytes
            end = s.index(b"\0", n)
            path.append(s[n:end].decode())
            name, n = "/" + "/".join(path[1:]), (end + 4) & ~3
            nodes[name] = {}
        elif tag == 2:  # end node
            path.pop()
        elif tag == 3:  # property: length, name offset, value padded to 4 bytes
            ln, nameoff = struct.unpack(">2I", s[n:n + 8])
            strings = b[off_strings + nameoff:]
            name = strings[:strings.index(b"\0")].decode()
            nodes["/" + "/".join(path[1:])][name] = s[n + 8:n + 8 + ln]
            n = (n + 8 + ln + 3) & ~3
        elif tag not in (4, 9) or n > len(s):
            raise ValueError("bad device tree structure")
        tags.append((tag, o, n, name))
        if tag == 9:
            return nodes, tags, off_struct, off_strings, total
        o = n


def fit_regions(tags, inc):
    """Struct-block byte ranges U-Boot hashes for a signature over the nodes in inc
    (the same walk as its fdt_find_regions)."""
    out, start, want, stack = [], None, 0, []
    for tag, off, nxt, name in tags:
        stop = nxt
        if tag in (3, 4):
            include, stop = want >= 2 and name not in FIT_EXC, off
        elif tag == 1:
            stack.append(want)
            if want == 1 or (name not in inc and not want):
                stop = off
            want = 2 if name in inc else max(want - 1, 0)
            include = want
        elif tag == 2:
            include, want = want, stack.pop()
        else:
            include = True
        if include and start is None:
            start = off
        if not include and start is not None:
            out.append((start, stop))
            start = None
    out.append((start, tags[-1][2]))
    return out


def text(prop):
    return (prop or b"").rstrip(b"\0").decode(errors="replace")


def required_keys(*blobs):
    """{modulus: (name hint, exponent)} of every key marked required = "conf" in the
    device trees embedded in the given U-Boot images."""
    keys = {}
    for b in blobs:
        for m in re.finditer(re.escape(FDT_MAGIC), b):
            try:
                nodes = fdt_parse(b[m.start():])[0]
            except (ValueError, IndexError, struct.error):
                continue
            for path, props in nodes.items():
                if path.startswith("/signature/") and text(props.get("required")) == "conf" \
                        and "rsa,modulus" in props:
                    keys[props["rsa,modulus"]] = (
                        text(props.get("key-name-hint")),
                        int.from_bytes(props.get("rsa,exponent", b"\x01\x00\x01"), "big"))
    return keys


def fit_check(fit, keys):
    """Die unless the FIT's default configuration is signed by every key in keys, the
    signature covers the configuration and its images, and each image matches its hash."""
    try:
        nodes, tags, off_struct, off_strings, total = fdt_parse(fit)
    except (ValueError, IndexError, struct.error) as ex:
        die(f"the kernel fitImage is not a FIT: {ex}")
    conf = "/configurations/" + text(nodes.get("/configurations", {}).get("default"))
    if conf not in nodes:
        die("the kernel fitImage has no default configuration")
    if f"/images/{text(nodes[conf].get('kernel'))}" not in nodes:
        die("the kernel fitImage's default configuration has no kernel")
    images = sorted({f"/images/{v}" for k, val in nodes[conf].items() if k != "description"
                     for v in text(val).split("\0") if f"/images/{v}" in nodes})
    sigs = [p for p, props in nodes.items()
            if p.startswith(conf + "/") and "value" in props and "hashed-nodes" in props]
    for modulus, (hint, exponent) in keys.items():
        for sig in sigs:
            props = nodes[sig]
            if text(props.get("algo")).split(",")[0] != "sha256" or \
                    text(props.get("padding")) not in ("", "pkcs-1.5"):
                continue  # only sha256 with PKCS#1 v1.5 padding is checked here
            inc = text(props["hashed-nodes"]).split("\0")
            h = hashlib.sha256()
            for a, z in fit_regions(tags, inc):
                h.update(fit[off_struct + a:off_struct + z])
            if "hashed-strings" in props:
                h.update(fit[off_strings:off_strings + int.from_bytes(props["hashed-strings"][4:8], "big")])
            k = len(modulus)
            want = b"\x00\x01" + b"\xff" * (k - 3 - len(SHA256_DER) - 32) + b"\x00" + SHA256_DER + h.digest()
            got = pow(int.from_bytes(props["value"], "big"), exponent, int.from_bytes(modulus, "big"))
            if got.to_bytes(k, "big") != want:
                continue
            hashes = [p for p in nodes if "value" in nodes[p] and p.rsplit("/", 1)[0] in images]
            missing = [n for n in (conf, *images, *hashes) if n not in inc]
            if missing:
                die(f"the kernel FIT signature does not cover {', '.join(missing)}")
            break
        else:
            die(f"the kernel fitImage is not signed by U-Boot's required key {hint!r}; "
                "a secure-boot board would not boot it")
    for img in images:
        props = nodes[img]
        if "data" in props:
            data = props["data"]
        else:  # external data: absolute, or relative to the end of the tree (4-aligned)
            size = int.from_bytes(props.get("data-size", b""), "big")
            pos = int.from_bytes(props["data-position"], "big") if "data-position" in props \
                else ((total + 3) & ~3) + int.from_bytes(props.get("data-offset", b""), "big")
            data = fit[pos:pos + size]
        hs = [h for hp, h in nodes.items() if hp.startswith(img + "/hash") and "value" in h
              and text(h.get("algo")) in hashlib.algorithms_guaranteed]  # crc32 and the like are skipped
        if not hs:
            die(f"the kernel fitImage: {img} has no hash that can be checked")
        for h in hs:
            if hashlib.new(text(h["algo"]), data).digest() != h["value"]:
                die(f"the kernel fitImage: {img} does not match its {text(h['algo'])} hash")


FIP_MAGIC = 0xAA640001
BL33_UUID = bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4")


def fip_bl33(fip):
    """The U-Boot (BL33) image inside a firmware image package, None if it has none."""
    if len(fip) < 16 or struct.unpack_from("<I", fip)[0] != FIP_MAGIC:
        return None
    for off in range(16, len(fip) - 39, 40):  # 16-byte header, 40-byte entries
        uuid, pos, size = struct.unpack_from("<16sQQ", fip, off)
        if uuid == BL33_UUID:
            return fip[pos:pos + size] if pos + size <= len(fip) else None
        if uuid == bytes(16):
            break
    return None


def check_fip_uboot(root):
    """The board boots the U-Boot inside fip.bin; u-boot.bin must be that one."""
    boot = Path(root) / "boot"
    if fip_bl33((boot / "fip.bin").read_bytes()) != (boot / "u-boot.bin").read_bytes():
        die("/boot/u-boot.bin is not the U-Boot inside /boot/fip.bin; the board boots the "
            "one in fip.bin, which the ATF package carries, so this U-Boot would not run")


def check_secure_boot(root, dev):
    """securepalette: the kernel FIT must verify against the keys U-Boot requires."""
    boot = Path(root) / "boot"
    keys = required_keys((boot / "u-boot.bin").read_bytes(), (boot / "fip.bin").read_bytes())
    if not keys:
        die("U-Boot holds no required FIT key; a secure-boot board would not verify the kernel")
    if not dev and any(hint == "dev" for hint, _ in keys.values()):
        die("U-Boot trusts the development FIT key 'dev'; securepalette builds with it "
            "need --dev (a production key comes with SiMa.ai's ATF and U-Boot packages)")
    fit_check((boot / "fitImage").read_bytes(), keys)


# ---- build-time hook and cleanup ------------------------------------------

ORIGINS = {"customer": "localhost", "sima": "sima.ai", "elxr": "elxr.dev", "debian": "debian.org"}


def installed(root):
    """[(package, version)] from the chroot's dpkg status."""
    found = []
    for stanza in (Path(root) / "var/lib/dpkg/status").read_text().split("\n\n"):
        f = dict(ln.split(": ", 1) for ln in stanza.splitlines()
                 if ": " in ln and not ln.startswith(" "))
        if f.get("Status", "").endswith(" installed") and "Package" in f:
            found.append((f["Package"], f.get("Version", "")))
    return found


def origin_of(listname):
    host = listname.split("_dists_")[0]
    return next((o for o, mark in ORIGINS.items() if mark in host), host.split("_")[0])


def list_origins(root):
    """{(package, version): {origin}} from the chroot's apt package lists."""
    files = sorted((Path(root) / "var/lib/apt/lists").glob("*_Packages*"))
    if not files:
        die("no apt package lists in the chroot; cannot tag package origins")
    found = {}
    for f in files:
        opener = {".gz": gzip.open, ".xz": lzma.open}.get(f.suffix)
        if f.suffix == ".lz4":
            die(f"{f.name} is lz4-compressed; cannot tag package origins")
        origin, name, ver = origin_of(f.name), None, None
        with (opener or open)(f, "rt", errors="replace") as fh:
            for ln in fh:
                if ln.startswith("Package: "):
                    name = ln[9:].strip()
                elif ln.startswith("Version: "):
                    ver = ln[9:].strip()
                elif not ln.strip():
                    found.setdefault((name, ver), set()).add(origin)
                    name = ver = None
        if name:
            found.setdefault((name, ver), set()).add(origin)
    return found


def cmd_finish(a):
    """Runs last in the image build: origins, one boot chain, vendor."""
    policy = json.loads((Path(a.build) / "policy.json").read_text())
    pkgs, origins = installed(a.root), list_origins(a.root)
    out = []
    for name, ver in sorted(pkgs):
        got = origins.get((name, ver), set())
        out.append({"name": name, "version": ver, "origin": next(
            (o for o in ORIGINS if o in got), min(got, default="unknown"))})
    for label, pat in boot_chain(policy["target"]):
        got = [p["name"] for p in out if re.match(pat, p["name"])]
        if len(got) != 1:
            die(f"the image must hold one {label} package, found "
                f"{len(got)}: {', '.join(got) or 'none'}")
    root = Path(a.root)
    for f in ("fip.bin", "u-boot.bin", "fitImage"):
        if not (p := root / "boot" / f).is_file() or not p.stat().st_size:
            die(f"the image lacks /boot/{f}; the boot partition would be incomplete")
    check_fip_uboot(root)
    sets = sorted(d.name for d in (root / "lib").glob("linux-image-*") if d.is_dir())
    if len(sets) != 1:
        die(f"the boot partition would mix kernel/DTB sets: {', '.join(sets) or 'none'}")
    if not policy["own_sources"]:
        for pre, what in ROOTS:
            pk = [p for p in out if p["name"].startswith(pre)]
            if any(p["origin"] != "sima" for p in pk):
                die(f"the {what} package must come from SiMa.ai's repo, not "
                    f"{', '.join(p['origin'] for p in pk)}")
    if policy["base"] == "securepalette":
        check_secure_boot(root, policy["dev"])
    (Path(a.build) / "packages.json").write_text(json.dumps(out, indent=1) + "\n")
    if policy.get("vendor"):
        with open(root / "etc/buildinfo", "a") as f:
            f.write(f"VENDOR = {policy['vendor']}\n")


def cmd_clean(a):
    cfg = load_config(Path.cwd())
    # any flavor: the interrupted build may not be the one image.yaml names now
    pat = re.compile(rf"^elxr-\w+-{re.escape(cfg['target'])}-.*\.img$")
    # /dev is the host's: match this workspace's images by inode, not path; deleted ones are orphans
    own = {f"{os.major(s.st_dev)}:{os.minor(s.st_dev)} {s.st_ino}"
           for s in (f.stat() for f in Path("out").glob("*.img") if pat.match(f.name))}
    todo = [p[0] for ln in run(["losetup", "-l", "-n", "-O", "NAME,BACK-MAJ:MIN,BACK-INO,BACK-FILE"]).splitlines()
            if len(p := ln.split(None, 3)) == 4 and (" ".join(p[1:3]) in own or (
                p[3].endswith(" (deleted)") and pat.match(Path(p[3][:-10]).name)))]
    for dev in todo:
        parts = sorted(str(p) for p in Path("/dev").glob(Path(dev).name + "p*"))
        # pvs without devices would list every volume group on the host
        r = subprocess.run(["pvs", "--noheadings", "-o", "vg_name", *parts],
                           capture_output=True, text=True) if parts else None
        vgs = sorted(set(r.stdout.split())) if r else []
        if not a.yes:
            print(f"pib: would deactivate {' '.join(vgs) or 'no volume group'} "
                  f"and detach {dev}")
            continue
        for vg in vgs:
            run(["vgchange", "-an", vg])
        run(["losetup", "-d", dev])
        print(f"pib: detached {dev}")
    if todo and not a.yes:
        print("pib: run 'pib clean --yes' to do this (stop running builds first)")
    elif not todo:
        print("pib: nothing to clean")


# ---- diff -------------------------------------------------------------------

def components(path):
    """{package: version} from a CycloneDX .json or 'package version' lines."""
    p = Path(path)
    if p.suffix == ".json":
        data = json.loads(p.read_text())
        comps = data.get("components") or data.get("packages") or []
        # the SBOM also lists source packages; the manifest holds installed binaries only
        return {c["name"]: c.get("version", "") for c in comps
                if "arch=source" not in c.get("purl", "")}
    return dict(ln.split()[:2] for ln in p.read_text().splitlines()
                if len(ln.split()) >= 2)


def cmd_diff(a):
    img = a.image if a.image is not None else one_in_out("name the image SBOM with --image", "*.cdx.json")
    mine, ref = components(img), components(a.against)
    for name in sorted(mine.keys() | ref.keys()):
        if name not in ref:
            print(f"+ {name} {mine[name]}")
        elif name not in mine:
            print(f"- {name} {ref[name]}")
        elif mine[name] != ref[name]:
            print(f"~ {name} {ref[name]} -> {mine[name]}")


def cmd_doctor(a):
    """Check prerequisites after entrypoint emulation setup."""
    errors = []
    arch = run(["dpkg", "--print-architecture"]).strip()
    print(f"PIB {__version__}; platform {container_release()}; builder {arch}; target arm64")
    for name in ("rs", "mmdebstrap", "arch-test", "losetup", "dmsetup", "lvm",
                 "mke2fs", "mkfs.vfat", "cpio", "openssl", "reprepro", "debsbom"):
        if not shutil.which(name):
            errors.append(f"missing tool: {name}")
    if arch == "amd64":
        # Mount the registry view in this container's namespace. Do not register
        # handlers or bind-mount over /proc (blocked by recent runc versions).
        if not Path("/proc/sys/fs/binfmt_misc/register").exists():
            subprocess.run(["mount", "-t", "binfmt_misc", "binfmt_misc",
                            "/proc/sys/fs/binfmt_misc"], capture_output=True)
        entry = Path("/proc/sys/fs/binfmt_misc/qemu-aarch64")
        if not entry.is_file() or not entry.read_text().startswith("enabled\n"):
            errors.append("automatic ARM64 setup failed; use the PIB launcher with privileged Docker access")
        elif "F" not in next((ln for ln in entry.read_text().splitlines() if ln.startswith("flags:")), ""):
            errors.append("arm64 binfmt must have the F flag for chroot execution")
    elif arch != "arm64":
        errors.append(f"unsupported builder architecture: {arch}")
    for device in ("/dev/loop-control", "/dev/mapper/control"):
        if not Path(device).exists():
            errors.append(f"missing {device}; use the pib launcher for device access")
    for command in (["losetup", "-f"], ["dmsetup", "version"]):
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            errors.append(f"{' '.join(command)}: {result.stderr.strip()}")
    for directory in (Path.cwd(), Path("/var/tmp")):
        free = shutil.disk_usage(directory).free / 2**30
        print(f"Free space: {directory}: {free:.1f} GiB (allow 10 GiB minimal / 20 GiB palette)")
        if free < 10:
            errors.append(f"less than 10 GiB free at {directory}")
    if errors:
        die("preflight failed:\n  " + "\n  ".join(errors))
    print("pib: host prerequisites OK; this does not test package availability or board boot")


# ---- entry ------------------------------------------------------------------

def parser():
    p = argparse.ArgumentParser(prog="pib", description=__doc__)
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="create a workspace from a reference flavor")
    s.add_argument("dir", nargs="?", default=".")
    s.add_argument("--target", default="modalix")
    selection = s.add_mutually_exclusive_group()
    selection.add_argument("--example", choices=["custom-image"], help="copy a runnable sample spec, package, overlay and hook")
    selection.add_argument("--flavor", default="palette",
                   choices=["minimal", "palette", "securepalette"])
    s.add_argument("--release")
    s.add_argument("--configs", help="reference configs dir (or PIB_CONFIGS); default: the configs shipped in the container")
    s.set_defaults(fn=cmd_init)

    sub.add_parser("doctor", help="check image-build prerequisites").set_defaults(fn=cmd_doctor)

    keys = sub.add_parser("keys", help="signing keys").add_subparsers(
        dest="sub", required=True)
    s = keys.add_parser("payload", help="create the AES key for pib sign --encrypt")
    s.add_argument("--out", default="keys")
    s.set_defaults(fn=cmd_keys_payload)
    s = keys.add_parser("fit", help="create the kernel FIT signing key for pib sbp")
    s.add_argument("--out", default="keys")
    s.add_argument("--cn", default="Customer")
    s.set_defaults(fn=cmd_keys_fit)
    for name, fn, text in (
            ("init", cmd_keys_init, "create the customer CA and SWU leaf"),
            ("renew", cmd_keys_renew, "replace the SWU leaf with a new one from the same CA")):
        s = keys.add_parser(name, help=text)
        s.add_argument("--algo", default="rsa4096", choices=["rsa4096", "ecdsa-p384"])
        s.add_argument("--out", default="keys")
        s.add_argument("--cn", default="Customer")
        s.set_defaults(fn=fn)

    sub.add_parser("verify-debs", help="check custom-debs/ signatures").set_defaults(fn=cmd_verify_debs)

    # pib sbp is routed in main(): its options are sbp's and pass through. Listed here for --help.
    sub.add_parser("sbp", help="build SiMa.ai packages (the kernel) with sbp into custom-debs/ "
                   "(pib-sbp image)", add_help=False).set_defaults(fn=lambda a: sbp_main([]))

    s = sub.add_parser("sign-debs", help="sign every custom-debs/*.deb (writes <deb>.sig)")
    s.add_argument("--key", default="keys/debs-signing.secret.asc")
    s.set_defaults(fn=cmd_sign_debs)

    s = sub.add_parser("build", help="run the image build (rs build)")
    s.add_argument("--dev", action="store_true",
                   help="throwaway signing key, version gets -dev")
    s.add_argument("--sign", action="store_true", help="sign and verify the completed bundle using your configured key")
    s.add_argument("--supplier", help="SBOM distro supplier (default SiMa.ai)")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("sign", help="(re)sign a .swu with the customer key")
    s.add_argument("swu", nargs="?")
    s.add_argument("--key")
    s.add_argument("--pkcs11", metavar="URI")
    s.add_argument("--cert")
    s.add_argument("--dev", action="store_true")
    s.add_argument("--encrypt", action="store_true",
                   help="AES-256-CBC encrypt the rootfs and boot payloads")
    s.add_argument("--aes-key", metavar="FILE",
                   help="payload key (default: encryption.key in image.yaml)")
    s.add_argument("-o", "--out")
    s.set_defaults(fn=cmd_sign)

    s = sub.add_parser("verify", help="check a .swu signature and hashes")
    s.add_argument("swu", nargs="?", help="default: current project version in out/")
    s.add_argument("--ca", metavar="CRT", help="default: signing.ca from image.yaml")
    s.add_argument("--manifest", metavar="JSON",
                   help="also check boot0.be against the build manifest")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("clean", help="detach loop devices and volume groups "
                                     "left by an interrupted build")
    s.add_argument("--yes", action="store_true", help="do it (default: only list)")
    s.set_defaults(fn=cmd_clean)

    s = sub.add_parser("_finish")
    for arg in ("root", "build"):
        s.add_argument(arg)
    s.set_defaults(fn=cmd_finish)

    s = sub.add_parser("diff", help="package differences against a manifest")
    s.add_argument("--against", required=True, metavar="MANIFEST")
    s.add_argument("--image", help="image SBOM (default out/*.cdx.json)")
    s.set_defaults(fn=cmd_diff)
    sub.metavar = "{%s}" % ",".join(n for n in sub.choices if n[0] != "_")  # hide _finish
    return p


def sbp_main(argv):
    from pib import sbp  # only the pib-sbp image can run it; importing it costs nothing elsewhere
    sbp.cmd_sbp(argv)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        if argv[:1] == ["sbp"]:  # before argparse, which would take sbp's options as its own
            sbp_main(argv[1:])
            return
        a = parser().parse_args(argv)
        a.fn(a)
    except FileNotFoundError as e:  # a missing input file: one line, not a traceback
        die(f"{e.filename}: {e.strerror}")


if __name__ == "__main__":
    main()
