#!/usr/bin/env python3
"""Check that an Acorn runs the expected fpgas.online image and holds the expected images in its flash.

Runs on every boot of a Pi with an Acorn on PCIe (fpgas-acorn-verify.service), and on demand. Three tiers:

  1. PCI IDs, from sysfs: which image family is running. The fpgas.online SoC is LitePCIe's 10ee:7021 with
     the board named in the subsystem IDs; SQRL's factory image and the vendor XDMA sample are recognised and
     reported as unconverted. Nothing past this tier runs against a design we did not build: its BAR0 has a
     register layout we do not know.
  2. The SoC's identifier string, over BAR0: which build is running. It carries the build timestamp, so it
     names one image exactly. It must be the operational or golden build of the installed release; the
     golden one means the operational slot did not boot (degraded).
  3. The flash, over BAR0 through spi_flash.py (read opcodes only): the golden slot (0x000000) and the
     operational slot (0x400000) are compared with the images the release puts there.

Nothing is ever written to the flash or reconfigured: a board that fails is reported, not repaired. The
images and manifest come from the fpgas-online-acorn-bitstreams package; each installed file is checked
against the manifest's sha256 before it is trusted. The result is written as JSON to /run, printed, and
published as a fleet-event `fpga-verified` stage, and the exit status is 0 only for "pass" and "none" (no
FPGA on PCIe), so a failure also shows as a failed unit.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.

    sudo fpgas-acorn-verify              # check, report, publish
    sudo fpgas-acorn-verify --no-publish --report -
"""

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import importlib.util
import json
import mmap
import os
import pathlib
import struct
import subprocess
import sys

_HERE = pathlib.Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("spi_flash", _HERE / "spi_flash.py")
spi_flash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spi_flash)

SCHEMA_VERSION = 1
SYSFS_PCI = pathlib.Path("/sys/bus/pci/devices")
IMAGES = pathlib.Path("/usr/share/fpgas-online/acorn-pcie/images")
REPORT = pathlib.Path("/run/fpgas-online/acorn-verify.json")
LOCK = pathlib.Path("/run/lock/fpgas-acorn.lock")

CSR_BASE = spi_flash.CSR_BASE
IDENTIFIER_BASE = CSR_BASE + 0x800  # csr_map: identifier_mem = 1
IDENTIFIER_MAX = 256
# The CSR bases this tool and spi_flash.py drive. A build whose csr.json says otherwise is not read.
CSR_EXPECTED = {"identifier_mem": IDENTIFIER_BASE, "flash": spi_flash.SPI_CONTROL, "flash_cs_n": spi_flash.FLASH_CS_N}
BAR0_SIZE = 0x10000

XILINX, SQRL = 0x10EE, 0x1E24
LITEPCIE_X1, VENDOR_XDMA = 0x7021, 0x7011
# designs/acorn-pcie/gateware/acorn_pcie_soc.py PCIE_SUBSYSTEM_*: tests/test_acorn_verify.py holds them equal.
OUR_SUBSYSTEMS = {(SQRL, 0x021F): "cle-215+", (SQRL, 0x0101): "cle-101"}
# SQRL's factory images use these as their own vendor:device, with the subsystem left at 0000:0000.
SQRL_FACTORY = {0x021F: "cle-215+", 0x0101: "cle-101"}
SLOTS = (("0x000000", spi_flash.GOLDEN_ADDR), ("0x400000", spi_flash.OPERATIONAL_ADDR))

# Worst first wins when there is more than one board.
SEVERITY = ("none", "pass", "degraded", "unconverted", "fail", "error")


class Problem(Exception):
    def __init__(self, result, reason):
        super().__init__(reason)
        self.result, self.reason = result, reason


# -- tier 1: PCI IDs ---------------------------------------------------------------------------------


def _hex(path):
    return int(path.read_text().strip(), 16)


def classify(vendor, device, sub_vendor, sub_device):
    """(kind, variant) of an endpoint, from its config-space IDs alone."""
    if (vendor, device) == (XILINX, LITEPCIE_X1):
        variant = OUR_SUBSYSTEMS.get((sub_vendor, sub_device))
        return ("fpgas-online", variant) if variant else ("litex-other", None)
    if (vendor, device) == (XILINX, VENDOR_XDMA):
        return "vendor-xdma", None
    if vendor == SQRL and device in SQRL_FACTORY:
        return "sqrl-factory", SQRL_FACTORY[device]
    return "unknown", None


def scan_pci(root=SYSFS_PCI):
    """Every Xilinx or SQRL endpoint under /sys/bus/pci/devices, classified."""
    found = []
    for d in sorted(pathlib.Path(root).iterdir()):
        try:
            ids = [_hex(d / n) for n in ("vendor", "device", "subsystem_vendor", "subsystem_device")]
        except (OSError, ValueError):
            continue
        if ids[0] not in (XILINX, SQRL):
            continue
        kind, variant = classify(*ids)
        found.append(
            {
                "bdf": d.name,
                "ids": f"{ids[0]:04x}:{ids[1]:04x}",
                "subsystem": f"{ids[2]:04x}:{ids[3]:04x}",
                "kind": kind,
                "variant": variant,
            }
        )
    return found


# -- BAR0 --------------------------------------------------------------------------------------------


class _Bar0:
    def __init__(self, mapping):
        self._map = mapping

    def read(self, addr):
        off = addr - CSR_BASE
        return struct.unpack("<I", self._map[off : off + 4])[0]

    def write(self, addr, value):
        off = addr - CSR_BASE
        self._map[off : off + 4] = struct.pack("<I", value)


@contextlib.contextmanager
def open_bar0(bdf, sysfs=SYSFS_PCI):
    """BAR0 of `bdf`, with memory decoding on for the duration and put back as it was afterwards.

    With no driver bound (litepcie.ko is not loaded on the fleet) the endpoint's COMMAND register has memory
    decoding off, and every BAR read returns all ones.
    """
    dev = pathlib.Path(sysfs) / bdf
    with open(dev / "config", "r+b") as cfg:
        cfg.seek(4)
        command = struct.unpack("<H", cfg.read(2))[0]
        if not command & 0x2:
            cfg.seek(4)
            cfg.write(struct.pack("<H", command | 0x2))
            cfg.flush()
        try:
            fd = os.open(dev / "resource0", os.O_RDWR | os.O_SYNC)
            try:
                mapping = mmap.mmap(fd, BAR0_SIZE, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)
            finally:
                os.close(fd)
            try:
                yield _Bar0(mapping)
            finally:
                mapping.close()
        finally:
            if not command & 0x2:
                cfg.seek(4)
                cfg.write(struct.pack("<H", command))
                cfg.flush()


def read_identifier(bus):
    """The SoC's identifier memory: one character in the low byte of each word, NUL-terminated."""
    out = bytearray()
    for i in range(IDENTIFIER_MAX):
        c = bus.read(IDENTIFIER_BASE + 4 * i) & 0xFF
        if c == 0:
            break
        out.append(c)
    return out.decode("ascii", "replace")


# -- the release ---------------------------------------------------------------------------------------


def load_release(images):
    path = pathlib.Path(images) / "manifest.json"
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise Problem("error", f"cannot read {path}: {e}") from None
    return manifest, {f["asset"]: f for f in manifest.get("files", [])}


def _checked_file(images, entry):
    """An installed file's bytes, refused unless they are what the manifest says."""
    path = pathlib.Path(images) / entry["asset"]
    try:
        data = path.read_bytes()
    except OSError as e:
        raise Problem("error", f"{path} is missing: {e}") from None
    if hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise Problem("error", f"{path} does not match its manifest sha256: the installed release is damaged")
    return data


def _expectations(manifest, files, variant):
    layout = manifest.get("flash_layout", {}).get(variant)
    if not layout or set(layout) != {s for s, _ in SLOTS}:
        raise Problem("error", f"release {manifest.get('tag')} has no flash layout for {variant}")
    golden, operational = files[layout["0x000000"]], files[layout["0x400000"]]
    return {"golden": golden, "operational": operational}, layout


def _csr_file(files, build_variant):
    for f in files.values():
        if f["file"] == "csr.json" and f["variant"] == build_variant:
            return f
    raise Problem("error", f"the release has no csr.json for the {build_variant} build")


# -- the check ---------------------------------------------------------------------------------------


def check_board(dev, images, release, open_bar):
    board = dict(dev)
    try:
        board.update(_check_board(dev, images, release, open_bar))
    except Problem as p:
        board.update(result=p.result, reason=p.reason)
    return board


def _check_board(dev, images, release, open_bar):
    kind = dev["kind"]
    if kind in ("sqrl-factory", "vendor-xdma"):
        what = "SQRL's factory image" if kind == "sqrl-factory" else "the vendor XDMA sample image"
        return {"result": "unconverted", "reason": f"runs {what}, not the fpgas.online design"}
    if kind != "fpgas-online":
        return {"result": "fail", "reason": f"{dev['ids']} subsystem {dev['subsystem']} is not a design we built"}

    manifest, files = release
    tag = manifest.get("tag")
    builds, layout = _expectations(manifest, files, dev["variant"])
    slot_images = {slot: _checked_file(images, files[layout[slot]]) for slot, _ in SLOTS}

    with open_bar(dev["bdf"]) as bus:
        identifier = read_identifier(bus)
        running = next(
            (name for name, f in builds.items() if f["config_identifier"].casefold() == identifier.casefold()), None
        )
        out = {"running": {"identifier": identifier, "build": running}}
        if running is None:  # its CSR map is unknown to us, so the flash is not read
            return {**out, "result": "fail", "reason": f"runs {identifier!r}, which is not in release {tag}"}

        csr_entry = _csr_file(files, builds[running]["variant"])
        bases = json.loads(_checked_file(images, csr_entry)).get("csr_bases", {})
        for name, want in CSR_EXPECTED.items():
            if bases.get(name) != want:
                got = bases.get(name)
                got = "missing" if got is None else f"{got:#x}"
                return {
                    **out,
                    "result": "error",
                    "reason": f"{csr_entry['asset']} puts {name} at {got}, not {want:#x}: not reading this flash",
                }

        flash = spi_flash.Flash(bus)  # read opcodes only
        ident = flash.identify()
        slots = []
        for slot, addr in SLOTS:
            diff = flash.first_difference(addr, slot_images[slot])
            entry = {"slot": slot, "asset": layout[slot], "result": "match" if diff is None else "mismatch"}
            if diff is not None:
                entry["first_difference"] = f"{diff:#x}"
            slots.append(entry)
        out["flash"] = {"part": ident["part"], "unique_id": ident["unique_id"], "slots": slots}

    if any(s["result"] != "match" for s in slots):
        bad = ", ".join(f"{s['slot']} differs at {s['first_difference']}" for s in slots if s["result"] != "match")
        return {**out, "result": "fail", "reason": f"flash does not hold release {tag}: {bad}"}
    if running == "golden":
        return {**out, "result": "degraded", "reason": "running the golden image: the operational slot did not boot"}
    return {**out, "result": "pass"}


def verify(devices, images=IMAGES, open_bar=open_bar0):
    release, release_error = None, None
    if any(d["kind"] == "fpgas-online" for d in devices):
        try:
            release = load_release(images)
        except Problem as p:
            release_error = p
    boards = []
    for dev in devices:
        if release_error and dev["kind"] == "fpgas-online":
            boards.append({**dev, "result": release_error.result, "reason": release_error.reason})
        else:
            boards.append(check_board(dev, images, release, open_bar))
    result = max((b["result"] for b in boards), key=SEVERITY.index, default="none")
    return {
        "schema_version": SCHEMA_VERSION,
        "result": result,
        "release": release[0].get("tag") if release else None,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "boards": boards,
    }


def exit_code(report):
    return 0 if report["result"] in ("pass", "none") else 1


# -- reporting ---------------------------------------------------------------------------------------


def fleet_event_argv(report):
    """`fleet-event fpga-verified` with a flat summary: fleet-event details are single strings."""
    details = {"result": report["result"], "release": report["release"] or "-"}
    for i, b in enumerate(report["boards"]):
        details[f"board{i}"] = f"{b['bdf']} {b['kind']} {b['variant'] or '-'} {b['result']}"
        if "running" in b:
            details[f"board{i}_identifier"] = b["running"]["identifier"]
        if "flash" in b:
            details[f"board{i}_flash"] = " ".join(f"{s['slot']}={s['result']}" for s in b["flash"]["slots"])
        if "reason" in b:
            details[f"board{i}_reason"] = b["reason"]
    argv = ["fleet-event", "fpga-verified"]
    for k, v in details.items():
        argv += ["--detail", f"{k}={v}"]
    return argv


def publish(report, kept_in):
    """Send the fleet-event. A failure is reported loudly but does not change the result: the hardware is
    what it is whether or not the broker heard about it, and `kept_in` still holds the report."""
    argv = fleet_event_argv(report)
    try:
        subprocess.run(argv, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"fpgas-acorn-verify: could not publish the result ({e}); the report is in {kept_in}", file=sys.stderr)
        return False
    return True


def _summary(report):
    lines = [f"acorn verify: {report['result']} (release {report['release'] or '-'})"]
    for b in report["boards"]:
        lines.append(f"  {b['bdf']} {b['ids']} subsystem {b['subsystem']}: {b['kind']} {b['variant'] or '-'}")
        if "running" in b:
            lines.append(f"    running  {b['running']['identifier']!r} ({b['running']['build'] or 'not in release'})")
        for s in b.get("flash", {}).get("slots", []):
            where = f" at {s['first_difference']}" if "first_difference" in s else ""
            lines.append(f"    flash    {s['slot']} {s['result']}{where}  ({s['asset']})")
        if "reason" in b:
            lines.append(f"    {b['result']}: {b['reason']}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--images", type=pathlib.Path, default=IMAGES, help="installed release (manifest.json)")
    parser.add_argument("--report", default=str(REPORT), help="where to write the JSON report ('-' for stdout)")
    parser.add_argument("--no-publish", action="store_true", help="do not send the fleet-event")
    args = parser.parse_args(argv)

    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)  # one BAR0 user at a time: this check, or an operator's spi_flash.py
        report = verify(scan_pci(), args.images)

    text = json.dumps(report, indent=2) + "\n"
    if args.report == "-":
        sys.stdout.write(text)
    else:
        out = pathlib.Path(args.report)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    print(_summary(report), file=sys.stderr)
    if not args.no_publish:
        publish(report, "stdout" if args.report == "-" else args.report)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
