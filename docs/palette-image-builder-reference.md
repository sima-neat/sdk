# Palette Image Builder reference

Start with [Create a custom Modalix image](palette-image-builder.md). This page
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

## Commands

| Command | Purpose |
|---|---|
| `pib doctor` | Check tools, storage, loop devices, device-mapper, and emulation |
| `pib init DIR --flavor minimal` | Create a project; flavors: minimal, palette, securepalette |
| `pib init DIR --example custom-image` | Copy the complete sample image spec and inputs |
| `pib shell` | Open the selected container with the current project mounted |
| `pib keys init --cn NAME` | Generate CA, SWU signing leaf, and Debian signing identity |
| `pib keys renew --cn NAME` | Renew the leaf using the existing CA |
| `pib sign-debs` / `pib verify-debs` | Sign/check local Debian packages |
| `pib build [--sign] [--supplier NAME]` | Build, optionally sign and verify |
| `pib sign [FILE]` | Sign a bundle; defaults to the current project version |
| `pib verify [FILE] [--ca CRT] [--manifest JSON]` | Verify signature and payloads; infer project defaults and an adjacent manifest |
| `pib diff --against MANIFEST` | Show package differences against a previous build |
| `pib clean [--yes]` | Inspect/remove leftover build loop devices and volume groups |

All commands run inside the container. The host launcher only handles Docker,
workspace mounts, and explicitly selected external files. `build`, `doctor`,
`clean`, and the interactive shell use privileged device access; signing,
verification, key generation, and project creation do not need it.

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
it must be the only installed kernel. Local tRoot, ATF, and U-Boot replacement
packages are rejected. The packaged U-Boot must match the one embedded in `fip.bin`.

Custom `swu.description` and `swu.script` overrides can replace the update
instructions. Copy the release defaults from `configs/images/files/` first.
Preserve the version/hardware compatibility placeholders, hashes, and required
boot/SBOM members. Test changes on a board that you can recover; these scripts run
on the board during installation.

`securepalette` enforces additional kernel FIT signature checks and requires
production-signed boot packages for a shippable image. It has not been qualified
by this port's minimal-image smoke test. `--dev` builds use a throwaway identity;
they cannot be combined with `--sign` for normal delivery. Generated customer
CA/leaf keys used for development are distinct from `--dev` mode.

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

The current PIB layout uses GPT `boot.A`, `boot.B`, and an LVM partition containing
rootfs A/B and data. Do not apply older raw-partition U-Boot flashing instructions
to this layout. Exact geometry belongs to the release's board templates.

## New platform release

Pull the appropriate builder image and extract its launcher, then create a fresh
project with `pib init`. Preserve the original CA and signing identity. Transfer
your overlay/hooks and merge customer settings into the new `image.yaml`, retaining
the new `release` and `version` values.

Only copy Debian packages compatible with the new platform. Rebase custom update
scripts/descriptions against that release's defaults. Do not copy all the old
`configs/` over the new ones. Retain the old project and pinned launcher/image
reference when maintaining an older release.
