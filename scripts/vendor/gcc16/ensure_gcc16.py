#!/usr/bin/env python3
"""Reuse GCC16, or build the pinned release in a private, locked cache.

Print only the selected prefix to stdout; progress and retained build logs go to
stderr. Never change compiler alternatives, the SDK, or an explicit installation.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

VERSION = "16.2.0"
ARCHIVE_SHA512 = "c51c30ca7422d0cbecf504b2e0f33c3aca31e0f90a76b65217f465163fa6fa17b3f5de39e145c47e5bab90ac0ce7fff3b03c8d553ae36e01faaea5a50f8648d1"
SOURCE_URL = f"https://gcc.gnu.org/pub/gcc/releases/gcc-{VERSION}/gcc-{VERSION}.tar.xz"


def output(*command, **kwargs):
    return subprocess.check_output(command, text=True, **kwargs).strip()


def host_executable(path):
    kind = output("file", "-b", "-L", str(path))
    machine = platform.machine().lower()
    architecture = "x86-64" if machine in ("x86_64", "amd64") else "ARM aarch64"
    if (
        machine not in ("x86_64", "amd64", "aarch64", "arm64")
        or not kind.startswith("ELF ")
        or architecture not in kind
    ):
        raise ValueError(f"not a native Linux compiler executable: {path}: {kind}")


def drivers(root, target):
    prefix = "aarch64-linux-gnu-" if target == "aarch64" else ""
    found = []
    for name in ("gcc", "g++"):
        candidates = [root / "bin" / f"{prefix}{name}{suffix}" for suffix in ("-16", "")]
        driver = next((p for p in candidates if p.is_file()), None)
        if driver is None:
            raise ValueError(f"missing GCC16 driver {prefix}{name} under {root}")
        host_executable(driver)
        version = output(str(driver), "-dumpfullversion", "-dumpversion")
        if not re.fullmatch(r"16\.(?:[2-9]|[1-9][0-9]+)(?:\.[0-9]+)?", version):
            raise ValueError(f"GCC16.2+ required, found {version}: {driver}")
        triple = output(str(driver), "-dumpmachine")
        macros = output(str(driver), "-dM", "-E", "-x", "c", "/dev/null")
        if "#define __GNUC__ 16\n" not in macros + "\n" or "__clang__" in macros:
            raise ValueError(f"not a GNU GCC16 driver: {driver}")
        if target == "aarch64" and not re.fullmatch(r"aarch64[^-]*-.*linux.*", triple):
            raise ValueError(f"not an AArch64 Linux compiler: {triple}")
        if target == "host" and triple.split("-", 1)[0] not in (
            {"x86_64"} if platform.machine() in ("x86_64", "amd64") else {"aarch64"}
        ):
            raise ValueError(f"not a native target: {triple}")
        found.append((driver, version, triple))
    if found[0][1:] != found[1][1:]:
        raise ValueError("GCC C/C++ versions and targets differ")
    return found[0][0], found[1][0]


def verify(root, target, sysroot):
    """Compile/link a C++20 probe; do not execute it, even for a native build."""
    _, cxx = drivers(root, target)
    env = clean_environment()
    with tempfile.TemporaryDirectory(prefix="gcc16-check-") as temporary:
        source = Path(temporary) / "probe.cpp"
        source.write_text(
            "#include <span>\n#include <string>\n"
            "static_assert(_GLIBCXX_RELEASE == 16);\n"
            "int main(int n, char**) { int v[]{n}; std::span<int> s(v);"
            " return std::stoi(std::to_string(s[0])) != n; }\n"
        )
        command = [str(cxx), "-std=c++20", str(source), "-o", str(Path(temporary) / "probe")]
        if sysroot:
            command.append(f"--sysroot={sysroot}")
        subprocess.run(command, check=True, env=env, stdout=subprocess.DEVNULL)


def clean_environment():
    env = os.environ.copy()
    for key in (
        "CC",
        "CXX",
        "CFLAGS",
        "CXXFLAGS",
        "CPPFLAGS",
        "LDFLAGS",
        "LIBRARY_PATH",
        "LD_LIBRARY_PATH",
        "CPATH",
        "C_INCLUDE_PATH",
        "CPLUS_INCLUDE_PATH",
        "GCC_EXEC_PREFIX",
        "COMPILER_PATH",
        "AR",
        "AS",
        "LD",
        "NM",
        "RANLIB",
        "STRIP",
        "OBJCOPY",
        "OBJDUMP",
    ):
        env.pop(key, None)
    return env


def archive(cache):
    path = cache / f"gcc-{VERSION}.tar.xz"

    def valid(candidate):
        digest = hashlib.sha512()
        with candidate.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest() == ARCHIVE_SHA512

    if path.exists():
        if not valid(path):
            raise ValueError(f"GCC source checksum mismatch: {path}")
        return path
    with tempfile.NamedTemporaryFile(dir=cache, prefix="download-", delete=False) as stream:
        partial = Path(stream.name)
        try:
            with urllib.request.urlopen(SOURCE_URL, timeout=120) as response:
                if not response.url.startswith("https://"):
                    raise ValueError("GCC download redirected outside HTTPS")
                shutil.copyfileobj(response, stream)
            stream.flush()
            if not valid(partial):
                raise ValueError("GCC source checksum mismatch; nothing installed")
            partial.replace(path)
        finally:
            partial.unlink(missing_ok=True)
    return path


def extract_source(source, destination):
    # Minimal SDK images need not ship the xz executable. Python decompresses
    # the SHA-512-verified source directly; the data filter confines extraction.
    with tarfile.open(source, "r:xz") as archive:
        archive.extractall(destination, filter="data")


def host_binutils():
    # The ARM SDK copies triplet-prefixed binutils but not all plain aliases.
    # Use the bootstrap compiler's target, NOT the compiler we are building:
    # GMP and the compiler executable must use host tools during a cross-build.
    triple = output(shutil.which("gcc"), "-dumpmachine", env=clean_environment())
    tools = {}
    missing = []
    for name in ("ar", "as", "ld", "nm", "ranlib", "strip", "objcopy", "objdump", "readelf"):
        path = shutil.which(name) or shutil.which(f"{triple}-{name}")
        if path:
            tools[name] = Path(path).absolute()
        else:
            missing.append(name)
    if missing:
        raise ValueError("GCC bootstrap host binutils missing: " + ", ".join(missing)
                         + "; install host binutils before building GCC")
    return tools


def install(root, cache, target, sysroot, jobs):
    # GCC's own prerequisite script still uses tar for .gz and .bz2 archives.
    required = ["gcc", "g++", "make", "tar", "gzip", "bzip2", "sha512sum", "file"]
    if not shutil.which("wget") and not shutil.which("curl"):
        raise ValueError("GCC bootstrap prerequisites require wget or curl")
    if target == "aarch64":
        required += ["aarch64-linux-gnu-as", "aarch64-linux-gnu-ld"]
    missing = [name for name in required if not shutil.which(name)]
    if missing:
        raise ValueError("GCC bootstrap prerequisites missing: " + ", ".join(missing))
    for name in ("gcc", "g++"):
        host_executable(Path(shutil.which(name)))
    binutils = host_binutils()
    work = Path(tempfile.mkdtemp(prefix="build-", dir=cache))
    log = work / "build.log"
    print(
        f"Installing GCC {VERSION} ({target}); first build can take tens of minutes. Log: {log}",
        file=sys.stderr,
        flush=True,
    )
    env = clean_environment()
    env.update(CC=shutil.which("gcc"), CXX=shutil.which("g++"))
    # Private aliases cover libtool's literal `ar`/`ranlib` calls too. Never
    # replace system/SDK tools or leave compiler runtime paths pointing here.
    aliases = work / "host-bin"
    aliases.mkdir()
    for name, path in binutils.items():
        (aliases / name).symlink_to(path)
    env["PATH"] = str(aliases) + os.pathsep + env.get("PATH", "")
    with log.open("w") as stream:

        def run(command, cwd=work):
            print("+ " + " ".join(map(str, command)), file=stream, flush=True)
            try:
                subprocess.run(
                    list(map(str, command)),
                    cwd=cwd,
                    env=env,
                    check=True,
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                )
            except (OSError, subprocess.CalledProcessError):
                # Container-local logs may disappear after CI teardown. Show a
                # bounded tail in the job log and retain the complete build log.
                stream.flush()
                with log.open("rb") as failed:
                    failed.seek(max(0, log.stat().st_size - 8192))
                    print(failed.read().decode(errors="replace"), file=sys.stderr)
                print(f"Full GCC bootstrap log: {log}", file=sys.stderr)
                raise

        extract_source(archive(cache), work)
        source = work / f"gcc-{VERSION}"
        # This script and its SHA512 prerequisite manifest are in the verified
        # GCC release; it downloads/validates GMP, MPFR, MPC, ISL and gettext.
        run(["sh", source / "contrib/download_prerequisites", "--verify", "--sha512"], source)
        build = work / "objects"
        build.mkdir()
        options = [
            f"--prefix={root}",
            "--enable-languages=c,c++",
            "--disable-bootstrap",
            "--disable-multilib",
            "--disable-nls",
            "--disable-libcc1",
            "--with-system-zlib",
            "--enable-default-pie",
        ]
        if target == "aarch64":
            options += [
                "--target=aarch64-linux-gnu",
                f"--with-sysroot={sysroot}",
                "--with-as=" + shutil.which("aarch64-linux-gnu-as"),
                "--with-ld=" + shutil.which("aarch64-linux-gnu-ld"),
                "--disable-libsanitizer",
            ]
        else:
            options += [f"--with-as={binutils['as']}", f"--with-ld={binutils['ld']}"]
        run([source / "configure", *options], build)
        run(["make", f"-j{jobs}"], build)
        staging = work / "stage"
        run(["make", "install", f"DESTDIR={staging}"], build)
        installed = staging / root.relative_to("/")
        verify(installed, target, sysroot)
        # Publish only after the complete installation links successfully. A
        # failed attempt retains its logs, not a discoverable partial compiler.
        installed.rename(root)
    shutil.rmtree(work)


def ensure(target, sysroot, cache, explicit=None, auto_install=True, jobs=4):
    if target == "aarch64" and (not sysroot or not (sysroot / "usr/include").is_dir()):
        raise ValueError(
            "A65 compiler installation requires an existing SDK sysroot with usr/include"
        )
    if explicit:
        root = explicit.resolve(strict=True)
        verify(root, target, sysroot)
        return root
    # Reuse complete system installations, never change alternatives.
    prefix = "aarch64-linux-gnu-" if target == "aarch64" else ""
    for name in (prefix + "gcc-16", prefix + "gcc"):
        candidate = shutil.which(name)
        if candidate:
            root = Path(candidate).absolute().parent.parent
            try:
                drivers(root, target)
            except (ValueError, subprocess.SubprocessError):
                continue
            verify(root, target, sysroot)
            return root
    identity = json.dumps(
        [VERSION, platform.machine(), platform.libc_ver(), target, str(sysroot), "default-pie-v1"],
        sort_keys=True,
    )
    key = hashlib.sha256(identity.encode()).hexdigest()[:16]
    cache = cache.resolve()
    cache.mkdir(parents=True, exist_ok=True)
    root = cache / f"{VERSION}-{target}-{key}"
    with (cache / "install.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not root.exists():
            if not auto_install:
                raise ValueError("GCC16 is absent and automatic installation is disabled")
            install(root, cache, target, sysroot, jobs)
        verify(root, target, sysroot)
    return root


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("host", "aarch64"), required=True)
    parser.add_argument("--sysroot", type=Path)
    parser.add_argument("--root", type=Path, default=os.environ.get("SIMA_GCC16_ROOT"))
    parser.add_argument(
        "--cache",
        type=Path,
        default=os.environ.get(
            "SIMA_GCC16_CACHE",
            str(Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "sima/gcc16"),
        ),
    )
    parser.add_argument("--no-install", action="store_true")
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    print(
        ensure(
            args.target,
            args.sysroot.resolve() if args.sysroot else None,
            args.cache,
            args.root,
            not args.no_install,
            args.jobs,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError) as error:
        print(f"GCC16 setup failed: {error}", file=sys.stderr)
        sys.exit(1)
