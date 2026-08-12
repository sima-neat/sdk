"""
Copyright (c) 2025 SiMa Technologies, Inc.

SPDX-License-Identifier: Apache-2.0

Vendored from simaai-sdk-tools 2.0.0.

Local SDK image changes:
- Resolve SDK-versioned packages to the requested platform version when a
  dependency is unversioned.
- Never fall back to the newest candidate for SDK-versioned packages.
- Validate downloaded SDK-versioned packages before extraction.
- For an explicit local sysroot overlay, prefer the selected ~preN build
  cohort for dependencies whose package versions carry that build suffix.
- Keep extraction deterministic and extract platform-owned packages after
  generic build dependencies.
- Skip libdlpack-dev because the SiMa TVM package owns the compatible
  dlpack/dlpack.h header in this sysroot.
"""

import apt
import concurrent.futures
import fnmatch
import glob
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import time


DEFAULT_PLATFORM_PACKAGE_PATTERNS = (
    "simaai-palette-modalix",
    "simaai-palette-davinci",
    "appcomplex",
    "a65apps",
    "evtransforms",
    "inferencetools",
    "vdpcli",
    "mpktools",
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

APT_UPDATE_RETRY_DELAYS_SECONDS = (10, 30)


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
PLATFORM_BUILD_REVISION = os.environ.get("SIMAAI_PLATFORM_BUILD_REVISION", "")
DOWNLOAD_WORKERS = max(1, int(os.environ.get("SIMAAI_DOWNLOAD_WORKERS", "8")))


class DownloadProgress:
    """TTY spinner and log-safe progress checkpoints for package downloads."""

    SPINNER = ("|", "/", "-", "\\")

    def __init__(self):
        self.started_at = time.monotonic()
        self.known = set()
        self.completed = set()
        self.cached = set()
        self.lock = threading.Lock()
        self.stop_event = None
        self.thread = None
        self.is_tty = sys.stdout.isatty()
        self.last_log_at = self.started_at

    def discover(self, names):
        with self.lock:
            self.known.update(names)

    def complete(self, name, cached):
        with self.lock:
            self.completed.add(name)
            if cached:
                self.cached.add(name)

    def snapshot(self):
        with self.lock:
            ready = len(self.completed)
            total = len(self.known)
            cached = len(self.cached)
        elapsed = int(time.monotonic() - self.started_at)
        return ready, total, cached, elapsed

    def message(self, frame=0):
        ready, total, cached, elapsed = self.snapshot()
        downloaded = ready - cached
        spinner = self.SPINNER[frame % len(self.SPINNER)]
        return (
            f"{spinner} Packages ready: {ready}/{total} "
            f"(downloaded {downloaded}, cached {cached}) [{elapsed}s]"
        )

    def render_loop(self):
        frame = 0
        interval = 0.2 if self.is_tty else 15
        while not self.stop_event.wait(interval):
            if self.is_tty:
                print(f"\r\033[2K{self.message(frame)}", end="", flush=True)
            else:
                print(self.message(frame), flush=True)
                self.last_log_at = time.monotonic()
            frame += 1

    def begin_batch(self, names):
        self.discover(names)
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.render_loop, daemon=True)
        self.thread.start()

    def end_batch(self):
        if self.stop_event is not None:
            self.stop_event.set()
        if self.thread is not None:
            self.thread.join()
        if self.is_tty:
            print(f"\r\033[2K{self.message()} ", flush=True)
        elif time.monotonic() - self.last_log_at >= 15:
            print(self.message(), flush=True)
            self.last_log_at = time.monotonic()
        self.stop_event = None
        self.thread = None

    def finish(self):
        ready, total, cached, elapsed = self.snapshot()
        print(
            f"Package transfer complete: {ready}/{total} ready "
            f"({ready - cached} downloaded, {cached} cached) in {elapsed}s.",
            flush=True,
        )


class ExtractionProgress:
    """Show activity while packages are extracted sequentially."""

    SPINNER = DownloadProgress.SPINNER

    def __init__(self, total):
        self.total = total
        self.completed = 0
        self.current = "waiting"
        self.started_at = time.monotonic()
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.is_tty = sys.stdout.isatty()
        self.thread = threading.Thread(target=self.render_loop, daemon=True)

    def message(self, frame=0):
        with self.lock:
            completed = self.completed
            current = self.current
        elapsed = int(time.monotonic() - self.started_at)
        spinner = self.SPINNER[frame % len(self.SPINNER)]
        return (
            f"{spinner} Extracting packages: {completed}/{self.total} "
            f"(current: {current}) [{elapsed}s]"
        )

    def render_loop(self):
        frame = 0
        interval = 0.2 if self.is_tty else 15
        while not self.stop_event.wait(interval):
            if self.is_tty:
                print(f"\r\033[2K{self.message(frame)}", end="", flush=True)
            else:
                print(self.message(frame), flush=True)
            frame += 1

    def start(self):
        self.thread.start()

    def begin_package(self, filename):
        with self.lock:
            self.current = filename

    def complete_package(self):
        with self.lock:
            self.completed += 1

    def finish(self, succeeded=True):
        self.stop_event.set()
        self.thread.join()
        elapsed = int(time.monotonic() - self.started_at)
        if self.is_tty:
            print("\r\033[2K", end="", flush=True)
        state = "complete" if succeeded else "stopped"
        print(
            f"Package extraction {state}: {self.completed}/{self.total} in {elapsed}s.",
            flush=True,
        )


def matches_platform_build_revision(package_version, build_revision):
    if not build_revision or not build_revision.isdigit():
        return False
    return package_version.endswith(f"~pre{build_revision}")


def update_apt_cache(cache):
    attempts = len(APT_UPDATE_RETRY_DELAYS_SECONDS) + 1
    for attempt in range(attempts):
        try:
            cache.update()
            return
        except apt.cache.FetchFailedException:
            if attempt == attempts - 1:
                raise
            delay = APT_UPDATE_RETRY_DELAYS_SECONDS[attempt]
            print(f"Cache update failed; retrying in {delay}s...", flush=True)
            time.sleep(delay)


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


def package_control_fields(deb_path, *wanted_fields):
    """Read several Debian control fields with one dpkg-deb process."""

    output = subprocess.check_output(
        ["dpkg-deb", "-f", deb_path, *wanted_fields], text=True
    )
    values = {}
    for line in output.splitlines():
        field, separator, value = line.partition(":")
        if separator:
            values[field] = value.strip()
    missing = [field for field in wanted_fields if field not in values]
    if missing:
        raise RuntimeError(
            f"Missing control fields {', '.join(missing)} in {deb_path}"
        )
    return tuple(values[field] for field in wanted_fields)


def package_payload_locations(deb_path):
    """Summarize the primary sysroot directories populated by a package."""

    listing = subprocess.check_output(["dpkg-deb", "-c", deb_path], text=True)
    locations = set()
    for line in listing.splitlines():
        fields = line.split(maxsplit=5)
        if len(fields) < 6:
            continue
        path = fields[5].split(" ->", 1)[0].removeprefix("./").lstrip("/")
        if not path or path.endswith("/"):
            continue
        parts = path.split("/")
        if len(parts) >= 3 and parts[:2] == ["usr", "lib"] and parts[2].endswith("linux-gnu"):
            locations.add("/" + "/".join(parts[:3]))
        elif len(parts) >= 2:
            locations.add("/" + "/".join(parts[:2]))
        else:
            locations.add("/" + parts[0])
    return ",".join(sorted(locations))


def write_sysroot_package_inventory(download_dir, sysroot):
    """Record every package represented by the resolved sysroot cohort."""

    deb_paths = sorted(
        os.path.join(download_dir, filename)
        for filename in os.listdir(download_dir)
        if filename.endswith(".deb")
        and os.path.isfile(os.path.join(download_dir, filename))
    )
    if not deb_paths:
        raise RuntimeError("Cannot record an empty sysroot package inventory")

    print(
        f"Recording package inventory for {len(deb_paths)} packages...",
        flush=True,
    )

    def inspect_package(deb_path):
        package, architecture, version = package_control_fields(
            deb_path, "Package", "Architecture", "Version"
        )
        return (
            package,
            architecture,
            version,
            package_payload_locations(deb_path),
        )

    entries = {}
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(DOWNLOAD_WORKERS, len(deb_paths))
    ) as executor:
        inspected = executor.map(inspect_package, deb_paths)
    for package, architecture, version, locations in inspected:
        entries[(package, architecture)] = (
            version,
            locations,
        )

    inventory_dir = os.path.join(sysroot, "var/lib/sima-sdk")
    inventory = os.path.join(inventory_dir, "sysroot-packages.tsv")
    temporary = f"{inventory}.tmp"
    os.makedirs(inventory_dir, exist_ok=True)
    with open(temporary, "wt", encoding="utf-8") as wf:
        for (package, architecture), (version, locations) in sorted(entries.items()):
            wf.write(f"{package}\t{architecture}\t{version}\t{locations}\n")
    os.replace(temporary, inventory)
    print(f"Recorded {len(entries)} package inventory entries.", flush=True)


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
        "smifb-modalix": "",
        "smifb-modalix:arm64": "",
        "smifb-davinci": "",
        "smifb-davinci:arm64": "",
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

        if PLATFORM_BUILD_REVISION:
            for candidate in pkg.versions:
                if matches_platform_build_revision(
                    candidate.version, PLATFORM_BUILD_REVISION
                ):
                    return candidate

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

    expected_versions_manifest = os.path.join(dldir, "expected-package-versions.tsv")
    expected_versions_lock = threading.Lock()
    selected_downloads = set()
    selected_downloads_lock = threading.Lock()
    download_progress = DownloadProgress()

    def record_expected_version(pkg, expected_version):
        if expected_version:
            with expected_versions_lock:
                with open(expected_versions_manifest, "at", encoding="utf-8") as wf:
                    wf.write(f"{pkg}\t{expected_version}\n")

    def file_sha256(path):
        digest = hashlib.sha256()
        with open(path, "rb") as rf:
            for chunk in iter(lambda: rf.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def downloaded_package_matches(
        dlname, expected_package, expected_version, expected_sha256
    ):
        if not os.path.isfile(dlname):
            return False
        try:
            pkg = package_field(dlname, "Package")
            ver = package_field(dlname, "Version")
        except (OSError, subprocess.SubprocessError):
            return False
        if pkg != expected_package or ver != expected_version:
            return False
        return not expected_sha256 or file_sha256(dlname) == expected_sha256

    def download(uri, dlname, expected_package, expected_version, expected_sha256):
        """Download a package and validate the resolved package version."""

        cached = downloaded_package_matches(
            dlname, expected_package, expected_version, expected_sha256
        )
        if not cached:
            partial = f"{dlname}.partial"
            try:
                os.unlink(partial)
            except FileNotFoundError:
                pass
            cmd = ["wget", "--timeout=30", "--tries=3", uri, "-O", partial]
            try:
                subprocess.run(cmd, capture_output=True, text=True, check=True)
                if expected_sha256 and file_sha256(partial) != expected_sha256:
                    raise RuntimeError(
                        f"SHA256 mismatch for downloaded package {expected_package}"
                    )
                os.replace(partial, dlname)
            except (subprocess.CalledProcessError, RuntimeError) as exc:
                try:
                    os.unlink(partial)
                except FileNotFoundError:
                    pass
                detail = getattr(exc, "stderr", None) or str(exc)
                raise RuntimeError(
                    f"Error while downloading OSS package {dlname}:\n{detail}"
                ) from exc

        pkg = package_field(dlname, "Package")
        ver = package_field(dlname, "Version")
        if pkg != expected_package:
            raise RuntimeError(f"Unexpected package {pkg}; expected {expected_package}")
        if expected_version and ver != expected_version:
            raise RuntimeError(f"Unexpected {pkg} version {ver}; expected {expected_version}")
        record_expected_version(pkg, expected_version)
        with selected_downloads_lock:
            selected_downloads.add(os.path.abspath(dlname))
        return cached

    def download_candidates(candidates):
        """Download candidate tuples concurrently, then surface every failure."""

        if not candidates:
            return
        download_progress.begin_batch(name for name, _candidate in candidates)
        try:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=min(DOWNLOAD_WORKERS, len(candidates))
            ) as executor:
                futures = {
                    executor.submit(
                        download,
                        candidate.uri,
                        os.path.join(dldir, f"{name}.deb"),
                        base_package_name(name),
                        candidate.version,
                        candidate.record.get("SHA256", ""),
                    ): name
                    for name, candidate in candidates
                }
                for future in concurrent.futures.as_completed(futures):
                    name = futures[future]
                    download_progress.complete(name, future.result())
        finally:
            download_progress.end_batch()

    def collect_bdeps(initial_packages):
        """Collect build dependencies in parallel breadth-first batches."""

        pending = {
            name: candidate
            for name, candidate in initial_packages
            if candidate is not None
        }
        while pending:
            batch = list(pending.items())
            download_candidates(batch)
            pending = {}
            for name, _candidate in batch:
                dlname = os.path.join(dldir, f"{name}.deb")
                for bdep in get_build_depends_list(dlname):
                    if not bdep or bdep in graph or bdep in shadow or bdep in blacklist:
                        continue
                    shadow[bdep] = ""
                    candidate = get_candidate(bdep, "")
                    if candidate is not None:
                        pending[bdep] = candidate

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
    update_apt_cache(cache)
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
    if not PLATFORM_BUILD_REVISION:
        shutil.rmtree(dldir, ignore_errors=True)
    os.makedirs(dldir, exist_ok=True)
    with open(expected_versions_manifest, "wt", encoding="utf-8"):
        pass

    print("Collecting buildtime dependencies...")
    collect_bdeps(
        (name, get_candidate(name, ver)) for name, ver in graph.items()
    )

    full = graph.copy()
    full.update(shadow)
    graph.clear()

    for name, ver in shadow.items():
        collect_rdeps(get_candidate(name, ver), True)

    full.update(graph)

    download_candidates(
        [
            (name, candidate)
            for name, ver in graph.items()
            if (candidate := get_candidate(name, ver)) is not None
        ]
    )
    download_progress.finish()

    for filename in os.listdir(dldir):
        path = os.path.abspath(os.path.join(dldir, filename))
        if filename.endswith(".partial") or (
            filename.endswith(".deb") and path not in selected_downloads
        ):
            os.unlink(path)

    if os.environ.get("SIMAAI_SETUP_DOWNLOAD_ONLY") == "1":
        print("SDK package download and dependency validation completed; skipping extraction.")
        return

    os.makedirs(installdir, exist_ok=True)

    print("Setting up sysroot...")
    deb_files = [
        filename
        for filename in os.listdir(dldir)
        if os.path.isfile(os.path.join(dldir, filename)) and filename.endswith(".deb")
    ]
    sorted_deb_files = sorted(deb_files, key=extraction_sort_key)
    extraction_progress = ExtractionProgress(len(sorted_deb_files))
    extraction_succeeded = False
    extraction_progress.start()
    try:
        for filename in sorted_deb_files:
            extraction_progress.begin_package(filename)
            extract(filename)
            extraction_progress.complete_package()
        extraction_succeeded = True
    finally:
        extraction_progress.finish(extraction_succeeded)

    validate_tvm_dlpack_header()
    write_sysroot_package_inventory(dldir, installdir)

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
    installdir = os.environ.get(
        "SIMAAI_SYSROOT", f"/opt/toolchain/aarch64/{platform}"
    )
    dldir = os.environ.get("SIMAAI_DOWNLOAD_DIR", f"/tmp/{platform}")

    main(pkg_name, palette_ver, libc_ver, dldir, installdir)
