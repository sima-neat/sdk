import argparse
import re
import subprocess
import tempfile
from pathlib import Path

PACKAGE = "libgcc-s1"
ARCH = "arm64"
INSTALLED_VERSION = "14.2.0-4ubuntu2~24.04.1"
TARGET_VERSION = "12.2.0-14+deb12u1"
TARGET_ORIGIN = 'origin "debian.neat.sima.ai"'


def read_target_priority(path: Path) -> int:
    stanza = ""
    for candidate in path.read_text(encoding="utf-8").split("\n\n"):
        if f"Pin: {TARGET_ORIGIN}" in candidate:
            stanza = candidate
            break
    if not stanza:
        raise AssertionError(f"missing target-origin stanza: {TARGET_ORIGIN}")

    match = re.search(r"^Pin-Priority:\s*(\d+)\s*$", stanza, re.MULTILINE)
    if match is None:
        raise AssertionError("target-origin stanza has no numeric priority")
    return int(match.group(1))


def apt_options(root: Path) -> list[str]:
    return [
        "-o",
        f"Dir::State::status={root / 'status'}",
        "-o",
        f"Dir::State::lists={root / 'lists'}",
        "-o",
        f"Dir::Etc::sourcelist={root / 'sources.list'}",
        "-o",
        "Dir::Etc::sourceparts=-",
        "-o",
        f"APT::Architecture={ARCH}",
        "-o",
        f"APT::Architectures::={ARCH}",
    ]


def write_fixture(root: Path) -> None:
    status = root / "status"
    lists = root / "lists"
    (lists / "partial").mkdir(parents=True)
    repository = root / "repository"
    repository.mkdir()
    cache = root / "cache"
    (cache / "archives" / "partial").mkdir(parents=True)
    status.write_text(
        f"""Package: {PACKAGE}
Status: install ok installed
Priority: required
Section: libs
Installed-Size: 1
Maintainer: SDK Test <sdk-test@example.invalid>
Architecture: {ARCH}
Multi-Arch: same
Version: {INSTALLED_VERSION}
Description: installed Ubuntu fixture

""",
        encoding="utf-8",
    )
    (repository / "Packages").write_text(
        f"""Package: {PACKAGE}
Architecture: {ARCH}
Version: {TARGET_VERSION}
Priority: required
Section: libs
Filename: pool/{PACKAGE}_{TARGET_VERSION}_{ARCH}.deb
Size: 1
Description: approved target fixture

""",
        encoding="utf-8",
    )
    sources = root / "sources.list"
    sources.write_text(
        f"deb [trusted=yes] file:{repository} ./\n",
        encoding="utf-8",
    )
    subprocess.run(
        [
            "apt-get",
            *apt_options(root),
            "-o",
            f"Dir::Cache={cache}",
            "update",
        ],
        check=True,
        capture_output=True,
        text=True,
    )


def candidate_for(root: Path, priority: int) -> tuple[str, str]:
    preferences_dir = root / "preferences.d"
    preferences_dir.mkdir(exist_ok=True)
    preferences = preferences_dir / "target.pref"
    preferences.write_text(
        f"""Package: {PACKAGE}
Pin: version {TARGET_VERSION}
Pin-Priority: {priority}

""",
        encoding="utf-8",
    )
    command = [
        "apt-cache",
        *apt_options(root),
        "-o",
        "Dir::Etc::preferences=/dev/null",
        "-o",
        f"Dir::Etc::preferencesparts={preferences_dir}",
        "policy",
        f"{PACKAGE}:{ARCH}",
    ]
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    match = re.search(r"^\s*Candidate:\s*(\S+)\s*$", result.stdout, re.MULTILINE)
    if match is None:
        raise AssertionError(f"apt-cache did not report a candidate:\n{result.stdout}")
    return match.group(1), result.stdout


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("preferences", type=Path)
    args = parser.parse_args()

    target_priority = read_target_priority(args.preferences)
    with tempfile.TemporaryDirectory(prefix="sysroot-apt-candidate-") as tmpdir:
        root = Path(tmpdir)
        write_fixture(root)

        baseline, baseline_policy = candidate_for(root, 990)
        if baseline != INSTALLED_VERSION:
            raise AssertionError(
                f"priority 990 selected {baseline}, expected installed "
                f"{INSTALLED_VERSION}:\n{baseline_policy}"
            )

        patched, patched_policy = candidate_for(root, target_priority)
        if patched != TARGET_VERSION:
            raise AssertionError(
                f"priority {target_priority} selected {patched}, expected target "
                f"{TARGET_VERSION}:\n{patched_policy}"
            )

    print(
        f"APT candidate regression passed: 990 -> {baseline}; "
        f"{target_priority} -> {patched}"
    )


if __name__ == "__main__":
    main()
