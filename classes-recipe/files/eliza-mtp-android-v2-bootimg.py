#!/usr/bin/env python3
"""Build and check the Android-v2 boot image used on Eliza MTP."""

from __future__ import annotations

import argparse
import hashlib
import gzip
import math
import pathlib
import re
import stat
import subprocess
import tempfile


SECTOR_SIZE = 4096
BOOT_A_BYTES = 100_663_296
DTB_LOAD_ADDRESS = 0x81F00000
RAMDISK_LOAD_ADDRESS = 0x81000000
EXPECTED_HEADLESS_RAMDISK_SHA256 = "101eba6fc04f5bfa7c37d84e2d31050cc6fcf577137e79be361ae4063b0b79a0"
ROOT_COMPATIBLE = 'compatible = "qcom,eliza-mtp", "qcom,eliza";'
SELECTORS = (
    '\n\tqcom,msm-id = <0x2dc 0x10000 0x2ae 0x10000 '
    '0x293 0x10000 0x2db 0x10000>;'
    '\n\tqcom,board-id = <0x20008 0x01>;'
)


def run(args: list[str]) -> str:
    result = subprocess.run(args, check=True, text=True, capture_output=True)
    return result.stdout


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def align4(value: int) -> int:
    return (value + 3) & ~3


def strip_newc_prefix(archive: bytes, prefix: str) -> tuple[bytes, list[tuple[str, int]]]:
    """Remove every entry under a path prefix from a newc CPIO archive."""
    output = bytearray()
    offset = 0
    removed: list[tuple[str, int]] = []
    saw_trailer = False

    while offset + 110 <= len(archive):
        header = archive[offset:offset + 110]
        magic = header[:6]
        if magic not in (b"070701", b"070702"):
            if not archive[offset:].strip(b"\0"):
                output.extend(archive[offset:])
                break
            raise SystemExit(f"unexpected CPIO header at offset {offset}: {magic!r}")

        fields = [int(header[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        file_size = fields[6]
        name_size = fields[11]
        name_start = offset + 110
        name_end = name_start + name_size
        data_start = align4(name_end)
        data_end = data_start + file_size
        record_end = align4(data_end)
        if name_size < 1 or name_end > len(archive) or record_end > len(archive):
            raise SystemExit(f"invalid CPIO record at offset {offset}")

        name_field = archive[name_start:name_end]
        if name_field[-1:] != b"\0":
            raise SystemExit(f"unterminated CPIO name at offset {offset}")
        name = name_field[:-1].decode("utf-8", errors="strict")
        normalized = name
        while normalized.startswith("./"):
            normalized = normalized[2:]

        if normalized == prefix or normalized.startswith(prefix + "/"):
            removed.append((name, file_size))
        else:
            output.extend(archive[offset:record_end])

        offset = record_end
        if name == "TRAILER!!!":
            output.extend(archive[offset:])
            saw_trailer = True
            break

    if not saw_trailer:
        raise SystemExit("CPIO archive has no TRAILER!!! entry")
    if not removed:
        raise SystemExit(f"expected entries under {prefix}, found none")
    return bytes(output), removed


def replace_newc_module(archive: bytes, module_suffix: str, replacement: bytes) -> tuple[bytes, str]:
    """Replace one regular file in a gzip-decoded newc CPIO archive."""
    output = bytearray()
    offset = 0
    replaced = 0
    old_hash = ""
    saw_trailer = False

    while offset + 110 <= len(archive):
        header = archive[offset:offset + 110]
        magic = header[:6]
        if magic not in (b"070701", b"070702"):
            if not archive[offset:].strip(b"\0"):
                output.extend(archive[offset:])
                break
            raise SystemExit(f"unexpected CPIO header at offset {offset}: {magic!r}")

        fields = [int(header[6 + 8 * i:14 + 8 * i], 16) for i in range(13)]
        file_size = fields[6]
        name_size = fields[11]
        name_start = offset + 110
        name_end = name_start + name_size
        data_start = align4(name_end)
        data_end = data_start + file_size
        record_end = align4(data_end)
        if name_size < 1 or name_end > len(archive) or record_end > len(archive):
            raise SystemExit(f"invalid CPIO record at offset {offset}")

        name_field = archive[name_start:name_end]
        if name_field[-1:] != b"\0":
            raise SystemExit(f"unterminated CPIO name at offset {offset}")
        name = name_field[:-1].decode("utf-8", errors="strict")
        file_data = archive[data_start:data_end]

        if name.endswith(module_suffix):
            if not stat.S_ISREG(fields[1]):
                raise SystemExit(f"CPIO target is not a regular file: {name}")
            replaced += 1
            if replaced > 1:
                raise SystemExit(f"multiple CPIO entries match {module_suffix}")
            old_hash = hashlib.sha256(file_data).hexdigest()
            fields[6] = len(replacement)
            if magic == b"070702":
                fields[12] = sum(replacement) & 0xFFFFFFFF
            new_header = magic + b"".join(f"{field:08x}".encode("ascii") for field in fields)
            record = bytearray(new_header)
            record.extend(name_field)
            record.extend(b"\0" * (align4(len(record)) - len(record)))
            record.extend(replacement)
            record.extend(b"\0" * (align4(len(record)) - len(record)))
            output.extend(record)
        else:
            output.extend(archive[offset:record_end])

        offset = record_end
        if name == "TRAILER!!!":
            output.extend(archive[offset:])
            saw_trailer = True
            break

    if not saw_trailer:
        raise SystemExit("CPIO archive has no TRAILER!!! entry")
    if replaced != 1:
        raise SystemExit(f"expected one CPIO entry ending in {module_suffix}, found {replaced}")
    return bytes(output), old_hash


def find_node_body(dts: str, name: str) -> tuple[int, int, str]:
    matches = list(re.finditer(rf"(?m)^([ \t]*){re.escape(name)}\s*\{{\s*$", dts))
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one {name} node, found {len(matches)}")
    opening = dts.find("{", matches[0].start())
    depth = 0
    quote = False
    escaped = False
    line_comment = False
    block_comment = False
    i = opening
    while i < len(dts):
        char = dts[i]
        next_char = dts[i + 1] if i + 1 < len(dts) else ""
        if line_comment:
            if char == "\n":
                line_comment = False
        elif block_comment:
            if char == "*" and next_char == "/":
                block_comment = False
                i += 1
        elif quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quote = False
        elif char == '"':
            quote = True
        elif char == "/" and next_char == "/":
            line_comment = True
            i += 1
        elif char == "/" and next_char == "*":
            block_comment = True
            i += 1
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return opening, i, dts[opening + 1:i]
        i += 1
    raise SystemExit(f"unterminated {name} node")


def main() -> None:
    parser = argparse.ArgumentParser()
    for name in ("kernel", "ramdisk", "dtb", "dtc", "mkbootimg", "unpack-bootimg", "tcsrcc-module", "output", "cmdline", "page-size", "base"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()

    kernel = pathlib.Path(args.kernel)
    ramdisk = pathlib.Path(args.ramdisk)
    dtb = pathlib.Path(args.dtb)
    tcsrcc_module = pathlib.Path(args.tcsrcc_module)
    output = pathlib.Path(args.output)
    tools = (pathlib.Path(args.dtc), pathlib.Path(args.mkbootimg), pathlib.Path(args.unpack_bootimg))
    for path in (kernel, ramdisk, dtb, tcsrcc_module, *tools):
        if not path.is_file():
            raise SystemExit(f"required input/tool is missing: {path}")
    if sha256(ramdisk) != EXPECTED_HEADLESS_RAMDISK_SHA256:
        raise SystemExit("Attempt-39 headless QLI ramdisk hash mismatch")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing image: {output}")
    if int(args.page_size, 0) != 2048:
        raise SystemExit(f"Eliza C1 ABL boot image requires 2048-byte pages, got {args.page_size}")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eliza-mtp-boot-v2-") as temp:
        work = pathlib.Path(temp)
        original_cpio = gzip.decompress(ramdisk.read_bytes())
        firmware_free_cpio, removed_firmware = strip_newc_prefix(original_cpio, "lib/firmware")
        removed_names = {name.removeprefix("./") for name, _ in removed_firmware}
        required_old_assets = {
            "lib/firmware/wcn7750/wpss.mdt",
            "lib/firmware/eliza/eliza_wcn_late_probe.ko",
            "lib/firmware/eliza/wifi-enable.dtbo",
        }
        missing_old_assets = required_old_assets - removed_names
        if missing_old_assets:
            raise SystemExit(f"pinned initramfs is missing expected temporary WLAN assets: {sorted(missing_old_assets)}")
        patched_cpio, old_tcsrcc_hash = replace_newc_module(
            firmware_free_cpio,
            "kernel/drivers/clk/qcom/tcsrcc-eliza.ko",
            tcsrcc_module.read_bytes(),
        )
        patched_ramdisk = work / "headless-ramdisk-matched.cpio.gz"
        patched_ramdisk.write_bytes(gzip.compress(patched_cpio, compresslevel=9, mtime=0))
        ramdisk_for_image = patched_ramdisk
        print(
            "ramdisk /lib/firmware removed: "
            f"{len(removed_firmware)} entries, {sum(size for _, size in removed_firmware)} file bytes"
        )
        print("ramdisk temporary Eliza helper KO and wifi-enable DTBO removed")
        print(f"ramdisk tcsrcc-eliza.ko old SHA256={old_tcsrcc_hash}")
        print(f"ramdisk tcsrcc-eliza.ko new SHA256={sha256(tcsrcc_module)}")
        print(f"matched ramdisk SHA256={sha256(patched_ramdisk)}")

        source_dts = work / "eliza-mtp.dts"
        selector_dts = work / "eliza-mtp-selector.dts"
        selector_dtb = work / "eliza-mtp-selector.dtb"
        unpack_dir = work / "unpacked"
        run([args.dtc, "-I", "dtb", "-O", "dts", "-o", str(source_dts), str(dtb)])
        dts = source_dts.read_text()
        if dts.count(ROOT_COMPATIBLE) != 1:
            raise SystemExit("expected exactly one C1 Eliza MTP root compatible")
        if "qcom,msm-id" in dts or "qcom,board-id" in dts:
            raise SystemExit("input DTB already has ABL selectors; refusing to duplicate")
        dts = dts.replace(ROOT_COMPATIBLE, ROOT_COMPATIBLE + SELECTORS, 1)
        selector_dts.write_text(dts)
        run([args.dtc, "-I", "dts", "-O", "dtb", "-o", str(selector_dtb), str(selector_dts)])

        cmd = [
            "python3", args.mkbootimg,
            "--header_version", "2",
            "--os_version", "0.0.0",
            "--kernel", str(kernel),
            "--ramdisk", str(ramdisk_for_image),
            "--dtb", str(selector_dtb),
            "--pagesize", args.page_size,
            "--base", args.base,
            "--kernel_offset", "0x8000",
            "--ramdisk_offset", "0x01000000",
            "--second_offset", "0",
            "--tags_offset", "0x100",
            "--dtb_offset", "0x01f00000",
            "--board", "",
            "--cmdline", args.cmdline,
            "--output", str(output),
        ]
        run(cmd)

        before_pad = output.stat().st_size
        padding = (-before_pad) % SECTOR_SIZE
        if padding:
            with output.open("ab") as stream:
                stream.write(b"\0" * padding)

        unpack_dir.mkdir()
        info = run([
            "python3", args.unpack_bootimg, "--boot_img", str(output),
            "--out", str(unpack_dir), "--format", "info",
        ])
        expected = (
            "boot image header version: 2",
            "page size: 2048",
            "kernel load address: 0x80008000",
            "ramdisk load address: 0x81000000",
            "dtb address: 0x0000000081f00000",
            args.cmdline,
        )
        if not all(value in info for value in expected):
            raise SystemExit("Android-v2 header/cmdline verification failed")
        for name, source in (("kernel", kernel), ("ramdisk", ramdisk_for_image), ("dtb", selector_dtb)):
            extracted = unpack_dir / name
            if not extracted.is_file() or sha256(extracted) != sha256(source):
                raise SystemExit(f"Android-v2 {name} payload did not round-trip")
        verify_dts = work / "verify.dts"
        run([args.dtc, "-I", "dtb", "-O", "dts", "-o", str(verify_dts), str(selector_dtb)])
        verified_dts = verify_dts.read_text()
        for property_name in ("qcom,msm-id", "qcom,board-id"):
            if verified_dts.count(property_name) != 1:
                raise SystemExit(f"selector DTB verification failed for {property_name}")
        _, _, verified_wifi = find_node_body(verified_dts, "wifi")
        if not re.search(r'(?m)^\s*status\s*=\s*"okay";', verified_wifi):
            raise SystemExit("selector DTB did not preserve the enabled Eliza WLAN host node")
        ramdisk_size = (unpack_dir / "ramdisk").stat().st_size
        if RAMDISK_LOAD_ADDRESS + ramdisk_size >= DTB_LOAD_ADDRESS:
            raise SystemExit("ramdisk overlaps the fixed DTB load address")
        selector_dtb_hash = sha256(selector_dtb)

    if output.stat().st_size > BOOT_A_BYTES:
        raise SystemExit("Android-v2 image exceeds the C1 boot_a partition")
    print(info.rstrip())
    print(f"boot image bytes={output.stat().st_size}")
    print(f"boot image sectors={math.ceil(output.stat().st_size / SECTOR_SIZE)}")
    print(f"boot image SHA256={sha256(output)}")
    print(f"C1 selector DTB SHA256={selector_dtb_hash}")


if __name__ == "__main__":
    main()
