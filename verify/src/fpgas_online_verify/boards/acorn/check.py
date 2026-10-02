"""The PCIe side of the Acorn check: what runs on the board, its CSRs over BAR0, and its flash.

The Acorn's part of fpgas-verify (the board module is fpgas_online_verify.boards.acorn; suite.py runs the
tests in order). What lives here:

  * PCI IDs, from sysfs: which image family is running. The fpgas.online SoC is LitePCIe's 10ee:7021 with
    the board named in the subsystem IDs; SQRL's factory image and the vendor XDMA sample are recognised and
    fail, with "unconverted" in the reason. Two other Xilinx PCIe boards on the fleet are named (a PCIe
    Screamer running PCILeech, a stock XDMA design that is most likely a PicoEVB) and fail because
    fpgas.online has no test design for them. The XDMA design has the same IDs as an old LitePCIe build of
    ours (both keep the Xilinx default subsystem 10ee:0007), so it is told apart by what LitePCIe never has:
    the XDMA class code 070001 and a BAR2. Nothing is sent to a design we did not build: its BARs have a
    register layout we do not know.
  * The SoC's identifier string, over BAR0: which build is running. It carries the build timestamp, so it
    names one image exactly. It must be the operational or golden build of the installed release; nothing
    past the identifier read is sent over BAR0 otherwise: the release's csr.json for that build gives the CSR addresses.
  * The CSRs the design has for the board itself: device DNA, XADC temperature and voltages, and the ctrl
    scratch register.
  * The flash, through spi_flash.py (read opcodes only): its identity, and the golden slot (0x000000) and the
    operational slot (0x400000) read whole and compared with the images the release puts there.

A kernel driver bound to the board (litepcie.ko, loaded by an operator) owns BAR0. The check unbinds it for
the duration and binds it again afterwards (driver_released), so the board is still tested.

Nothing is ever written to the flash or reconfigured: a board that fails is reported, not repaired. The
images and manifest come from the fpgas-online-acorn-bitstreams package; each installed file is checked
against the manifest's sha256 before it is trusted.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import contextlib
import hashlib
import json
import pathlib

from ...core import Problem, pci_devices
from . import spi_flash

SYSFS_PCI = pathlib.Path("/sys/bus/pci/devices")
IMAGES = pathlib.Path("/usr/share/fpgas-online/acorn-pcie/images")
LOCK = pathlib.Path(spi_flash.LOCK)  # one user of the SoC at a time: this, or an operator's spi_flash.py

CSR_BASE = spi_flash.CSR_BASE
IDENTIFIER_BASE = CSR_BASE + 0x800  # csr_map: identifier_mem = 1
IDENTIFIER_MAX = 256
# The CSR bases this tool and spi_flash.py drive. A build whose csr.json says otherwise is not read.
CSR_EXPECTED = {"identifier_mem": IDENTIFIER_BASE, "flash": spi_flash.SPI_CONTROL, "flash_cs_n": spi_flash.FLASH_CS_N}
BAR0_SIZE = spi_flash.BAR0_SIZE
# Every CSR the check reads or writes; build_csrs() refuses a csr.json that puts one outside the mapped BAR0.
USED_CSRS = (
    "ctrl_scratch",
    "dna_id",
    "xadc_temperature",
    "xadc_vccint",
    "xadc_vccaux",
    "xadc_vccbram",
    "p2_gpio_oe",
    "p2_gpio_in",
    "p2_gpio_out",
    "uartbone_bridge_phy_tuning_word",
    "uart_xover_rxtx",
    "uart_xover_rxempty",
    *(
        f"dram_{core}_{reg}"
        for core in ("generator", "checker")
        for reg in ("reset", "start", "done", "base", "end", "length", "random", "ticks")
    ),
    "dram_checker_errors",
    *(f"p2_serial_{reg}" for reg in ("mode", "oe", "in", "out", "timeout")),
)

XILINX, SQRL = 0x10EE, 0x1E24
LITEPCIE_X1, VENDOR_XDMA, PCILEECH = 0x7021, 0x7011, 0x0666
XDMA_CLASS = 0x070001  # the XDMA IP's default class code; the fpgas.online SoC's is 0x058000
# designs/acorn-pcie/gateware/acorn_pcie_soc.py PCIE_SUBSYSTEM_*: tests/test_acorn_verify.py holds them equal.
OUR_SUBSYSTEMS = {(SQRL, 0x021F): "cle-215+", (SQRL, 0x0101): "cle-101"}
# SQRL's factory images use these as their own vendor:device, with the subsystem left at 0000:0000.
SQRL_FACTORY = {0x021F: "cle-215+", 0x0101: "cle-101"}
SLOTS = (("0x000000", spi_flash.GOLDEN_ADDR), ("0x400000", spi_flash.OPERATIONAL_ADDR))
# Xilinx PCIe boards that are not Acorns, seen on the fleet (pi-sw1-p38, pi-sw2-p37).
OTHER_BOARDS = {
    "pcileech": "PCIe Screamer (PCILeech image)",
    "xilinx-xdma": "Xilinx XDMA design (likely PicoEVB)",
}
NO_TEST_DESIGN = "fpgas.online has no test design for this board yet"

XADC_TEMPERATURE = ("temperature_c", "xadc_temperature")
XADC_VOLTAGES = (("vccint_v", "xadc_vccint"), ("vccaux_v", "xadc_vccaux"), ("vccbram_v", "xadc_vccbram"))
DNA_BITS = 57
SCRATCH_PATTERNS = (0xA5A55A5A, 0x5A5AA5A5)


# -- PCI IDs -------------------------------------------------------------------------------------------


def classify(vendor, device, sub_vendor, sub_device, pci_class=None, bars=()):
    """(kind, variant) of an endpoint, from its config space alone: IDs, class code, which BARs it has."""
    if (vendor, device) == (XILINX, LITEPCIE_X1):
        variant = OUR_SUBSYSTEMS.get((sub_vendor, sub_device))
        if variant:
            return "fpgas-online", variant
        if pci_class == XDMA_CLASS and 2 in bars:  # the XDMA IP's DMA BAR as well as BAR0; LitePCIe has one BAR
            return "xilinx-xdma", None
        return "litex-other", None
    if (vendor, device) == (XILINX, VENDOR_XDMA):
        return "vendor-xdma", None
    if (vendor, device) == (XILINX, PCILEECH):
        return "pcileech", None
    if vendor == SQRL and device in SQRL_FACTORY:
        return "sqrl-factory", SQRL_FACTORY[device]
    return "unknown", None


def _class_and_bars(dev_dir):
    """The class code and the indexes of the BARs a function has, from sysfs (no config-space access)."""
    try:
        pci_class = int((dev_dir / "class").read_text(), 16)
    except (OSError, ValueError):
        pci_class = None
    bars = []
    try:
        for i, line in enumerate((dev_dir / "resource").read_text().splitlines()[:6]):
            end = int(line.split()[1], 16)
            if end:
                bars.append(i)
    except (OSError, ValueError):
        pass
    return pci_class, tuple(bars)


def describe(dev, root=SYSFS_PCI):
    """A Xilinx or SQRL function from core.pci_devices(), classified, with the kernel driver bound to it;
    None for anyone else's."""
    if dev["vendor"] not in (XILINX, SQRL):
        return None
    ids = (dev["vendor"], dev["device"], dev["subsystem_vendor"], dev["subsystem_device"])
    pci_class, bars = _class_and_bars(pathlib.Path(root) / dev["bdf"])
    kind, variant = classify(*ids, pci_class, bars)
    out = {
        "bdf": dev["bdf"],
        "ids": f"{ids[0]:04x}:{ids[1]:04x}",
        "subsystem": f"{ids[2]:04x}:{ids[3]:04x}",
        "kind": kind,
        "variant": variant,
        "driver": spi_flash.bound_driver(dev["bdf"], root),
    }
    if kind in OTHER_BOARDS:
        out["title"] = OTHER_BOARDS[kind]
    return out


def scan_pci(root=SYSFS_PCI):
    """Every Xilinx or SQRL endpoint under /sys/bus/pci/devices, classified.

    A Pi with no PCIe at all (a Pi 3, an Orange Pi) has no such directory: that is no devices, not an error
    (core.pci_devices).
    """
    return [d for d in (describe(dev, root) for dev in pci_devices(root)) if d]


def not_ours(dev):
    """The reason a board found on PCI is not running the fpgas.online SoC, or None if it is.

    A board still on SQRL's factory image (or the vendor XDMA sample) cannot be offered to users; the reason
    says it is unconverted, so the fix (fpgas-acorn-flash) is plain from the report."""
    kind = dev["kind"]
    if kind == "fpgas-online":
        return None
    if kind in ("sqrl-factory", "vendor-xdma"):
        what = "SQRL's factory image" if kind == "sqrl-factory" else "the vendor XDMA sample image"
        return f"unconverted: runs {what}, not the fpgas.online design"
    if kind in OTHER_BOARDS:
        return f"{OTHER_BOARDS[kind]}: {NO_TEST_DESIGN}"
    return f"{dev['ids']} subsystem {dev['subsystem']} is not a design we built"


def is_acorn(dev):
    """True for a board known to be an Acorn, whatever it runs."""
    return dev["kind"] in ("fpgas-online", "sqrl-factory")


# -- the PCIe link -------------------------------------------------------------------------------------


def link_status(bdf, root=SYSFS_PCI):
    """{speed_gt_s, width, max_speed_gt_s, max_width} from sysfs ("5.0 GT/s PCIe" -> 5.0)."""
    dev = pathlib.Path(root) / bdf
    out = {}
    for key, name in (("speed_gt_s", "current_link_speed"), ("width", "current_link_width"),
                      ("max_speed_gt_s", "max_link_speed"), ("max_width", "max_link_width")):  # fmt: skip
        try:
            text = (dev / name).read_text().split()[0]
            out[key] = int(text) if key.endswith("width") else float(text)
        except (OSError, ValueError, IndexError) as e:
            raise Problem("error", f"cannot read {dev / name}: {e}") from None
    return out


def link_faults(status, expected):
    """What differs from the expected link, as sentences."""
    faults = []
    if status["speed_gt_s"] != expected["speed_gt_s"]:
        faults.append(f"link runs at {status['speed_gt_s']} GT/s, expected {expected['speed_gt_s']} GT/s")
    if status["width"] != expected["width"]:
        faults.append(f"link is x{status['width']}, expected x{expected['width']}")
    return faults


# -- a driver that holds BAR0 --------------------------------------------------------------------------


@contextlib.contextmanager
def driver_released(dev, note, root=SYSFS_PCI):
    """Unbind the kernel driver bound to the board for the duration, and bind it again afterwards.

    A bound driver (litepcie.ko) owns BAR0, and nothing in the kernel stops a second user mapping resource0:
    both would drive the same CSRs at once. So the driver lets go while the check reads, and `note` records
    what happened ({"driver", "unbound", "rebound" or "rebind_error"})."""
    driver = dev.get("driver")
    if not driver:
        yield
        return
    control = (pathlib.Path(root) / dev["bdf"] / "driver").resolve()  # /sys/bus/pci/drivers/<driver>
    note["driver"] = driver
    try:
        (control / "unbind").write_text(dev["bdf"])
    except OSError as e:
        raise Problem("error", f"the {driver} driver holds the board and could not be unbound: {e}") from None
    note["unbound"] = True
    try:
        yield
    finally:
        try:
            (control / "bind").write_text(dev["bdf"])
            note["rebound"] = True
        except OSError as e:
            note["rebind_error"] = f"the {driver} driver could not be bound again: {e}"


# -- BAR0 ----------------------------------------------------------------------------------------------


def open_bar0(bdf, sysfs=SYSFS_PCI):
    """BAR0 of `bdf`, with memory decoding on for the duration (spi_flash.open_bar0, which fpgas-acorn-flash
    uses too)."""
    return spi_flash.open_bar0(bdf, sysfs)


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


def expectations(manifest, files, variant):
    """({"golden": entry, "operational": entry}, flash layout) for a variant."""
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


class Csrs:
    """A build's CSR map, from the release's csr.json: the addresses are the build's, not this tool's."""

    def __init__(self, data, asset="csr.json"):
        self.asset = asset
        self.bases = data.get("csr_bases", {})
        self.registers = data.get("csr_registers", {})
        self.constants = data.get("constants", {})
        self.memories = data.get("memories", {})

    def addr(self, name):
        reg = self.registers.get(name)
        if reg is None:
            raise Problem("fail", f"the running build has no {name} CSR ({self.asset})")
        return reg["addr"]

    def words(self, name):
        return self.registers.get(name, {}).get("size", 1)

    def has(self, name):
        return name in self.registers


def build_csrs(images, files, build):
    """The Csrs of a build (a manifest entry), refused unless its bases are the ones spi_flash.py drives."""
    entry = _csr_file(files, build["variant"])
    csrs = Csrs(json.loads(_checked_file(images, entry)), entry["asset"])
    for name, want in CSR_EXPECTED.items():
        if csrs.bases.get(name) != want:
            got = "missing" if csrs.bases.get(name) is None else f"{csrs.bases[name]:#x}"
            raise Problem("error", f"{entry['asset']} puts {name} at {got}, not {want:#x}: not reading this board")
    for name in USED_CSRS:
        if csrs.has(name):
            first, last = csrs.registers[name]["addr"], csrs.registers[name]["addr"] + 4 * csrs.words(name)
            if not CSR_BASE <= first < last <= CSR_BASE + BAR0_SIZE:
                raise Problem("error", f"{entry['asset']} puts {name} at {first:#x}, outside the {BAR0_SIZE:#x} bytes "
                                       "of BAR0 this tool maps: not reading this board")  # fmt: skip
    return csrs


def known_build(identifier, builds):
    """The name of the release build ("golden", "operational") whose identifier this is, or None."""
    return next((n for n, f in builds.items() if f["config_identifier"].casefold() == identifier.casefold()), None)


def gate(bus, images, files, builds, tag):
    """The gate for everything on BAR0 after the identifier: the running build must be one of the release's,
    and its register map the one spi_flash.py drives. Returns (what was seen, build name, Csrs)."""
    identifier = read_identifier(bus)
    running = known_build(identifier, builds)
    seen = {"running": {"identifier": identifier, "build": running}}
    if running is None:  # its CSR map is unknown to us, so nothing more is read
        raise Problem("fail", f"runs {identifier!r}, which is not in release {tag}", **seen)
    try:
        csrs = build_csrs(images, files, builds[running])
    except Problem as p:
        raise Problem(p.result, p.reason, **seen) from None
    except (KeyError, TypeError, ValueError) as e:  # a malformed csr.json: its map cannot be trusted
        raise Problem("error", f"the release's csr.json for this build cannot be read: {type(e).__name__}: {e}",
                      **seen) from None  # fmt: skip
    return seen, running, csrs


# -- the design's own CSRs, over either bridge ---------------------------------------------------------
#
# `read(addr) -> int` and `write(addr, value)` are a bus: BAR0, or the P2 UARTBone link.


def read_dna(read, csrs):
    """The device DNA from the `dna_id` CSR: 57 bits in two words, the upper word first."""
    addr = csrs.addr("dna_id")
    value = 0
    for i in range(csrs.words("dna_id")):
        value = value << 32 | read(addr + 4 * i)
    return value


def dna_faults(dna, where):
    if dna == 0 or dna == (1 << DNA_BITS) - 1:
        return [f"device DNA over {where} reads {dna:#x}: the DNA port is not being read"]
    return []


def read_xadc(read, csrs):
    """XADC temperature (°C) and supply voltages (V), from the raw 12-bit readings (UG480 transfer functions)."""
    key, name = XADC_TEMPERATURE
    out = {key: round(read(csrs.addr(name)) * 503.975 / 4096 - 273.15, 1)}
    for key, name in XADC_VOLTAGES:
        out[key] = round(read(csrs.addr(name)) * 3.0 / 4096, 3)
    return out


def xadc_faults(xadc, ranges, where):
    faults = []
    for key, value in xadc.items():
        low, high = ranges.get(key, (None, None))
        if low is not None and not low <= value <= high:
            faults.append(f"XADC {key} over {where} is {value}, outside {low} to {high}")
    return faults


def scratch_faults(read, write, csrs, where):
    """Write two patterns to the ctrl scratch register, read each back, and put the old value back."""
    addr = csrs.addr("ctrl_scratch")
    old = read(addr)
    faults = []
    try:
        for pattern in SCRATCH_PATTERNS:
            write(addr, pattern)
            got = read(addr)
            if got != pattern:
                faults.append(f"scratch over {where}: wrote {pattern:#010x}, read {got:#010x}")
    finally:
        write(addr, old)
    return faults


# -- the flash -----------------------------------------------------------------------------------------


def flash_identity(flash):
    """Everything the flash said about itself (spi_flash.Flash.identify()): all six RDID bytes, the part, its
    size, the status and configuration registers, and the factory unique ID. openFPGALoader reads an
    S25FL-S's unique id with the same OTPR (0x4B, 3 address + 1 dummy, 16 bytes from 0) that identify() sends;
    on pi-sw2-p48 the two gave the same 128 bits in the same order.

    part, jedec and unique_id are what the recorded state has always had;
    identity.flash_fields() turns the whole read into the identity's flash fields."""
    ident = flash.identify()
    return {
        "part": ident["part"],
        "jedec": "0x" + ident["rdid"][:6],
        "unique_id": ident["unique_id"],
        "size_bytes": ident["size_bytes"],
        "rdid": ident["rdid"],
        "status": ident["status"],
        "config": ident["config"],
        "quad_enabled": ident["quad_enabled"],
        "unique_id_opcode": ident["unique_id_opcode"],
    }


def _first_difference(held, want):
    """The offset of the first byte of `want` that `held` (read from the start of the slot) does not match."""
    if held[: len(want)] == want:
        return None
    return next(i for i in range(len(want)) if held[i] != want[i])


def flash_slots(bus, images, files, layout):
    """Both slots read whole and compared with the release's images: [{slot, asset, result, sha256, ...}]."""
    slot_images = {slot: _checked_file(images, files[layout[slot]]) for slot, _ in SLOTS}
    flash = spi_flash.Flash(bus)  # read opcodes only
    slots = []
    for slot, addr in SLOTS:
        held = flash.read(addr, spi_flash.SLOT_SIZE)  # the whole slot: its sha256 is part of the state
        diff = _first_difference(held, slot_images[slot])
        entry = {"slot": slot, "asset": layout[slot], "result": "match" if diff is None else "mismatch",
                 "sha256": hashlib.sha256(held).hexdigest()}  # fmt: skip
        if diff is not None:
            entry["first_difference"] = f"{addr + diff:#x}"
        slots.append(entry)
    return slots
