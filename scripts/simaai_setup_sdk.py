"""
Copyright (c) 2025 SiMa Technologies, Inc.

SPDX-License-Identifier: Apache-2.0

Vendored from simaai-sdk-tools 2.0.0.

Local SDK image changes:
- Resolve platform-owned packages to the requested platform version when a
  dependency is unversioned.
- Never fall back to the newest candidate for platform-owned packages.
- Validate downloaded platform-owned packages before extraction.
- Keep extraction deterministic and extract platform-owned packages after
  generic build dependencies.
- Skip libdlpack-dev because the SiMa TVM package owns the compatible
  dlpack/dlpack.h header in this sysroot.
"""

import apt
import fnmatch
import glob
import os
import shutil
import subprocess
import sys


DEFAULT_PLATFORM_PACKAGE_PATTERNS = (
    "simaai-*",
    "appcomplex",
    "a65apps",
    "evtransforms",
    "inferencetools",
    "vdpcli",
    "mpktools",
    "vdpspy",
    "vdp-llm-libs",
    "swsoc-*",
    "smifb-*",
    "cvu-sw*",
    "m4-mla-*",
    "troot-*",
    "libsynopsys",
    "atf-*",
    "optee-*",
    "oot-dtbo-*",
)

# TVM is SDK-owned, but its package version is not the platform version
# (for example, Modalix 2.0 uses tvm 1.4.0). Extract it after generic build
# dependencies so its bundled dlpack header remains paired with TVM headers.
SDK_OWNED_NON_PLATFORM_PACKAGES = {
    "tvm",
    "python3-tvm",
}

SKIP_PACKAGES = {
    "libdlpack-dev",
}


def load_platform_package_patterns():
    patterns_file = os.environ.get(
        "PLATFORM_PACKAGE_PATTERNS_FILE",
        "/usr/local/share/sima-sdk/platform-package-patterns.txt",
    )
    if not os.path.exists(patterns_file):
        return DEFAULT_PLATFORM_PACKAGE_PATTERNS

    patterns = []
    with open(patterns_file, "rt", encoding="utf-8") as rf:
        for line in rf:
            item = line.split("#", 1)[0].strip()
            if item:
                patterns.append(item)

    return tuple(patterns) or DEFAULT_PLATFORM_PACKAGE_PATTERNS


PLATFORM_PACKAGE_PATTERNS = load_platform_package_patterns()


def usage():
    print("Usage: python3 simaai_setup_sdk.py <platform> <palette-version> <libc-version> <whitelist>")
    print("where:")
    print("\tplatform        = SiMa.ai platform name e.g. modalix")
    print("\tpalette-version = SiMa.ai palette package version string e.g. 2.0.0*")
    print("\tlibc-version    = Version string of libc headers e.g. 6.1.22-modalix-485")
    print("\twhitelist       = Comma separated list of additional packages e.g. libgrpc-dev,protobuf-compiler-grpc")


def base_package_name(pkgname):
    return pkgname.split(":", 1)[0]


def is_platform_package(pkgname):
    base = base_package_name(pkgname)
    return any(fnmatch.fnmatch(base, pattern) for pattern in PLATFORM_PACKAGE_PATTERNS)


def normalize_arm64_name(pkgname):
    if ":" in pkgname:
        return pkgname
    return f"{pkgname}:arm64"


def package_field(deb_path, field):
    return subprocess.check_output(["dpkg-deb", "-f", deb_path, field], text=True).strip()


def main(pkg_name, version, libc_ver, dldir, installdir):
    # packages that are to be ignored
    blacklist = {
        "m4-mla-modalix:armhf": "",
        "m4-mla-davinci:armhf": "",
        "c++-compiler:arm64": "",
        "cvu-sw:arc": "",
        "binutils:arm64": "",
        "g++:arm64": "",
        "gcc:arm64": "",
        "smifb3-modalix": "",
        "smifb3-davinci": "",
        "simaai-pcie-drv-modalix": "",
        "simaai-pcie-drv-davinci": "",
        "lttng-modules-modalix": "",
        "lttng-modules-davinci": "",
    }

    def get_build_depends_list(deb_file_path):
        """Extract the package names from the Build-Depends tag."""

        result = subprocess.run(
            ["dpkg-deb", "-I", deb_file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"dpkg-deb failed: {result.stderr}")

        formatted_line = ""

        for line in result.stdout.splitlines():
            if line.startswith(" "):
                formatted_line += "#" + line.strip()
            elif line.startswith("\t"):
                formatted_line += " " + line.strip()

        _, _, val = formatted_line.partition("#Build-Depends:")
        if val:
            dep_str = val.strip().split("#")[0]
            return [d.strip() for d in dep_str.split(",")]

        return []

    def get_candidate(pkgname, requested_version):
        """Find a package candidate, enforcing platform-version determinism."""

        base = base_package_name(pkgname)
        if base in SKIP_PACKAGES:
            print(f"Skipping {pkgname}; SDK-owned package provides the required files")
            return None

        if pkgname not in cache:
            return None

        if is_platform_package(pkgname) and not requested_version:
            requested_version = version

        pkg = cache[pkgname]
        if requested_version:
            for candidate in pkg.versions:
                if fnmatch.fnmatch(candidate.version, requested_version):
                    return candidate
            if is_platform_package(pkgname):
                print(f"Skipping {pkgname}; no candidate matches platform version {version}")
                return None
            return None

        return pkg.candidate

    def collect_rdeps(candidate, recursive):
        """Collect the runtime dependencies of the package."""

        if candidate is None:
            return

        for dep_list in candidate.get_dependencies("Depends"):
            for dep in dep_list:
                name = normalize_arm64_name(dep.name)

                dep_str = str(dep)
                if "=" in dep_str:
                    ver = dep_str.split("=")[1].strip()
                else:
                    ver = ""

                if name in blacklist:
                    continue

                if name in graph:
                    continue

                graph[name] = ver
                if recursive:
                    collect_rdeps(get_candidate(name, ver), recursive)

    def download(uri, dlname):
        """Download a package and validate platform-owned versions."""

        cmd = ["wget", uri, "-O", dlname]
        ret = subprocess.run(cmd, capture_output=True, text=True, check=True)
        if ret.returncode != 0:
            print(f"Error while downloading OSS package {dlname}:\n{ret.stderr}")
            return

        pkg = package_field(dlname, "Package")
        ver = package_field(dlname, "Version")
        if is_platform_package(pkg) and ver != version:
            raise RuntimeError(f"Unexpected {pkg} version {ver}; expected {version}")

    def collect_bdeps(candidate, name):
        """Collect the build-time dependencies."""

        if candidate is None:
            return

        dlname = dldir + "/" + name + ".deb"
        # Need to download the package first to run dpkg-deb and find build
        # dependencies.
        download(candidate.uri, dlname)

        bdep_list = get_build_depends_list(dlname)

        if bdep_list:
            for bdep in bdep_list:
                if not bdep:
                    continue
                if bdep in graph or bdep in shadow or bdep in blacklist:
                    continue
                ver = ""
                shadow[bdep] = ver
                collect_bdeps(get_candidate(bdep, ver), bdep)

    def extract(filename):
        """Extract a package into the sysroot."""

        deb_path = dldir + "/" + filename
        dpkg = subprocess.Popen(
            ["dpkg-deb", "--fsys-tarfile", deb_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,
        )
        tar = subprocess.run(
            [
                "tar",
                "-x",
                "-C",
                installdir,
                "--exclude=./usr/share/doc/*",
                "--exclude=./usr/share/man/*",
                "--exclude=./usr/share/lintian/*",
                "--exclude=./usr/share/locale/*",
            ],
            stdin=dpkg.stdout,
            capture_output=True,
            text=True,
        )
        if dpkg.stdout is not None:
            dpkg.stdout.close()
        dpkg_stderr = dpkg.stderr.read() if dpkg.stderr is not None else b""
        dpkg_returncode = dpkg.wait()

        if dpkg_returncode != 0 or tar.returncode != 0:
            stderr = ""
            if dpkg_stderr:
                stderr += dpkg_stderr.decode("utf-8", errors="replace")
            stderr += tar.stderr
            raise RuntimeError(
                f"Error while extracting OSS package {filename}:\n{stderr}"
            )

    def tweak_conf(files, old, new):
        for f in glob.glob(files):
            if os.path.islink(f):
                target = os.readlink(f)
                if target.startswith("/usr"):
                    sysroot_target = installdir + target
                    if os.path.exists(sysroot_target):
                        os.unlink(f)
                        os.symlink(sysroot_target, f)

            if not os.path.exists(f):
                print(f"Skipping stale config symlink {f}")
                continue

            with open(f, "rt", encoding="utf-8") as rf:
                data = rf.read()
                data = data.replace(old, new)
            with open(f, "wt", encoding="utf-8") as wf:
                wf.write(data)

    def process_whitelist():
        for item in whitelist:
            if not item or item == ":arm64":
                continue
            if item in graph:
                continue

            graph[item] = ""
            c = get_candidate(item, "")
            if c is not None:
                collect_rdeps(c, True)

    def extraction_sort_key(filename):
        deb_path = os.path.join(dldir, filename)
        pkg = package_field(deb_path, "Package")
        if base_package_name(pkg) in SDK_OWNED_NON_PLATFORM_PACKAGES:
            priority = 2
        elif is_platform_package(pkg):
            priority = 1
        else:
            priority = 0
        return (priority, pkg, filename)

    def validate_tvm_dlpack_header():
        header = os.path.join(installdir, "usr/include/dlpack/dlpack.h")
        if not os.path.exists(header):
            return
        with open(header, "rt", encoding="utf-8") as rf:
            data = rf.read()
        missing = [
            name
            for name in ("kDLOneAPI", "kDLWebGPU", "kDLHexagon")
            if name not in data
        ]
        if missing:
            raise RuntimeError(
                f"{header} is incompatible with TVM headers; missing {', '.join(missing)}"
            )

    print("Updating cache...")
    cache = apt.Cache()
    cache.update()
    cache.open(None)

    if pkg_name not in cache:
        print(f"Package {pkg_name} not found!")
        return

    c_palette = get_candidate(pkg_name, version)
    if c_palette is None:
        raise RuntimeError(f"No {pkg_name} candidate matches platform version {version}")
    print(f"Using {pkg_name} = {c_palette.version}")

    graph = {}
    # first get all rdeps of palette only
    collect_rdeps(c_palette, False)

    # need a shadow copy to iterate over
    shadow = graph.copy()

    print("Collecting runtime dependencies...")
    for name, ver in shadow.items():
        collect_rdeps(get_candidate(name, ver), True)

    process_whitelist()
    # fix linux-libc-dev version
    graph["linux-libc-dev:arm64"] = libc_ver

    shadow.clear()
    shutil.rmtree(dldir, ignore_errors=True)
    os.makedirs(dldir, exist_ok=True)

    print("Collecting buildtime dependencies...")
    for name, ver in graph.items():
        collect_bdeps(get_candidate(name, ver), name)

    full = graph.copy()
    full.update(shadow)
    graph.clear()

    for name, ver in shadow.items():
        collect_rdeps(get_candidate(name, ver), True)

    full.update(graph)

    for name, ver in graph.items():
        c = get_candidate(name, ver)
        if c is not None:
            download(c.uri, dldir + "/" + name + ".deb")

    os.makedirs(installdir, exist_ok=True)

    print("Setting up sysroot...")
    deb_files = [
        filename
        for filename in os.listdir(dldir)
        if os.path.isfile(os.path.join(dldir, filename)) and filename.endswith(".deb")
    ]
    for filename in sorted(deb_files, key=extraction_sort_key):
        extract(filename)

    validate_tvm_dlpack_header()

    pcpath = "usr/lib/aarch64-linux-gnu/pkgconfig/"
    tweak_conf(installdir + "/" + pcpath + "*.pc", "=/usr", "=" + installdir + "/usr")

    cmakeconfpath = "usr/lib/aarch64-linux-gnu/cmake/"
    tweak_conf(installdir + "/" + cmakeconfpath + "*/*.cmake", "/usr", installdir + "/usr")

    print("SDK deployment completed!")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        usage()
        sys.exit(1)

    platform = sys.argv[1]
    palette_ver = sys.argv[2]
    libc_ver = sys.argv[3]

    if platform != "modalix" and platform != "davinci":
        usage()
        sys.exit(1)

    if len(sys.argv) > 4:
        whitelist = [
            f"{item.strip()}:arm64"
            for item in sys.argv[4].split(",")
            if item.strip()
        ]
    else:
        whitelist = []

    pkg_name = f"simaai-palette-{platform}:arm64"
    installdir = f"/opt/toolchain/aarch64/{platform}"
    dldir = f"/tmp/{platform}"

    main(pkg_name, palette_ver, libc_ver, dldir, installdir)
