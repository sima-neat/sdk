# Palette SDK System Stack

The Palette SDK provides the tools to build software for Modalix. Palette Image
Builder (PIB) assembles that software into a custom eLxr operating-system image.
They are separate containers: use the Palette SDK toolchain to prepare target
software and PIB to assemble the device image. This guide is for system engineers
working on image packaging and the lower-level software stack. For application
APIs and application-development workflows, visit
[developer.sima.ai/software](https://developer.sima.ai/software).

SDK setup also installs a version-compatible **Model Compiler extension** using
the SDK compatibility catalog. It can be skipped when not needed. The extension
compiles model artifacts; the SDK toolchain builds the application that uses them,
and PIB packages the deployable software into a system image.

[![Palette SDK system stack: SDK development tools and Model Compiler extension supply software to the separate PIB companion, which creates images for a Modalix DevKit.](../images/palette-sdk-system-stack.svg#gh-light-mode-only)](../images/palette-sdk-system-stack.svg)

[![Palette SDK system stack: SDK development tools and Model Compiler extension supply software to the separate PIB companion, which creates images for a Modalix DevKit.](../images/palette-sdk-system-stack-dark.svg#gh-dark-mode-only)](../images/palette-sdk-system-stack-dark.svg)

## What runs where

| Component | Runs on | Responsibility |
|---|---|---|
| sima-cli | Your computer | Installs packages and starts or configures the development environment |
| Palette SDK container | Docker on your computer | Cross-compiles applications against the ARM64 sysroot and provides development tools |
| Model Compiler extension | Your development environment, installed during SDK setup | Compiles models for Modalix acceleration |
| PIB container | Docker on your computer | Builds root filesystems, packages, disk images, and signed SWU updates from your image specification |
| Modalix DevKit | The target device | Runs the ARM64 application and the installed eLxr image |

Both SDK and PIB have native x86 and ARM64 container variants. Docker selects the
variant for your host. The target application and device image remain ARM64.
PIB uses ARM64 emulation automatically when assembling an image on an x86 host.

## Open the SDK development environment

Install Palette SDK and configure your development environment:

```bash
sima-cli neat install sdk
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

## How software reaches the device

Use the SDK toolchain to build applications against the Modalix ARM64 sysroot.
The Model Compiler extension produces the compiled model artifacts used by those
applications. Package the application, model assets, and required files as Debian
packages with architecture `arm64`; architecture-independent scripts can use `all`.

PIB consumes those packages together with an image specification, configuration
overlay, hooks, and signing identity. It creates a signed `.swu` for updates and an
`.img.gz` for initial provisioning or recovery. Building an application container
alone does not create either system-image artifact. PIB can run independently of
the SDK container.

Follow [Custom Image Workflow](palette-image-builder.md) for the general process,
or [Example Image](palette-image-builder-example.md) for the complete sample recipe.

## Keep toolchain, image, and board versions aligned

The container's platform release determines the compatible image inputs. PIB
rejects a project for a different platform release. The image version adds a
numeric build number, such as `3.0.0.1`, and is used by the update policy.

Retain the build manifest, SBOM, checksums, and signing identity alongside each
release. These identify what was shipped and allow subsequent updates to remain
under the same trusted CA. Signing keys are not embedded in the published builder
container.

## Choose the right next step

- To create a first image, follow the [Custom Image Workflow](palette-image-builder.md).
- To build the working application example, follow the [Example Image](palette-image-builder-example.md).
- For custom kernels, external signing identities, and board updates, use the [Palette Image Builder Reference](palette-image-builder-reference.md).
