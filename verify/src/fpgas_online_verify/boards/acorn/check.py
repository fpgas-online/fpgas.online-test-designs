"""Check that an Acorn runs the expected fpgas.online image and holds the expected images in its flash.

The Acorn's part of fpgas-verify (the board module is fpgas_online_verify.boards.acorn): run at boot by
fpgas-verify.service when the host is set up for an Acorn, and on demand as fpgas-acorn-verify. Three tiers:

  1. PCI IDs, from sysfs: which image family is running. The fpgas.online SoC is LitePCIe's 10ee:7021 with
     the board named in the subsystem IDs; SQRL's factory image and the vendor XDMA sample are recognised and
     reported as unconverted. Nothing past this tier runs against a design we did not build: its BAR0 has a
     register layout we do not know.
  2. The SoC's identifier string, over BAR0: which build is running. It carries the build timestamp, so it
     names one image exactly. It must be the operational or golden build of the installed release; the
     golden one means the operational slot did not boot (degraded).
  3. The flash, over BAR0 through spi_flash.py (read opcodes only): the golden slot (0x000000) and the
     operational slot (0x400000) are read whole and compared with the images the release puts there; their
     sha256s, with the flash's identity, are the board's state (fpgas_online_verify.state).

A board whose BAR0 a kernel driver holds (litepcie.ko, loaded by an operator) is not read at all: it is
reported "driver-bound", because two users of BAR0 would drive the same CSRs at once.

Nothing is ever written to the flash or reconfigured: a board that fails is reported, not repaired. The
images and manifest come from the fpgas-online-acorn-bitstreams package; each installed file is checked
against the manifest's sha256 before it is trusted.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import contextlib
import datetime
import hashlib
import json
import mmap
import os
import pathlib
import struct

from ...core import Problem, pci_devices
from . import spi_flash

SCHEMA_VERSION = 1
SYSFS_PCI = pathlib.Path("/sys/bus/pci/devices")
IMAGES = pathlib.Path("/usr/share/fpgas-online/acorn-pcie/images")
LOCK = pathlib.Path(spi_flash.LOCK)  # one user of the SoC at a time: this, or an operator's spi_flash.py

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
# driver-bound: a kernel driver (litepcie.ko) holds BAR0, so nothing was read. Not a fault, but not a pass either.
SEVERITY = ("none", "pass", "driver-bound", "degraded", "unconverted", "fail", "error")


# -- tier 1: PCI IDs ---------------------------------------------------------------------------------


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


def describe(dev, root=SYSFS_PCI):
    """A Xilinx or SQRL function from core.pci_devices(), classified, with the kernel driver bound to it (a
    driver holding BAR0 means the board is left alone); None for anyone else's."""
    if dev["vendor"] not in (XILINX, SQRL):
        return None
    ids = (dev["vendor"], dev["device"], dev["subsystem_vendor"], dev["subsystem_device"])
    kind, variant = classify(*ids)
    return {
        "bdf": dev["bdf"],
        "ids": f"{ids[0]:04x}:{ids[1]:04x}",
        "subsystem": f"{ids[2]:04x}:{ids[3]:04x}",
        "kind": kind,
        "variant": variant,
        "driver": spi_flash.bound_driver(dev["bdf"], root),
    }


def scan_pci(root=SYSFS_PCI):
    """Every Xilinx or SQRL endpoint under /sys/bus/pci/devices, classified.

    A Pi with no PCIe at all (a Pi 3, an Orange Pi) has no such directory: that is no devices, not an error
    (core.pci_devices).
    """
    return [d for d in (describe(dev, root) for dev in pci_devices(root)) if d]


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
        board.update(p.seen, result=p.result, reason=p.reason)
    return board


def _tier1(dev):
    """Refuse, from the PCI IDs alone, anything that is not our SoC: its BAR0 layout is unknown to us."""
    kind = dev["kind"]
    if kind in ("sqrl-factory", "vendor-xdma"):
        what = "SQRL's factory image" if kind == "sqrl-factory" else "the vendor XDMA sample image"
        raise Problem("unconverted", f"runs {what}, not the fpgas.online design")
    if kind != "fpgas-online":
        raise Problem("fail", f"{dev['ids']} subsystem {dev['subsystem']} is not a design we built")


def _not_driver_bound(dev):
    """Refuse a board whose BAR0 a kernel driver holds: see spi_flash.bound_driver()."""
    if dev.get("driver"):
        raise Problem("driver-bound", spi_flash.driver_bound_reason(dev["driver"]))


def _known_build(bus, images, files, builds, tag):
    """Tier 2, and the gate for everything after it: the running build must be one of the release's, and
    its register map must be the one spi_flash.py drives. Returns what was seen and which build runs."""
    identifier = read_identifier(bus)
    running = next(
        (name for name, f in builds.items() if f["config_identifier"].casefold() == identifier.casefold()), None
    )
    seen = {"running": {"identifier": identifier, "build": running}}
    if running is None:  # its CSR map is unknown to us, so the flash is not read
        raise Problem("fail", f"runs {identifier!r}, which is not in release {tag}", **seen)
    csr_entry = _csr_file(files, builds[running]["variant"])
    bases = json.loads(_checked_file(images, csr_entry)).get("csr_bases", {})
    for name, want in CSR_EXPECTED.items():
        if bases.get(name) != want:
            got = "missing" if bases.get(name) is None else f"{bases[name]:#x}"
            raise Problem(
                "error", f"{csr_entry['asset']} puts {name} at {got}, not {want:#x}: not reading this flash", **seen
            )
    return seen, running


def _flash_identity(flash):
    """The flash row of an rpi-hwid label. openFPGALoader reads an S25FL-S's unique id with the same OTPR
    (0x4B, 3 address + 1 dummy, 16 bytes from 0) that spi_flash.identify() sends; on pi-sw2-p48 the two gave
    the same 128 bits in the same order."""
    ident = flash.identify()
    return {
        "part": ident["part"],
        "jedec": "0x" + ident["rdid"][:6],
        "unique_id": ident["unique_id"],
        "size_bytes": ident["size_bytes"],
    }


def _first_difference(held, want):
    """The offset of the first byte of `want` that `held` (read from the start of the slot) does not match."""
    if held[: len(want)] == want:
        return None
    return next(i for i in range(len(want)) if held[i] != want[i])


def _check_board(dev, images, release, open_bar):
    _tier1(dev)
    _not_driver_bound(dev)
    manifest, files = release
    tag = manifest.get("tag")
    builds, layout = _expectations(manifest, files, dev["variant"])
    slot_images = {slot: _checked_file(images, files[layout[slot]]) for slot, _ in SLOTS}

    with open_bar(dev["bdf"]) as bus:
        out, running = _known_build(bus, images, files, builds, tag)
        flash = spi_flash.Flash(bus)  # read opcodes only
        identity = _flash_identity(flash)
        slots = []
        for slot, addr in SLOTS:
            held = flash.read(addr, spi_flash.SLOT_SIZE)  # the whole slot: its sha256 is part of the state
            diff = _first_difference(held, slot_images[slot])
            entry = {"slot": slot, "asset": layout[slot], "result": "match" if diff is None else "mismatch",
                     "sha256": hashlib.sha256(held).hexdigest()}  # fmt: skip
            if diff is not None:
                entry["first_difference"] = f"{addr + diff:#x}"
            slots.append(entry)
        out["flash"] = {**identity, "slots": slots}

    if any(s["result"] != "match" for s in slots):
        bad = ", ".join(f"{s['slot']} differs at {s['first_difference']}" for s in slots if s["result"] != "match")
        return {**out, "result": "fail", "reason": f"flash does not hold release {tag}: {bad}"}
    if running == "golden":
        return {**out, "result": "degraded", "reason": "running the golden image: the operational slot did not boot"}
    return {**out, "result": "pass"}


def _identify_board(dev, images, release, open_bar):
    _tier1(dev)
    _not_driver_bound(dev)
    manifest, files = release
    builds, _ = _expectations(manifest, files, dev["variant"])
    with open_bar(dev["bdf"]) as bus:
        out, _ = _known_build(bus, images, files, builds, manifest.get("tag"))
        out["flash"] = _flash_identity(spi_flash.Flash(bus))
    return {**out, "result": "read"}


def identify(devices, images=IMAGES, open_bar=open_bar0):
    """Each board's flash row, read live and nothing more: no slot is read. For rpi-hwid's labels.

    The same gates as the full check apply before anything is sent to the flash. "read" for a board
    whose flash identified itself; otherwise the board's result and reason say why not."""
    try:
        release = load_release(images) if any(d["kind"] == "fpgas-online" for d in devices) else None
    except Problem as p:
        release, failure = None, p
    else:
        failure = None
    boards = []
    for dev in devices:
        board = dict(dev)
        try:
            if failure and dev["kind"] == "fpgas-online":
                raise failure
            board.update(_identify_board(dev, images, release, open_bar))
        except Problem as p:
            board.update(p.seen, result=p.result, reason=p.reason)
        boards.append(board)
    worst = max((b["result"] for b in boards if b["result"] != "read"), key=SEVERITY.index, default=None)
    result = worst or ("read" if boards else "none")
    return {"schema_version": SCHEMA_VERSION, "result": result, "boards": boards}


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
    """0 for what is fine as far as this module goes: pass, an identity read, or no Acorn at all."""
    return 0 if report["result"] in ("pass", "read", "none") else 1
