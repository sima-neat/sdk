# Example Image

This walkthrough creates a signed Modalix image containing a small application,
a configuration file, and a service that starts automatically. The complete sample
ships in PIB; you do not need to clone this repository or install build tools on
your computer. The same image specification is tested on x86 and ARM64 in CI.

Install PIB using the [Custom Image Workflow](palette-image-builder.md#install-pib) before starting. This page focuses on the files and commands specific to the included example.

## 1. Copy the example into a project

```bash
pib init my-custom-image --example custom-image
cd my-custom-image
```

The files you will customize are:

| File | Purpose |
|---|---|
| `image.yaml` | Flavor, image version, packages, overlay, hooks, and signing settings |
| `package-root/usr/bin/pib-example-app` | Application installed by the example Debian package |
| `package-root/DEBIAN/control` | Package name, version, and architecture |
| `overlay/etc/pib-example.conf` | Application configuration copied into the image |
| `overlay/etc/systemd/system/pib-example.service` | Service definition |
| `hooks/enable-example.sh` | Enables the service and writes a build marker |

For a Linux shell inside the container, run:

```bash
pib shell
```

Your project is mounted at `/workspace`. Run `exit` to return to your computer.
The remaining commands in this walkthrough run from the project directory on
your computer; each `pib` command starts the container automatically.

## 2. Create your development signing identity

```bash
pib keys init --cn 'My Company Development'
```

This creates a CA, an SWU signing certificate and private key, and the signing
identity for your custom Debian packages. Move `keys/ca.key` to a secure location
outside the project after setup. Keep the same CA when updating existing boards.
Use your organization's production signing process for shipping images.

## 3. Package and sign the application

Build the package inside PIB, then sign and verify it:

```bash
pib shell -c 'dpkg-deb --root-owner-group --build package-root custom-debs/pib-example-app_1.0.0_all.deb'
pib sign-debs
pib verify-debs
```

The application is a shell script, so the package uses architecture `all`. A
compiled Modalix application must be built for `arm64`, normally using the SDK.
PIB accepts ARM64 or architecture-independent packages; it does not cross-compile
application source code.

## 4. Review the image specification

The example includes these customization settings:

```yaml
base: minimal
target: modalix
slots: ab
release: 3.0.0
version: 3.0.0.1
vendor: PIB Example
packages:
  add: [pib-example-app]
  remove: []
overlay: overlay/
hooks: [hooks/enable-example.sh]
signing:
  ca: keys/ca.crt
  cert: keys/swu-signing.crt
  key: keys/swu-signing.key
debs:
  key: keys/debs-signing.asc
```

The package list uses the Debian package name, not the `.deb` filename. Change
`overlay/etc/pib-example.conf` in your editor to try your own configuration. The
hook enables the sample service after package installation.

The image version must match the container's platform release followed by a build
number, for example `3.0.0.1`. Increase the final number for your next image:
boards enforce the image's no-downgrade policy.

## 5. Build, sign, and verify the image

```bash
pib build --sign --supplier 'My Company'
pib verify
```

The first command assembles a new root filesystem, installs the application,
applies your overlay and hook, creates the deployment artifacts, signs the SWU,
and verifies it. The second command demonstrates standalone verification using
the project's default CA and the adjacent build manifest.

## 6. Find the outputs

Open the project's `out/` directory:

| Output | How to use it |
|---|---|
| `*.swu` | Signed software update for a running board |
| `*.img.gz` | Full disk image for initial provisioning or recovery |
| `*.manifest.json` | Installed package versions, origins, and build identity |
| `*.cdx.json` | Software bill of materials |
| `SHA256SUMS` | Artifact checksums |

An SWU and a full disk image are different deployment formats. Follow the
[board update reference](palette-image-builder-reference.md#installing-an-swu)
for SWU installation and initial CA trust. Use the Modalix provisioning procedure
for a full disk image. Qualify your image on a development board before production.

## 7. Check the example's behavior

The package installs `/usr/bin/pib-example-app`. The overlay supplies its
configuration and `pib-example.service`. The post-install hook enables that
service for `multi-user.target` and writes `/etc/pib-example-build` into the image.

After installing the image on a development board using the
[board update reference](palette-image-builder-reference.md#installing-an-swu),
run these commands **on the board**:

```bash
sudo systemctl status pib-example.service --no-pager
sudo journalctl -u pib-example.service --no-pager
cat /etc/pib-example-build
```

The service is a one-shot application, so a successful run remains active with
an exited process. Its journal includes `Hello from the custom PIB image.` and
the contents of `/etc/pib-example.conf`. The build marker contains
`PIB example post-install hook`.

CI checks the sample's packaged files, configuration, service enablement, build
marker, and signed SWU payload on both builder architectures. These board-side
checks additionally confirm startup behavior on your hardware.
