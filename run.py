#!/usr/bin/env python3
import argparse
import ipaddress
import os
import platform
import re
import shlex
import socket
import subprocess
import sys
from pathlib import Path


def run(cmd, check=True, capture=False):
    return subprocess.run(cmd, check=check, text=True, capture_output=capture)


def has_cmd(name: str) -> bool:
    return subprocess.run(["bash", "-lc", f"command -v {shlex.quote(name)} >/dev/null 2>&1"], check=False).returncode == 0


def _is_linux_virtual_iface(iface: str) -> bool:
    prefixes = ("lo", "docker", "br-", "veth", "virbr", "tun", "tap", "wg", "zt", "tailscale", "vmnet", "vboxnet")
    return iface.startswith(prefixes)


def _detect_physical_ipv4s_macos() -> list[tuple[str, str]]:
    try:
        out = run(["ifconfig"], capture=True).stdout or ""
    except Exception:
        return []

    found: list[tuple[str, str]] = []
    iface = ""
    status = ""
    inet: str | None = None
    is_physical = False

    def flush_current() -> None:
        nonlocal iface, status, inet, is_physical
        if iface and is_physical and status == "active" and inet and not inet.startswith("127."):
            found.append((iface, inet))

    for line in out.splitlines():
        m = re.match(r"^([a-zA-Z0-9]+): flags=", line)
        if m:
            flush_current()
            iface = m.group(1)
            status = ""
            inet = None
            is_physical = iface.startswith("en")
            continue
        if not iface:
            continue
        s = line.strip()
        if s.startswith("status:"):
            status = s.split(":", 1)[1].strip()
        elif s.startswith("inet "):
            parts = s.split()
            if len(parts) >= 2:
                inet = parts[1]

    flush_current()
    return found


def _detect_physical_ipv4s_linux() -> list[tuple[str, str]]:
    if not has_cmd("ip"):
        return []
    try:
        out = run(["ip", "-o", "-4", "addr", "show", "up", "scope", "global"], capture=True).stdout or ""
    except Exception:
        return []

    found: list[tuple[str, str]] = []
    for line in out.splitlines():
        # Example: "2: eth0    inet 192.168.1.10/24 ..."
        m = re.match(r"^\d+:\s+([^\s]+)\s+inet\s+(\d+\.\d+\.\d+\.\d+)/\d+", line)
        if not m:
            continue
        iface, ip = m.group(1), m.group(2)
        if _is_linux_virtual_iface(iface):
            continue
        if iface.startswith(("en", "eth")):
            found.append((iface, ip))
    return found


def detect_host_ip(devkit_ip: str | None) -> tuple[str, str, list[tuple[str, str]]]:
    candidates: list[tuple[str, str]] = []
    if sys.platform == "darwin":
        candidates = _detect_physical_ipv4s_macos()
    elif sys.platform.startswith("linux"):
        candidates = _detect_physical_ipv4s_linux()
    if candidates:
        iface, ip = candidates[0]
        return ip, iface, candidates

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((devkit_ip or "8.8.8.8", 80))
        return s.getsockname()[0], "auto", []
    finally:
        s.close()


def configure_nfs_export(host_dir: Path, devkit_ip: str | None, host_os: str, host_ip: str) -> None:
    host_path = str(host_dir.resolve())
    if host_os == "darwin":
        uid = os.getuid()
        gid = os.getgid()
        if devkit_ip:
            line = f"{host_path} -alldirs -mapall={uid}:{gid} {devkit_ip}"
        else:
            # macOS exports doesn't accept "*" host; export to detected /24 instead.
            iface = ipaddress.IPv4Interface(f"{host_ip}/24")
            network = str(iface.network.network_address)
            mask = str(iface.network.netmask)
            line = f"{host_path} -alldirs -mapall={uid}:{gid} -network {network} -mask {mask}"
        script = (
            "set -eu; "
            "touch /etc/exports; "
            f"tmpf=$(mktemp); awk -v p={shlex.quote(host_path)} '"
            "/^[[:space:]]*#/ || NF==0 { print; next } "
            "{ path=$1 } "
            "(path==p) || (index(path, p \"/\")==1) || (index(p, path \"/\")==1) { next } "
            "{ print }' /etc/exports > \"$tmpf\"; "
            f"echo {shlex.quote(line)} >> \"$tmpf\"; "
            "cp \"$tmpf\" /etc/exports; rm -f \"$tmpf\"; "
            "nfsd checkexports; nfsd restart"
        )
        run(["sudo", "sh", "-c", script])
        return

    if host_os == "linux":
        client = devkit_ip if devkit_ip else "*"
        line = f"{host_path} {client}(rw,sync,no_subtree_check,no_root_squash,insecure)"
        script = (
            "set -eu; mkdir -p /etc/exports.d; "
            f"echo {shlex.quote(line)} > /etc/exports.d/elxr-sdk.exports; "
            "exportfs -ra; "
            "(systemctl restart nfs-server || systemctl restart nfs-kernel-server || true)"
        )
        run(["sudo", "sh", "-c", script])
        return

    raise RuntimeError("Host NFS setup is only implemented for macOS/Linux")


def configure_smb_share_windows(host_dir: Path) -> None:
    share_name = "elxr_workspace"
    path = str(host_dir.resolve())
    ps = (
        f"$name='{share_name}'; $path='{path}'; "
        "if (-not (Get-SmbShare -Name $name -ErrorAction SilentlyContinue)) { "
        "New-SmbShare -Name $name -Path $path -FullAccess Everyone | Out-Null }; "
        "Write-Output $name"
    )
    run(["powershell", "-NoProfile", "-Command", ps])


def docker_image_resolve(image_ref: str, remote_ref: str, prefer_local: bool) -> str:
    if prefer_local and subprocess.run(["docker", "image", "inspect", image_ref], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        print(f"Preferring local image {image_ref}")
        return image_ref

    if prefer_local:
        print(f"Preferred local image {image_ref} not found, trying {remote_ref}")

    if subprocess.run(["docker", "pull", remote_ref], check=False).returncode == 0:
        print(f"Using image {remote_ref}")
        return remote_ref

    if subprocess.run(["docker", "image", "inspect", image_ref], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        print(f"Using local fallback image {image_ref}")
        return image_ref

    raise RuntimeError(f"Unable to use image {remote_ref} or {image_ref}")


def container_exists(name: str, running_only: bool = False) -> bool:
    args = ["docker", "ps", "--format", "{{.Names}}"] if running_only else ["docker", "ps", "-a", "--format", "{{.Names}}"]
    out = run(args, capture=True).stdout or ""
    return name in out.splitlines()


def make_hostname(image_name: str, image_tag: str) -> str:
    raw = f"{image_name}-{image_tag}".lower()
    cleaned = re.sub(r"[^a-z0-9-]", "-", raw)
    cleaned = re.sub(r"-{2,}", "-", cleaned).strip("-")
    if not cleaned:
        cleaned = "elxr-sdk"
    return cleaned[:63]


def interactive_shell_argv() -> list[str]:
    init = """
if [ -n "${DEVKIT_SYNC_DEVKIT_IP:-}" ] && [ -f /usr/local/bin/devkit.sh ] && [ ! -f "${HOME}/.devkit-sync.rc" ]; then
  source /usr/local/bin/devkit.sh "${DEVKIT_SYNC_DEVKIT_IP}"
fi
exec /bin/bash -l
""".strip()
    return ["/bin/bash", "-lc", init]


def main() -> int:
    p = argparse.ArgumentParser(description="Start eLxr SDK container + host share setup")
    p.add_argument("--prefer-local", action="store_true")
    p.add_argument("--background", action="store_true")
    p.add_argument("--connect", action="store_true")
    p.add_argument("--stop", action="store_true")
    p.add_argument("--devkit-ip", default=os.getenv("DEVKIT_IP", ""), help="Optional DevKit IP for restricted NFS export")
    p.add_argument("--hostip", default=os.getenv("HOST_IP", ""), help="Override detected host IP")
    p.add_argument("--share-backend", choices=["auto", "nfs", "smb", "none"], default="auto")
    p.add_argument("image_name", nargs="?", default=os.getenv("IMAGE_NAME", "elxr"))
    p.add_argument("image_tag", nargs="?", default=os.getenv("IMAGE_TAG", "latest"))
    args = p.parse_args()

    modes = sum([args.background, args.connect, args.stop])
    if modes > 1:
        raise SystemExit("Use only one of --background/--connect/--stop")

    container_name = os.getenv("CONTAINER_NAME", "elxr")
    workdir = os.getenv("CONTAINER_WORKDIR", "/workspace")
    host_dir = Path.cwd()
    ghcr_owner = os.getenv("GHCR_OWNER", "sima-neat")
    image_ref = f"{args.image_name}:{args.image_tag}"
    remote_ref = f"ghcr.io/{ghcr_owner}/{args.image_name}:{args.image_tag}"
    container_hostname = make_hostname(args.image_name, args.image_tag)

    if args.stop:
        if container_exists(container_name):
            run(["docker", "rm", "-f", container_name])
            print(f"Stopped container '{container_name}'.")
        else:
            print(f"Container '{container_name}' is not present.")
        return 0

    if args.connect:
        if not container_exists(container_name, running_only=True):
            raise SystemExit(f"Container '{container_name}' is not running")
        os.execvp("docker", ["docker", "exec", "-it", container_name, *interactive_shell_argv()])

    host_os = platform.system().lower()
    backend = args.share_backend
    if backend == "auto":
        backend = "smb" if host_os.startswith("win") else "nfs"

    auto_host_ip, auto_iface, auto_candidates = detect_host_ip(args.devkit_ip or None)
    host_ip = args.hostip or auto_host_ip

    if backend == "nfs":
        devkit_ip = args.devkit_ip or None
        configure_nfs_export(host_dir, devkit_ip, host_os, host_ip)
        if devkit_ip:
            print(f"Host NFS export configured: {host_dir} -> {devkit_ip}")
        else:
            print(f"Host NFS export configured: {host_dir} -> *")
            print("Warning: no --devkit-ip provided, export is open to all clients.")
    elif backend == "smb":
        if not host_os.startswith("win"):
            raise SystemExit("SMB backend automation is only implemented on Windows")
        configure_smb_share_windows(host_dir)
        print(f"Host SMB share configured for {host_dir}")
    else:
        print("Host share setup skipped (--share-backend none)")

    chosen_image = docker_image_resolve(image_ref, remote_ref, args.prefer_local)

    if container_exists(container_name, running_only=True):
        print(f"Container '{container_name}' is already running; connecting.")
        os.execvp("docker", ["docker", "exec", "-it", container_name, *interactive_shell_argv()])

    if container_exists(container_name):
        run(["docker", "rm", "-f", container_name], check=False)

    docker_cmd = [
        "docker", "run",
        "--name", container_name,
        "--hostname", container_hostname,
        "--privileged",
        "-v", f"{host_dir}:{workdir}",
        "-w", workdir,
        "-v", "/dev:/dev",
        "-e", f"NFS_SERVER_HOST_IP={host_ip}",
        "-e", f"DEVKIT_HOST_EXPORT_PATH={host_dir}",
        "-e", f"DEVKIT_HOST_PLATFORM={host_os}",
        "-e", f"DEVKIT_SYNC_DEVKIT_IP={args.devkit_ip}",
        "-e", f"SDK_IMAGE_TAG={args.image_tag}",
        chosen_image,
    ]

    if host_os.startswith("linux"):
        docker_cmd[2:2] = ["--network", "host"]

    if args.background:
        docker_cmd.insert(2, "-d")
        docker_cmd.insert(3, "--rm")
        docker_cmd += ["sleep", "infinity"]
        run(docker_cmd)
        print(f"Started container '{container_name}' in background.")
        print("Connect with: ./run.sh --connect")
        return 0

    docker_cmd.insert(2, "-it")
    docker_cmd.insert(3, "--rm")
    docker_cmd += interactive_shell_argv()

    print(f"Running {chosen_image}")
    if args.hostip:
        print(f"Host IP: {host_ip} (override)")
    elif auto_iface != "auto":
        print(f"Host IP: {host_ip} (interface: {auto_iface})")
        if len(auto_candidates) > 1:
            others = ", ".join([f"{i}:{ip}" for i, ip in auto_candidates[1:]])
            print(f"Detected multiple physical interfaces, using first. Override with --hostip. Others: {others}")
    else:
        print(f"Host IP: {host_ip} (auto)")
    print(f"Workspace: {host_dir} -> {workdir}")
    os.execvp("docker", docker_cmd)


if __name__ == "__main__":
    raise SystemExit(main())
