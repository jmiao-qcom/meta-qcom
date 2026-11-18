SUMMARY = "Eliza MTP debug-image adbd root bootstrap"
DESCRIPTION = "Writes the adbd root-state marker before the Eliza MTP debug-image service starts."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
SRC_URI = "file://90-adbd-root-debug.conf"
S = "${UNPACKDIR}"

inherit allarch

RDEPENDS:${PN} = "android-tools-adbd"

do_install() {
    install -D -m 0644 ${UNPACKDIR}/90-adbd-root-debug.conf \
        ${D}${sysconfdir}/systemd/system/android-tools-adbd.service.d/90-adbd-root-debug.conf
}

FILES:${PN} = "${sysconfdir}/systemd/system/android-tools-adbd.service.d/90-adbd-root-debug.conf"
