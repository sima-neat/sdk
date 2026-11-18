# Create a custom Modalix image

Palette Image Builder (PIB) creates a custom eLxr image for Modalix. It is provided
as a separate Docker container maintained in the Neat SDK repository. You do not
need to install the main Neat SDK, sima-cli, or build the PIB container yourself.

One project produces two deployment formats:

- **`.swu`**: a signed update bundle for a running board.
- **`.img.gz`**: a full disk image for initial provisioning or recovery.

## 1. Install PIB

You need Docker with privileged containers enabled, Bash, network access to the
Debian/eLxr and SiMa package repositories, and a local folder with at least 10 GiB
free for `minimal` or 20 GiB for `palette`. Allow similar free space in Docker's
storage. Keep the project off NFS.

Published images support native Linux x86_64 and ARM64 Docker hosts. Apple Silicon
with Colima has also completed the minimal-image smoke test. Other Docker Desktop,
WSL, and VM configurations must expose Linux loop devices and device-mapper; run
`pib doctor` to check your configuration. The generated board image is always ARM64.

Choose the development channel, pull the image, and extract its small launcher:

```bash
export PIB_IMAGE=ghcr.io/sima-neat/palette-image-builder-develop:latest
docker pull "$PIB_IMAGE"
mkdir -p "$HOME/.local/bin"
docker run --rm --entrypoint cat "$PIB_IMAGE" \
  /usr/local/share/pib/host/pib > "$HOME/.local/bin/pib"
chmod +x "$HOME/.local/bin/pib"
export PATH="$HOME/.local/bin:$PATH"
pib --version
pib doctor
```

The launcher invokes PIB inside the container and mounts your current directory
as `/workspace`. It does not install Python packages or image-building tools on
your computer. Published CI launchers embed their build's commit-tagged image reference, so
they also work in a new terminal without restoring environment variables. The
`PIB_IMAGE` override above selects a different image when needed; unset it to use
the launcher's embedded reference.

For a released image, use
`ghcr.io/sima-neat/palette-image-builder:v<SDK-version>` instead. Branch images use
`palette-image-builder-<branch>:latest`, following the SDK naming scheme. Repeating
the pull and extraction steps installs the matching launcher for a newer image.
Check available tags before selecting a release; publication runs separately from
editing these docs.

On **Linux x86_64**, enable ARM64 execution on the Docker host once. For example,
on an Ubuntu host:

```bash
sudo apt-get install qemu-user-static binfmt-support
sudo update-binfmts --enable qemu-aarch64
```

Then rerun `pib doctor`. ARM64 hosts execute target binaries natively and do not
need this step. Installing emulation inside the builder container alone does not
register it in the Docker host's kernel.

## 2. Create an image project

```bash
mkdir -p "$HOME/device-images"
cd "$HOME/device-images"
pib init my-image --flavor minimal
cd my-image
```

Use `--flavor palette` if you need the desktop and larger package set. The image's
platform release comes from the selected container. Your project contains:

```text
my-image/
├── image.yaml       # version and customizations
├── custom-debs/     # your ARM64 or architecture-independent Debian packages
├── overlay/         # files to add to the root filesystem
├── hooks/           # optional post-install scripts
├── keys/            # your signing identity and public trust material
├── configs/         # release-specific board defaults; normally leave unchanged
└── out/             # generated artifacts
```

Run subsequent commands from this project directory. To open a shell with its
files mounted, run `pib shell`; run `pib` directly inside that shell, then `exit`
to return to the host.

For a runnable example with a sample application package, configuration overlay,
and service-enablement hook, use `pib init my-image --example custom-image` instead.
The [example recipe](../palette-image-builder/examples/custom-image/README.md)
shows the complete sequence; CI builds that same checked-in `image.yaml` on both
architectures. The example is included in the container, so no checkout is needed.

## 3. Set up signing once

For development, create a test CA and signing identity:

```bash
pib keys init --cn 'My Company Development'
mkdir -p ../secure
chmod 700 ../secure
mv keys/ca.key ../secure/
```

Keep `ca.key` offline after setup. The signing leaf and its private key remain
in `keys/`; generated `.gitignore` rules exclude private keys and build outputs.
Back up your identity securely. Existing boards trust your CA, so keep that CA
when moving to a new project or platform release.

For production, use your organization's signing identity. See
[external keys and certificate renewal](palette-image-builder-reference.md#signing).
The container includes no SiMa production signing keys.

## 4. Customize the image

For a first build, add a marker file:

```bash
mkdir -p overlay/etc
printf 'My custom Modalix image\n' > overlay/etc/motd
```

Files under `overlay/` retain their permissions and become root-owned in the
image. The overlay is applied before package installation: a package may replace
files outside `/etc`. Use a hook for changes that must happen after installation.

To install your application as a Debian package:

```bash
cp /path/to/my-app_1.0_arm64.deb custom-debs/
pib sign-debs
pib verify-debs
```

Add its **package name**, not its filename, to `image.yaml`:

```yaml
packages:
  add: [my-app]
  remove: []
```

Packages must target `arm64` or `all`. Kernel replacement, package removal, service
enablement, and custom update scripts are covered in the
[customization reference](palette-image-builder-reference.md#customization).

## 5. Build a signed update

```bash
pib build --sign
```

This builds the image, signs its SWU with your configured identity, and verifies
its signature, payload hashes, and build manifest. A typical build takes several
minutes, depending on your host and network. Results are in `out/`, including:

| Output | Purpose |
|---|---|
| `*.swu` | Signed update bundle |
| `*.unsigned.swu` | Bundle for a separate signing step |
| `*.img.gz` | Compressed disk image for provisioning/recovery |
| `*-boot0.be` | Associated tRoot payload |
| `*.manifest.json` | Package versions/origins and boot payload provenance |
| `*.cdx.json` | CycloneDX software bill of materials |
| `SHA256SUMS` | Artifact checksums |

To verify again, without locating the filenames yourself:

```bash
pib verify
```

For CI or a separate signing system, use `pib build`, `pib sign`, and `pib verify`
as individual steps. `pib sign` and `pib verify` select the current `image.yaml`
version, even when `out/` also contains earlier versions.

Before the next build, increment the final component of `version` in `image.yaml`
(for example, `3.0.0.1` to `3.0.0.2`). Rebuilding the same version replaces its
outputs, including an existing signed SWU. Boards enforce the image version policy.

## 6. Prepare for deployment

Building and verifying a bundle does not change a board. Before deployment:

- Configure first-boot access if you will flash a fresh board. By default `root`
  and `sima` are locked; an existing board's preserved credentials may survive an
  update. See [board access](palette-image-builder-reference.md#board-access).
- Provision your CA through your authorized board-provisioning process. A stock
  board does not automatically trust the CA you just created.
- Use the correct path for your task: SWUpdate for `.swu`, and the board's
  qualified media/recovery procedure for `.img.gz` and any required boot payloads.

See [installing an SWU](palette-image-builder-reference.md#installing-an-swu) for
SSH update commands. Validate your custom image on a recoverable development board
before using it in production.

## Troubleshooting

- **Missing loop/device-mapper access:** run `pib doctor`. The launcher supplies
  the required privileges, but the Linux Docker host must provide those devices.
- **Missing ARM64 emulation on x86:** register `qemu-aarch64` on the Docker host,
  not just inside the image. It needs the `F` flag for chroot execution.
- **Interrupted image build:** stop builds first, run `pib clean` to inspect
  leftover resources, then `pib clean --yes` to remove them. Cleanup can include
  other PIB projects on the same Docker host.
- **Package/bootstrap failure:** inspect `configs/images/mmdebstrap.log`. Package
  repositories must remain reachable during the build.
- **New platform release:** initialize a new project with that release's container,
  preserve your existing CA, and carry over compatible packages/customizations.
  See the [upgrade reference](palette-image-builder-reference.md#new-platform-release).
