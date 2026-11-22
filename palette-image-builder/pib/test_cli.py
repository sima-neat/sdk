"""assert checks for pib.cli; run: python3 pib/test_cli.py (host, no container)."""
import argparse, contextlib, hashlib, io, json, os, re, shlex, shutil, signal, socket, struct, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pib"))
import pib.cli as c
TEST_ENV = tempfile.TemporaryDirectory()
TEST_RELEASE_FILE = Path(TEST_ENV.name) / "release-absent"
TEST_CODENAME_FILE = Path(TEST_ENV.name) / "codename-absent"
c.RELEASE_FILE = TEST_RELEASE_FILE
c.CODENAME_FILE = TEST_CODENAME_FILE
os.environ.pop("PIB_SIMA_APT_URL", None)
for v in ("SIMA_RELEASE", "PIB_UID", "PIB_GID", "PIB_CREDENTIALS"): os.environ.pop(v, None)

def dies(fn, *a, **k):
    try:
        fn(*a, **k)
    except SystemExit as e:
        return str(e.code)
    raise AssertionError("did not die")

# built()/discard(): stem anchoring
with tempfile.TemporaryDirectory() as t:
    out = Path(t)
    names = ["elxr-minimal-modalix-3.0.0.1-agate-arm64-boot0.be",
             "elxr-minimal-modalix-3.0.0.1-agate-arm64.swu",
             "elxr-minimal-modalix-3.0.0.1-agate-arm64.img",
             "elxr-palette-modalix-3.0.0.1-agate-arm64-boot0.be",      # other flavor, same version
             "elxr-minimal-modalix-3.0.0.1-dev-agate-arm64-boot0.be",  # dev build
             "elxr-minimal-modalix-3.0.0.1-dev-agate-arm64.swu",
             "elxr-minimal-modalix-3.0.0.10-agate-arm64-boot0.be",     # longer build number
             "SHA256SUMS"]
    for n in names: (out / n).write_text("x")
    (out / "elxr-minimal-modalix-3.0.0.1-agate-arm64-dir").mkdir()
    stem = "elxr-minimal-modalix-3.0.0.1-"
    assert [p.name for p in c.built(out, stem, r"-boot0\.be")] == [names[0]]
    assert [p.name for p in c.built(out, stem, r"\.swu")] == [names[1]]
    assert [p.name for p in c.built(out, "elxr-minimal-modalix-3.0.0.1-dev-", r"\.swu")] == [names[5]]
    assert c.built(out, "elxr-minimal-modalix-9.9.9.9-", r"\.swu") == []
    (out / "elxr-minimal-modalix-3.0.0.1-agate-arm64.unsigned.swu").write_text("x")
    (out / "elxr-minimal-modalix-3.0.0.1-agate-arm64.img.gz").write_text("x")
    (out / "elxr-minimal-modalix-3.0.0.1-agate-arm64-boot.vfat").write_text("x")
    (out / "elxr-minimal-modalix-3.0.0.1-agate-arm64-boot.vfat.gz").write_text("x")
    assert [p.name for p in c.built(out, stem, r"\.swu")] == [names[1]], "unsigned.swu is not .swu"
    assert len(c.built(out, stem)) == 7, [p.name for p in c.built(out, stem)]
    c.write_sums(out)
    assert "boot.vfat" in (out / "SHA256SUMS").read_text()
    c.discard(out, stem)
    sums = (out / "SHA256SUMS").read_text()
    assert stem + "agate" not in sums and "elxr-palette-modalix-3.0.0.1-agate-arm64-boot0.be" in sums, sums
    left = sorted(p.name for p in out.iterdir())
    assert left == sorted([names[3], names[4], names[5], names[6], "SHA256SUMS",
                           "elxr-minimal-modalix-3.0.0.1-agate-arm64-dir"]), left
    c.discard(out, "nomatch-"); assert sorted(p.name for p in out.iterdir()) == left
    c.discard(out, "elxr-minimal-modalix-3.0.0.1-dev-")
    assert sorted(p.name for p in out.iterdir()) == sorted([names[3], names[6], "SHA256SUMS",
                           "elxr-minimal-modalix-3.0.0.1-agate-arm64-dir"])

# subj(): CN with / or \ refused, plain CN accepted
assert c.subj("Acme Ltd", "SWU CA") == "/CN=Acme Ltd SWU CA"
assert "must not contain" in dies(c.subj, "Acme/Products", "SWU CA")
assert "must not contain" in dies(c.subj, "Acme\\x", "SWU CA")
assert "must not contain" in dies(c.subj, "a+b", "SWU CA")
assert c.subj("", "SWU CA") == "/CN= SWU CA"

# load_config(): bad YAML, non-mapping, field types (exact text), version rule, trailing newline
with tempfile.TemporaryDirectory() as t:
    ws, good = Path(t), "target: modalix\nrelease: 3.0.0\n"
    G = "base: minimal\n" + good + "version: 3.0.0.1\n"
    for body, msg in (("base: 1\n" + good + "version: 3.0.0.1\n", "base must be text"),
                      (G + "hooks: x\n", "hooks must be a list"), (G + "slots: [a]\n", "slots must be text or a number"),
                      (G + "troot: {boot0: b}\n", "unknown field troot")):
        (ws / "image.yaml").write_text(body); assert dies(c.load_config, ws) == "pib: image.yaml: " + msg, body
    for body, msg in (("base: [", "not valid YAML"), ("- a\n", "must hold a mapping"),
                      ("base: minimal\n" + good + 'version: "3.0.0.1\\n"\n', "must be 3.0.0.<build>"),
                      (G + "hooks: [1]\n", "hooks must be a list of script file names")):
        (ws / "image.yaml").write_text(body); assert msg in dies(c.load_config, ws), body
    (ws / "image.yaml").write_text(G)
    assert c.load_config(ws)["version"] == "3.0.0.1"

# cmd_init(): --release validated; --configs copies the named directory itself
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    cfgdir = t / "mycfgs"                      # not named "configs"
    (cfgdir / "images").mkdir(parents=True)
    (cfgdir / "images/image-minimal-modalix.yaml").write_text("version: 3.0.0\n")
    (cfgdir / "images/marker").write_text("mine")
    a = argparse.Namespace(dir=str(t / "ws"), flavor="minimal", target="modalix",
                           release="3.0", configs=str(cfgdir))
    assert "must be numeric" in dies(c.cmd_init, a)
    a.release = "3.0.0a"; assert "must be numeric" in dies(c.cmd_init, a)
    a.release = None; assert "--release or SIMA_RELEASE is required" in dies(c.cmd_init, a)
    a.release = "3.0.0"
    # --configs pointing at a dir named configs still works; an existing .gitignore is kept
    a2 = argparse.Namespace(dir=str(t / "ws2"), flavor="minimal", target="modalix", release="3.0.0",
                            configs=str(t / "repo/configs"))
    (t / "repo/configs/images").mkdir(parents=True)
    (t / "repo/configs/images/image-minimal-modalix.yaml").write_text("version: 3.0.0\n")
    (t / "ws2").mkdir(); (t / "ws2/.gitignore").write_text("mine\n")
    with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
        c.cmd_init(a); c.cmd_init(a2)
    assert (t / "ws/configs/images/marker").read_text() == "mine", "copied the named configs dir"
    assert (t / "ws/image.yaml").read_text().startswith("base: minimal")
    assert "image.yaml exists" in dies(c.cmd_init, a)
    assert (t / "ws2/configs/images/image-minimal-modalix.yaml").is_file()
    assert (t / "ws/.gitignore").read_text() == c.GITIGNORE and "keys/*.key" in c.GITIGNORE
    # no --release: SIMA_RELEASE (the container's) gives release and version <release>.1
    a3 = argparse.Namespace(dir=str(t / "ws4"), flavor="minimal", target="modalix", release=None, configs=str(cfgdir))
    os.environ["SIMA_RELEASE"] = "3.0.0"
    try:
        with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
            c.cmd_init(a3)
        y = c.load_config(t / "ws4")
        assert (y["release"], y["version"]) == ("3.0.0", "3.0.0.1"), y
        os.environ["SIMA_RELEASE"] = "3.1.0"
        assert "image.yaml release 3.0.0 != container release 3.1.0" in dies(c.load_config, t / "ws4")
    finally:
        os.environ.pop("SIMA_RELEASE")
    # in the container /etc/pib-release is the release, even when SIMA_RELEASE is unset or says otherwise
    c.RELEASE_FILE = t / "pib-release"; c.RELEASE_FILE.write_text("3.1.0\n")
    try:
        assert "image.yaml release 3.0.0 != container release 3.1.0" in dies(c.load_config, t / "ws4")
        os.environ["SIMA_RELEASE"] = "3.0.0"
        assert "image.yaml release 3.0.0 != container release 3.1.0" in dies(c.load_config, t / "ws4")
    finally:
        os.environ.pop("SIMA_RELEASE"); c.RELEASE_FILE = TEST_RELEASE_FILE
    assert (t / "ws2/.gitignore").read_text() == "mine\n", "existing .gitignore kept"
    assert "reference config" in dies(c.cmd_init, argparse.Namespace(
        dir=str(t / "ws3"), flavor="palette", target="modalix", release="3.0.0", configs=str(cfgdir)))

# cmd_verify --manifest error paths need a bundle; covered in the container run.

# chown(): a file already owned by PIB_UID/GID is left alone, so its setuid bit survives
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "helper"; f.write_text("x"); f.chmod(0o4755)
    os.environ["PIB_UID"], os.environ["PIB_GID"] = str(os.getuid()), str(os.getgid())
    c.chown(d)
    assert f.stat().st_mode & 0o4000, "setuid bit lost"
    del os.environ["PIB_UID"], os.environ["PIB_GID"]

# strip_comments / artifacts: comments ignored, // inside a string kept
desc = ('software = { version = "3.0.0.1"; images = (\n'
        '  { filename = "a.img"; sha256 = "AA"; },  // { filename = "gone"; sha256 = "x"; }\n'
        '  # { filename = "gone2"; sha256 = "x"; }\n'
        '  { filename = "http://h/b.img"; sha256 = "bb"; } ); }')
assert list(c.artifacts(desc)) == [("a.img", "aa"), ("http://h/b.img", "bb")], list(c.artifacts(desc))

# components(): source packages in an SBOM are not installed packages
with tempfile.TemporaryDirectory() as d:
    f = Path(d) / "s.cdx.json"
    f.write_text(json.dumps({"components": [
        {"name": "bash", "version": "5", "purl": "pkg:deb/debian/bash@5?arch=arm64"},
        {"name": "bash", "version": "5", "purl": "pkg:deb/debian/bash@5?arch=source"},
        {"name": "src-only", "version": "1", "purl": "pkg:deb/debian/src-only@1?arch=source"}]}))
    assert c.components(f) == {"bash": "5"}, c.components(f)

# check_issued: a missing file is named, not blamed on the CA
assert "nope.crt not found" in dies(c.check_issued, "nope.crt", "nope.crt")

# sign / verify round trip, tampering, -dev suffix, missing bundle
with tempfile.TemporaryDirectory() as d:
    t = Path(d); here = os.getcwd(); os.chdir(t)
    try:
        c.gen_keys(t / "keys", algo="ec", cn="T")
        assert (t / "keys/ca.key").stat().st_mode & 0o777 == 0o600
        c.gen_deb_key(t / "keys")
        assert (t / "keys/debs-signing.secret.asc").stat().st_mode & 0o777 == 0o600
        src = t / "src"; src.mkdir()
        (src / "boot0.be").write_text("b")
        (src / "sw-description").write_text(
            'software = { version = "3.0.0.1"; hardware-compatibility = ["1"];\n'
            f' images = ( {{ filename = "boot0.be"; sha256 = "{c.sha256(src / "boot0.be")}"; }} ); }}')
        c.write_swu(["sw-description", "boot0.be"], src, t / "u.swu")
        def sign(swu, out, dev=False, encrypt=False):
            c.cmd_sign(argparse.Namespace(swu=str(swu), out=str(out), dev=dev, key=str(t / "keys/swu-signing.key"),
                                          cert=str(t / "keys/swu-signing.crt"), pkcs11=None, encrypt=encrypt,
                                          aes_key=str(t / "keys/payload.key") if encrypt else None))
        def version(swu):
            with tempfile.TemporaryDirectory() as x:
                c.read_swu(swu, x)
                return re.search(r'version = "([^"]*)"', (Path(x) / "sw-description").read_text())[1]
        def verify(swu):
            c.cmd_verify(argparse.Namespace(swu=str(swu), ca=str(t / "keys/ca.crt"), manifest=None))
        sign(t / "u.swu", t / "s.swu")
        verify(t / "s.swu")
        sign(t / "u.swu", t / "d1.swu", dev=True); sign(t / "d1.swu", t / "d2.swu", dev=True)
        assert version(t / "d1.swu") == version(t / "d2.swu") == "3.0.0.1-dev", version(t / "d2.swu")
        assert "not found" in dies(sign, t / "missing.swu", t / "x.swu")
        # payload encryption: key file checks, round trip, sha256 over the ciphertext, no double encryption
        c.gen_payload_key(t / "keys")
        assert (t / "keys/payload.key").stat().st_mode & 0o777 == 0o600
        assert "exists" in dies(c.gen_payload_key, t / "keys")
        (t / "bad.key").write_text("nothex\n")
        assert "must hold" in dies(c.read_aes_key, t / "bad.key")
        assert "not found" in dies(c.read_aes_key, t / "none.key")
        assert "has none of" in dies(sign, t / "u.swu", t / "e0.swu", encrypt=True)
        (src / "rootfs.ext4.gz").write_bytes(os.urandom(1000))
        (src / "boot.vfat.gz").write_bytes(os.urandom(37))
        (src / "sw-description").write_text(
            'software = { version = "3.0.0.1"; hardware-compatibility = ["1"]; update = { full = { images = (\n'
            + "".join(f' {{\n\t\tfilename = "{n}";\n\t\tsha256 = "{c.sha256(src / n)}";\n }},\n'
                      for n in ("rootfs.ext4.gz", "boot.vfat.gz"))
            + f' {{ filename = "boot0.be"; sha256 = "{c.sha256(src / "boot0.be")}"; }} ); }}; }}; }}')
        plain_rootfs = (src / "rootfs.ext4.gz").read_bytes()
        c.write_swu(["sw-description", "boot0.be", "rootfs.ext4.gz", "boot.vfat.gz"], src, t / "p.swu")
        sign(t / "p.swu", t / "e.swu", encrypt=True)
        verify(t / "e.swu")
        with tempfile.TemporaryDirectory() as x:
            c.read_swu(t / "e.swu", x)
            desc = (Path(x) / "sw-description").read_text()
            assert desc.count("encrypted = true;") == 2 and desc.count("ivt = ") == 2, desc
            ivt = re.search(r'filename = "rootfs.ext4.gz";\s*encrypted = true;\s*ivt = "([0-9a-f]{32})"', desc)[1]
            assert (Path(x) / "boot0.be").read_text() == "b", "boot0.be must stay plain"
            enc = Path(x) / "rootfs.ext4.gz"
            assert enc.read_bytes() != plain_rootfs
            dec = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-K", c.read_aes_key(t / "keys/payload.key"),
                                  "-iv", ivt, "-in", enc], capture_output=True, check=True).stdout
            assert dec == plain_rootfs, "round trip"
        assert "already encrypted" in dies(sign, t / "e.swu", t / "e2.swu", encrypt=True)
        with tempfile.TemporaryDirectory() as x:   # a changed member no longer matches the signed sha256
            c.read_swu(t / "s.swu", x); (Path(x) / "boot0.be").write_text("evil")
            c.write_swu(["sw-description", "sw-description.sig", "boot0.be"], x, t / "bad.swu")
        assert "does not match its signed sha256" in dies(verify, t / "bad.swu")
        # encryption refuses a member whose entry it cannot mark (here inside a nested block)
        (src / "sw-description").write_text(
            'software = { version = "3.0.0.1"; images = ( { filename = "rootfs.ext4.gz";\n'
            ' properties = { x = "y"; }; sha256 = "s"; } ); }')
        c.write_swu(["sw-description", "rootfs.ext4.gz"], src, t / "n.swu")
        assert "cannot find the sw-description entry of rootfs.ext4.gz" in dies(sign, t / "n.swu", t / "n2.swu", encrypt=True)
        assert not (t / "n2.swu").exists()
        (src / "sw-description").write_text(   # filename not first on its line: still marked
            'software = { version = "3.0.0.1"; images = ( { filename = "rootfs.ext4.gz"; sha256 = "s"; } ); }')
        c.write_swu(["sw-description", "rootfs.ext4.gz"], src, t / "n.swu")
        sign(t / "n.swu", t / "n3.swu", encrypt=True)
        with tempfile.TemporaryDirectory() as x:
            c.read_swu(t / "n3.swu", x); one = (Path(x) / "sw-description").read_text()
            assert re.search(r'filename = "rootfs.ext4.gz";\s*encrypted = true;\s*ivt = "[0-9a-f]{32}";', one), one
            assert c.sha256(Path(x) / "rootfs.ext4.gz") in one
        # pib sign: a CA named in image.yaml must exist; with none named a missing keys/ca.crt only warns
        (t / "image.yaml").write_text("signing: {ca: keys/none.crt}\n")
        assert dies(sign, t / "u.swu", t / "x.swu") == "pib: keys/none.crt not found"
        (t / "image.yaml").write_text("signing: {ca: keys/ca.crt}\n"); sign(t / "u.swu", t / "x.swu")
        (t / "image.yaml").unlink()
        with contextlib.redirect_stderr(io.StringIO()) as err:
            sign(t / "u.swu", t / "x.swu")        # cwd t: keys/ca.crt exists, so no warning
        assert err.getvalue() == "", err.getvalue()
        os.rename(t / "keys/ca.crt", t / "keys/ca.off")
        with contextlib.redirect_stderr(io.StringIO()) as err:
            sign(t / "u.swu", t / "x.swu")        # none named, none there: a warning, and it signs
        os.rename(t / "keys/ca.off", t / "keys/ca.crt")
        assert "keys/ca.crt not found; not checking" in err.getvalue(), err.getvalue()
        # pib sign refusals: a --dev bundle without --dev, a leaf from another CA, no key or cert
        assert "was built with --dev" in dies(sign, t / "d1.swu", t / "x.swu")
        c.gen_keys(t / "k3", algo="ec", cn="Other")
        other = argparse.Namespace(swu=str(t / "u.swu"), out=str(t / "x.swu"), dev=False, key=str(t / "k3/swu-signing.key"),
                                   cert=str(t / "k3/swu-signing.crt"), pkcs11=None, encrypt=False, aes_key=None)
        assert dies(c.cmd_sign, other) == f"pib: {t}/k3/swu-signing.crt is not issued by keys/ca.crt; the board would reject the bundle"
        for v in ("SWU_SIGNING_KEY", "SWU_SIGNING_CERT"): os.environ.pop(v, None)
        for key, cert in ((None, None), (str(t / "keys/swu-signing.key"), None), (None, str(t / "keys/swu-signing.crt"))):
            assert dies(c.cmd_sign, argparse.Namespace(**{**vars(other), "key": key, "cert": cert})) == \
                "pib: need --cert and --key (or --pkcs11), or --dev", (key, cert)
        # pib verify refusals
        def bundle(desc, files, name, signed=True):
            b = t / "b"; shutil.rmtree(b, ignore_errors=True); b.mkdir()
            (b / "sw-description").write_text(desc)
            for n, body in files.items(): (b / n).write_text(body)
            c.write_swu(["sw-description", *files], b, t / f"{name}.unsigned.swu")
            if not signed:
                return t / f"{name}.unsigned.swu"
            c.cmd_sign(argparse.Namespace(swu=str(t / f"{name}.unsigned.swu"), out=str(t / f"{name}.swu"), dev=False,
                                          key=str(t / "keys/swu-signing.key"), cert=str(t / "keys/swu-signing.crt"),
                                          pkcs11=None, encrypt=False, aes_key=None))
            return t / f"{name}.swu"
        S0 = c.sha256(src / "boot0.be")
        def D(ver='"3.0.0.1"', compat='hardware-compatibility = ["1"];', arts=f'{{ filename = "boot0.be"; sha256 = "{S0}"; }}'):
            return f'software = {{ version = {ver}; {compat}\n images = ( {arts} ); }}'
        c.gen_keys(t / "k2", algo="ec", cn="Other")
        assert "sw-description.sig must be the second member" in dies(verify, bundle(D(), {"boot0.be": "b"}, "v0", signed=False))
        assert "does not verify against" in dies(c.cmd_verify, argparse.Namespace(
            swu=str(bundle(D(), {"boot0.be": "b"}, "v1")), ca=str(t / "k2/ca.crt"), manifest=None)), "other CA"
        for desc, files, want in ((D(ver='"3.0.0"'), {"boot0.be": "b"}, "is not numeric"),
                                  (D(ver='"3.0.0.1x"'), {"boot0.be": "b"}, "is not numeric"),
                                  (D(compat=""), {"boot0.be": "b"}, "hardware-compatibility is missing"),
                                  (D(compat="hardware-compatibility = [ ];"), {"boot0.be": "b"}, "hardware-compatibility is missing"),
                                  (D(arts=""), {"boot0.be": "b"}, "lists no artifacts"),
                                  (D(), {}, "boot0.be is referenced but not in the bundle"),
                                  (D(arts='{ filename = "boot0.be"; }'), {"boot0.be": "b"}, "boot0.be has no sha256")):
            assert want in dies(verify, bundle(desc, files, "v2")), want
        good = bundle(D(), {"boot0.be": "b"}, "v3")
        def verify_m(m):
            (t / "m.json").write_text(m)
            c.cmd_verify(argparse.Namespace(swu=str(good), ca=str(t / "keys/ca.crt"), manifest=str(t / "m.json")))
        with contextlib.redirect_stdout(io.StringIO()):
            verify_m(json.dumps({"version": "3.0.0.1", "boot0": {"sha256": S0}}))
        for m, want in (("{", "is not a pib manifest"), ("[]", "is not a pib manifest"), ('{"version": "3.0.0.1"}', "is not a pib manifest"),
                        (json.dumps({"version": "3.0.0.2", "boot0": {"sha256": S0}}), "describes version 3.0.0.2, the bundle is 3.0.0.1"),
                        (json.dumps({"version": "3.0.0.1", "boot0": {"sha256": "0" * 64}}), "boot0.be does not match the manifest")):
            assert want in dies(verify_m, m), m
        # read_swu refusals: wrong first member, paths, duplicates, links
        r = t / "r"; r.mkdir(); (r / "sw-description").write_text("x"); (r / "a").write_text("a")
        (r / "sub").mkdir(); (r / "sub/x").write_text("x"); os.symlink("/etc/passwd", r / "ln"); os.link(r / "a", r / "hl"); (r / "b").write_text("b")
        for names, want in ((["b", "sw-description"], "sw-description must be the first member"),
                            (["sw-description", "sub/x"], "is not a plain, unique file name"),
                            (["sw-description", "a", "a"], "is not a plain, unique file name"),
                            (["sw-description", "ln"], "member 'ln' is a link or not a regular file"),
                            (["sw-description", "a", "hl"], "is a link or not a regular file")):
            c.write_swu(names, r, t / "r.swu")
            with tempfile.TemporaryDirectory() as x:
                assert want in dies(c.read_swu, t / "r.swu", x), names
        (t / "empty.swu").write_bytes(b"")
        with tempfile.TemporaryDirectory() as x:
            assert "cpio failed on" in dies(c.read_swu, t / "empty.swu", x)
    finally:
        os.chdir(here)
# check_debs: a customer atf-*, troot-* or u-boot-<target> package is refused, u-boot-tools passes
with tempfile.TemporaryDirectory() as d:
    ws = Path(d); (ws / c.DEBS).mkdir()
    deb = ws / c.DEBS / "x.deb"; deb.write_text("x")
    cfg = {"target": "modalix", "debs": {"key": "k"}}
    real = c.check_deb_signature, c.run
    try:
        c.check_deb_signature = lambda *a: None
        for pkg, msg in (("atf-modalix", "ATF comes from SiMa"), ("atf-modalix-secure", "ATF comes from SiMa"),
                         ("troot-modalix", "tRoot comes from SiMa"), ("u-boot-modalix", "U-Boot inside fip.bin")):
            c.run = lambda cmd, **k: f"Package: {pkg}\nVersion: 9\nArchitecture: arm64\n"
            assert msg in dies(c.check_debs, ws, cfg), pkg
        c.run = lambda cmd, **k: "Package: u-boot-tools\nVersion: 9\nArchitecture: arm64\n"
        assert c.check_debs(ws, cfg) == [("u-boot-tools", "9")]
    finally:
        c.check_deb_signature, c.run = real
with tempfile.TemporaryDirectory() as d:
    t = Path(d); deb = t / "a.deb"; deb.write_bytes(b"deb")
    (t / "mine").mkdir(); (t / "other").mkdir(); c.gen_deb_key(t / "mine"); c.gen_deb_key(t / "other")
    def sign_deb(keydir, *gpg_opts):
        with c.gpg_home() as h:
            c.gpg(h, *gpg_opts, "--import", keydir / "debs-signing.secret.asc")
            c.gpg(h, *gpg_opts, "--yes", "--detach-sign", "--output", f"{deb}.sig", deb)
    pub = t / "mine/debs-signing.asc"
    assert "a.deb is not signed: a.deb.sig not found" in dies(c.check_deb_signature, [deb], pub)
    sign_deb(t / "mine"); c.check_deb_signature([deb], pub)
    deb.write_bytes(b"deb2"); assert "not signed by the customer key" in dies(c.check_deb_signature, [deb], pub)
    deb.write_bytes(b"deb"); sign_deb(t / "other")
    assert "not signed by the customer key" in dies(c.check_deb_signature, [deb], pub), "other key"
    with c.gpg_home() as h:   # a key that expired after signing: gpg exits 0 and says VALIDSIG, not GOODSIG
        old = ["--faked-system-time", "20200101T000000!"]
        c.gpg(h, *old, "--passphrase", "", "--quick-gen-key", "old", "ed25519", "sign", "1d")
        c.gpg(h, *old, "--yes", "--detach-sign", "--output", f"{deb}.sig", deb)
        (t / "old.asc").write_text(c.gpg(h, "--armor", "--export"))
    assert "not signed by the customer key" in dies(c.check_deb_signature, [deb], t / "old.asc"), "expired key"
    both = t / "both.asc"; both.write_text(pub.read_text() + (t / "other/debs-signing.asc").read_text())
    with c.gpg_home() as h:   # two signatures in one .sig, both keys in debs.key: refused, whichever comes first
        for k in ("mine", "other"): c.gpg(h, "--import", t / k / "debs-signing.secret.asc")
        ids = [ln.split(":")[9] for ln in c.gpg(h, "--with-colons", "--list-secret-keys").splitlines() if ln.startswith("fpr:")]
        for first in ids:   # the customer key's signature first, then second
            c.gpg(h, "--yes", "--detach-sign", "-u", first, "-u", next(i for i in ids if i != first),
                  "--output", f"{deb}.sig", deb)
            assert "not signed by the customer key" in dies(c.check_deb_signature, [deb], both), "two signatures"
# kernel FIT signature: a FIT made and signed by mkimage, checked against the key mkimage wrote
if all(shutil.which(x) for x in ("mkimage", "dtc", "openssl")):
    with tempfile.TemporaryDirectory() as d:
        t = Path(d); (t / "keys").mkdir(); (t / "k.bin").write_bytes(os.urandom(5000))
        def sh(*cmd):
            subprocess.run(cmd, cwd=t, check=True, capture_output=True)
        def make(hint, *opts):
            if not (t / f"keys/{hint}.key").exists():
                sh("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", f"keys/{hint}.key",
                   "-out", f"keys/{hint}.crt", "-subj", "/CN=t", "-days", "1")
            (t / "t.its").write_text('/dts-v1/; / { description = "t"; #address-cells = <1>;\n'
                ' images { kernel { description = "k"; data = /incbin/("k.bin"); type = "kernel"; arch = "arm64";\n'
                '  os = "linux"; compression = "none"; load = <0x80000>; entry = <0x80000>; hash-1 { algo = "sha256"; }; }; };\n'
                ' configurations { default = "conf"; conf { description = "c"; kernel = "kernel";\n'
                '  signature-1 { algo = "sha256,rsa2048"; key-name-hint = "%s"; sign-images = "kernel"; }; }; }; };\n' % hint)
            (t / "e.dts").write_text("/dts-v1/; / { };\n")
            sh("dtc", "-O", "dtb", "-o", f"{hint}.dtb", "e.dts")
            sh("mkimage", *opts, "-f", "t.its", "-k", "keys", "-K", f"{hint}.dtb", "-r", f"{hint}.itb")
            return (t / f"{hint}.itb").read_bytes(), c.required_keys(b"junk" + (t / f"{hint}.dtb").read_bytes())
        fit, keys = make("prod")
        assert [h for h, _ in keys.values()] == ["prod"], keys
        c.fit_check(fit, keys)                                   # inline data
        ext, _ = make("prod", "-E")
        c.fit_check(ext, keys)                                   # external data (data-offset)
        bad = bytearray(fit); bad[fit.find(b"c\0", fit.find(b"conf"))] ^= 1
        assert "not signed by" in dies(c.fit_check, bytes(bad), keys), "changed configuration"
        j = fit.find((t / "k.bin").read_bytes()[:64]); bad = bytearray(fit); bad[j + 9] ^= 1
        assert "does not match its sha256 hash" in dies(c.fit_check, bytes(bad), keys), "changed kernel"
        _, other = make("other")
        assert "not signed by U-Boot's required key 'other'" in dies(c.fit_check, fit, other)
        # a signature over the kernel only: the configuration's fdt image could be swapped
        (t / "cov.its").write_text('/dts-v1/; / { description = "t"; #address-cells = <1>;\n images {\n'
            ' kernel { data = /incbin/("k.bin"); type = "kernel"; arch = "arm64"; os = "linux"; compression = "none";\n'
            '  load = <0x80000>; entry = <0x80000>; hash-1 { algo = "sha256"; }; };\n'
            ' fdt-1 { data = /incbin/("e.dts"); type = "flat_dt"; arch = "arm64"; compression = "none"; hash-1 { algo = "sha256"; }; }; };\n'
            ' configurations { default = "conf"; conf { kernel = "kernel"; fdt = "fdt-1";\n'
            '  signature-1 { algo = "sha256,rsa2048"; key-name-hint = "prod"; sign-images = "kernel"; }; }; }; };\n')
        sh("dtc", "-O", "dtb", "-o", "cov.dtb", "e.dts")
        sh("mkimage", "-f", "cov.its", "-k", "keys", "-K", "cov.dtb", "-r", "cov.itb")
        assert dies(c.fit_check, (t / "cov.itb").read_bytes(), c.required_keys((t / "cov.dtb").read_bytes())) == \
            "pib: the kernel FIT signature does not cover /images/fdt-1, /images/fdt-1/hash-1"
        assert "not a FIT" in dies(c.fit_check, b"junk" * 20, keys)
        def fdt(conf, hashes):   # unsigned: no keys, so only the configuration and image hashes are checked
            (t / "x.dts").write_text('/dts-v1/; / { images { kernel { data = [00]; %s }; };\n'
                                     ' configurations { default = "conf"; conf { %s }; }; };\n' % (hashes, conf))
            sh("dtc", "-O", "dtb", "-o", "x.dtb", "x.dts"); return (t / "x.dtb").read_bytes()
        H0 = 'hash-1 { algo = "sha256"; value = [%s]; };' % c.hashlib.sha256(b"\0").hexdigest()
        c.fit_check(fdt('kernel = "kernel";', H0), {})
        assert "has no kernel" in dies(c.fit_check, fdt('fdt = "kernel";', H0), {})
        assert "has no kernel" in dies(c.fit_check, fdt('kernel = "gone";', H0), {})
        for bad in ("", 'hash-1 { algo = "crc32"; value = <0>; };', 'hash-1 { algo = "sha256"; };'):
            assert "has no hash that can be checked" in dies(c.fit_check, fdt('kernel = "kernel";', bad), {}), bad
        c.fit_check(fdt('kernel = "kernel";', 'hash-1 { algo = "crc32"; value = <0>; };' + H0.replace("hash-1", "hash-2")), {})
        assert "does not match its sha256 hash" in dies(c.fit_check, fdt('kernel = "kernel";', H0.replace("[6e", "[6f")), {})
        assert c.required_keys(b"no trees here") == {}
        # check_secure_boot: no key, the development key without --dev, and with it
        devfit, _ = make("dev")
        boot = t / "root/boot"; boot.mkdir(parents=True)
        (boot / "fitImage").write_bytes(devfit); (boot / "fip.bin").write_bytes(b"x")
        (boot / "u-boot.bin").write_bytes(b"x")
        assert "no required FIT key" in dies(c.check_secure_boot, t / "root", False)
        (boot / "u-boot.bin").write_bytes(b"pad" + (t / "dev.dtb").read_bytes())
        assert "need --dev" in dies(c.check_secure_boot, t / "root", False)
        c.check_secure_boot(t / "root", True)
        (boot / "fitImage").write_bytes(fit)                    # signed by prod, U-Boot wants dev
        assert "not signed by" in dies(c.check_secure_boot, t / "root", True)
else:
    FIT_SKIPPED = True
# fip_bl33 / check_fip_uboot: the U-Boot inside fip.bin must be /boot/u-boot.bin
def fip(*entries, magic=0xAA640001, end=True):
    toc = [(u, d) for u, d in entries] + ([(bytes(16), b"")] if end else [])
    pos, head, body = 16 + 40 * len(toc), struct.pack("<IIQ", magic, 0, 0), b""
    for u, d in toc:
        head += struct.pack("<16sQQQ", u, pos + len(body) if d else 0, len(d), 0); body += d
    return head + body
OTHER, UB = bytes(range(1, 17)), b"u-boot" * 100
assert c.fip_bl33(fip((OTHER, b"bl31"), (c.BL33_UUID, UB), (OTHER, b"cert"))) == UB, "middle entry"
assert c.fip_bl33(fip((c.BL33_UUID, UB))) == UB, "only entry"
assert c.fip_bl33(fip((c.BL33_UUID, b""))) == b"", "empty U-Boot entry"
assert c.fip_bl33(fip((OTHER, b"bl31"))) is None, "no U-Boot entry"
assert c.fip_bl33(fip((OTHER, b"x"), (c.BL33_UUID, UB), end=False)) == UB, "no end marker"
assert c.fip_bl33(fip((OTHER, b"x"), end=False)) is None, "no end marker, no U-Boot"
assert c.fip_bl33(fip((c.BL33_UUID, UB), magic=0xAA640002)) is None, "wrong magic"
assert c.fip_bl33(fip() + struct.pack("<16sQQQ", c.BL33_UUID, 0, 4, 0)) is None, "entry after the end"
assert all(c.fip_bl33(b) is None for b in (b"", b"x", fip((c.BL33_UUID, UB))[:55])), "too short"
assert c.fip_bl33(fip((c.BL33_UUID, UB))[:-1]) is None, "cut payload"
assert c.fip_bl33(fip((c.BL33_UUID, b""), end=False)) == b"", "table ends at end of file"
assert c.fip_bl33(fip((c.BL33_UUID, b"first"), (c.BL33_UUID, b"second"))) == b"first", "first entry wins"
assert c.BL33_UUID == bytes.fromhex("d6d0eea7fcead54b97829934f234b6e4"), "TF-A's BL33 UUID"
with tempfile.TemporaryDirectory() as t:
    boot = Path(t) / "boot"; boot.mkdir()
    (boot / "fip.bin").write_bytes(fip((OTHER, b"bl31"), (c.BL33_UUID, UB)))
    (boot / "u-boot.bin").write_bytes(UB)
    c.check_fip_uboot(t)
    for other in (UB[:-1], UB + b"x", UB.replace(b"u", b"v", 1), b""):
        (boot / "u-boot.bin").write_bytes(other)
        assert "not the U-Boot inside /boot/fip.bin" in dies(c.check_fip_uboot, t), other[:8]
    (boot / "u-boot.bin").write_bytes(UB)
    for bad in (b"junk" * 20, fip((OTHER, UB)), fip((c.BL33_UUID, UB))[:-1]):
        (boot / "fip.bin").write_bytes(bad)
        assert "not the U-Boot inside /boot/fip.bin" in dies(c.check_fip_uboot, t)
    (boot / "fip.bin").write_bytes(fip((c.BL33_UUID, UB))[:-1]); (boot / "u-boot.bin").write_bytes(UB[:-1])
    assert "not the U-Boot inside /boot/fip.bin" in dies(c.check_fip_uboot, t), "both cut alike"
    # the check runs in cmd_finish, after the boot files are known to exist
    (boot / "fip.bin").write_bytes(fip((c.BL33_UUID, UB))); (boot / "fitImage").write_bytes(b"f")
    (Path(t) / "lib/linux-image-6-m").mkdir(parents=True)
    (Path(t) / "etc").mkdir(); (Path(t) / "var/lib/dpkg").mkdir(parents=True); (Path(t) / "var/lib/apt/lists").mkdir(parents=True)
    (Path(t) / "var/lib/dpkg/status").write_text("".join(
        f"Package: {p}\nStatus: install ok installed\nVersion: 1\n\n"
        for p in ("linux-image-6-m", "u-boot-m", "atf-m")))
    (Path(t) / "var/lib/apt/lists/repo.sima.ai_dists_x_Packages").write_text(
        "".join(f"Package: {p}\nVersion: 1\n\n" for p in ("linux-image-6-m", "u-boot-m", "atf-m")))
    (Path(t) / "policy.json").write_text(json.dumps(
        {"own_sources": False, "base": "minimal", "dev": False, "target": "m", "vendor": "Acme"}))
    fin = argparse.Namespace(root=t, build=t)
    assert "not the U-Boot inside /boot/fip.bin" in dies(c.cmd_finish, fin), "cmd_finish refuses"
    (boot / "u-boot.bin").write_bytes(UB)
    c.cmd_finish(fin)
    assert [p["name"] for p in json.loads((Path(t) / "packages.json").read_text())] == \
        ["atf-m", "linux-image-6-m", "u-boot-m"], "cmd_finish passes with the matching U-Boot"
    assert (Path(t) / "etc/buildinfo").read_text() == "VENDOR = Acme\n", "vendor from policy.json"
    # cmd_finish refusals: empty boot file, two kernel sets, ATF from another repo, a missing boot package
    (boot / "fitImage").write_bytes(b"")
    assert "lacks /boot/fitImage" in dies(c.cmd_finish, fin); (boot / "fitImage").write_bytes(b"f")
    (Path(t) / "lib/linux-image-7-m").mkdir()
    assert "would mix kernel/DTB sets: linux-image-6-m, linux-image-7-m" in dies(c.cmd_finish, fin)
    (Path(t) / "lib/linux-image-7-m").rmdir()
    lists = Path(t) / "var/lib/apt/lists"
    (lists / "repo.sima.ai_dists_x_Packages").rename(lists / "deb.debian.org_dists_x_Packages")
    assert "the ATF package must come from SiMa.ai's repo, not debian" in dies(c.cmd_finish, fin)
    (lists / "deb.debian.org_dists_x_Packages").rename(lists / "repo.sima.ai_dists_x_Packages")
    st = Path(t) / "var/lib/dpkg/status"; full = st.read_text()
    st.write_text(full.replace("Package: atf-m", "Package: atf-other"))
    assert "must hold one ATF package, found 0: none" in dies(c.cmd_finish, fin)
    st.write_text(full); c.cmd_finish(fin)
# gen_leaf: a failed certificate swap restores the old key; a good renew changes both
with tempfile.TemporaryDirectory() as t:
    t = Path(t)
    c.gen_keys(t, "ecdsa-p384", "T")
    k0, c0 = (t / "swu-signing.key").read_bytes(), (t / "swu-signing.crt").read_bytes()
    real = os.replace
    for exc in (OSError("disk full"), KeyboardInterrupt()):
        def flaky(s, d):
            if str(d).endswith("swu-signing.crt"):
                raise exc
            real(s, d)
        os.replace = flaky
        try:
            c.gen_leaf(t, "ecdsa-p384", "T"); raise AssertionError("did not fail")
        except type(exc):
            pass
        finally:
            os.replace = real
        assert (t / "swu-signing.key").read_bytes() == k0 and (t / "swu-signing.crt").read_bytes() == c0, exc
    def late(s, d):
        real(s, d)
        if str(d).endswith("swu-signing.crt"):
            raise KeyboardInterrupt
    os.replace = late
    try:
        c.gen_leaf(t, "ecdsa-p384", "T"); raise AssertionError("did not fail")
    except KeyboardInterrupt:
        pass
    finally:
        os.replace = real
    c.check_issued(t / "swu-signing.crt", t / "ca.crt")
    pair = [subprocess.run(["openssl", k, "-in", t / f, "-noout", "-pubkey"] if k == "x509" else
                           ["openssl", "pkey", "-in", t / f, "-pubout"], capture_output=True, check=True).stdout
            for k, f in (("x509", "swu-signing.crt"), ("pkey", "swu-signing.key"))]
    assert pair[0] == pair[1], "key and certificate match after a late interrupt"
    k0, c0 = (t / "swu-signing.key").read_bytes(), (t / "swu-signing.crt").read_bytes()
    c.gen_leaf(t, "ecdsa-p384", "T")
    assert (t / "swu-signing.key").read_bytes() != k0 and (t / "swu-signing.crt").read_bytes() != c0
    c.check_issued(t / "swu-signing.crt", t / "ca.crt")
    # no key copy outlives the run; a leftover from a SIGKILL is swept; signal handlers come back
    (t / ".pib-renew-dead").mkdir(); (t / ".pib-renew-dead/old.key").write_text("old secret")
    (t / "keep.me").write_text("x")
    before = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)
    c.gen_leaf(t, "ecdsa-p384", "T")
    assert not list(t.glob(".pib-renew-*")), "stale and own work dirs removed"
    assert (t / "keep.me").read_text() == "x" and (t / "ca.key").is_file()
    assert (signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGHUP)) == before, "handlers restored"
    k0, c0 = (t / "swu-signing.key").read_bytes(), (t / "swu-signing.crt").read_bytes()
    code = ("import os, signal, sys; sys.path.insert(0, %r); import pib.cli as c; from pathlib import Path\n"
            "real = os.replace\n"
            "def hit(s, d):\n"
            "    os.kill(os.getpid(), signal.SIGTERM); real(s, d)\n"
            "os.replace = hit\n"
            "c.gen_leaf(Path(%r), 'ecdsa-p384', 'T')\n") % (str(ROOT / "pib"), str(t))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert r.returncode == 128 + signal.SIGTERM, (r.returncode, r.stderr)
    assert not list(t.glob(".pib-renew-*")), "SIGTERM mid-swap leaves no key copy"
    assert (t / "swu-signing.key").read_bytes() == k0 and (t / "swu-signing.crt").read_bytes() == c0, "old pair intact"
assert "keys/.pib-renew-*/" in c.GITIGNORE
# update_modalix.sh: the inactive boot partition is unmounted when postinst fails, and by postfailure
src = (ROOT / "configs/images/files/update_modalix.sh").read_text()
snip = src[src.index("\t\tbootmnt=$(mktemp -d)"):src.index("\t\tfatlabel ")]
func = src[src.index("release_boot() {"):src.index('echo "== Start $1 =="')]
STUBS = (  # a mount is a marker file M; findmnt lists the last mount point while M exists
    'mount() {{ echo mount >> $LOG; touch $D/M; }}\n'
    'umount() {{ echo umount >> $LOG; {ufail} rm -f $D/M "$1"/*; }}\n'
    'findmnt() {{ [ -f $D/M ] && cat $D/last; return 0; }}\n'
    'mktemp() {{ d=$(command mktemp -d); echo "$d" > $D/last; {chmod} echo "$d"; }}\n')
def run_boot(body, fail=False, ufail=False):
    with tempfile.TemporaryDirectory() as t:
        D = Path(t)
        script = (f'set -e\nLOG={D}/log\nD={t}\n: > $LOG\n' + STUBS.format(chmod='ln -s /dev/full "$d/dm-table.env";' if fail else "",
                  ufail="return 1;" if ufail else "") + 'inactive_boot=/dev/x dmoff=1 dmlen=2 clean_env=1 keep_ddr=0\n'
                  + func + body + 'echo done >> $LOG\n')
        r = subprocess.run(["sh", "-c", script], capture_output=True, text=True)
        last = (D / "last").read_text().strip() if (D / "last").exists() else ""
        return r.returncode, (D / "log").read_text().split(), r.stderr, last
rc, steps, err, last = run_boot(snip)
assert (rc, steps) == (0, ["mount", "umount", "done"]), "clean run unmounts once and clears the trap"
assert not os.path.exists(last)
rc, steps, err, last = run_boot(snip, fail=True)
assert rc != 0 and steps == ["mount", "umount"], (rc, steps)  # a failed write still unmounts
assert not os.path.exists(last), "and removes the mount point"
rc, steps, err, last = run_boot(snip, fail=True, ufail=True)
assert rc != 0 and "could not unmount" in err and "before retrying" in err, err  # a busy mount is reported
# postfailure: whatever is still mounted from the inactive boot partition is unmounted first
fail_part = src[src.index("postfailure)"):]
assert fail_part.index("\t\trelease_boot\n") < fail_part.index("dd if=/dev/zero"), "postfailure calls release_boot"
rc, steps, err, last = run_boot('d=$(mktemp -d); mount /dev/x "$d"\nrelease_boot\n')
assert steps == ["mount", "umount", "done"], steps
rc, steps, err, last = run_boot("release_boot\n")
assert (rc, steps) == (0, ["done"]), "nothing mounted: nothing to do"
# postinst refuses a rootfs slot that is not exactly one linear dm segment
dmsnip = src[src.index("\t\tdm=$(dmsetup"):src.index("\t\tlvchange", src.index("\t\tdm=$(dmsetup"))]
for table, ok in (("0 8 linear 179:2 2048", True), ("0 8 linear 179:2 2048\n8 8 linear 179:2 9000", False),
                  ("0 8 striped 2 128 179:2 0 179:3 0", False), ("", False)):
    r = subprocess.run(["sh", "-c", 'set -e\nvg=v inactive=B\ndmsetup() { printf "%s" "$DM"; }\n' + dmsnip + 'echo "$dmoff $dmlen"'],
                       env={**os.environ, "DM": table}, capture_output=True, text=True)
    assert (r.returncode == 0) == ok and (r.stdout == "2048 8\n" if ok else "not one linear segment" in r.stderr), (table, r)
# PIB_CREDENTIALS: optional, validated up front, mounted by host/pib, read by base.sh with chpasswd -e
H = "$6$salt$" + "a" * 20
CREDS = tempfile.TemporaryDirectory()
def cred(text, name="credentials"):
    f = Path(CREDS.name) / name; f.write_text(text); os.environ["PIB_CREDENTIALS"] = str(f); return f
import contextlib, io
with contextlib.redirect_stderr(io.StringIO()) as e:
    assert c.check_credentials() is None
assert e.getvalue().startswith("pib: no PIB_CREDENTIALS: root and sima are locked") and e.getvalue().count("\n") == 1, e.getvalue()
os.environ["PIB_CREDENTIALS"] = "/nonexistent/credentials"; assert "not found" in dies(c.check_credentials)
LINE, ONE = ":{} must be root:<hash> or sima:<hash> with a $id$ crypt hash, not a password", " must hold exactly one root and one sima line"
for bad, want in ((f"root:root\nsima:{H}\n", LINE.format(1)), (f"root:{H}\n", ONE), (f"sima:{H}\n", ONE),
                  (f"root:{H}\nroot:{H}\nsima:{H}\n", ONE), (f"root:{H}\nsima:{H}\nbob:{H}\n", LINE.format(3)),
                  (f"root:!\nsima:{H}\n", LINE.format(1)), (f"root:{H}\n\nsima:{H}\n", LINE.format(2)),
                  (f"root:{H} \nsima:{H}\n", LINE.format(1)), ("", ONE)):
    f = cred(bad); assert dies(c.check_credentials) == f"pib: {f}{want}", (bad, dies(c.check_credentials))
cred(f"root:{H}\nsima:{H}\n"); c.check_credentials()
cred(f"sima:{H}\nroot:{H}", "a b"); assert "paths used in hooks" in dies(c.check_credentials), "space in path"
os.environ.pop("PIB_CREDENTIALS", None)
# host/pib mounts the file read-only and passes the container path, not the content
with tempfile.TemporaryDirectory() as t:
    t = Path(t); (t / "bin").mkdir(); (t / "keys").mkdir()
    (t / "bin/docker").write_text('#!/bin/sh\nprintf "%s\\n" "$@"\n'); (t / "bin/docker").chmod(0o755)
    (t / "keys/cred.txt").write_text("secret\n")
    r = subprocess.run([str(ROOT / "host/pib"), "build"], cwd=t,
                       env={**os.environ, "PATH": f"{t}/bin:{os.environ['PATH']}", "PIB_CREDENTIALS": str(t / "keys/cred.txt")},
                       capture_output=True, text=True)
    args = r.stdout.split("\n")
    assert f"{t}/keys/cred.txt:/keys/PIB_CREDENTIALS:ro" in args and "PIB_CREDENTIALS=/keys/PIB_CREDENTIALS" in args, args
    assert "secret" not in r.stdout and not any(a.startswith(f"{t}/keys:") for a in args), "only the file is mounted"
    # RELEASE is the one place the release is set: one <major>.<minor>.<patch> line, matching the pinned Pasha artifact
    rel = (ROOT / "RELEASE").read_text()
    assert re.fullmatch(r"\d+\.\d+\.\d+\n", rel), rel
    rel = rel.strip()
    # CODENAME is the one place the eLxr suite is set; the image configs include both files
    assert re.fullmatch(r"[a-z][a-z0-9]*\n", (ROOT / "CODENAME").read_text())
    for f in sorted((ROOT / "configs/images").glob("image-*-modalix.yaml")):
        head = f.read_text().splitlines()[5:7]
        assert head == ["version: ${include:/etc/pib-release}", "codename: ${include:/etc/pib-codename}"], (f, head)
    assert "ARG CODENAME" not in (ROOT / "Dockerfile").read_text(), "the suite is set only in CODENAME"
    locked = json.loads((ROOT / "deps/artifacts.json").read_text())
    assert locked["platform_release"] == rel
    assert locked["artifacts"][0]["filename"] == f"pasha-{rel}-py3-none-any.whl"
    (t / "copy").mkdir(); shutil.copy(ROOT / "host/pib", t / "copy/pib")
    e = {k: v for k, v in os.environ.items() if k not in ("SIMA_RELEASE", "PIB_IMAGE", "PIB_CREDENTIALS")}
    for shim, env, tag in ((ROOT / "host/pib", {}, "ghcr.io/sima-neat/palette-image-builder:latest"),
                           (t / "copy/pib", {}, "ghcr.io/sima-neat/palette-image-builder:latest"),
                           (t / "copy/pib", {"PIB_IMAGE": "reg/x:7"}, "reg/x:7")):
        r = subprocess.run([str(shim), "verify"], cwd=t, capture_output=True, text=True,
                           env={**e, **env, "PATH": f"{t}/bin:{os.environ['PATH']}"})
        assert r.returncode == 0 and r.stdout.split("\n")[-4:-1] == [tag, "pib", "verify"], (r.stdout, r.stderr)
        assert "--privileged" not in r.stdout
    for missing in (t / "keys/none", t / "keys"):
        r = subprocess.run([str(ROOT / "host/pib"), "sign"], cwd=t, capture_output=True, text=True,
                           env={**os.environ, "PATH": f"{t}/bin:{os.environ['PATH']}", "SWU_SIGNING_KEY": str(missing)})
        assert r.returncode == 1 and r.stdout == "" and f"SWU_SIGNING_KEY: {missing} is not a file" in r.stderr, r
    # pcscd: a socket in a temp dir stands in for the host's, so every branch runs on any machine
    (t / "pcscd").mkdir(); (t / "nopcscd").mkdir()
    sk = socket.socket(socket.AF_UNIX); sk.bind(str(t / "pcscd/pcscd.comm"))
    M, KEY, CRT = f"{t}/pcscd:/run/pcscd:ro", "pkcs11:token=t;object=k", "pkcs11:object=c"
    def shim(argv, **env):  # a None value removes the variable
        env = {k: v for k, v in {**e, "PATH": f"{t}/bin:{os.environ['PATH']}", **env}.items() if v is not None}
        r = subprocess.run([str(ROOT / "host/pib"), *argv], cwd=t, capture_output=True, text=True, env=env)
        assert r.returncode == 0 and r.stderr == "", r
        return r.stdout.split("\n")
    for argv, env, mounts, passed in (
            # every pib sign gets the socket, however the key reaches it (--key, image.yaml, --pkcs)
            (["sign"], {"SWU_SIGNING_KEY": KEY}, 1, [f"SWU_SIGNING_KEY={KEY}"]),
            (["sign"], {"SWU_SIGNING_KEY": str(t / "keys/cred.txt")}, 1, ["SWU_SIGNING_KEY=/keys/SWU_SIGNING_KEY"]),
            (["sign", "--pkcs11", KEY, "x.swu"], {}, 1, []),
            (["sign"], {}, 1, []),
            # two URIs share one mount: docker refuses a duplicate mount point
            (["sign"], {"SWU_SIGNING_KEY": KEY, "SWU_SIGNING_CERT": CRT}, 1,
             [f"SWU_SIGNING_KEY={KEY}", f"SWU_SIGNING_CERT={CRT}"]),
            # a relative PIB_PCSCD_DIR is mounted by its absolute path, not as a named volume
            (["sign"], {"PIB_PCSCD_DIR": "pcscd"}, 1, []),
            (["sign"], {"SWU_SIGNING_KEY": KEY, "PIB_PCSCD_DIR": str(t / "nopcscd")}, 0, [f"SWU_SIGNING_KEY={KEY}"]),
            (["sign"], {"PIB_PCSCD_DIR": str(t / "missing")}, 0, []),
            (["sign"], {"PIB_PCSCD_DIR": "missing"}, 0, []),
            (["sign"], {"PIB_PCSCD_DIR": "pcscd", "CDPATH": str(t)}, 1, []),  # cd prints the path
            # the default is the host's /run/pcscd, mounted only where its socket is up
            (["sign"], {"PIB_PCSCD_DIR": None},
             ["/run/pcscd:/run/pcscd:ro"] if Path("/run/pcscd/pcscd.comm").is_socket() else [], []),
            # each variable reaches only the command that reads it
            (["sign"], {"PIB_CREDENTIALS": str(t / "keys/cred.txt")}, 1, []),
            (["build"], {"SWU_SIGNING_KEY": KEY, "SWU_SIGNING_CERT": str(t / "keys/cred.txt")}, 0, []),
            (["build", "--pkcs11", KEY], {}, 0, []),
            (["verify"], {"SWU_SIGNING_KEY": KEY, "PIB_CREDENTIALS": str(t / "keys/cred.txt")}, 0, []),
            (["--version"], {"SWU_SIGNING_KEY": KEY}, 0, []),
            ([], {"SWU_SIGNING_KEY": KEY}, 0, [])):
        args = shim(argv, **{"PIB_PCSCD_DIR": str(t / "pcscd"), **env})
        want = [M] * mounts if isinstance(mounts, int) else mounts
        assert [a for a in args if a.endswith(":/run/pcscd:ro")] == want, (argv, env, args)
        assert [a for a in args if a.startswith(("SWU_", "PIB_CREDENTIALS="))] == passed, (argv, env, args)
        assert any(a.startswith(f"{t}/keys/") for a in args) == any("=/keys/" in a for a in passed), (argv, env, args)
    sk.close()
hook = (ROOT / "configs/images/hooks/base.sh").read_text()
assert all(" chpasswd" not in ln or "chpasswd -e" in ln for ln in hook.splitlines()), "no password in the hook"
snip = hook[hook.index("if [ -n \"${PIB_CREDENTIALS"):hook.index("chroot \"$1\" usermod -a -G sima root")].replace('"$1"', "/r")
def hook_run(env):
    return subprocess.run(["sh", "-c", 'chroot() { echo "chroot $*"; cat; }\nset -e\n' + snip + 'echo reached'],
                          env={"PATH": os.environ["PATH"], **env}, stdin=subprocess.DEVNULL, capture_output=True, text=True)
r = hook_run({})
assert r.returncode == 0 and r.stdout == "reached\n", r
f = cred(f"root:{H}\nsima:{H}\n"); os.environ.pop("PIB_CREDENTIALS")
r = hook_run({"PIB_CREDENTIALS": str(f)})
assert r.returncode == 0 and r.stdout.split("\n")[0] == "chroot /r chpasswd -e" and f"root:{H}" in r.stdout, r
# SSH: no root password login, no host keys in the image, each board makes its own on first boot
unit = (ROOT / "configs/images/overlay/simaai/usr/lib/systemd/system/simaai-ssh-hostkeys.service").read_text()
assert "PermitRootLogin yes" not in hook, "root keeps the default prohibit-password"
assert hook.rstrip().endswith('rm -f "$1"/etc/ssh/ssh_host_*'), "host keys removed last, after every package is configured"
assert 'systemctl enable --root="$1" simaai-ssh-hostkeys' in hook
assert "Before=ssh.service" in unit and "ExecStart=/usr/bin/ssh-keygen -A" in unit and "WantedBy=ssh.service" in unit
# --supplier: checked before anything else; empty means SiMa.ai
with tempfile.TemporaryDirectory() as t:
    here = os.getcwd(); os.chdir(t)
    try:
        for bad in ("  ", "a\nb", "a\tb", "a\x7f", "a\x85b", "a\u2028b", "a\u2029b", "x" * 257, "a${x}"):
            assert "--supplier must be" in dies(c.cmd_build, argparse.Namespace(supplier=bad, dev=False)), repr(bad)
        for ok in (None, "", "x" * 256, "Acme's $HOME `x` Corp"):
            assert "image.yaml" in dies(c.cmd_build, argparse.Namespace(supplier=ok, dev=False)), repr(ok)
    finally:
        os.chdir(here)
# the shipped sw-description lists the SBOM; a customer one must too
M = {"rootfs.ext4.gz", "boot.vfat.gz", "boot0.be", "swu-os-marker", "sbom.cdx.json", "update_modalix.sh"}
SWD = (ROOT / "configs/images/files/sw-description").read_text()
c.check_description(SWD, M)
assert ("sbom.cdx.json", "@@sbom.cdx.json@@") in list(c.artifacts(SWD))
d = 'software = { version = "@@VERSION@@"; hardware-compatibility: [ @@HW_COMPAT@@ ];\n'
b0 = '{ filename = "boot0.be"; sha256 = "@@boot0.be@@"; }\n'
sb = '{ filename = "sbom.cdx.json"; sha256 = "@@sbom.cdx.json@@"; }\n'
assert "must list sbom.cdx.json" in dies(c.check_description, d + b0 + "}", M)
assert "must list boot0.be" in dies(c.check_description, d + sb + "}", M)
assert "must be @@sbom.cdx.json@@" in dies(c.check_description, d + b0 + sb.replace("@@sbom", "@@x") + "}", M)
assert "does not carry" in dies(c.check_description, d + b0 + sb + "}", M - {"sbom.cdx.json"})
c.check_description(d + b0 + sb + "}", M)
# stages: SBOM made after the unpack, copied into the tree before the cpio and ext4 are made,
# and packed into the swu as sbom.cdx.json
import yaml
st = yaml.safe_load((ROOT / "configs/images/image-stages.yaml").read_text())["install"]
names = [s["name"] for s in st]
i = {k: next(n for n, s in enumerate(names) if s.startswith(k)) for k in (
    "Unpack the rootfs", "Generate CycloneDX", "Generate CPIO", "Create rootfs file system", "Generate SWUpdate")}
assert list(i.values()) == sorted(i.values()), i
sbom_cmds = st[i["Generate CycloneDX"]]["options"]["commands"]
assert sbom_cmds[1].startswith("install -D -m 0644 ${params.sbom} ${params.rootfs}/usr/share/doc/sbom/")
assert {"src": "${params.sbom}", "name": "sbom.cdx.json"} in st[i["Generate SWUpdate"]]["options"]["files"]
# write_effective(): the supplier reaches debsbom as one shell word, exactly as given
with tempfile.TemporaryDirectory() as t:
    ws = Path(t); img = ws / "configs/images"; (ws / "ca.crt").write_text("ca")
    for o in ("elxr", "simaai"): (img / "overlay" / o).mkdir(parents=True)
    for f in ("image-minimal-modalix.yaml", "image-params.yaml", "image-stages.yaml"):
        shutil.copy(ROOT / "configs/images" / f, img)
    cfg = {"base": "minimal", "target": "modalix", "version": "3.0.0.1", "release": "3.0.0"}
    for sup in ("SiMa.ai", "Acme's $HOME `x` Corp", "Société Générale", "-Acme"):
        c.write_effective(ws, cfg, "3.0.0.1", ws / "ca.crt", [], None, sup)
        st2 = yaml.safe_load((ws / "configs/images/pib-stages.yaml").read_text())["install"]
        cmd = next(s for s in st2 if s["name"].startswith("Generate CycloneDX"))["options"]["commands"][0]
        assert [w for w in shlex.split(cmd) if w.startswith("--distro-supplier")] == ["--distro-supplier=" + sup], cmd
        r = subprocess.run(["sh", "-c", "printf %s " + shlex.quote(sup)], capture_output=True, text=True)
        assert r.stdout == sup, r
# write_manifest(): records the supplier
with tempfile.TemporaryDirectory() as t:
    ws = Path(t); out = ws / "out"; out.mkdir(); (ws / "build").mkdir()
    stem = "elxr-minimal-modalix-3.0.0.1-"
    (out / (stem + "agate-arm64-boot0.be")).write_bytes(b"b0")
    (ws / "build/packages.json").write_text(json.dumps([{"name": "troot-modalix", "version": "3.0.0", "origin": "sima"}]))
    real = c.release_boot0_md5
    c.release_boot0_md5 = lambda spec, cfg: hashlib.md5(b"b0").hexdigest()
    try:
        assert c.write_manifest(ws, out, {"release": "3.0.0"}, "3.0.0.1", stem, "Acme Corp") is None
    finally:
        c.release_boot0_md5 = real
    m = json.loads((out / (stem + "agate-arm64.manifest.json")).read_text())
    assert m["supplier"] == "Acme Corp" and m["boot0"]["package"] == "troot-modalix 3.0.0 (sima)", m
# write_manifest(): no package list or boot0.be, several tRoot packages, no tRoot, the secure tRoot
with tempfile.TemporaryDirectory() as t:
    ws = Path(t); out = ws / "out"; out.mkdir(); (ws / "build").mkdir()
    stem, man = "elxr-minimal-modalix-3.0.0.1-", out / "elxr-minimal-modalix-3.0.0.1-agate-arm64.manifest.json"
    b0 = out / (stem + "agate-arm64-boot0.be"); pk = ws / "build/packages.json"
    asked = []
    real = c.release_boot0_md5
    c.release_boot0_md5 = lambda spec, cfg: asked.append(spec) or hashlib.md5(b"b0").hexdigest()
    wm = lambda: c.write_manifest(ws, out, {"release": "3.0.0"}, "3.0.0.1", stem, "S")
    NONE = "pib: the build left no package list or boot0.be to check"
    try:
        assert dies(wm) == NONE, "no boot0.be"
        b0.write_bytes(b"b0"); assert dies(wm) == NONE, "no packages.json"
        pk.write_text("[]"); (out / (stem + "agate-arm64-boot0.bex")).write_bytes(b"x")
        (out / (stem + "trixie-arm64-boot0.be")).write_bytes(b"b0"); assert dies(wm) == NONE, "two boot0.be"
        (out / (stem + "trixie-arm64-boot0.be")).unlink()
        T = lambda n, v="3": {"name": n, "version": v, "origin": "sima"}
        pk.write_text(json.dumps([T("troot-modalix"), T("troot-modalix-secure"), T("bash")]))
        assert dies(wm) == "pib: the image holds more than one tRoot package: troot-modalix, troot-modalix-secure"
        assert not man.exists() and asked == [], "nothing written, nothing asked"
        pk.write_text(json.dumps([T("bash")])); wm()
        assert asked == ["troot-modalix"] and json.loads(man.read_text())["boot0"]["package"] == "unknown"
        pk.write_text(json.dumps([T("troot-modalix-secure", "3.0.1"), T("bash")])); wm()
        assert asked[-1] == "troot-modalix-secure=3.0.1"
        assert json.loads(man.read_text())["boot0"]["package"] == "troot-modalix-secure 3.0.1 (sima)"
    finally:
        c.release_boot0_md5 = real
# entrypoint: only "pib build" and a shell get the build set-up; other pib commands run at once
ep = (ROOT / "entrypoint.sh").read_text()
case = ep[ep.index('case "${1:-} ${2:-}" in'):ep.index("# --- arm64 emulation")]
# Emulation setup has its own kernel-boundary tests; isolate dispatch here.
case = case.replace("python3 -m pib.emulation", "true")
with tempfile.TemporaryDirectory() as t:
    (Path(t) / "pib").write_text('#!/bin/sh\necho "ran $*"\n'); (Path(t) / "pib").chmod(0o755)
    for argv, want in ((["pib", "sign", "x"], "ran sign x\n"), (["pib", "verify"], "ran verify\n"),
                       (["pib", "build", "--dev"], "setup\n"), (["pib", "build"], "setup\n"), (["bash"], "setup\n"), (["bash", "-c", "x"], "setup\n"),
                        (["pib", "builder"], "ran builder\n")):
        r = subprocess.run(["bash", "-c", case + "echo setup", "ep", *argv], capture_output=True, text=True,
                           env={"PATH": f"{t}:{os.environ['PATH']}"})
        assert r.stdout == want, (argv, r.stdout, r.stderr)
# update_modalix.sh: preinst drops a boot0.be or OS marker left in /tmp before swupdate writes this bundle's
pre = src[src.index("preinst)\n"):src.index("postinst)\n")]
assert pre.index('rm -f "$BOOT0" "$OSMARK"') < pre.index("resolve_slots"), "cleared first"
with tempfile.TemporaryDirectory() as t:
    b0, osm = Path(t) / "boot0.be", Path(t) / "os"; b0.write_text("stale"); osm.write_text("stale")
    r = subprocess.run(["sh", "-c", f'BOOT0={b0} OSMARK={osm}\n' + pre.split("\n", 3)[2] + "\n"], capture_output=True, text=True)
    assert r.returncode == 0 and not b0.exists() and not osm.exists(), r
# check_debs: unsigned, wrong architecture, two of one boot package, none at all
with tempfile.TemporaryDirectory() as d:
    ws = Path(d); (ws / c.DEBS).mkdir(); cfg = {"target": "modalix", "debs": {"key": "k"}}
    assert c.check_debs(ws, {"target": "modalix"}) == [], "no debs, no key needed"
    (ws / c.DEBS / "a.deb").write_text("x"); (ws / c.DEBS / "b.deb").write_text("x")
    assert dies(c.check_debs, ws, {"target": "modalix"}) == "pib: custom .debs must be signed: set debs.key in image.yaml"
    CTRL = {"a.deb": "Package: linux-image-6.18-modalix\nVersion: 1\nArchitecture: arm64\n",
            "b.deb": "Package: linux-image-6.19-modalix\nVersion: 2\nArchitecture: all\n"}
    real = c.check_deb_signature, c.run
    try:
        c.check_deb_signature = lambda *a: None
        c.run = lambda cmd, **k: CTRL[Path(cmd[2]).name]
        assert "custom-debs/ holds more than one kernel package: linux-image-6.18-modalix, linux-image-6.19-modalix" \
            in dies(c.check_debs, ws, cfg)
        CTRL["b.deb"] = "Package: x\nVersion: 2\nArchitecture: amd64\n"
        assert dies(c.check_debs, ws, cfg) == "pib: b.deb is for amd64, not arm64"
        CTRL["b.deb"] = "Package: x\nVersion: 2\nArchitecture: all\n"
        assert c.check_debs(ws, cfg) == [("linux-image-6.18-modalix", "1"), ("x", "2")]
    finally:
        c.check_deb_signature, c.run = real
# check_repo: needs the container's codename and published repo, and every custom deb in it
with tempfile.TemporaryDirectory() as d:
    os.environ["PIB_REPO_DIR"] = d; os.environ.pop("PIB_CODENAME", None)
    try:
        assert "/etc/pib-codename is missing" in dies(c.check_repo, [])
        os.environ["PIB_CODENAME"] = "agate"
        assert dies(c.check_repo, []) == f"pib: local repo {d}/dists/agate is not published; start via the entrypoint"
        dist = Path(d) / "dists/agate"; (dist / "non-free/binary-arm64").mkdir(parents=True); (dist / "Release").write_text("r")
        c.check_repo([])
        assert "x 2 is missing from the local repo" in dies(c.check_repo, [("x", "2")]), "empty index"
        (dist / "non-free/binary-arm64/Packages").write_text("Package: x\nVersion: 1\n\nPackage: y\nVersion: 2\n")
        c.check_repo([("x", "1"), ("y", "2")])
        assert "x 2 is missing" in dies(c.check_repo, [("x", "2")]), "other version"
    finally:
        os.environ.pop("PIB_REPO_DIR"); os.environ.pop("PIB_CODENAME", None)
# container_codename() and sima_release_line(): /etc/pib-codename wins over PIB_CODENAME; sima_source wins over both
with tempfile.TemporaryDirectory() as d:
    saved = {k: os.environ.pop(k, None) for k in ("PIB_CODENAME", "PIB_SIMA_APT_URL", "MIRROR_1")}
    try:
        assert c.container_codename() is None
        assert "PIB_SIMA_APT_URL or /etc/pib-codename is missing" in dies(c.sima_release_line, {})
        assert c.sima_release_line({"sima_source": "deb http://m.example/x s non-free"}) == "deb http://m.example/x s non-free"
        os.environ.update(PIB_CODENAME="envsuite", PIB_SIMA_APT_URL="https://r.example/rel")
        assert c.sima_release_line({}) == "deb [signed-by=/usr/share/keyrings/simaai-public.gpg] https://r.example/rel envsuite non-free"
        assert c.sima_release_line({"sima_source": ""}) == c.sima_release_line({}), "empty sima_source is unset"
        c.CODENAME_FILE = Path(d) / "pib-codename"; c.CODENAME_FILE.write_text("filesuite\n")
        assert c.container_codename() == "filesuite"
        assert c.sima_release_line({}).endswith(" https://r.example/rel filesuite non-free")
        os.environ["MIRROR_1"] = "deb http://ignored/ x non-free"
        assert c.sima_release_line({}).endswith(" filesuite non-free"), "MIRROR_1 in pib's own env is not read"
        assert c.sima_release_line({"sima_source": "deb http://m.example/x s non-free"}) == "deb http://m.example/x s non-free"
    finally:
        c.CODENAME_FILE = TEST_CODENAME_FILE
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None: os.environ[k] = v
# cmd_clean: this workspace's elxr-*-<target>-*.img by inode, deleted backing files too; --yes deactivates and detaches
with tempfile.TemporaryDirectory() as d:
    calls = []
    (Path(d) / "out").mkdir()
    def ino(n):
        f = Path(d) / "out" / n; f.touch(); s = f.stat(); return f"{os.major(s.st_dev)}:{os.minor(s.st_dev)} {s.st_ino}"
    mine, other = ino("elxr-minimal-modalix-3.0.0.1-agate-arm64.img"), ino("elxr-minimal-other-3.0.0.1-agate-arm64.img")
    LOOPS = (f"/dev/loop7 {mine} /workspace/out/elxr-minimal-modalix-3.0.0.1-agate-arm64.img\n"
             "/dev/loop8 8:1 99 /w2/x/elxr-palette-modalix-3.0.0.2-agate-arm64.img (deleted)\n"
             "/dev/loop6 8:1 98 /workspace/out/elxr-minimal-modalix-3.0.0.1-agate-arm64.img\n"
             f"/dev/loop9 {other} /workspace/out/elxr-minimal-other-3.0.0.1-agate-arm64.img\n"
             "/dev/loop10 8:1 97 /var/lib/snapd/core.snap\n/dev/loop11\n")
    cwd = os.getcwd(); os.chdir(d)
    def fake_clean(cmd, **k):
        calls.append(cmd); return LOOPS if cmd[0] == "losetup" and "-l" in cmd else ""
    saved = c.run, c.load_config, c.subprocess.run
    def fake_sp(cmd, *a, **k):
        assert cmd[:2] == ["pvs", "--noheadings"], cmd; return subprocess.CompletedProcess(cmd, 0, "  vgA\n  vgA\n", "")
    try:
        c.run, c.load_config, c.subprocess.run = fake_clean, lambda ws: {"target": "modalix"}, fake_sp
        real_glob = Path.glob
        Path.glob = lambda self, pat: iter([Path(f"/dev/{pat[:-1]}1")]) if str(self) == "/dev" else real_glob(self, pat)
        with contextlib.redirect_stdout(io.StringIO()) as o:
            c.cmd_clean(argparse.Namespace(yes=False))
        assert o.getvalue() == ("pib: would deactivate vgA and detach /dev/loop7\npib: would deactivate vgA and detach /dev/loop8\n"
                                "pib: run 'pib clean --yes' to do this (stop running builds first)\n"), o.getvalue()
        assert [x for x in calls if x[0] != "losetup"] == [], "a dry run changes nothing"
        calls.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            c.cmd_clean(argparse.Namespace(yes=True))
        assert calls[1:] == [["vgchange", "-an", "vgA"], ["losetup", "-d", "/dev/loop7"],
                             ["vgchange", "-an", "vgA"], ["losetup", "-d", "/dev/loop8"]], calls
        LOOPS = f"/dev/loop9 {other} /workspace/out/elxr-minimal-other-3.0.0.1-agate-arm64.img\n"
        with contextlib.redirect_stdout(io.StringIO()) as o:
            c.cmd_clean(argparse.Namespace(yes=True))
        assert o.getvalue() == "pib: nothing to clean\n"
    finally:
        Path.glob = real_glob; os.chdir(cwd)
        c.run, c.load_config, c.subprocess.run = saved
# cmd_diff: + added, - removed, ~ changed, between an SBOM and a 'package version' list
with tempfile.TemporaryDirectory() as d:
    img, ref = Path(d) / "i.cdx.json", Path(d) / "ref.txt"
    img.write_text(json.dumps({"components": [{"name": "a", "version": "2"}, {"name": "b", "version": "1"},
                                              {"name": "new", "version": "1"}]}))
    ref.write_text("a 1\nb 1\ngone 3\n\njunk\n")
    with contextlib.redirect_stdout(io.StringIO()) as o:
        c.cmd_diff(argparse.Namespace(image=str(img), against=str(ref)))
    assert o.getvalue() == "~ a 1 -> 2\n- gone 3\n+ new 1\n", o.getvalue()
    with contextlib.redirect_stdout(io.StringIO()) as o:
        c.cmd_diff(argparse.Namespace(image=str(img), against=str(img)))
    assert o.getvalue() == "", "same file: no difference"
# keys init refuses any existing key file; keys renew needs the CA and reports a write failure
with tempfile.TemporaryDirectory() as d:
    k = Path(d) / "k"
    with contextlib.redirect_stdout(io.StringIO()):
        c.cmd_keys_init(argparse.Namespace(out=str(k), algo="ec", cn="T"))
    assert sorted(p.name for p in k.iterdir()) == sorted(["ca.key", "ca.crt", "swu-signing.key", "swu-signing.crt",
                                                         "debs-signing.asc", "debs-signing.secret.asc"])
    c.check_issued(k / "swu-signing.crt", k / "ca.crt")
    for name in ("ca.crt", "swu-signing.key", "debs-signing.asc"):
        e = Path(d) / "e"; e.mkdir(exist_ok=True); (e / name).write_text("mine")
        assert dies(c.cmd_keys_init, argparse.Namespace(out=str(e), algo="ec", cn="T")) == f"pib: {e}/{name} exists; refusing to overwrite keys"
        assert (e / name).read_text() == "mine" and len(list(e.iterdir())) == 1; (e / name).unlink()
    (k / "ca.key").rename(Path(d) / "ca.key")
    assert dies(c.cmd_keys_renew, argparse.Namespace(out=str(k), algo="ec", cn="T")) == f"pib: {k}/ca.key not found; a new signing leaf needs the CA"
    (Path(d) / "ca.key").rename(k / "ca.key")
    real = c.gen_leaf
    try:
        c.gen_leaf = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
        assert dies(c.cmd_keys_renew, argparse.Namespace(out=str(k), algo="ec", cn="T")) == "pib: cannot write the new signing leaf: disk full"
    finally:
        c.gen_leaf = real
    old = (k / "swu-signing.crt").read_bytes()
    with contextlib.redirect_stdout(io.StringIO()):
        c.cmd_keys_renew(argparse.Namespace(out=str(k), algo="ec", cn="T"))
    assert (k / "swu-signing.crt").read_bytes() != old; c.check_issued(k / "swu-signing.crt", k / "ca.crt")
# release_boot0_md5: only the line sima_release_line() gives, the version asked for, the md5 from the package's md5sums
calls, lists = [], []
def fake_run(cmd, cwd=None, **k):
    calls.append(cmd)
    if cmd[0] == "apt-get" and cmd[-1] == "update":
        lists.append(Path(next(o for o in cmd if o.startswith("-oDir::Etc::sourcelist=")).partition("=")[2]).read_text())
    if cmd[0] == "apt-get" and cmd[-2] == "download":
        (Path(cwd) / "troot-modalix_3.0.0_arm64.deb").write_text("deb")
    if cmd[0] == "dpkg-deb":
        return MD5SUMS
    return ""
real = c.run
assert dies(c.release_boot0_md5, "troot-modalix", {}) == "pib: PIB_SIMA_APT_URL or /etc/pib-codename is missing; run inside the PIB container"
os.environ.update(PIB_SIMA_APT_URL="https://r.example/rel", PIB_CODENAME="agate")
try:
    c.run = fake_run
    MD5SUMS = "aa  boot/Release/boot0.bex\nbb  boot/Release/boot0.be\ncc  boot/other\n"
    assert c.release_boot0_md5("troot-modalix=3.0.0", {}) == "bb"
    assert calls[1][-2:] == ["download", "troot-modalix=3.0.0"] and "-oDir::Etc::sourceparts=/dev/null" in calls[0], calls
    assert lists == ["deb [signed-by=/usr/share/keyrings/simaai-public.gpg] https://r.example/rel agate non-free\n"], lists
    assert c.release_boot0_md5("troot-modalix", {"sima_source": "deb http://m.example/sima agate non-free"}) == "bb"
    assert lists[1] == "deb http://m.example/sima agate non-free\n", lists
    MD5SUMS = "aa  boot/other\n"
    assert dies(c.release_boot0_md5, "troot-modalix", {}) == "pib: troot-modalix md5sums has no boot/Release/boot0.be"
finally:
    c.run = real
    os.environ.pop("PIB_SIMA_APT_URL"); os.environ.pop("PIB_CODENAME")
# cmd_build: a boot0.be check that fails, or cannot run, leaves no out/<stem>* behind
with tempfile.TemporaryDirectory() as t:
    ws = Path(t); here = os.getcwd(); os.chdir(ws)
    out = ws / "out"; (ws / "build").mkdir(); (ws / "configs/images").mkdir(parents=True)
    cfg = {"base": "minimal", "target": "modalix", "version": "3.0.0.1", "release": "3.0.0"}
    stubs = dict(load_config=lambda ws: cfg, check_credentials=lambda: None, check_debs=lambda ws, cfg: [],
                 check_repo=lambda debs: None, build_signing=lambda ws, cfg, dev: ("k", "c", "ca"),
                 write_effective=lambda *a: ws / "configs/images/pib.yaml")
    saved = {k: getattr(c, k) for k in (*stubs, "release_boot0_md5")}
    real_sp = c.subprocess.run
    def fake_rs(cmd, *a, **k):
        if cmd[:2] != ["rs", "build"]:
            return real_sp(cmd, *a, **k)
        for n in ("agate-arm64-boot0.be", "agate-arm64.unsigned.swu", "agate-arm64.img.gz"):
            (out / ("elxr-minimal-modalix-3.0.0.1-" + n)).write_text("b0")
        (ws / "build/packages.json").write_text(json.dumps([{"name": "troot-modalix", "version": "3", "origin": "sima"}]))
        return subprocess.CompletedProcess(cmd, 0)
    (ws / "out").mkdir(); (out / "elxr-palette-modalix-3.0.0.1-agate-arm64.swu").write_text("other image")
    os.environ.update(PIB_SIMA_APT_URL="https://r.example/rel", PIB_CODENAME="agate")
    try:
        for k, v in stubs.items(): setattr(c, k, v)
        c.subprocess.run = fake_rs
        def stop(spec, cfg): next(iter(()))   # StopIteration, as when apt-get download leaves no .deb
        for md5, want in ((lambda spec, cfg: "0" * 32, "md5 check failed for boot0.be"),
                          (lambda spec, cfg: c.die("no SiMa release apt line"), "no SiMa release apt line"), (stop, None)):
            c.release_boot0_md5 = md5
            if want:
                assert want in dies(c.cmd_build, argparse.Namespace(supplier=None, dev=False)), want
            else:
                try:
                    c.cmd_build(argparse.Namespace(supplier=None, dev=False)); raise AssertionError("did not fail")
                except StopIteration:
                    pass
            assert sorted(p.name for p in out.iterdir()) == ["elxr-palette-modalix-3.0.0.1-agate-arm64.swu"], list(out.iterdir())
        # success: manifest written, the throwaway signature dropped, SHA256SUMS over out/
        def fake_ok(cmd, *a, **k):
            if cmd[:2] != ["rs", "build"]:
                return real_sp(cmd, *a, **k)
            assert k["env"]["MIRROR_1"] == want_m1, k["env"].get("MIRROR_1")
            b = ws / "b"; b.mkdir(exist_ok=True)
            for n in ("sw-description", "sw-description.sig", "boot0.be"): (b / n).write_text(n)
            c.write_swu(["sw-description", "sw-description.sig", "boot0.be"], b, out / "elxr-minimal-modalix-3.0.0.1-agate-arm64.swu")
            (out / "elxr-minimal-modalix-3.0.0.1-agate-arm64-boot0.be").write_text("b0")
            return subprocess.CompletedProcess(cmd, 0)
        c.subprocess.run = fake_ok
        want_m1 = "deb [signed-by=/usr/share/keyrings/simaai-public.gpg] https://r.example/rel agate non-free"
        c.release_boot0_md5 = lambda spec, cfg: hashlib.md5(b"b0").hexdigest()
        with contextlib.redirect_stdout(io.StringIO()) as o:
            c.cmd_build(argparse.Namespace(supplier=None, dev=False))
        S = "elxr-minimal-modalix-3.0.0.1-agate-arm64"
        assert sorted(p.name for p in out.iterdir()) == sorted(["SHA256SUMS", S + "-boot0.be", S + ".manifest.json", S + ".unsigned.swu",
                                                                "elxr-palette-modalix-3.0.0.1-agate-arm64.swu"]), list(out.iterdir())
        with tempfile.TemporaryDirectory() as x:
            assert c.read_swu(out / (S + ".unsigned.swu"), x) == ["sw-description", "boot0.be"]
        m = json.loads((out / (S + ".manifest.json")).read_text())
        assert m["version"] == "3.0.0.1" and m["supplier"] == "SiMa.ai" and m["boot0"]["sha256"] == c.sha256(out / (S + "-boot0.be"))
        assert len((out / "SHA256SUMS").read_text().splitlines()) == 4 and o.getvalue().endswith(f"pib: artifacts in {out}\n")
        # sima_source: rs installs from it and the boot0.be check reads the same line
        cfg["sima_source"] = want_m1 = "deb [signed-by=/usr/share/keyrings/simaai-public.gpg] http://m.example/sima agate non-free"
        checked = []
        c.release_boot0_md5 = lambda spec, cfg: checked.append(c.sima_release_line(cfg)) or hashlib.md5(b"b0").hexdigest()
        with contextlib.redirect_stdout(io.StringIO()):
            c.cmd_build(argparse.Namespace(supplier=None, dev=False))
        assert checked == [want_m1], checked
    finally:
        c.subprocess.run = real_sp
        for k, v in saved.items(): setattr(c, k, v)
        os.environ.pop("PIB_SIMA_APT_URL"); os.environ.pop("PIB_CODENAME")
        os.chdir(here)
# sign-debs: every custom-debs/*.deb, nothing else, re-signs in place
with tempfile.TemporaryDirectory() as d:
    t = Path(d); here = os.getcwd(); os.chdir(t)
    try:
        (t / "keys").mkdir(); c.gen_deb_key(t / "keys"); pub, key = t / "keys/debs-signing.asc", "keys/debs-signing.secret.asc"
        sign = lambda k=key: c.cmd_sign_debs(argparse.Namespace(key=k))
        assert "no .debs in custom-debs/" in dies(sign), "no folder"
        (t / c.DEBS).mkdir(); assert "no .debs in custom-debs/" in dies(sign), "empty folder"
        a, b = t / c.DEBS / "a_1_arm64.deb", t / c.DEBS / "b_1_all.deb"
        a.write_bytes(b"a"); (t / c.DEBS / "notes.txt").write_text("x")
        sign(); c.check_deb_signature([a], pub)   # one deb
        b.write_bytes(b"b"); out = io.StringIO()
        with contextlib.redirect_stdout(out): sign()
        c.check_deb_signature([a, b], pub)
        assert out.getvalue() == "pib: wrote custom-debs/a_1_arm64.deb.sig\npib: wrote custom-debs/b_1_all.deb.sig\n", out.getvalue()
        assert not (t / c.DEBS / "notes.txt.sig").exists()
        b.write_bytes(b"b2"); assert "not signed by the customer key" in dies(c.check_deb_signature, [b], pub)
        sign(); c.check_deb_signature([a, b], pub)   # existing .sig overwritten
        b.with_name(b.name + ".sig").unlink()
        assert "gpg failed" in dies(sign, "keys/missing.asc"); assert not b.with_name(b.name + ".sig").exists(), "bad key"
    finally:
        os.chdir(here)
assert c.parser().parse_args(["sign-debs"]).fn is c.cmd_sign_debs
assert dies(c.parser().parse_args, ["sign-deb", "x.deb"]) == "2", "old name gone"
# --help lists the public commands only
h = c.parser().format_help()
assert "_finish" not in h and "SUPPRESS" not in h and "verify-debs" in h, h
# licence heuristic: whole words only, LGPL is not GPL
import importlib.util
spec = importlib.util.spec_from_file_location("xl", ROOT / "scripts/extract_licenses.py")
xl = importlib.util.module_from_spec(spec); spec.loader.exec_module(xl)
with tempfile.TemporaryDirectory() as d:
    def lic(text):
        Path(d, "copyright").write_text(text)
        return xl.extract_licenses(str(Path(d, "copyright")))
    assert lic("misc files, see disc") is None, "misc is not ISC"
    assert lic("Under the LGPL v2 or later") == {"LGPL-2+"}, lic("Under the LGPL v2 or later")
    assert lic("LGPL version 2") == {"LGPL-2"} and lic("LGPL version 3") == {"LGPL-3"}
    assert lic("GPL v2 or later") == {"GPL-2+"} and lic("GPL version 3") == {"GPL-3"}
    assert lic("ISC License") == {"ISC"} and lic("") is None
    assert lic("License: MIT\nsome GPL v2 text") == {"MIT"}, "DEP-5 wins over the heuristic"
    assert xl.extract_licenses(str(Path(d, "missing"))) is None
# a missing input file ends in one pib: line, not a traceback
with tempfile.TemporaryDirectory() as d:
    for argv in (["verify", "--ca", f"{d}/ca.crt", f"{d}/no.swu"], ["diff", "--against", f"{d}/no.json", "--image", f"{d}/no.cdx.json"]):
        try:
            c.main(argv)
            raise AssertionError(argv)
        except SystemExit as e:
            assert str(e.code).startswith("pib: ") and "No such file or directory" in str(e.code), e.code
# pib sign with no SWU: the image.yaml version's bundle, not whatever else out/ still holds
import argparse, contextlib, io
with tempfile.TemporaryDirectory() as t:
    here = os.getcwd(); os.chdir(t); (Path(t) / "out").mkdir()
    real_rs, real_gk = c.read_swu, c.gen_keys
    picked = []
    def pick(swu, d): picked.append(str(swu)); raise StopIteration
    def sign(ver):
        y = Path("image.yaml")
        y.unlink(missing_ok=True)
        if ver: y.write_text(f"base: minimal\ntarget: modalix\nversion: {ver}\n")
        with contextlib.redirect_stderr(io.StringIO()):
            try: c.cmd_sign(argparse.Namespace(swu=None, out=None, dev=True, key=None, cert=None, pkcs11=None, encrypt=False, aes_key=None))
            except StopIteration: return picked.pop()
            except SystemExit as e: return str(e.code)
    N = "out/elxr-minimal-modalix-{}-agate-arm64.{}swu"
    for v, k in (("3.0.0.1", "unsigned."), ("3.0.0.1", ""), ("3.0.0.10", "unsigned."), ("3.0.0.2", "unsigned.")):
        Path(N.format(v, k)).write_text("x")
    try:
        c.read_swu, c.gen_keys = pick, lambda *a, **k: None
        assert sign("3.0.0.2") == N.format("3.0.0.2", "unsigned.")
        assert sign("3.0.0.1") == N.format("3.0.0.1", "unsigned."), "not 3.0.0.10, not the signed one"
        assert sign(None) == "pib: name the .swu to sign (out/ holds 3)", "no image.yaml: every unsigned bundle"
        assert sign("3.0.0.3") == "pib: name the .swu to sign (out/ holds 0)"
        Path(N.format("3.0.0.1", "unsigned.")).unlink()
        assert sign("3.0.0.1") == N.format("3.0.0.1", ""), "only the signed one left: re-sign it"
    finally:
        c.read_swu, c.gen_keys = real_rs, real_gk; os.chdir(here)
# simaai-growlvm: no LV behind / (netboot, cpio) exits 0; growpart 1 is NOCHANGE, 2 a failure
gl = (ROOT / "configs/images/overlay/simaai/usr/sbin/simaai-growlvm").read_text()
pre = gl[:gl.index("# Discover the volume group")].replace("/proc/cmdline", "/dev/null")
for src_ in ("10.0.0.1:/nfs", "rootfs", ""):
    r = subprocess.run(["bash", "-c", f'findmnt() {{ echo "{src_}"; }}\n' + pre + "echo past"], capture_output=True, text=True)
    assert r.returncode == 0 and "not on a logical volume" in r.stdout and "past" not in r.stdout, (src_, r)
gp = gl[gl.index("rc=0\ngrowpart"):gl.index("# Let LVM see")]
for rc_, out_ in ((0, "grew /dev/d partition 1"), (1, "already spans"), (2, "failed (exit 2)")):
    r = subprocess.run(["bash", "-c", gl[gl.index("set -eu"):gl.index("# The rootfs A/B")] + f"growpart() {{ return {rc_}; }}\npartprobe() {{ :; }}\nDISK=d PART_NUM=1\n" + gp + "echo past"],
                       capture_output=True, text=True)
    assert out_ in r.stdout + r.stderr and (r.returncode == 0) == (rc_ < 2) and ("past" in r.stdout) == (rc_ < 2), (rc_, r)
if "FIT_SKIPPED" in globals():
    sys.exit("the FIT asserts did not run: mkimage, dtc or openssl missing; the other asserts passed")
print("ALL CLI ASSERTS PASSED")
