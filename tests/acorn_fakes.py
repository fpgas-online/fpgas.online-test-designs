"""Fakes for the Acorn check's tests.

  FakeSoC   the fpgas.online Acorn SoC's CSRs: the identifier memory, device DNA, XADC, ctrl scratch, the P2
            GPIOTristate and, through tests/test_spi_flash.py's FakeBus, the SPI master and its S25FL256S. It
            is the BAR0 bus, and (SoCLink) the far end of the P2 UARTBone link.
  FakePi    the Pi's side as the check drives it: `pinctrl get/set` on its pins, and openFPGALoader on P1. The
            spare balls J5/H5 are wired to GPIO3/GPIO4 as on the Pi 5 setup; a wire can be cut.
  release   an installed fpgas-online-acorn-bitstreams: both flash images, both builds' csr.json, a manifest.
  FakeLitePCIe  litepcie.ko and the SoC behind it, as far as dma.Bridge can tell: the two rings of DMA buffers
            and the PCIeDRAMBridge's CSRs through the register ioctl. FakePi has one, with the kernel's side
            of it: lsmod, modprobe, rmmod and whether /dev/litepcie0 is there.

Register addresses are the ones in the pinned release's csr.csv (vivado-bitstreams-acorn-pcie-20260923).
"""

import hashlib
import json

from fpgas_online_verify.boards.acorn import dma

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
    "sdram_dfii_control": 0xF0008800,
    **{f"pcie_dram_{reg}": 0xF000A800 + 4 * i
       for i, reg in enumerate(("base", "length", "mode", "start", "done", "count"))},
}  # fmt: skip
GOLDEN_HAS_NO = tuple(n for n in REGS if n.startswith(("p2_gpio_", "p2_serial_", "dram_", "sdram_", "pcie_dram_")))
BRIDGE_REGS = tuple(n for n in REGS if n.startswith(("sdram_", "pcie_dram_")))  # what the driver's ioctl reaches
NAMES = {a: n for n, a in REGS.items()}  # address -> name
DRAM_BYTES = 64 * 16  # 64 words of the BIST's 128 bits
DMA_BYTES = 3 * dma.DMA_BUFFER_SIZE + 8  # the `dma` test's timed block: small, ending part-way through a buffer
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


DETECT = "index 0:\n\tidcode {idcode:#x}\n\tmanufacturer xilinx\n\tfamily artix a7 200t\n\tmodel  xc7a200\n"


class FakePi:
    """The Pi's pins, through pinctrl, and openFPGALoader on P1. Pins start as fpgas.online Pi 5s have them."""

    def __init__(self, soc=None, idcode=0x3636093, jtag_dna=DNA, chain=True, cut=(), tool=True):
        self.soc, self.idcode, self.jtag_dna, self.chain, self.cut, self.tool = soc, idcode, jtag_dna, chain, cut, tool
        if soc is not None:
            soc.pi = self
        self.pins = {g: ["no", "pu", None] for g in (2, 3, 4)}
        self.pins.update({g: ["ip", "pd", None] for g in (8, 9, 10, 11)})
        self.pins.update({14: ["a4", "pn", None], 15: ["a4", "pu", None]})
        self.calls = []
        # litepcie.ko: installed for this kernel but not loaded, as on a fleet Pi; it binds when it is loaded
        self.modules, self.module_installed, self.module_binds = [], True, True
        self.liteuart_late = False  # udev loads liteuart only once litepcie's probe has registered its device
        self.others = {}
        self.lsmod_fails = False
        self.litepcie = FakeLitePCIe(
            ident=soc.identifier.rstrip(b"\0").decode() if soc is not None else OP_IDENT_ON_CHIP
        )

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

    def dma_devices(self):
        """litepcie.ko's device nodes: one, while the module is loaded and bound to the board. `others` are
        boards of other designs the same driver has bound, by node: {path: FakeLitePCIe}."""
        mine = [self.litepcie.node] if "litepcie" in self.modules and self.module_binds else []
        return sorted([*mine, *self.others]) if "litepcie" in self.modules else []

    def dma_bridge(self, csrs, device):
        d = self.others.get(device, self.litepcie)
        if "liteuart" not in self.modules:
            self.modules.append("liteuart")
        return dma.Bridge(csrs, device, opener=d.open, ioctl=d.ioctl, clock=d.clock, sleep=d.sleep, read=d.read,
                          write=d.write, close=d.close)  # fmt: skip

    def __call__(self, argv, timeout):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        if argv[0] == "lsmod":
            if self.lsmod_fails:
                return 1, "lsmod: ERROR: could not open /proc/modules\n"
            return 0, "Module                  Size  Used by\n" + "".join(f"{m} 20480 0\n" for m in self.modules)
        if argv == ["modprobe", "litepcie"]:
            if not self.module_installed:
                return 1, "modprobe: FATAL: Module litepcie not found in directory /lib/modules/6.12.109+rpt-rpi-v8\n"
            # liteuart through its platform alias: at once, or a moment later (by the time the device is used)
            self.modules += ["litepcie"] if self.liteuart_late else ["litepcie", "liteuart"]
            return 0, ""
        if argv[0] == "rmmod":
            self.modules.remove(argv[1])
            return 0, ""
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
                return 0, DETECT.format(idcode=self.idcode)
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


IDENTIFIER_BASE = 0xF0000800  # csr_map: identifier_mem = 1


class FakeLitePCIe:
    """litepcie.ko and the SoC behind it, as far as dma.Bridge can tell: the two rings of DMA buffers, the
    bridge's CSRs through the register ioctl, and the three things that make a block transfer more than a
    write() and a read():

      * the FPGA fetches the reader's ring from buffer 0 each time the reader is enabled, and stops fetching
        when the bridge stops taking;
      * the driver's count of complete writer buffers only moves on an interrupt, raised when buffer 0, 32,
        64, ... completes; read() gives no more than that count;
      * while the writer is off its FIFOs are held in reset, and words the bridge sends then are lost.

    `irq_counts` picks what the interrupt after buffer i reports, i or i+1 buffers: LitePCIe's loop status is
    the index of "the last descriptor executed", and the transfers must not depend on which of the two that
    means. `stuck`: a bridge that never finishes. `corrupt`: a DRAM word that does not hold what is written."""

    FD = 7

    def __init__(self, irq_counts="next", stuck=False, ident=OP_IDENT_ON_CHIP, corrupt=None, node=dma.DEVICE):
        self.irq_counts, self.stuck, self.ident, self.corrupt, self.node = irq_counts, stuck, ident, corrupt, node
        self.dram = {}  # word address -> 8 bytes
        self.regs = dict.fromkeys(BRIDGE_REGS, 0)
        self.regs["sdram_dfii_control"] = 1
        self.tx = bytearray(dma.DMA_BUFFER_COUNT * dma.DMA_BUFFER_SIZE)
        self.rx = bytearray(dma.DMA_BUFFER_COUNT * dma.DMA_BUFFER_SIZE)
        self.reader_on = self.writer_on = False
        self.tx_sw = 0  # buffers write() has filled since the reader was last off
        self.tx_taken = 0  # words the FPGA has taken from the ring since the reader was enabled
        self.rx_words = 0  # words the FPGA has stored since the writer was enabled
        self.rx_hw = self.rx_sw = 0  # the driver's counts of complete and of read buffers
        self.pending = None  # a to-DRAM transfer waiting for the reader
        self.lost = 0  # words sent while the writer was off
        self.locks = {"reader": False, "writer": False}
        self.mine = set()  # the locks this file took
        self.closed = False
        self.now = 0.0

    # -- what dma.Bridge is given ----------------------------------------------------------------------

    def open(self, path):
        assert path == self.node
        return self.FD

    def close(self, fd):
        """The driver's release(): a direction is stopped, and its lock given back, only if this file had
        locked it. A lock another process holds stays."""
        for which in self.mine:
            setattr(self, f"{which}_on", False)
            self.locks[which] = False
        self.mine = set()
        self.closed = True

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds

    def write(self, fd, data):
        assert not self.reader_on, "write() while the reader runs would race the FPGA"
        n = min(len(data) // dma.DMA_BUFFER_SIZE, dma.DMA_BUFFER_COUNT // 2 - self.tx_sw)
        at = self.tx_sw * dma.DMA_BUFFER_SIZE
        self.tx[at : at + n * dma.DMA_BUFFER_SIZE] = data[: n * dma.DMA_BUFFER_SIZE]
        self.tx_sw += n
        return n * dma.DMA_BUFFER_SIZE

    def read(self, fd, size):
        n = min(size // dma.DMA_BUFFER_SIZE, self.rx_hw - self.rx_sw)
        at = self.rx_sw * dma.DMA_BUFFER_SIZE
        self.rx_sw += n
        return bytes(self.rx[at : at + n * dma.DMA_BUFFER_SIZE])

    def ioctl(self, fd, request, buf):
        assert fd == self.FD
        if request == dma.IOCTL_REG:
            addr, value, is_write = dma.REG.unpack(buf)
            if is_write:
                self._reg_write(NAMES[addr], value)
            elif addr in NAMES:
                buf[:] = dma.REG.pack(addr, self.regs[NAMES[addr]], 0)
            else:  # the identifier memory
                i = (addr - IDENTIFIER_BASE) // 4
                buf[:] = dma.REG.pack(addr, ord(self.ident[i]) if i < len(self.ident) else 0, 0)
        elif request == dma.IOCTL_DMA:
            self.loopback = dma.DMA.unpack(buf)[0]
        elif request == dma.IOCTL_DMA_READER:
            enable = bool(dma.DMA_DIR.unpack(buf)[0])
            if enable != self.reader_on:
                self.reader_on, self.tx_taken = enable, 0
                if not enable:
                    self.tx_sw, self.pending = 0, None
            self._run()
        elif request == dma.IOCTL_DMA_WRITER:
            enable = bool(dma.DMA_DIR.unpack(buf)[0])
            if enable != self.writer_on:
                self.writer_on, self.rx_words, self.rx_hw, self.rx_sw = enable, 0, 0, 0
            buf[:] = dma.DMA_DIR.pack(enable, self.rx_hw, self.rx_sw)
        elif request == dma.IOCTL_LOCK:
            reader_req, writer_req, reader_rel, writer_rel, _, _ = dma.LOCK.unpack(buf)
            status = []
            for which, req, rel in (("reader", reader_req, reader_rel), ("writer", writer_req, writer_rel)):
                ok = 1
                if req:
                    ok = 0 if self.locks[which] else 1
                    if ok:
                        self.locks[which] = True
                        self.mine.add(which)
                if rel:
                    self.locks[which] = False
                    self.mine.discard(which)
                status.append(ok)
            buf[:] = dma.LOCK.pack(reader_req, writer_req, reader_rel, writer_rel, *status)
        else:
            raise AssertionError(f"unexpected ioctl {request:#x}")

    # -- the SoC ---------------------------------------------------------------------------------------

    def _reg_write(self, name, value):
        self.regs[name] = value
        if name != "pcie_dram_start":
            return
        base, length, mode = (self.regs[f"pcie_dram_{r}"] for r in ("base", "length", "mode"))
        self.regs["pcie_dram_done"], self.regs["pcie_dram_count"] = int(length == 0), 0
        if length == 0 or self.stuck:
            return
        if mode == dma.MODE_TO_DRAM:
            self.pending = (base, length)
            self._run()
        elif mode == dma.MODE_FROM_DRAM:
            for word in range(base, base + length):
                self._store(self.dram.get(word, bytes(dma.WORD)))
            self.regs["pcie_dram_done"], self.regs["pcie_dram_count"] = 1, length

    def _run(self):
        """A waiting to-DRAM transfer takes its words from the ring once the reader is fetching it."""
        if not (self.reader_on and self.pending):
            return
        base, length = self.pending
        for i in range(length):
            at = (self.tx_taken + i) * dma.WORD
            word = bytes(self.tx[at : at + dma.WORD])
            self.dram[base + i] = bytes(8) if base + i == self.corrupt else word  # `corrupt`: a word that does not hold
        self.tx_taken += length
        self.pending = None
        self.regs["pcie_dram_done"], self.regs["pcie_dram_count"] = 1, length

    def _store(self, word):
        if not self.writer_on:
            self.lost += 1
            return
        at = self.rx_words * dma.WORD
        self.rx[at : at + dma.WORD] = word
        self.rx_words += 1
        complete, part = divmod(self.rx_words, dma.BUFFER_WORDS)
        if part == 0 and (complete - 1) % dma.DMA_BUFFER_PER_IRQ == 0:  # buffer 0, 32, 64, ... just completed
            self.rx_hw = complete if self.irq_counts == "next" else complete - 1
