# Build BSP Software

These are advanced BSP workflows for building kernel, U-Boot, and device-tree artifacts from inside the SDK container.

The examples use the `modalix` platform. Adapt the defconfig values for other supported platforms.

## Linux Kernel

Fetch the kernel source:

```bash
git clone https://github.com/SiMa-ai/simaai-linux.git
cd simaai-linux
```

Configure the kernel:

```bash
make ARCH=arm64 <platform-defconfig>
```

Supported `platform-defconfig` values:

- `simaai_modalix_defconfig`
- `simaai_davinci_defconfig`

Example:

```text
root@83a273303643:/data/simaai-linux# make ARCH=arm64 simaai_modalix_defconfig
...
#
# configuration written to .config
#
```

Build the kernel:

```bash
make all -j8 ARCH=arm64 LOCALVERSION="-modalix" DTC_FLAGS=-@
```

Generated artifacts:

- Kernel image: `arch/arm64/boot/Image`
- Device trees: `arch/arm64/boot/dts/simaai/*.dtb`

Example:

```text
root@83a273303643:/data/simaai-linux# make all -j8 ARCH=arm64 LOCALVERSION="-modalix" DTC_FLAGS=-@
...
NM      System.map
SORTTAB vmlinux
OBJCOPY arch/arm64/boot/Image
GZIP    arch/arm64/boot/Image.gz
```

## Overlay Device Tree

Create the device tree overlay file (`.dtso`) and build the overlay device tree blob (`.dtbo`):

```bash
dtc -@ -I dts -O dtb -o <dtbo-name> <dtso-name>
```

Example:

```text
root@83a273303643:/data# dtc -@ -I dts -O dtb -o imx415.dtbo imx415.dtso
```

## U-Boot

Fetch the U-Boot source:

```bash
git clone https://github.com/SiMa-ai/sima-ai-uboot.git
cd sima-ai-uboot
```

Configure U-Boot:

```bash
make ARCH=arm64 <platform-defconfig>
```

Supported `platform-defconfig` values:

- `simaai_modalix_debug_defconfig`
- `sima_davinci-a65_defconfig`

Example:

```text
root@83a273303643:/data/sima-ai-uboot# make ARCH=arm64 simaai_modalix_debug_defconfig
...
#
# configuration written to .config
#
```

Build U-Boot:

```bash
make all u-boot-initial-env V=1
```

Generated artifact:

- U-Boot image: `u-boot.bin`

Example:

```text
root@83a273303643:/data/sima-ai-uboot# make all u-boot-initial-env V=1
...
make -f ./scripts/Makefile.build obj=tools ./tools/printinitialenv
cc -Wp,-MD,tools/.printinitialenv.d -Wall -Wstrict-prototypes -O2 -fomit-frame-pointer -std=gnu11 -DCONFIG_FIT_SIGNATURE -DCONFIG_FIT_SIGNATURE_MAX_SIZE=0xffffffff -DCONFIG_FIT_CIPHER -include ./include/compiler.h -idirafterinclude -idirafter./arch/arm/include -idirafter./dts/upstream/include -I./scripts/dtc/libfdt -I./tools -DUSE_HOSTCC -D__KERNEL_STRICT_NAMES -D_GNU_SOURCE -o tools/printinitialenv tools/printinitialenv.c
./tools/printinitialenv | sed -e '/^\s*$/d' | sort -t '=' -k 1,1 -s -o u-boot-initial-env
```
