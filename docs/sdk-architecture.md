# Understand the Palette SDK system stack

The Palette SDK provides the tools to build software for Modalix. Palette Image
Builder (PIB) assembles that software into a custom eLxr operating-system image.
They are separate containers: use the Palette SDK toolchain to prepare target
software and PIB to assemble the device image. This guide is for system engineers
working on image packaging and the lower-level software stack. For application
APIs and application-development workflows, visit
[developer.sima.ai/software](https://developer.sima.ai/software).

## What runs where

| Component | Runs on | Responsibility |
|---|---|---|
| sima-cli | Your computer | Installs packages and starts or configures the development environment |
| Palette SDK container | Docker on your computer | Cross-compiles applications against the ARM64 sysroot and provides development tools |
| PIB container | Docker on your computer | Builds root filesystems, packages, disk images, and signed SWU updates from your image specification |
| Modalix DevKit | The target device | Runs the ARM64 application and the installed eLxr image |

Both SDK and PIB have native x86 and ARM64 container variants. Docker selects the
variant for your host. The target application and device image remain ARM64.
PIB uses ARM64 emulation automatically when assembling an image on an x86 host.

## Open the system software toolchain

Install Palette SDK and configure your system-software development environment:

```bash
sima-cli neat install sdk@develop
sima-cli sdk setup
sima-cli sdk neat
```

To pair with a DevKit during setup, provide its address:

```bash
sima-cli sdk setup --devkit 192.0.2.10
```

Replace the example address with your DevKit's address. Pairing is optional for
building software; it is useful for deploying and testing on hardware.

The SDK contains the cross-toolchain, target sysroot, headers, libraries, and
development helpers. Your workspace is mounted into the container at `/workspace`
so you can edit files on your computer and build inside the SDK.

## Package the result for your image

Build against the Modalix ARM64 sysroot. Package the resulting application and its
required files as a Debian package with architecture `arm64`. Scripts and other
architecture-independent content may use architecture `all`.

An application container and a device operating-system image serve different
purposes. Building an application Docker image does not create an SWU or replace
the board's eLxr root filesystem.

## Assemble a device image with PIB

Install PIB independently:

```bash
sima-cli neat install sdk/pib
pib doctor
pib init my-image --flavor minimal
cd my-image
```

Your project combines:

- `image.yaml` to select the flavor, version, packages, and signing identity.
- `custom-debs/` for your signed ARM64 or architecture-independent packages.
- `overlay/` for configuration and other root-owned files.
- `hooks/` for changes that must happen after package installation.
- `keys/` for the signing identity and public trust material.

PIB downloads packages from the configured repositories and constructs a new root
filesystem. It creates a signed `.swu` for updates and an `.img.gz` for full-disk
provisioning or recovery. It does not require the main SDK container to be running.

Start with the [complete custom-image example](palette-image-builder-example.md)
to see application packaging, a service, and a post-install hook together.

## Keep toolchain, image, and board versions aligned

The container's platform release determines the compatible image inputs. PIB
rejects a project for a different platform release. The image version adds a
numeric build number, such as `3.0.0.1`, and is used by the update policy.

Retain the build manifest, SBOM, checksums, and signing identity alongside each
release. These identify what was shipped and allow subsequent updates to remain
under the same trusted CA. Signing keys are not embedded in the published builder
container.

## Choose the right next step

- To create a first image, follow the [PIB getting-started guide](palette-image-builder.md).
- To build the working application example, follow the [sample walkthrough](palette-image-builder-example.md).
- For custom kernels, external signing identities, and board updates, use the [PIB reference](palette-image-builder-reference.md).
