# Palette Image Builder Reference

Start with [Custom Image Workflow](palette-image-builder.md). This page
covers optional features and board operations; container maintenance belongs in
the [builder README](../palette-image-builder/README.md).

## Installation

The standard installer is `sima-cli neat install sdk/pib`. It reads the `pib/`
metadata subfolder of the selected SDK publication, pulls its qualified
multi-platform image, and installs the portable host launcher. Python comes from
your sima-cli setup; build tools remain in the container. The default target uses
main; `sdk/pib@develop` and `sdk/pib@<release>` select other publications.

On Windows, run from PowerShell with Docker Desktop in Linux-container mode. The
installer creates a `pib.cmd` entry point and updates the user PATH. On Linux/macOS,
it installs to `~/.local/bin` and updates the user shell profile if needed. These
install paths select the same amd64/arm64 image automatically. Linux Docker hosts
need kernel support for loop devices, device-mapper, and binfmt_misc; desktop VMs
must expose those facilities. `pib doctor` performs the checks. Full image creation
has been qualified on native Linux x86/ARM and locally with Apple Silicon/Colima;
Windows installer tests do not constitute Windows full-image qualification.

For manual Docker use without sima-cli, pull a published image and extract the
launcher (Python 3 must be on PATH):

```bash
export PIB_IMAGE=ghcr.io/sima-neat/palette-image-builder-develop:latest
docker pull "$PIB_IMAGE"
mkdir -p "$HOME/.local/bin"
docker run --rm --entrypoint cat "$PIB_IMAGE" \
  /usr/local/share/pib/host/pib > "$HOME/.local/bin/pib"
chmod +x "$HOME/.local/bin/pib"
export PATH="$HOME/.local/bin:$PATH"
pib doctor
```

The emulator is installed in the x86 image. At runtime, privileged PIB starts
register it with the Docker host's Linux kernel only when a working ARM64 handler
is missing. An existing working handler is preserved; native ARM64 needs no
emulator registration. This runtime setup must be repeated after a Docker-host
reboot and is automatic. It does not install packages on the host.

## Environment variables

Set these optional variables in the host shell that runs `pib`. File paths must be accessible to Docker. Selected credentials and signing files are mounted read-only only for commands that use them. `PIB_CONFIGS` mounts its parent directory read-only; `PIB_DEB_CACHE` is writable.

| Variable | Used by | Purpose |
|---|---|---|
| `PIB_IMAGE` | All commands | Override the installed container image with an explicit image tag or digest. |
| `PIB_CREDENTIALS` | `pib build` | File containing `root:<hash>` and `sima:<hash>` password hashes. Without it, fresh images lock both passwords; existing boards may retain credentials in their persistent overlay. |
| `SWU_SIGNING_KEY`, `SWU_SIGNING_CERT` | `pib sign`, `pib build --sign` | External signing key and certificate. The key can be a `pkcs11:` URI. Defaults come from the project signing configuration; the certificate must chain to the image’s trusted CA. |
| `PIB_CONFIGS` | `pib init` | Advanced: use an external image configuration directory instead of bundled configurations. |
| `PIB_PCSCD_DIR` | Signing commands | Override the Docker host’s pcscd socket directory; default `/run/pcscd`. Requires a socket accessible to the Linux container. |
| `PIB_DEB_CACHE` | `pib build`, `pib shell` | Host directory for verified Debian package downloads. Package hashes and sizes are checked against authenticated repository metadata on every build. |
| `PIB_KERNEL_URL`, `PIB_KERNEL_REF` | `pib package` | Kernel repository (an https URL without credentials) and branch or commit to build on every run. `--kernel-url` and `--kernel-ref` override them for one run. |
| `PIB_KERNEL_SRC` | `pib package` | Git repository on the host, a checkout or a bare repository, holding your kernel; mounted read-only. Use it for a private repository or commits not pushed anywhere. |
| `PIB_PKGBUILD_SRC` | `pib package` | Checkout holding sbp (`pkgbuild/`) and its package configurations (`configs/packages/`), used instead of the ones in the PIB image; required until the image includes them. Only those two directories are mounted, read-only. |
| `PIB_PACKAGE_JOBS`, `PIB_CCACHE_SIZE`, `PIB_PACKAGE_VOLUME` | `pib package` | Parallel compile jobs; compiler cache size (default `5G`); Docker volume for sbp's work tree, package repository and cache (default `pib-package-<uid>`). |

## Commands

Image compression uses pigz on the builder's available CPU cores. Outputs remain
gzip-compatible; signing and verification still cover the actual compressed payloads.

To reuse Debian downloads between builds, set a host cache directory before building:

```bash
export PIB_DEB_CACHE="$HOME/.cache/sima/pib-debs"
pib build --sign
```

Only package bytes are cached. Each bootstrap downloads and authenticates current
repository metadata, then checks cached packages against its SHA256 and size.
Corrupted bytes are discarded and downloaded again. Root filesystems, package
installation, customization hooks, signing, and verification are rebuilt each time.
The cache can contain your custom packages; keep it in your own user directory.

| Command | Purpose |
|---|---|
| `pib doctor` | Check tools, storage, loop devices, device-mapper, and emulation |
| `pib init DIR --flavor minimal` | Create a project; flavors: minimal, palette |
| `pib init DIR --example custom-image` | Copy the complete sample image spec and inputs |
| `pib shell` | Open the selected container with the current project mounted |
| `pib keys init --cn NAME` | Generate CA, SWU signing leaf, and Debian signing identity |
| `pib keys renew --cn NAME` | Renew the leaf using the existing CA |
| `pib keys fit` | Generate the key pair that signs kernel FIT images built by `pib package` |
| `pib package -p linux` | Build the kernel, and palette's kernel-module packages, into `custom-debs/` |
| `pib sign-debs` / `pib verify-debs` | Sign/check local Debian packages |
| `pib build [--sign] [--supplier NAME]` | Build, optionally sign and verify |
| `pib sign [FILE]` | Sign a bundle; defaults to the current project version |
| `pib verify [FILE] [--ca CRT] [--manifest JSON]` | Verify signature and payloads; infer project defaults and an adjacent manifest |
| `pib diff --against MANIFEST` | Show package differences against a previous build |
| `pib clean [--yes]` | Inspect/remove leftover build loop devices and volume groups |

All commands run inside the container. The host launcher only handles Docker,
workspace mounts, and explicitly selected external files. `build`, `doctor`,
`clean`, and the interactive shell use privileged device access; signing,
verification, key generation, and project creation do not need it. `pib package`
runs unprivileged and sees the project read-only, except `custom-debs/`; of
`keys/` it sees only the kernel FIT key pair.

## Build outputs

| File | Technical purpose |
|---|---|
| `*.swu` | Signed update bundle |
| `*.unsigned.swu` | Input for a separate signing step |
| `*.img.gz` | Compressed disk image for provisioning or recovery |
| `*-boot0.be` | Associated tRoot payload; follow the platform provisioning procedure |
| `*.manifest.json` | Package versions, origins, and boot-payload provenance |
| `*.cdx.json` | CycloneDX software bill of materials |
| `SHA256SUMS` | Artifact checksums |

`pib sign` and `pib verify` select the current `image.yaml` version even if `out/`
contains older builds. Rebuilding the same version replaces its outputs,
including a previously signed SWU. Increase the version for subsequent updates.

## Media and partition layout

The Modalix eMMC/SD image uses GPT boot partitions and an LVM partition for the
root filesystems and data. These are the defaults of the current PIB platform
release (`3.0.0`), not fixed sizes for every release. Check the selected builder's
`configs/images/image-params.yaml` and `image-stages.yaml` for its exact geometry.
The LVM partition and data volume grow to the device's available capacity on first
boot; the downloaded disk image can be smaller than the physical device.

### Physical partitions

| # | Name | Size | Format | Contents |
|---|---|---|---|---|
| 1 | `boot.A` | 256 MiB | vFAT | Slot A boot artifacts: `fip.bin`, U-Boot, boot scripts, kernel FIT/device-tree data, and U-Boot environment |
| 2 | `boot.B` | 256 MiB | vFAT | Boot artifacts for slot B |
| 3 | `lvm` | Remaining usable device capacity after first-boot growth | LVM physical volume | Holds the logical volumes below |

### Logical volumes

The logical volumes reside inside partition 3.

| Volume | Size | File system | Purpose |
|---|---|---|---|
| `rootfs.A` | 1.5 GiB for `minimal`; 5.5 GiB for `palette` | ext4 | Slot A root filesystem |
| `rootfs.B` | Same size as `rootfs.A` | ext4 when populated | Slot B root filesystem; initial population depends on `slots` |
| `data` | Remaining LVM capacity after space for both rootfs slots is reserved | ext4 | General storage, expanded on first boot |

### Slot population

- **`slots: ab` (PIB default):** both rootfs volumes are created and populated in the disk image.
- **`slots: a`:** the disk image contains only `rootfs.A`. On first boot, `simaai-growlvm` creates `rootfs.B` at the same size before expanding `data`. Slot B has no root filesystem until an update populates it.

The `slots` setting controls the initial disk image population; it does not
remove A/B update support. Updates write the inactive slot. The boot artifacts
and root filesystem in the two slots can differ after an update.

## Troubleshooting

- **Missing loop or device-mapper access:** run `pib doctor`. Docker must provide these devices and allow privileged containers.
- **ARM64 setup fails on x86:** check that the Linux Docker engine permits privileged binfmt registration.
- **Interrupted image build:** stop builds, inspect leftovers with `pib clean`, then use `pib clean --yes` if appropriate. Cleanup can affect other PIB projects on the same Docker host.
- **Package or bootstrap failure:** inspect `configs/images/mmdebstrap.log` and check repository connectivity.

## Customization

Edit `image.yaml`; leave the release defaults under `configs/` unchanged unless
you are developing board support.

```yaml
base: minimal
release: 3.0.0
version: 3.0.0.2
packages:
  add: [my-app]
  remove: []
overlay: overlay/
hooks: [hooks/enable-my-app.sh]
vendor: My Company
```

Overlay files retain their permissions and become root-owned in the image. The overlay is applied before package installation, so packages can replace files outside `/etc`. Use a post-install hook for changes that must happen after packages are installed.

Create a post-install hook to enable your application's service:

```sh
#!/bin/sh
set -eu
systemctl --root="$1" enable my-app.service
```

Hooks execute with `sh`, in order, after SiMa's hooks and package installation.
`$1` is the rootfs directory. Write under it or use `systemctl --root="$1"`;
`chroot "$1"` executes an ARM64 program in the image. Use workspace-relative hook
paths containing only letters, digits, `_ . / + -`.

Removing a package required by another package causes APT resolution to fail.
Retain packages that board hooks require, such as `swupdate` and palette's `kea`.
Changing from `palette` to `minimal` also changes image sizes and package defaults.

Custom Debian packages require detached signatures accepted by `debs.key` in
`image.yaml`. `pib sign-debs` uses the generated Debian signing key. To use an
existing GPG identity, export its public key into `keys/debs-signing.asc`, sign
packages with that identity externally, and use `pib verify-debs` before building.

Kernel packages are special: keep the release's existing kernel package name,
found in `configs/images/image-params.yaml`. PIB selects that kernel automatically;
it must be the only installed kernel. `pib package` builds such packages from SiMa's
kernel source or yours; see [Building the kernel](#building-the-kernel). Local
tRoot, ATF, and U-Boot replacement packages are rejected. The packaged U-Boot must
match the one embedded in `fip.bin`.

Custom `swu.description` and `swu.script` overrides can replace the update
instructions. Copy the release defaults from `configs/images/files/` first.
Preserve the version/hardware compatibility placeholders, hashes, and required
boot/SBOM members. Test changes on a board that you can recover; these scripts run
on the board during installation.

`--dev` builds use a throwaway identity;
they cannot be combined with `--sign` for normal delivery. Generated customer
CA/leaf keys used for development are distinct from `--dev` mode.

## Building the kernel

`pib package` builds the Modalix kernel from SiMa's public kernel source or your
own, using sbp, SiMa's package builder, and puts the kernel's Debian packages in
`custom-debs/`. For palette projects it also rebuilds the kernel-module packages
palette images carry, smifb and lttng-modules, for that kernel. The PIB image
includes the ARM64 cross toolchain these builds use, which makes the image about
0.6 GB larger.

```bash
pib keys fit
pib package -p linux
pib sign-debs
pib build --sign
```

`pib keys fit` creates `keys/fit-signing.key` and `keys/fit-signing.crt` once;
`pib package` signs the kernel's FIT image with that key. Then choose the source:

| Kernel source | How to select it |
|---|---|
| SiMa's public repository, branch `master` | The default: `https://github.com/SiMa-ai/simaai-linux.git` |
| Your fork, one of its branches, or a commit | `--kernel-url https://github.com/<you>/simaai-linux.git --kernel-ref <branch>`, or `PIB_KERNEL_URL` and `PIB_KERNEL_REF` |
| A repository on your computer | `PIB_KERNEL_SRC=<path>`: its checked-out branch, or `PIB_KERNEL_REF` |

Each run looks the branch up and builds its latest commit, which `pib package`
prints; when the branch has moved, the kernel is rebuilt. Only committed changes
are built, and `pib package` warns about uncommitted ones. The build container has
no credentials: name a public repository by an https URL without a token, and a
private one by `PIB_KERNEL_SRC`, which is mounted read-only. The first build
from a repository downloads all of it.

Keep the release's kernel version (6.18.3), its `simaai_modalix_defconfig`
configuration, and SiMa's FIT packaging. The image installs only the release's
kernel package name, so another version is left out. A kernel package without a
FIT (`boot/fitImage`) boots unsigned, as a plain kernel image, and `pib package`
warns about it. It also compares the kernel's SiMa-specific headers with the
release's, which SiMa's prebuilt software, such as the camera ISP and the MLA
runtime, is built against, and warns when they differ. The `master` branch
currently holds SiMa's 3.0 kernel, which has the FIT packaging and the release's
headers, so neither warning appears.

A kernel build takes about half an hour and 6-8 GB in the Docker volume
`pib-package-<uid>`. Until sbp itself is included in the PIB image, set
`PIB_PKGBUILD_SRC` to a checkout that contains it (`pkgbuild/` and
`configs/packages/`).

## Signing

The image embeds `signing.ca` as its update trust root. Preserve that CA when
upgrading images for existing boards. To use keys outside the workspace:

```bash
cp /path/to/public-ca.crt keys/ca.crt
SWU_SIGNING_KEY=/path/to/private-signing.key \
SWU_SIGNING_CERT=/path/to/public-signing.crt pib sign
pib verify
```

The launcher mounts each selected external file read-only, rather than mounting
its whole directory. `pib build --sign` also accepts these variables. For stronger
separation, keep the private signing key on a separate signing machine and run
build/sign independently. The CA private key is only needed for issuing/renewing
leaf certificates; keep it offline, not in your regular build project.

To renew a generated leaf, temporarily restore `ca.key` into `keys/`, run
`pib keys renew --cn 'My Company Development'` using the same algorithm as setup,
then return the CA key to offline storage. Leaf certificates last 825 days.

For PKCS#11, use `pib sign --pkcs11 'pkcs11:...' --cert keys/swu-signing.crt`.
The Docker host needs pcscd and its reader driver. The launcher mounts an available
pcscd socket during signing; `PIB_PCSCD_DIR` overrides its location. Physical
card/token operation was not tested in this port. A macOS host socket is not
necessarily available to its Linux Docker VM.

For encrypted payloads, run `pib keys payload`, set
`encryption: {key: keys/payload.key}` before building, then use `pib sign --encrypt`.
The resulting image carries the payload-decryption key; this does not provide
protection against someone who can extract that image. Use separate build/sign
steps for encryption; `build --sign` uses the normal unencrypted signing path.

## Board access

For a fresh flash, configure credentials or an authorized SSH key before building.
To provide root and sima password hashes, create a protected credentials file
outside the project and name it through `PIB_CREDENTIALS`:

```bash
mkdir -p ../secure
chmod 700 ../secure
(umask 077; printf 'root:%s\nsima:%s\n' \
  "$(openssl passwd -6)" "$(openssl passwd -6)" > ../secure/credentials)
PIB_CREDENTIALS="$(cd ../secure && pwd)/credentials" pib build --sign
```

This optional path needs OpenSSL on the host. Passwords are prompted for and only
hashes are saved. Root SSH access remains key-only. Alternatively, place an
approved public key at `overlay/root/.ssh/authorized_keys` with directory mode 700
and file mode 600. Each board generates its own SSH host keys on first boot.

For optional root SSH access, run these commands from the project directory before building. Append only an approved **public** key; keep private keys off the image.

```bash
mkdir -p overlay/root/.ssh
chmod 700 overlay/root/.ssh
cat "$HOME/.ssh/id_ed25519.pub" >> overlay/root/.ssh/authorized_keys
chmod 600 overlay/root/.ssh/authorized_keys
```

Root password authentication over SSH remains disabled, even when `PIB_CREDENTIALS` sets a root password. Each line authorizes one public key. After deploying the image, an authorized key can connect as `ssh root@<board-address>`. Existing boards may retain SSH configuration through their persistent overlay.

## Installing an SWU

These commands modify a board. Select the **signed** `.swu` and the intended
board explicitly. The board must run a compatible SiMa/PIB eLxr image and provide
SSH access as `sima` with sudo.

On first installation, use your authorized provisioning procedure to establish
the CA. The guide's development-board bootstrap path is:

```bash
BOARD=192.0.2.10
SWU=out/your-image.swu
scp "$SWU" keys/ca.crt "sima@$BOARD:/tmp/"
ssh -t "sima@$BOARD" sudo swupdate -i "/tmp/$(basename "$SWU")" \
  -k /tmp/ca.crt -e update,full
ssh -t "sima@$BOARD" sudo reboot
```

For subsequent updates, the board uses its installed CA and version policy:

```bash
scp "$SWU" "sima@$BOARD:/tmp/"
ssh -t "sima@$BOARD" sudo simaai-update "/tmp/$(basename "$SWU")" -e update,full
ssh -t "sima@$BOARD" sudo reboot
```

The update targets the inactive slot. Boot selection and watchdog rollback depend
on the platform boot/update implementation and need hardware validation for your
image. The default update preserves the board's writable overlay; a clean-overlay
update can remove local credentials/settings. Follow the platform recovery guide
for initial eMMC flashing; an SWU is not a raw disk image.

Use the [media and partition layout](#media-and-partition-layout) for this release.
Do not apply older raw-partition U-Boot flashing instructions to the GPT/LVM layout.

## New platform release

Pull the appropriate builder image and extract its launcher, then create a fresh
project with `pib init`. Preserve the original CA and signing identity. Transfer
your overlay/hooks and merge customer settings into the new `image.yaml`, retaining
the new `release` and `version` values.

Only copy Debian packages compatible with the new platform. Rebase custom update
scripts/descriptions against that release's defaults. Do not copy all the old
`configs/` over the new ones. Retain the old project and pinned launcher/image
reference when maintaining an older release.
