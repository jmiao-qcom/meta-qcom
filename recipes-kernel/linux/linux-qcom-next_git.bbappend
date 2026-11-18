# Keep ATH12K modular for the Eliza MTP QLI rootfs device probe.
FILESEXTRAPATHS:prepend := "${THISDIR}/linux-qcom-next:"
SRC_URI:append:eliza-mtp = " file://configs/eliza-mtp-ath12k-module.cfg"
