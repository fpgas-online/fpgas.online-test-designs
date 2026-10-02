"""Fakes for the Acorn check's tests.

  FakeSoC   the fpgas.online Acorn SoC's CSRs: the identifier memory, device DNA, XADC, ctrl scratch, the P2
            GPIOTristate and, through tests/test_spi_flash.py's FakeBus, the SPI master and its S25FL256S. It
            is the BAR0 bus, and (SoCLink) the far end of the P2 UARTBone link.
  FakePi    the Pi's side as the check drives it: `pinctrl get/set` on its pins, and openFPGALoader on P1. The
            spare balls J5/H5 are wired to GPIO3/GPIO4 as on the Pi 5 setup; a wire can be cut.
  release   an installed fpgas-online-acorn-bitstreams: both flash images, both builds' csr.json, a manifest.

Register addresses are the ones in the pinned release's csr.csv (vivado-bitstreams-acorn-pcie-20260923).
"""

import hashlib
import json

from tests.test_spi_flash import FakeBus, FakeS25FL, image, sf
from tests.test_uartbone_link import FakeFPGA

# What csr.json records (lower case) and what the SoC's identifier memory holds (as written in the gateware).
OP_IDENT = "fpgas-online acorn pcie soc cle-215+ 2026-09-21 14:23:32"
GOLDEN_IDENT = "fpgas-online acorn pcie soc cle-215+ golden 2026-09-21 14:31:19"
OP_IDENT_ON_CHIP = "fpgas-online Acorn PCIe SoC cle-215+ 2026-09-21 14:23:32"
GOLDEN_IDENT_ON_CHIP = "fpgas-online Acorn PCIe SoC cle-215+ golden 2026-09-21 14:31:19"
TAG = "vivado-bitstreams-acorn-pcie-20260921-gf3355dccf443"

DNA = 0x54B48664B04854  # pi-sw2-p48's, over BAR0 and over JTAG (2026-10-01)
REGS = {
    "ctrl_scratch": 0xF0000004,
    "uartbone_bridge_phy_tuning_word": 0xF0001800,
    "dna_id": 0xF0002800,
    "xadc_temperature": 0xF0003000,
    "xadc_vccint": 0xF0003004,
    "xadc_vccaux": 0xF0003008,
    "xadc_vccbram": 0xF000300C,
    "p2_gpio_oe": 0xF0008000,
    "p2_gpio_in": 0xF0008004,
    "p2_gpio_out": 0xF0008008,
    "uart_xover_rxtx": 0xF0001020,
    "uart_xover_rxempty": 0xF0001028,
    **{f"dram_{core}_{reg}": base + 4 * i for core, base in (("generator", 0xF0009000), ("checker", 0xF0009800))
       for i, reg in enumerate(("reset", "start", "done", "base", "end", "length", "random", "ticks", "errors"))
       if (core, reg) != ("generator", "errors")},
    **{f"p2_serial_{reg}": 0xF000A000 + 4 * i for i, reg in enumerate(("mode", "oe", "in", "out", "timeout"))},
}  # fmt: skip
GOLDEN_HAS_NO = tuple(n for n in REGS if n.startswith(("p2_gpio_", "p2_serial_", "dram_")))
NAMES = {a: n for n, a in REGS.items()}  # address -> name
DRAM_BYTES = 64 * 16  # 64 words of the BIST's 128 bits
P48_MBPS = 1327.4  # pi-sw2-p48's DRAM write bandwidth, 2026-10-01
# pi-sw2-p48's readings: 39.1 °C, VCCINT 1.022 V, VCCAUX 1.789 V, VCCBRAM 1.022 V
XADC_RAW = {"xadc_temperature": 0x9EA, "xadc_vccint": 0x573, "xadc_vccaux": 0x98A, "xadc_vccbram": 0x573}
# ball -> (FPGA module, bit, Pi GPIO): J2/K2 as on both setups, J5/H5 as on the Pi 5's
BALLS = {"J2": ("p2_serial", 0, 14), "K2": ("p2_serial", 1, 15), "J5": ("p2_gpio", 0, 3), "H5": ("p2_gpio", 1, 4)}

PI5 = "Raspberry Pi 5 Model B Rev 1.1"
CM4 = "Raspberry Pi Compute Module 4 Rev 1.1"
CM5 = "Raspberry Pi Compute Module 5 Rev 1.0"


def csr_json(golden=False):
    regs = {n: {"addr": a, "size": 2 if n == "dna_id" else 1, "type": "ro"} for n, a in REGS.items()}
    if golden:
        regs = {n: r for n, r in regs.items() if n not in GOLDEN_HAS_NO}
    return {
        "csr_bases": {"identifier_mem": 0xF0000800, "flash": 0xF0003800, "flash_cs_n": 0xF0004000},
        "csr_registers": regs,
        "constants": {"uart_fast_baud": 921600, "uart_fast_tuning_word": 39582418,
                      "config_clock_frequency": 100_000_000},
        "memories": {} if golden else {"main_ram": {"base": 0x40000000, "size": DRAM_BYTES, "type": "cached"}},
    }  # fmt: skip


def golden_image():
    return image(wbstar=sf.OPERATIONAL_ADDR, iprog=True, fill=0x11)


def operational_image():
    return image(fill=0x22)


def release(d):
    """An installed images directory in `d`: the flash images for cle-215+, both builds' csr.json, a manifest."""
    d.mkdir(exist_ok=True)
    files = []

    def add(asset, data, variant, golden, name, ident, slot):
        (d / asset).write_bytes(data)
        files.append({"asset": asset, "variant": variant, "golden": golden, "file": name,
                      "config_identifier": ident, "slot": slot, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})  # fmt: skip

    add("acorn-cle-215p-golden-sqrl_acorn_fallback.bin", golden_image(), "cle-215+-golden", True,
        "sqrl_acorn_fallback.bin", GOLDEN_IDENT, "0x000000")  # fmt: skip
    add("acorn-cle-215p-sqrl_acorn_operational.bin", operational_image(), "cle-215+", False,
        "sqrl_acorn_operational.bin", OP_IDENT, "0x400000")  # fmt: skip
    add("acorn-cle-215p-csr.json", json.dumps(csr_json()).encode(), "cle-215+", False, "csr.json", OP_IDENT, None)
    add("acorn-cle-215p-golden-csr.json", json.dumps(csr_json(golden=True)).encode(), "cle-215+-golden", True,
        "csr.json", GOLDEN_IDENT, None)  # fmt: skip
    manifest = {
        "schema_version": 1,
        "tag": TAG,
        "flash_layout": {"cle-215+": {"0x000000": "acorn-cle-215p-golden-sqrl_acorn_fallback.bin",
                                      "0x400000": "acorn-cle-215p-sqrl_acorn_operational.bin"}},
        "files": files,
    }  # fmt: skip
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


def rewrite(images, asset, data):
    """Replace an installed file and keep the manifest's sha256 right, as a different release would."""
    (images / asset).write_bytes(data)
    manifest = json.loads((images / "manifest.json").read_text())
    for f in manifest["files"]:
        if f["asset"] == asset:
            f["sha256"], f["size"] = hashlib.sha256(data).hexdigest(), len(data)
    (images / "manifest.json").write_text(json.dumps(manifest))


def chip():
    c = FakeS25FL()
    golden, operational = golden_image(), operational_image()
    c.mem[: len(golden)] = golden
    c.mem[sf.OPERATIONAL_ADDR : sf.OPERATIONAL_ADDR + len(operational)] = operational
    return c


class FakeSoC(FakeBus):
    """The SoC's CSRs. `pi` (a FakePi) is on the other end of the P2 balls."""

    def __init__(self, flash=None, identifier=OP_IDENT_ON_CHIP, dna=DNA, golden=False):
        super().__init__(flash or chip())
        self.identifier = identifier.encode() + b"\0"
        self.dna = dna
        self.xadc = dict(XADC_RAW)
        self.scratch = 0x12345678
        self.scratch_stuck = None  # a bit that never sets
        self.golden = golden
        self.oe = self.out = 0
        self.pi = None
        self.flash_touched = False
        self.console = bytearray(b"")  # what the BIOS has printed and nobody has read yet
        self.dram = DramModel(DRAM_BYTES)
        self.serial = {"mode": 0, "oe": 0, "out": 0, "timeout": 5000}
        self.now, self.mode_at = 0.0, 0.0
        self.switch_stuck = False  # a switch whose timeout never fires

    def sleep(self, seconds):
        self.now += seconds

    def clock(self):
        return self.now

    def _serial_mode(self):
        s = self.serial
        if s["mode"] and s["timeout"] and not self.switch_stuck and self.now - self.mode_at >= s["timeout"] / 1000:
            s["mode"] = 0
        return s["mode"]

    def _named(self, addr):
        return NAMES.get(addr)

    def read(self, addr):
        name = self._named(addr)
        if name and not (self.golden and name in GOLDEN_HAS_NO):
            if name == "uart_xover_rxempty":
                return 0 if self.console else 1
            if name == "uart_xover_rxtx":
                return self.console.pop(0) if self.console else 0
            if name.startswith("dram_"):
                return self.dram.read(name.removeprefix("dram_"))
            if name == "p2_serial_mode":
                return self._serial_mode()
            if name == "p2_serial_in":
                return self.pi.fpga_reads("p2_serial") if self.pi else 0b11
            if name.startswith("p2_serial_"):
                return self.serial[name.removeprefix("p2_serial_")]
        base = 0xF0000800
        if base <= addr < base + 4 * 256:
            i = (addr - base) // 4
            return self.identifier[i] if i < len(self.identifier) else 0
        if addr == REGS["dna_id"]:
            return self.dna >> 32
        if addr == REGS["dna_id"] + 4:
            return self.dna & 0xFFFFFFFF
        if NAMES.get(addr) in self.xadc:
            return self.xadc[NAMES[addr]]
        if addr == REGS["ctrl_scratch"]:
            return self.scratch
        if not self.golden and addr == REGS["p2_gpio_oe"]:
            return self.oe
        if not self.golden and addr == REGS["p2_gpio_out"]:
            return self.out
        if not self.golden and addr == REGS["p2_gpio_in"]:
            return self.pi.fpga_reads("p2_gpio") if self.pi else 0b11
        self.flash_touched = True
        return super().read(addr)

    def write(self, addr, value):
        name = self._named(addr)
        if name and name.startswith(("dram_", "p2_serial_")) and not self.golden:
            if name.startswith("dram_"):
                self.dram.write(name.removeprefix("dram_"), value)
            else:
                self.serial[name.removeprefix("p2_serial_")] = value & (1 if name.endswith("mode") else 0xFFFFFFFF)
                if name.endswith("mode"):
                    self.mode_at = self.now
            return
        if addr == REGS["ctrl_scratch"]:
            self.scratch = value & ~(self.scratch_stuck or 0)
        elif addr == REGS["uartbone_bridge_phy_tuning_word"]:
            pass
        elif not self.golden and addr == REGS["p2_gpio_oe"]:
            self.oe = value & 0b11
        elif not self.golden and addr == REGS["p2_gpio_out"]:
            self.out = value & 0b11
        else:
            self.flash_touched = True
            super().write(addr, value)


class _Mem:
    """FakeFPGA's memory, as the SoC's CSRs."""

    def __init__(self, soc):
        self.soc = soc

    def get(self, addr, default=0):
        return self.soc.read(addr)

    def __setitem__(self, addr, value):
        if addr != "corrupted":
            self.soc.write(addr, value)


class SoCLink(FakeFPGA):
    """The far end of the P2 UARTBone link: tests/test_uartbone_link.py's FakeFPGA over the SoC's CSRs."""

    def __init__(self, soc):
        super().__init__()
        self.mem = _Mem(soc)


class Cut(FakeFPGA):
    """A P2 UART with no wires: nothing ever answers."""

    def __init__(self):
        super().__init__()
        self.silent = True


# What openFPGALoader 1.1.1 printed on pi-sw2-p48 (2026-10-02) for `--detect --verbose-level 2`: the raw scan
# has the whole IDCODE; its part table, keyed without the version, gives the masked one after "idcode".
DETECT = (
    "index 0:\n\tidcode {masked:#x}\n\tmanufacturer xilinx\n\tfamily artix a7 200t\n\tmodel  xc7a200\n\tirlength 6\n"
)
RAW_SCAN = (
    "libgpiod jtag bitbang driver, dev=/dev/gpiochip0, tck_pin=11, tms_pin=8, tdi_pin=10, tdo_pin=9\n"
    "Raw IDCODE:\n- 0 -> {idcode:#010x}\n- 1 -> 0xffffffff\nFetched TDI, end-of-chain\nfound 1 devices\n"
)
P48_IDCODE = 0x13636093  # its XC7A200T is silicon version 1


class FakePi:
    """The Pi's pins, through pinctrl, and openFPGALoader on P1. Pins start as fpgas.online Pi 5s have them."""

    def __init__(self, soc=None, idcode=P48_IDCODE, jtag_dna=DNA, chain=True, cut=(), tool=True):
        self.soc, self.idcode, self.jtag_dna, self.chain, self.cut, self.tool = soc, idcode, jtag_dna, chain, cut, tool
        if soc is not None:
            soc.pi = self
        self.pins = {g: ["no", "pu", None] for g in (2, 3, 4)}
        self.pins.update({g: ["ip", "pd", None] for g in (8, 9, 10, 11)})
        self.pins.update({14: ["a4", "pn", None], 15: ["a4", "pu", None]})
        self.calls = []

    def _pull(self, gpio):
        return {"pu": 1, "pd": 0}.get(self.pins[gpio][1], 1)

    def _fpga_drives(self, module, bit):
        """The level the FPGA drives on a ball, or None."""
        soc = self.soc
        if module == "p2_gpio":
            return soc.out >> bit & 1 if soc.oe >> bit & 1 else None
        if not soc._serial_mode():
            return 1 if bit == 1 else None  # serial: K2 is the UART's TX, idle high; J2 its RX
        return soc.serial["out"] >> bit & 1 if soc.serial["oe"] >> bit & 1 else None

    def level(self, gpio):
        func, _, drive = self.pins[gpio]
        if func == "op":
            return drive
        for ball, (module, bit, g) in BALLS.items():
            if g == gpio and ball not in self.cut and self.soc:
                level = self._fpga_drives(module, bit)
                if level is not None:
                    return level
        return self._pull(gpio)

    def fpga_reads(self, module):
        value = 0
        for ball, (mod, bit, gpio) in BALLS.items():
            if mod != module:
                continue
            if ball in self.cut:
                value |= 1 << bit  # a floating input, read high
            elif self.pins[gpio][0] == "op":
                value |= self.pins[gpio][2] << bit
            else:
                value |= self._pull(gpio) << bit
        return value

    def __call__(self, argv, timeout):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if argv[:2] == ["pinctrl", "get"]:
            gpios = [int(g) for g in argv[2].split(",")]
            lines = []
            for g in gpios:
                func, pull, _ = self.pins[g]
                level = {1: "hi", 0: "lo"}[self.level(g)] if func != "no" else "--"
                drive = (" dh" if self.pins[g][2] else " dl") if func == "op" else ""
                lines.append(f"{g:2}: {func}{drive} {pull} | {level} // GPIO{g}")
            return 0, "\n".join(lines) + "\n"
        if argv[:2] == ["pinctrl", "set"]:
            for g in (int(x) for x in argv[2].split(",")):
                for word in argv[3:]:
                    if word in ("pu", "pd", "pn"):
                        self.pins[g][1] = word
                    elif word in ("dh", "dl"):
                        self.pins[g][2] = int(word == "dh")
                    else:
                        self.pins[g][0] = word
            return 0, ""
        if argv[0] == "openFPGALoader":
            if not self.tool:
                from fpgas_online_verify.core import Problem

                raise Problem("error", "openFPGALoader is not installed")
            pins = [int(p) for p in argv[argv.index("--pins") + 1].split(":")]
            for g in pins:  # it leaves TDI, TCK and TMS driven
                self.pins[g] = ["op", self.pins[g][1], 0]
            if not self.chain:
                return 1, "JTAG init failed with: no device found\n"
            if "--detect" in argv:
                raw = RAW_SCAN.format(idcode=self.idcode) if argv[-2:] == ["--verbose-level", "2"] else ""
                return 0, raw + DETECT.format(masked=self.idcode & 0x0FFFFFFF)
            if "--read-dna" in argv:
                return 0, json.dumps({"dna": f"{self.jtag_dna:#018x}"}) + "\n"
        raise AssertionError(f"unexpected command {argv}")

    def ran(self, program):
        return [c for c in self.calls if c[0] == program]


class Bar:
    """open_bar for a FakeSoC: a context manager per call, counting the opens."""

    def __init__(self, soc):
        self.soc, self.opened = soc, 0

    def __call__(self, bdf):
        outer = self

        class _Ctx:
            def __enter__(self):
                outer.opened += 1
                return outer.soc

            def __exit__(self, *exc):
                return False

        return _Ctx()


def refuse(bdf):
    raise AssertionError("BAR0 of a design we did not build must not be touched")


OURS = ("0x10ee", "0x7021", "0x1e24", "0x021f")
FACTORY = ("0x1e24", "0x021f", "0x0000", "0x0000")
VENDOR_XDMA = ("0x10ee", "0x7011", "0x0000", "0x0000")
RP1 = ("0x1de4", "0x0001", "0x0000", "0x0000")


def pci(root, bdf="0001:01:00.0", ids=OURS, cls="0x058000", bars=(0x100000,), driver=None, speed="5.0 GT/s PCIe",
        width="1"):  # fmt: skip
    """One function in a fake /sys/bus/pci/devices (`root`), as the kernel shows it. `bars` are BAR sizes by
    index (0 for none). A driver gets a /sys/bus/pci/drivers/<name> with bind and unbind files."""
    d = root / bdf
    d.mkdir(parents=True)
    for name, value in zip(("vendor", "device", "subsystem_vendor", "subsystem_device"), ids):
        (d / name).write_text(f"{value}\n")
    (d / "class").write_text(f"{cls}\n")
    lines = []
    for i in range(13):
        size = bars[i] if i < len(bars) else 0
        start = 0x1B00000000 + i * 0x1000000 if size else 0
        lines.append(f"{start:#018x} {start + size - 1 if size else 0:#018x} {0x40200 if size else 0:#018x}")
    (d / "resource").write_text("\n".join(lines) + "\n")
    for name, value in (("current_link_speed", speed), ("current_link_width", width),
                        ("max_link_speed", "5.0 GT/s PCIe"), ("max_link_width", "1")):  # fmt: skip
        (d / name).write_text(f"{value}\n")
    if driver:
        target = root.parent / "drivers" / driver
        target.mkdir(parents=True, exist_ok=True)
        (target / "bind").write_text("")
        (target / "unbind").write_text("")
        (d / "driver").symlink_to(target)
    return root


class DramModel:
    """LiteDRAM's BIST cores (dram_generator/dram_checker) over a DRAM of `size` bytes: `reset` restarts the
    pattern, `random` bit 0 picks a PRBS or a counter, one 16-byte word per address. Address bit `dead_bit` (a
    word-address bit) can do nothing, as an open top address line, or an image for twice the DRAM, looks from
    the controller. Each run takes as long as `MBps` says."""

    WORD = 16

    def __init__(self, size, dead_bit=None, mbps=P48_MBPS, clk=100_000_000, stuck_high=0, stuck_low=0):
        self.size, self.mbps, self.clk = size, mbps, clk
        # data bits stuck at 1 or at 0, as a dead DQ line or byte lane gives (a byte lane: 0xFF << 8 * lane)
        self.stuck_high, self.stuck_low = stuck_high, stuck_low
        self.mask = ~(1 << dead_bit) if dead_bit is not None else -1
        self.mem, self.regs, self.errors, self.runs = {}, {}, 0, []

    @staticmethod
    def pattern(prbs, i):
        # stand-ins for the PRBS and the counter: what matters is that they differ, and restart at reset
        return (i * 2654435761 + 0x5A5A) & 0x7FFFFFFF if prbs else i

    def read(self, name):
        core, reg = name.split("_", 1)
        if reg == "done":
            return 1
        if reg == "errors":
            return self.errors
        return self.regs.get(f"{core}_{reg}", 0)

    def write(self, name, value):
        core, reg = name.split("_", 1)
        self.regs[f"{core}_{reg}"] = value
        if reg == "start":
            self._run(core)

    def _run(self, core):
        base, length, prbs = (self.regs.get(f"{core}_{r}", 0) for r in ("base", "length", "random"))
        self.runs.append((core, base, length, prbs & 1))
        if core == "checker":
            self.errors = 0
        for i in range(length // self.WORD):
            addr = (base // self.WORD + i) & self.mask
            want = self.pattern(prbs & 1, i)
            if core == "generator":
                self.mem[addr] = (want | self.stuck_high) & ~self.stuck_low
            elif self.mem.get(addr) != want:
                self.errors += 1
        self.regs[f"{core}_ticks"] = round(length * self.clk / (self.mbps * 1e6))
