# Create a custom Modalix image

Palette Image Builder (PIB) creates a custom eLxr image for Modalix. It is provided
as a separate Docker container maintained in the Palette SDK repository. Install it
with sima-cli; the main SDK container is not required.

One project produces two deployment formats:

- **`.swu`**: a signed update bundle for a running board.
- **`.img.gz`**: a full disk image for initial provisioning or recovery.

## 1. Install PIB

With [sima-cli](https://docs.sima-neat.com/getting-started/installation) and Docker
installed, run:

```bash
sima-cli neat install sdk/pib
pib doctor
```

The installer downloads the matching x86_64 or ARM64 container and installs the
`pib` command on Linux, macOS, or Windows. Open a new terminal if it updates PATH.
PIB runs in Linux containers; Docker must be running and permit privileged access
for image assembly. ARM64 emulation is included and configured automatically on
x86 Docker hosts.

Use a local project folder with at least 10 GiB free for `minimal`, or 20 GiB for
`palette`, and similar space in Docker storage. The build needs access to the
Debian/eLxr and SiMa package repositories. The generated board image is ARM64.

`sdk/pib` selects the latest published main package. To select another SDK
branch or release, use the same syntax as the SDK, for example
`sima-cli neat install sdk/pib@develop`. See the
[installation reference](palette-image-builder-reference.md#installation) for
manual Docker installation and host details.

## 2. Create an image project

```bash
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
The [example walkthrough](palette-image-builder-example.md)
shows the complete sequence; CI builds that same checked-in `image.yaml` on both
architectures. The example is included in the container, so no checkout is needed.

## 3. Set up signing once

For development, create a test CA and signing identity:

```bash
pib keys init --cn 'My Company Development'
```

Move `keys/ca.key` to a secure offline location after setup. The signing leaf and its private key remain
in `keys/`; generated `.gitignore` rules exclude private keys and build outputs.
Back up your identity securely. Existing boards trust your CA, so keep that CA
when moving to a new project or platform release.

For production, use your organization's signing identity. See
[external keys and certificate renewal](palette-image-builder-reference.md#signing).
The container includes no SiMa production signing keys.

## 4. Customize the image

For a first build, create `overlay/etc/motd` in your editor:

```text
My custom Modalix image
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
- **ARM64 setup fails on x86:** PIB registers its packaged emulator automatically.
  Check that the Linux Docker engine permits privileged binfmt access.
- **Interrupted image build:** stop builds first, run `pib clean` to inspect
  leftover resources, then `pib clean --yes` to remove them. Cleanup can include
  other PIB projects on the same Docker host.
- **Package/bootstrap failure:** inspect `configs/images/mmdebstrap.log`. Package
  repositories must remain reachable during the build.
- **New platform release:** initialize a new project with that release's container,
  preserve your existing CA, and carry over compatible packages/customizations.
  See the [upgrade reference](palette-image-builder-reference.md#new-platform-release).
