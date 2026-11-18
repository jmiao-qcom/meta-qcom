#!/usr/bin/env python3
"""Create the C1-matched Eliza MTP QLI update bundle without touching GPT."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import shutil
import xml.etree.ElementTree as ET


SECTOR_SIZE = 4096
PROGRAMMER_NAME = "xbl_s_devprg_ns.melf"
PROGRAMMER_SHA256 = "86856254f8d4b8a921ac8d64e07938f4d99c38b3213d6d197fb14f4e8ad988eb"

PARTITIONS = {
    "system_a": {
        "lun": 0,
        "start_sector": 8712,
        "capacity_sectors": 1_048_576,
        "payload": "rootfs.img",
        "rawprogram": "rawprogram0.xml",
    },
    "boot_a": {
        "lun": 4,
        "start_sector": 142374,
        "capacity_sectors": 24_576,
        "payload": "boot.img",
        "rawprogram": "rawprogram4.xml",
    },
}


def sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def link_or_copy(source: pathlib.Path, destination: pathlib.Path) -> None:
    try:
        os.link(source, destination)
    except OSError:
        shutil.copy2(source, destination)


def write_rawprogram(path: pathlib.Path, label: str, source: pathlib.Path) -> dict[str, int | str]:
    mapping = PARTITIONS[label]
    size = source.stat().st_size
    if size == 0 or size % SECTOR_SIZE:
        raise SystemExit(f"{label} payload is not a non-empty 4096-byte-sector-aligned file")
    sectors = size // SECTOR_SIZE
    if sectors > mapping["capacity_sectors"]:
        raise SystemExit(f"{label} payload exceeds the C1 partition capacity")
    root = ET.Element("data")
    ET.SubElement(root, "program", {
        "SECTOR_SIZE_IN_BYTES": str(SECTOR_SIZE),
        "file_sector_offset": "0",
        "filename": mapping["payload"],
        "label": label,
        "num_partition_sectors": str(sectors),
        "partofsingleimage": "false",
        "physical_partition_number": str(mapping["lun"]),
        "readbackverify": "false",
        "size_in_KB": f"{size / 1024:.1f}",
        "sparse": "false",
        "start_sector": str(mapping["start_sector"]),
    })
    ET.indent(root, space="  ")
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n")
    return {
        "lun": mapping["lun"],
        "start_sector": mapping["start_sector"],
        "sector_count": sectors,
        "size_bytes": size,
        "sha256": sha256(source),
    }


def write_bootable_lun_select(path: pathlib.Path) -> None:
    # QDL v2.8 treats the empty-filename xbl_a label as a bootable-LU
    # selection request. It sends setbootablestoragedrive(value=1) and no
    # xbl_a partition bytes.
    root = ET.Element("data")
    ET.SubElement(root, "program", {
        "start_sector": "6",
        "size_in_KB": "3584.0",
        "physical_partition_number": "1",
        "partofsingleimage": "false",
        "file_sector_offset": "0",
        "num_partition_sectors": "896",
        "readbackverify": "false",
        "filename": "",
        "sparse": "false",
        "start_byte_hex": "0x6000",
        "SECTOR_SIZE_IN_BYTES": str(SECTOR_SIZE),
        "label": "xbl_a",
    })
    ET.indent(root, space="  ")
    path.write_text('<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rootfs", required=True, type=pathlib.Path)
    parser.add_argument("--boot", required=True, type=pathlib.Path)
    parser.add_argument("--firehose-dir", required=True, type=pathlib.Path)
    parser.add_argument("--outdir", required=True, type=pathlib.Path)
    args = parser.parse_args()

    programmer = args.firehose_dir / PROGRAMMER_NAME
    if not args.rootfs.is_file() or not args.boot.is_file() or not programmer.is_file():
        raise SystemExit("missing rootfs, Android-v2 boot image, or C1 programmer")
    programmer_hash = sha256(programmer)
    if programmer_hash != PROGRAMMER_SHA256:
        raise SystemExit(f"C1 programmer SHA256 mismatch: {programmer_hash}")
    args.outdir.mkdir(parents=True, exist_ok=True)

    rootfs_dest = args.outdir / PARTITIONS["system_a"]["payload"]
    boot_dest = args.outdir / PARTITIONS["boot_a"]["payload"]
    programmer_dest = args.outdir / PROGRAMMER_NAME
    boot_is_staged = args.boot.resolve() == boot_dest.resolve() and boot_dest.is_file()
    existing = {entry.name for entry in args.outdir.iterdir()}
    if existing != ({"boot.img"} if boot_is_staged else set()):
        raise SystemExit(f"refusing to mix with existing package contents: {sorted(existing)}")
    link_or_copy(args.rootfs, rootfs_dest)
    if not boot_is_staged:
        link_or_copy(args.boot, boot_dest)
    shutil.copy2(programmer, programmer_dest)

    programmed = {
        "system_a": write_rawprogram(args.outdir / "rawprogram0.xml", "system_a", rootfs_dest),
        "boot_a": write_rawprogram(args.outdir / "rawprogram4.xml", "boot_a", boot_dest),
    }
    write_bootable_lun_select(args.outdir / "rawprogram1.xml")
    manifest = {
        "board": "Eliza MTP / CQ7790M Meta",
        "source_build": "CQ7790M.LE.1.5.C1-00056",
        "storage": "UFS",
        "sector_size_bytes": SECTOR_SIZE,
        "programmer": {"filename": PROGRAMMER_NAME, "sha256": programmer_hash},
        "programmed_partitions": programmed,
        "boot_selection": {
            "partition_label": "xbl_a",
            "selected_drive": 1,
            "payload_written": False,
        },
        "gpt_written": False,
        "dtbo_written": False,
        "boot_chain_written": False,
    }
    (args.outdir / "eliza-mtp-qli-update.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    )

    expected = {
        PROGRAMMER_NAME, "rootfs.img", "boot.img", "rawprogram0.xml",
        "rawprogram1.xml", "rawprogram4.xml", "eliza-mtp-qli-update.json",
    }
    actual = {entry.name for entry in args.outdir.iterdir()}
    if actual != expected:
        raise SystemExit(f"unexpected package file set: {sorted(actual ^ expected)}")
    for filename in ("rawprogram0.xml", "rawprogram4.xml"):
        tree = ET.parse(args.outdir / filename)
        programs = tree.getroot().findall("program")
        if len(programs) != 1 or programs[0].get("filename") not in {"rootfs.img", "boot.img"}:
            raise SystemExit(f"invalid scoped update XML: {filename}")
        if programs[0].get("SECTOR_SIZE_IN_BYTES") != str(SECTOR_SIZE):
            raise SystemExit(f"wrong sector size in {filename}")
    select_xml = ET.parse(args.outdir / "rawprogram1.xml").getroot().findall("program")
    if len(select_xml) != 1 or select_xml[0].get("label") != "xbl_a" or select_xml[0].get("filename") != "":
        raise SystemExit("rawprogram1.xml must select UFS boot drive 1 without a payload")
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
