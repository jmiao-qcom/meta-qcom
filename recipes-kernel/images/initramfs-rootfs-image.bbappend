# Eliza MTP stores rootfs on UFS. The UFS PHY needs the TCSR qref clock
# before the initramfs can discover and mount that rootfs.
PACKAGE_INSTALL:append:eliza-mtp = " kernel-module-tcsrcc-eliza"
