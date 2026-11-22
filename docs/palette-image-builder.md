# Custom Image Workflow

Use Palette Image Builder (PIB), a companion to Palette SDK, to turn your software
and system configuration into a custom Modalix eLxr image. This page explains the
general process. For a complete package, service, and overlay recipe, follow
[Example Image](palette-image-builder-example.md).

## Install PIB

Install [sima-cli](https://docs.sima-neat.com/getting-started/installation), start
Docker with a Linux engine, then run:

```bash
sima-cli neat install sdk/pib
```

The installer selects the native x86_64 or ARM64 container, sets up the host
launcher and PATH, and checks the Docker host automatically. Open a new terminal
if PATH was updated. The main SDK container is not required to run PIB.

Image assembly requires privileged Docker access, repository connectivity, and
free space in both the project and Docker storage: allow 10 GiB for `minimal` or
20 GiB for `palette`. On x86, PIB configures ARM64 emulation automatically.
See the [installation reference](palette-image-builder-reference.md#installation)
for platform support, alternate releases, and manual installation.

## 1. Create an image project

```bash
pib init my-image --flavor minimal
cd my-image
```

Choose a flavor compatible with your platform release. Use `palette` when you
need its desktop and larger package set. The selected builder supplies the
release-specific board defaults under `configs/`; normally leave them unchanged.
Run subsequent commands from your project directory.

## 2. Define the image contents

| Input | Purpose |
|---|---|
| `image.yaml` | Flavor, release, image version, packages, and signing settings |
| `custom-debs/` | Your ARM64 or architecture-independent Debian packages |
| `overlay/` | Configuration and other files copied into the root filesystem |
| `hooks/` | Changes after package installation, such as enabling a service |

Build applications and compile models with Palette SDK, then package the required
files for the target. PIB assembles packages; it does not compile application
source. See [Palette SDK System Stack](sdk-architecture.md) for the component roles.

List Debian package names in `image.yaml`, rather than `.deb` filenames. Use an
overlay for files and a hook for changes that must follow package installation.
Detailed package, kernel, and hook rules are in the
[customization reference](palette-image-builder-reference.md#customization).

## 3. Prepare signing and trust

For development, create your project signing identity once:

```bash
pib keys init --cn 'My Company Development'
```

Keep the CA private key offline after setup. Preserve the same CA when updating
existing boards, and use your organization's production signing process for
shipping images. See the [signing reference](palette-image-builder-reference.md#signing)
for external keys, renewal, and separate build/sign workflows.

## 4. Configure board login

**For UART/console password login, set `PIB_CREDENTIALS` before building.** Signing-key creation does not set login passwords. Without this file, a fresh image leaves both `root` and `sima` passwords locked, so console password login fails even if SSH key access works.

From the project directory, use OpenSSL on the host to generate a protected file containing password hashes. Enter and confirm a password for `root`, then for `sima`:

```bash
mkdir -p ../secure
chmod 700 ../secure
(umask 077; printf 'root:%s\nsima:%s\n' \
  "$(openssl passwd -6)" "$(openssl passwd -6)" > ../secure/credentials)
chmod 600 ../secure/credentials
export PIB_CREDENTIALS="$(cd ../secure && pwd)/credentials"
```

Keep this file outside the project and source control. Run the build in the same shell; in a new shell, export `PIB_CREDENTIALS` again. PIB mounts the file read-only for the build.

If you only need SSH key access, you can omit the credentials file and add an authorized public key before building; see [Board access](palette-image-builder-reference.md#board-access). Root SSH remains key-only even when a root password is set. Existing boards may retain old credentials in their persistent overlay after an update.

## 5. Build and verify

When your project contains custom Debian packages, sign and verify them before
building the image:

```bash
pib sign-debs
pib verify-debs
pib build --sign
pib verify
```

The build creates a new root filesystem, applies the project inputs, generates
deployment artifacts, and signs and verifies the SWU. Results are written to
`out/`, alongside a package manifest, SBOM, and checksums.

## 6. Deploy and maintain

| Artifact | Deployment purpose |
|---|---|
| Signed `.swu` | Update a running board |
| `.img.gz` | Initial disk provisioning or recovery |

Prepare board access and establish trust in your CA before deployment. Follow the
[board access](palette-image-builder-reference.md#board-access) and
[SWU installation](palette-image-builder-reference.md#installing-an-swu) procedures;
a successful build does not change or qualify a board.

Validate the image on recoverable hardware. Retain its manifests, checksums, and
signing identity. Increase the image version for subsequent updates, and migrate
release-compatible inputs into a fresh project when changing platform releases.
See the [platform upgrade reference](palette-image-builder-reference.md#new-platform-release).

See [media and partition layout](palette-image-builder-reference.md#media-and-partition-layout) for boot partitions, rootfs slots, and data-volume allocation.

## Continue with the example or reference

- [Example Image](palette-image-builder-example.md): build the included application package, configuration, and service step by step.
- [Palette Image Builder Reference](palette-image-builder-reference.md): commands, customization rules, signing, troubleshooting, and board operations.
