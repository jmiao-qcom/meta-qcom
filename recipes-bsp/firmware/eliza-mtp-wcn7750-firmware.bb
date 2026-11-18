SUMMARY = "Eliza MTP C1 runtime WCN7750 Q6 and ath12k firmware"
DESCRIPTION = "C1 1.5.C1-00056 WLAN.ORN.1.0-02666 WPSS/Q6 payload and Eliza board-id 0x18 ath12k resources"
PV = "1.0"
LICENSE = "CLOSED"
PACKAGE_ARCH = "${MACHINE_ARCH}"
COMPATIBLE_MACHINE = "^eliza-mtp$"
# Q6/WPSS and ORNE core images are firmware, not AArch64 rootfs executables.
INSANE_SKIP:${PN} += "arch"

SRC_URI = "file://eliza-mtp-wcn7750-firmware-c1-runtime.tar.gz"

# The archive carries only C1 runtime WPSS/Q6 files and the already-qualified
# C1 board-id-0x18 ATH12K inputs. Validate every file before installation.
do_install() {
    FW_SOURCE_DIR="${UNPACKDIR}"
    if [ ! -d "${FW_SOURCE_DIR}/wcn7750" ]; then
        FW_SOURCE_DIR="${WORKDIR}"
    fi

    cd "${FW_SOURCE_DIR}"
    sha256sum -c SHA256SUMS || bbfatal "Eliza C1 runtime WCN7750 input checksum failed"

    install -d ${D}${nonarch_base_libdir}/firmware/wcn7750
    install -d ${D}${nonarch_base_libdir}/firmware/ath12k/WCN7750/hw1.0

    for name in wpss.qdb wpss.mdt; do
        install -m 0644 "wcn7750/${name}" ${D}${nonarch_base_libdir}/firmware/wcn7750/${name}
    done
    for segment in 00 01 02 03 04 05 06 07 08 09 10 12; do
        name="wpss.b${segment}"
        install -m 0644 "wcn7750/${name}" ${D}${nonarch_base_libdir}/firmware/wcn7750/${name}
    done

    for name in \
        aux_ucode.bin \
        aux_ucode.elf \
        board-2.bin \
        m3.bin \
        phy_ucode.elf \
        qdss_trace_config_debug_v1.cfg \
        qdss_trace_config_perf_v1.cfg \
        regdb.bin; do
        install -m 0644 "ath12k/WCN7750/hw1.0/${name}" \
            ${D}${nonarch_base_libdir}/firmware/ath12k/WCN7750/hw1.0/${name}
    done
}

FILES:${PN} = " \
    ${nonarch_base_libdir}/firmware/wcn7750/* \
    ${nonarch_base_libdir}/firmware/ath12k/WCN7750/hw1.0/* \
"
