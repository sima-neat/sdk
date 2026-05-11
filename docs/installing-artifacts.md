# Install BSP Artifacts On A Board

These are advanced BSP workflows for manually installing generated artifacts on a SiMa.ai platform.

## Assumptions

- The board is booted with an eLxr image.
- You have root access to the board.
- The board is reachable from the SDK container.
- The board is booted from eMMC, enumerated as `mmcblk0` on Linux.

## Artifacts

Artifacts to install:

- U-Boot image
- Linux kernel image
- Linux device trees
- Linux device tree overlays
- Linux kernel modules

eMMC has four partitions:

- `mmcblk0p1`: U-Boot primary
- `mmcblk0p2`: U-Boot backup
- `mmcblk0p3`: boot partition
- `mmcblk0p4`: rootfs partition

Partition 3 (`mmcblk0p3`) contains two boot directories, `boot-0` and `boot-1`. One is primary and one is backup.

## Copy U-Boot

Secure-copy U-Boot onto the board from the SDK container:

```text
root@83a273303643:/data# pwd
/data
root@83a273303643:/data# scp sima-ai-uboot/u-boot.bin root@192.168.90.139:/tmp/
root@192.168.90.139's password:
u-boot.bin                                                            100% 1024KB      6.9MB/s   00:00
```

Identify the U-Boot partition currently in use on the board:

```bash
parted /dev/mmcblk0 print | grep legacy_boot | cut -f2 -d" "
```

Example:

```text
root@modalix:~# parted /dev/mmcblk0 print | grep legacy_boot | cut -f2 -d" "
1
```

Flash the new `u-boot.bin` to the currently used U-Boot partition:

```bash
dd if=/tmp/u-boot.bin of=/dev/mmcblk0p1 status=progress
sync
```

Example:

```text
root@modalix:~# dd if=/tmp/u-boot.bin of=/dev/mmcblk0p1 status=progress
2047+1 records in
2047+1 records out
1048560 bytes (1.0 MB, 1.0 MiB) copied, 0.0944332 s, 11.1 MB/s
root@modalix:~# sync
```

## Copy Kernel Artifacts

Determine the current boot directory on the boot partition:

```bash
strings /boot/uboot.env | grep boot_path= | cut -f2 -d"="
```

Example:

```text
root@modalix:~# strings /boot/uboot.env | grep boot_path= | cut -f2 -d"="
/boot-0/
```

Copy the new kernel image to the boot directory:

```text
root@83a273303643:/data# scp simaai-linux/arch/arm64/boot/Image root@192.168.90.139:/boot/boot-0/
root@192.168.90.139's password:
Image
```

Copy kernel device trees to the boot directory:

```text
root@83a273303643:/data# scp simaai-linux/arch/arm64/boot/dts/simaai/modalix*.dtb root@192.168.90.139:/boot/boot-0/
root@192.168.90.139's password:
modalix-dvt.dtb                                                       100%  110KB     1.6MB/s   00:00
modalix-emulation-bench.dtb                                           100%  107KB   3.1MB/s   00:00
modalix-hhhl.dtb                                                      100%  110KB   4.1MB/s   00:00
modalix-som.dtb                                                       100%  108KB   3.2MB/s   00:00
modalix-vdk.dtb                                                       100%  108KB   3.6MB/s   00:00
```

Copy kernel device tree overlays to the boot directory:

```text
root@83a273303643:/data# scp imx415.dtbo root@192.168.90.139:/boot/boot-0/
root@192.168.90.139's password:
imx415.dtbo                                                        100%  895    41.9KB/s   00:00
```

## Copy Kernel Modules

Copy required kernel modules to the appropriate rootfs partition modules directory:

```text
/lib/modules/<kernel version string>/kernel/...
```

Use `uname -a` to determine the kernel version string.

Example:

```text
root@83a273303643:/data# scp simaai-linux/drivers/net/phy/marvell10g.ko root@192.168.90.139:/lib/modules/6.1.22-modalix/kernel/drivers/net/phy/
root@192.168.90.139's password:
marvell10g.ko                                                         100%   24KB 722.7KB/s   00:00
```

## Post Install

```bash
depmod -a <kernel version string>
sync
reboot
```

Example:

```text
root@modalix:~# depmod -a 6.1.22-modalix
root@modalix:~# sync
root@modalix:~# reboot
```

If new overlays are added:

1. Break into the U-Boot prompt.
2. Add the new overlays to the `dtbos` variable and save the environment.
3. Boot the platform.

```text
Hit any key to stop autoboot:  0
sima$ env set dtbos $dtbos imx415.dtbo
sima$ saveenv
Saving Environment to FAT... OK
sima$ boot
```
