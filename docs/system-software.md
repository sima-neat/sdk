# Work with lower-level system software

This guide is for system engineers preparing BSP software for a Modalix image.
Use the Palette SDK toolchain to work with kernel and device-tree sources, then
use PIB to assemble release-compatible packages into an image. Application APIs
and application-development tutorials are at
[developer.sima.ai/software](https://developer.sima.ai/software).

## Start from a compatible BSP release

Use the vendor source revision and configuration that match your target platform
release. A repository's default branch is not necessarily the source for the
image you are maintaining. Keep source revisions, configuration changes, and
package versions in your release records.

Run the following build commands inside the Palette SDK container, with its
ARM64 cross-toolchain environment configured. Source retrieval is shown below;
select the appropriate release revision before configuring or building.

## Configure and build the kernel

```bash
git clone https://github.com/SiMa-ai/simaai-linux.git
cd simaai-linux
make ARCH=arm64 simaai_modalix_defconfig
make all -j8 ARCH=arm64 LOCALVERSION="-modalix" DTC_FLAGS=-@
```

The kernel image is produced at `arch/arm64/boot/Image`. Platform device trees
are under `arch/arm64/boot/dts/simaai/`. Record the configuration and source
revision you used.

These are build artifacts, not a complete PIB-compatible kernel package. Use the
platform's supported Debian packaging process so the required boot files,
package scripts, and release integration are retained.

## Compile a device-tree overlay

```bash
dtc -@ -I dts -O dtb -o imx415.dtbo imx415.dtso
```

Replace the example filenames with your overlay. Validate the hardware bindings
and peripheral behavior on your development board. Package or install the overlay
using your platform release's supported boot configuration; copying a `.dtbo`
alone does not enable it automatically.

## Understand the boot-chain boundary

The image includes kernel, U-Boot, ATF, and tRoot components that must remain
compatible. In the current PIB workflow, a custom kernel must keep the release's
kernel package name and be the only installed kernel. Find the name in
`configs/images/image-params.yaml`.

PIB rejects local replacement packages for tRoot, ATF, and U-Boot. The U-Boot in
the image must match the copy embedded in `fip.bin`. Building a `u-boot.bin` is not
authorization or a supported procedure to overwrite boot firmware. Coordinate
boot-chain changes with the platform supplier and its recovery/signing process.

The `securepalette` flavor adds kernel FIT signature checks and requires
production-signed boot packages for shipping. Its secure-boot hardware behavior
is separate from the minimal-image CI qualification.

## Package system changes with PIB

Place release-compatible ARM64 Debian packages in `custom-debs/`, sign them with
your package identity, and build the image:

```bash
pib sign-debs
pib verify-debs
pib build --sign
pib verify
```

Use `image.yaml` to list additional package names, `overlay/` for configuration,
and post-install hooks for service enablement or other final changes. The
[PIB reference](palette-image-builder-reference.md#customization) explains the
kernel and package rules in more detail.

Retain manifests and checksums, test the resulting image on a recoverable
development board, and validate the peripherals and update/rollback behavior
affected by your changes. A successful artifact build does not establish hardware
compatibility.
