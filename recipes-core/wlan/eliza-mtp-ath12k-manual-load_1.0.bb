SUMMARY = "Eliza MTP manual ATH12K loading policy"
DESCRIPTION = "Prevents modalias-driven ATH12K loading so Eliza MTP bring-up can insert matching modules explicitly."
LICENSE = "MIT"
LIC_FILES_CHKSUM = "file://${COMMON_LICENSE_DIR}/MIT;md5=0835ade698e0bcf8506ecda2f7b4f302"

FILESEXTRAPATHS:prepend := "${THISDIR}/${PN}:"
SRC_URI = "file://ath12k-manual-load.conf"
S = "${UNPACKDIR}"

inherit allarch

do_install() {
	install -D -m 0644 ${UNPACKDIR}/ath12k-manual-load.conf \
		${D}${sysconfdir}/modprobe.d/ath12k-manual-load.conf
}

FILES:${PN} = "${sysconfdir}/modprobe.d/ath12k-manual-load.conf"
