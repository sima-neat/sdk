<p align="center">
  <img src="images/simaai_logo.png" alt="SiMa.ai Logo" width="50%">
</p>

# SiMa.ai eLxr Software Development Kit (SDK) Manual

[![Build Docker Image](https://github.com/sima-neat/elxr-sdk/actions/workflows/docker-build.yml/badge.svg)](https://github.com/sima-neat/elxr-sdk/actions/workflows/docker-build.yml)

> This is a user guide for the SiMa.ai eLxr Board Support Package (BSP).

This repository provides a custom build of the Neat SDK for SiMa.ai platforms. It supports both `x86_64` and `arm64` host builds, prepares the sysroot with NEAT-required dependencies during Docker build, installs `sima-cli`, and remains compatible with the official eLxr SDK `2.0` release.

## About eLxr Project

> The eLxr project is a community-driven effort dedicated to broadening access to cutting-edge technologies for both enthusiasts and enterprise users seeking reliable and innovative solutions that scale from edge to cloud. The project produces and maintains an open source, enterprise-grade Debian-derivative distribution called eLxr that is easy for users to adopt and that fully honors the open source philosophy.
>
> The eLxr project's mission is centered on accessibility, innovation, and maintaining the integrity of open source software. Making these advancements in an enterprise-grade Debian-derivative ensures that users benefit from a freely available Linux distribution.
>
> By emphasizing ease of adoption alongside open source principles, eLxr aims to attract a broad range of users and contributors who value both innovation and community-driven development, fostering collaboration and transparency and the spread of new technologies.
>
> The eLxr project is establishing a robust strategy for building on Debian's ecosystem while also contributing back to it. Because "Debian citizens" contribute eLxr innovations and improvements upstream, they are actively participating in the community's development activities. This approach not only enhances eLxr's own distribution but also strengthens Debian by expanding its feature set and improving its overall quality.
>
> The ability to release technologies at various stages of Debian's development lifecycle and to introduce innovative new content not yet available in Debian highlights eLxr's agility and responsiveness to emerging needs. Moreover, the commitment to sustainability ensures that contributions made by eLxr members remain accessible and beneficial to the broader Debian community over the long term.[2]

## Terminology

| Term | Meaning |
| --- | --- |
| **MLSoC** | Machine Learning System-on-Chip |
| **SDK** | Software Development Kit |
| **BSP** | Board Support Package |
| **Docker** | A Linux container [3] |
| **Platform** | SiMa.ai MLSoC name, for example `modalix` or `davinci` |

## Assumptions

This manual assumes an `Ubuntu 22.04` host build machine and that the user is familiar with basic Linux commands and environment setup.

This project can run on either `aarch64` or `x86_64` host architectures. The build flow automatically adapts to the host machine type when using the provided build helper.

The examples shown in this manual use the `modalix` platform; however, the instructions can be applied to `davinci` with little or no modification.

At the time of artifacts installation, it is assumed that:

- The user has a SiMa.ai platform booted with an eLxr image and has root access.
- The platform board is reachable from the Docker container so artifacts can be copied over.
- The platform is booted with eMMC, enumerated as `mmcblk0` on Linux.

## SiMa.ai eLxr SDK

The eLxr build system is extended to build SiMa.ai Debian packages and images for SiMa.ai MLSoCs.

An SDK, also referred to as a BSP, is provided for customers to build their software and install it on a SiMa.ai MLSoC.

### SDK Docker

Along with this manual, SiMa.ai SDK Dockerfiles, one for each platform, are provided to create the SDK Docker container.

The SDK Docker image contains all toolchains, headers, libraries, and related dependencies needed to build software for the SiMa.ai platform.

CI-built `elxr` images are available for both `aarch64` and `x86_64` machine types.

### Building SDK Docker

#### Prerequisite

- Install the Docker engine on the host build machine.[4]
- Install `qemu-user-static` only if your workflow needs to execute non-native target binaries during cross-architecture builds. It is not required for the normal SDK image build when the container is built for the host's native architecture and only carries an `arm64` sysroot for cross-compilation.

```bash
sudo apt install qemu-user-static
```

#### Build Docker Image

- Build the SDK Docker image with the provided `build.sh` helper:

```bash
./build.sh
```

- By default, this builds the `elxr:latest` image.
- The local build workflow supports both `aarch64` and `x86_64` hosts and automatically selects the matching Docker platform for the current machine.
- A custom image name and tag can be provided:

```bash
./build.sh elxr 2.0.0
```

> A comma-separated package list can be provided to install additional packages into the sysroot during Docker build. Example:
>
> `SDK_PKG_LIST=libzix-dev,vxi-dev ./build.sh`

```text
Building elxr:latest
Host architecture: arm64
Docker platform: linux/arm64
```

### Launching SDK Docker

Use the helper script:

```bash
./run.sh
```

This will try to pull `ghcr.io/sima-neat/elxr:<tag>` from GitHub Packages first and fall back to a matching local image if present.

You can also use standard Docker commands directly:

```bash
docker pull ghcr.io/sima-neat/elxr:latest
docker run --rm -it --name elxr --privileged \
  -p 9900:9900 -p 9000-9079:9000-9079 -p 9100-9179:9100-9179 -p 8081:8081 -p 8554:8554 \
  -v "$(pwd):/workspace" -w /workspace -v /dev:/dev --pid=host \
  ghcr.io/sima-neat/elxr:latest /bin/bash -l
```

> Notes:
>
> - The sysroot is set up under `/opt/toolchain/aarch64/<platform>`.
> - `run.sh` mounts the current host directory into `/workspace` inside the container.
> - Although the build environment is automatically configured when the container launches, it can also be set manually:
>   `source /opt/bin/simaai-init-build-env <platform>`

### NEAT Insight

The SDK image installs `neat-insight` into `/opt/neat-insight/venv` and starts it automatically under `supervisord` when the container starts. By default it listens on port `9900`.

Useful commands inside the running container:

```bash
insight-admin status
insight-admin logs
insight-admin restart
insight-admin stop
```

To temporarily upgrade Insight inside an existing container:

```bash
insight-admin update main latest
insight-admin restart
```

That change only affects the current container. To make an Insight upgrade permanent, rebuild the SDK image with the desired channel and version:

```bash
NEAT_INSIGHT_BRANCH=main NEAT_INSIGHT_VERSION=latest ./build.sh elxr 2.0.0
```

### DevKit Workspace (NFS)

The workspace sharing flow is now NFS-based.

1. Start SDK container and configure host-side export:

```bash
./run.sh --prefer-local --devkit-ip 10.0.0.244
```

If the host IP selected for NFS is not reachable from the DevKit, provide the host interface IP explicitly:

```bash
./run.sh --prefer-local --devkit-ip 10.0.0.244 --hostip 10.0.0.10
```

2. Inside the container, source the setup helper:

```bash
source devkit.sh
```

This configures the remote DevKit mount, updates DevKit `/etc/fstab`, enables a watchdog timer for stale mount recovery, and sets Git `safe.directory` for the mounted workspace path.

During setup, `devkit.sh` also compares the SDK NEAT framework package versions cached under `${SYSROOT:-/opt/toolchain/aarch64/modalix}/neat-install-packages` with the versions installed on the DevKit. If the DevKit is missing NEAT framework packages or has different versions, the SDK copies its cached artifacts to the DevKit and runs the cached installer locally there.

Optional controls:

```bash
DEVKIT_NEAT_SYNC=OFF          # skip NEAT framework version check/sync
DEVKIT_NEAT_SYNC_REQUIRED=ON  # fail setup if NEAT framework sync fails
DEVKIT_NEAT_SYNC_CACHE_DIR=... # override SDK artifact cache directory
```

To open a direct SSH shell to the paired DevKit from inside the SDK container:

```bash
dk shell
```

## Build Software

### Linux Kernel

#### Fetching kernel source

```bash
git clone https://github.com/SiMa-ai/simaai-linux.git && cd simaai-linux
```

#### Configuring kernel

```bash
make ARCH=arm64 <platform-defconfig>
```

Supported `platform-defconfig` values:

- `simaai_modalix_defconfig`
- `simaai_davinci_defconfig`

```text
root@83a273303643:/data/simaai-linux# make ARCH=arm64 simaai_modalix_defconfig
...
...
#
# configuration written to .config
#
```

#### Building kernel

```bash
make all -j8 ARCH=arm64 LOCALVERSION="-modalix" DTC_FLAGS=-@
```

Generated artifacts:

- Kernel image: `arch/arm64/boot/Image`
- Device trees: `arch/arm64/boot/dts/simaai/*.dtb`

```text
root@83a273303643:/data/simaai-linux# make all -j8 ARCH=arm64 LOCALVERSION="-modalix" DTC_FLAGS=-@
...
...
NM      System.map
SORTTAB vmlinux
OBJCOPY arch/arm64/boot/Image
GZIP    arch/arm64/boot/Image.gz
```

### Overlay Device Tree

- Create the device tree overlay file (`.dtso`).
- Build the overlay device tree blob (`.dtbo`):

```bash
dtc -@ -I dts -O dtb -o <dtbo-name> <dtso-name>
```

```text
root@83a273303643:/data# dtc -@ -I dts -O dtb -o imx415.dtbo imx415.dtso
```

### U-Boot

#### Fetching U-Boot source

```bash
git clone https://github.com/SiMa-ai/sima-ai-uboot.git && cd sima-ai-uboot
```

#### Configuring U-Boot

```bash
make ARCH=arm64 <platform-defconfig>
```

Supported `platform-defconfig` values:

- `simaai_modalix_debug_defconfig`
- `sima_davinci-a65_defconfig`

```text
root@83a273303643:/data/sima-ai-uboot# make ARCH=arm64 simaai_modalix_debug_defconfig
...
...
#
# configuration written to .config
#
```

#### Building U-Boot

```bash
make all u-boot-initial-env V=1
```

Generated artifact:

- U-Boot image: `u-boot.bin`

```text
root@83a273303643:/data/sima-ai-uboot# make all u-boot-initial-env V=1
...
...
make -f ./scripts/Makefile.build obj=tools ./tools/printinitialenv
cc -Wp,-MD,tools/.printinitialenv.d -Wall -Wstrict-prototypes -O2 -fomit-frame-pointer -std=gnu11 -DCONFIG_FIT_SIGNATURE -DCONFIG_FIT_SIGNATURE_MAX_SIZE=0xffffffff -DCONFIG_FIT_CIPHER -include ./include/compiler.h -idirafterinclude -idirafter./arch/arm/include -idirafter./dts/upstream/include -I./scripts/dtc/libfdt -I./tools -DUSE_HOSTCC -D__KERNEL_STRICT_NAMES -D_GNU_SOURCE -o tools/printinitialenv tools/printinitialenv.c
./tools/printinitialenv | sed -e '/^\s*$/d' | sort -t '=' -k 1,1 -s -o u-boot-initial-env
```

## Install Artifacts

Artifacts to install:

- U-Boot image
- Linux kernel image
- Linux device trees
- Linux device tree overlays
- Linux kernel modules

> eMMC has four partitions:
>
> - `mmcblk0p1`: U-Boot primary
> - `mmcblk0p2`: U-Boot backup
> - `mmcblk0p3`: boot partition
> - `mmcblk0p4`: rootfs partition
>
> Partition 3 (`mmcblk0p3`) contains two boot directories, `boot-0` and `boot-1`. One is primary and one is backup.

### Copying U-Boot

- Secure-copy U-Boot onto the board from the Docker container.

```text
root@83a273303643:/data# pwd
/data
root@83a273303643:/data# scp sima-ai-uboot/u-boot.bin root@192.168.90.139:/tmp/
root@192.168.90.139's password:
u-boot.bin                                                            100% 1024KB      6.9MB/s   00:00
```

- Identify the U-Boot partition currently in use on the board:

```bash
parted /dev/mmcblk0 print | grep legacy_boot | cut -f2 -d" "
```

```text
root@modalix:~# parted /dev/mmcblk0 print | grep legacy_boot | cut -f2 -d" "
1
```

- Flash the new `u-boot.bin` to the currently used U-Boot partition:

```bash
dd if=/tmp/u-boot.bin of=/dev/mmcblk0p1 status=progress
sync
```

```text
root@modalix:~# dd if=/tmp/u-boot.bin of=/dev/mmcblk0p1 status=progress
2047+1 records in
2047+1 records out
1048560 bytes (1.0 MB, 1.0 MiB) copied, 0.0944332 s, 11.1 MB/s
root@modalix:~# sync
```

### Copying Kernel

- Determine the current boot directory on the boot partition:

```bash
strings /boot/uboot.env | grep boot_path= | cut -f2 -d"="
```

```text
root@modalix:~# strings /boot/uboot.env | grep boot_path= | cut -f2 -d"="
/boot-0/
```

#### Linux Kernel

- Copy the new kernel image to the boot directory (`/boot/<boot directory>`):

```text
root@83a273303643:/data# scp simaai-linux/arch/arm64/boot/Image root@192.168.90.139:/boot/boot-0/
root@192.168.90.139's password:
Image
```

#### Device trees

- Copy kernel device trees to the boot directory (`/boot/<boot directory>`):

```text
root@83a273303643:/data# scp simaai-linux/arch/arm64/boot/dts/simaai/modalix*.dtb root@192.168.90.139:/boot/boot-0/
root@192.168.90.139's password:
modalix-dvt.dtb                                                       100%  110KB     1.6MB/s   00:00
modalix-emulation-bench.dtb                                           100%  107KB   3.1MB/s   00:00
modalix-hhhl.dtb                                                      100%  110KB   4.1MB/s   00:00
modalix-som.dtb                                                       100%  108KB   3.2MB/s   00:00
modalix-vdk.dtb                                                       100%  108KB   3.6MB/s   00:00
```

#### Device Tree Overlays

- Copy kernel device tree overlays to the boot directory (`/boot/<boot directory>`):

```text
root@83a273303643:/data# scp imx415.dtbo root@192.168.90.139:/boot/boot-0/
root@192.168.90.139's password:
imx415.dtbo                                                        100%  895    41.9KB/s   00:00
```

#### Kernel Modules

- Copy required kernel modules to the appropriate rootfs partition modules directory, `/lib/modules/<kernel version string>/kernel/...`.
- Use `uname -a` to determine the kernel version string.

```text
root@83a273303643:/data# scp simaai-linux/drivers/net/phy/marvell10g.ko root@192.168.90.139:/lib/modules/6.1.22-modalix/kernel/drivers/net/phy/
root@192.168.90.139's password:
marvell10g.ko                                                         100%   24KB 722.7KB/s   00:00
```

### Post Install

```bash
depmod -a <kernel version string>
sync
reboot
```

```text
root@modalix:~# depmod -a 6.1.22-modalix
root@modalix:~# sync
root@modalix:~# reboot
```

If new overlays are added:

- Break into the U-Boot prompt.
- Add the new overlays to the `dtbos` variable and save the environment.
- Boot the platform.

```text
Hit any key to stop autoboot:  0
sima$ env set dtbos $dtbos imx415.dtbo
sima$ saveenv
Saving Environment to FAT... OK
sima$ boot
```

## References

- [1] <https://elxr.org/about>
- [2] <https://www.windriver.com/blog/Introducing-eLxr>
- [3] <https://www.docker.com/>
- [4] <https://docs.docker.com/engine/install/ubuntu/>
