# A targeted, non-GPT Eliza MTP QLI update bundle.
# SPDX-License-Identifier: BSD-3-Clause-Clear

FILESEXTRAPATHS:prepend:pn-qcom-multimedia-image := "${LAYERDIR_qcom}/classes-recipe/files:"
SRC_URI:append:pn-qcom-multimedia-image = " \
    file://eliza-mtp-android-v2-bootimg.py \
    file://eliza-mtp-qli-qcomflash.py \
    file://eliza-mtp-qli-headless-ramdisk-attempt39.cpio.gz;unpack=0 \
"

IMAGE_CMD:qcomflash = "create_eliza_mtp_qli_qcomflash_pkg"

python __anonymous () {
    if d.getVar("MACHINE") == "eliza-mtp" and d.getVar("PN") == "qcom-multimedia-image":
        d.delVarFlag("do_fetch", "noexec")
        d.delVarFlag("do_unpack", "noexec")
        d.appendVarFlag("do_image_qcomflash", "depends",
                        " %s:do_unpack" % d.getVar("PN"))
        d.appendVarFlag("do_image_qcomflash", "depends",
                        " android-tools-native:do_populate_sysroot dtc-native:do_populate_sysroot python3-native:do_populate_sysroot")
        d.appendVarFlag("do_image_qcomflash", "vardeps", " ELIZA_MTP_C1_FIREHOSE_DIR")
}

create_eliza_mtp_qli_qcomflash_pkg() {
    test -n "${ELIZA_MTP_C1_FIREHOSE_DIR}" || \
        bbfatal "ELIZA_MTP_C1_FIREHOSE_DIR must point to the C1 1.5.C1 UFS/FIREHOSE directory"

    eliza_mtp_initramfs="${UNPACKDIR}/eliza-mtp-qli-headless-ramdisk-attempt39.cpio.gz"
    test -f "$eliza_mtp_initramfs" || \
        bbfatal "cannot find the pinned Attempt-39 Eliza MTP QLI headless ramdisk"

    # The pinned headless ramdisk contains an older TCSRCC module and stale
    # temporary WLAN firmware/helper/DTBO files. The packager removes its whole
    # /lib/firmware tree and replaces TCSRCC with this image's matching module.
    tcsrcc_module="$(find "${IMAGE_ROOTFS}/usr/lib/modules" -type f \
        -path '*/kernel/drivers/clk/qcom/tcsrcc-eliza.ko' -print -quit)"
    test -n "$tcsrcc_module" || \
        bbfatal "cannot find the Eliza tcsrcc module in this image's matching kernel modules"

    ${STAGING_BINDIR_NATIVE}/python3-native/python3 ${UNPACKDIR}/eliza-mtp-android-v2-bootimg.py \
        --kernel "${DEPLOY_DIR_IMAGE}/Image.gz" \
        --ramdisk "$eliza_mtp_initramfs" \
        --tcsrcc-module "$tcsrcc_module" \
        --dtb "${DEPLOY_DIR_IMAGE}/eliza-mtp.dtb" \
        --dtc "${STAGING_BINDIR_NATIVE}/dtc" \
        --mkbootimg "${STAGING_BINDIR_NATIVE}/mkbootimg.py" \
        --unpack-bootimg "${STAGING_BINDIR_NATIVE}/unpack_bootimg.py" \
        --output "${QCOMFLASH_DIR}/boot.img" \
        --cmdline "${ELIZA_MTP_QLI_CMDLINE}" \
        --page-size "${QCOM_BOOTIMG_PAGE_SIZE}" \
        --base "${QCOM_BOOTIMG_KERNEL_BASE}"

    ${STAGING_BINDIR_NATIVE}/python3-native/python3 ${UNPACKDIR}/eliza-mtp-qli-qcomflash.py \
        --rootfs "${IMGDEPLOYDIR}/${IMAGE_LINK_NAME}.${IMAGE_QCOMFLASH_FS_TYPE}" \
        --boot "${QCOMFLASH_DIR}/boot.img" \
        --firehose-dir "${ELIZA_MTP_C1_FIREHOSE_DIR}" \
        --outdir "${QCOMFLASH_DIR}"
}
