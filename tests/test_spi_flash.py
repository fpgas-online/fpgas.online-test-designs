"""Unit tests for the SPI flash host tool (designs/acorn-pcie/host/spi_flash.py).

A fake register bus stands in for the SoC: it models LiteX's 40-bit SPIMaster
CSRs and the separate `flash_cs_n` GPIO, and shifts every transfer through a
model of the Acorn's S25FL256S. The model has the behaviours that make a flash
writer go wrong on the real part:

  * the SoC resets `flash_cs_n` to 0, so the flash has been selected since
    configuration and ignores everything until it has seen CS rise;
  * programming can only clear bits;
  * the first 128 KiB is overlaid by 4 KiB parameter sectors, which a 64 KiB
    sector erase does not touch;
  * nothing is written without WREN, and WIP stays set for a few status reads.

Fault switches (`erase_fails_at`, `program_flips_at`, `p_err_at`) exist because
a flash that always works tests none of the checking code.
"""

import importlib.util
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "host" / "spi_flash.py"
_spec = importlib.util.spec_from_file_location("spi_flash", _PATH)
sf = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sf)

RDID = bytes.fromhex("0102194d0180")
SIZE = 8 << 20  # enough for both slots; the real part is 32 MiB
PARAM_END = 0x20000


class FakeS25FL:
    def __init__(self):
        self.mem = bytearray(b"\xff" * SIZE)
        self.wel = False
        self.busy_polls = 0
        self.sr_errors = 0
        self.seen_cs_rise = False
        self.opcodes = []
        self.erases = []
        self.erase_fails_at = None
        self.program_flips_at = None
        self.p_err_at = None
        self._rx = bytearray()
        self._tx = []

    # -- chip select ---------------------------------------------------------------------------

    def select(self):
        self._rx = bytearray()
        self._tx = []

    def deselect(self):
        if self.seen_cs_rise and self._rx:
            self._execute(bytes(self._rx))
        self.seen_cs_rise = True
        self._rx = bytearray()

    # -- one byte in, one byte out -------------------------------------------------------------

    def exchange(self, byte):
        if not self.seen_cs_rise:
            return 0xFF
        self._rx.append(byte)
        if len(self._rx) == 1:
            self.opcodes.append(byte)
        return self._reply(len(self._rx) - 1)

    def _reply(self, index):
        op = self._rx[0]
        if op == 0x9F and index >= 1:
            return RDID[index - 1] if index - 1 < len(RDID) else 0xFF
        if op == 0x05 and index >= 1:
            if self.busy_polls:
                self.busy_polls -= 1
                return 0x03
            return self.sr_errors | (0x02 if self.wel else 0)
        if op == 0x35 and index >= 1:
            return 0x02
        if op == 0x13 and index >= 5:
            return self.mem[(int.from_bytes(self._rx[1:5], "big") + index - 5) % SIZE]
        if op == 0x4B and index >= 5:
            return 0xA0 + (index - 5) if index - 5 < 16 else 0xFF
        return 0xFF

    # -- commands that act when CS rises ---------------------------------------------------------

    def _execute(self, rx):
        op = rx[0]
        if op == 0x06:
            self.wel = True
        elif op == 0x30:
            self.sr_errors = 0
        elif op in (0x21, 0xDC) and self.wel:
            addr = int.from_bytes(rx[1:5], "big")
            self.erases.append((op, addr))
            self.wel = False
            self.busy_polls = 2
            if addr == self.erase_fails_at:
                return
            if op == 0x21 and addr < PARAM_END:
                self.mem[addr & ~0xFFF : (addr & ~0xFFF) + 0x1000] = b"\xff" * 0x1000
            elif op == 0xDC and addr >= PARAM_END:
                self.mem[addr & ~0xFFFF : (addr & ~0xFFFF) + 0x10000] = b"\xff" * 0x10000
            # 0xDC inside the parameter region, or 0x21 outside it: the part does nothing.
        elif op == 0x12 and self.wel:
            addr = int.from_bytes(rx[1:5], "big")
            data = rx[5:]
            assert (addr & 0xFF) + len(data) <= 256, "page program wrapped inside a page"
            self.wel = False
            self.busy_polls = 1
            if addr == self.p_err_at:
                self.sr_errors = 0x40
                return
            for i, b in enumerate(data):
                self.mem[addr + i] &= b
            if self.program_flips_at is not None and addr <= self.program_flips_at < addr + len(data):
                self.mem[self.program_flips_at] ^= 0x01


class FakeBus:
    """The SoC side: SPIMaster(data_width=40) CSRs plus the flash_cs_n GPIO, which resets to 0 (selected)."""

    def __init__(self, flash):
        self.flash = flash
        self.cs_n = 0
        self.mosi = 0
        self.miso = 0
        self.writes = []

    def read(self, addr):
        if addr == sf.SPI_STATUS:
            return 1
        if addr == sf.SPI_MISO_HI:
            return self.miso >> 32
        if addr == sf.SPI_MISO_LO:
            return self.miso & 0xFFFFFFFF
        if addr == sf.FLASH_CS_N:
            return self.cs_n
        raise AssertionError(f"unexpected read of {addr:#x}")

    def write(self, addr, value):
        self.writes.append((addr, value))
        if addr == sf.FLASH_CS_N:
            if value and not self.cs_n:
                self.flash.deselect()
            if not value and self.cs_n:
                self.flash.select()
            self.cs_n = value
        elif addr == sf.SPI_MOSI_HI:
            self.mosi = (self.mosi & 0xFFFFFFFF) | value << 32
        elif addr == sf.SPI_MOSI_LO:
            self.mosi = (self.mosi & ~0xFFFFFFFF) | value
        elif addr == sf.SPI_CONTROL:
            bits = value >> 8
            assert value & 1 and bits % 8 == 0 and 8 <= bits <= 40
            assert self.cs_n == 0, "clocked the flash while it was deselected"
            out = (self.mosi >> (40 - bits)).to_bytes(bits // 8, "big")  # SPIMaster shifts from the top bit
            self.miso = int.from_bytes(bytes(self.flash.exchange(b) for b in out), "big")
        else:
            raise AssertionError(f"unexpected write to {addr:#x}")


def image(wbstar=0, iprog=False, timer=0x4001FBD0, idcode=0x03636093, size=70000, fill=0x5A):
    """A stand-in for a Vivado .bin: padding, sync word, then the header writes a flavour check looks at."""

    def w(reg, value):
        return (0x30000001 | reg << 13).to_bytes(4, "big") + value.to_bytes(4, "big")

    head = b"\xff" * 48 + bytes.fromhex("aa995566") + w(0x11, timer) + w(0x10, wbstar)
    head += w(0x04, 0xF if iprog else 0x0) + w(0x0C, idcode)
    return head + bytes([fill]) * (size - len(head))


GOLDEN = image(wbstar=0x400000, iprog=True)
OPERATIONAL = image()


@pytest.fixture
def chip():
    return FakeS25FL()


@pytest.fixture
def bus(chip):
    return FakeBus(chip)


def test_identify_works_from_the_reset_state_where_the_flash_is_already_selected(bus):
    info = sf.Flash(bus).identify()
    assert info["rdid"] == RDID.hex()
    assert info["size_bytes"] == 32 << 20
    assert info["part"] == "S25FL256S"
    assert info["unique_id"] == bytes(range(0xA0, 0xB0)).hex()
    assert info["quad_enabled"] is True
    assert bus.cs_n == 1


def test_read_spans_shifts_and_uses_four_byte_addresses(bus, chip):
    chip.mem[0x41FFFE:0x420009] = bytes(range(11))
    assert sf.Flash(bus).read(0x41FFFE, 11) == bytes(range(11))


def test_a_read_only_flash_never_sends_a_writing_opcode(bus, chip):
    flash = sf.Flash(bus)
    with pytest.raises(sf.FlashError, match="read-only"):
        flash.write_image(sf.OPERATIONAL_ADDR, OPERATIONAL, idcode=0x03636093)
    assert not set(chip.opcodes) & {0x06, 0x12, 0x21, 0xDC, 0x01, 0xC7, 0x60}


def test_write_operational_erases_only_its_own_sectors_programs_and_verifies(bus, chip):
    chip.mem[0x3F0000:0x400000] = b"\x11" * 0x10000  # the golden slot's last sector
    chip.mem[0x400000:0x420000] = b"\x00" * 0x20000
    chip.mem[0x420000] = 0x77  # first byte past the sectors this image needs
    sf.Flash(bus, allow_write=True).write_image(sf.OPERATIONAL_ADDR, OPERATIONAL, idcode=0x03636093)
    assert chip.mem[0x400000 : 0x400000 + len(OPERATIONAL)] == OPERATIONAL
    assert chip.mem[0x3F0000:0x400000] == b"\x11" * 0x10000
    assert chip.mem[0x420000] == 0x77
    assert chip.erases == [(0xDC, 0x400000), (0xDC, 0x410000)]
    assert bus.cs_n == 1


def test_golden_needs_the_flag_and_uses_4k_erases_in_the_parameter_region(bus, chip):
    chip.mem[0:0x30000] = b"\x00" * 0x30000
    flash = sf.Flash(bus, allow_write=True)
    with pytest.raises(sf.FlashError, match="golden"):
        flash.write_image(sf.GOLDEN_ADDR, GOLDEN, idcode=0x03636093)
    assert chip.erases == []
    big = image(wbstar=0x400000, iprog=True, size=0x28000)  # crosses out of the parameter region
    flash.write_image(sf.GOLDEN_ADDR, big, idcode=0x03636093, allow_golden=True)
    assert chip.mem[: len(big)] == big
    assert chip.erases == [(0x21, a) for a in range(0, PARAM_END, 0x1000)] + [(0xDC, 0x20000)]


@pytest.mark.parametrize(
    ("addr", "data", "kwargs", "why"),
    [
        (sf.OPERATIONAL_ADDR, GOLDEN, {}, "chain-loads"),
        (sf.GOLDEN_ADDR, OPERATIONAL, {"allow_golden": True}, "does not chain-load"),
        (sf.OPERATIONAL_ADDR, image(timer=0), {}, "watchdog"),
        (sf.OPERATIONAL_ADDR, image(idcode=0x03631093), {}, "IDCODE"),
        (sf.OPERATIONAL_ADDR, b"\x00" * 4096, {}, "sync word"),
        (sf.OPERATIONAL_ADDR, image(size=(4 << 20) + 1), {}, "does not fit"),
        (0x123456, OPERATIONAL, {}, "slot"),
    ],
)
def test_an_image_that_does_not_belong_in_the_slot_is_refused_before_any_erase(bus, chip, addr, data, kwargs, why):
    with pytest.raises(sf.FlashError, match=why):
        sf.Flash(bus, allow_write=True).write_image(addr, data, idcode=0x03636093, **kwargs)
    assert chip.erases == []
    assert 0x06 not in chip.opcodes


def test_an_erase_that_leaves_data_behind_is_caught_before_programming(bus, chip):
    chip.mem[0x410000:0x420000] = b"\x00" * 0x10000
    chip.erase_fails_at = 0x410000
    with pytest.raises(sf.FlashError, match="not blank after erase"):
        sf.Flash(bus, allow_write=True).write_image(sf.OPERATIONAL_ADDR, OPERATIONAL, idcode=0x03636093)
    assert 0x12 not in chip.opcodes


def test_a_bit_that_programs_wrong_fails_the_final_verify(bus, chip):
    chip.program_flips_at = 0x400000 + 12345
    with pytest.raises(sf.FlashError, match=r"verify failed at 0x403039"):
        sf.Flash(bus, allow_write=True).write_image(sf.OPERATIONAL_ADDR, OPERATIONAL, idcode=0x03636093)


def test_a_program_error_flag_is_reported_and_cleared(bus, chip):
    chip.p_err_at = 0x400100
    with pytest.raises(sf.FlashError, match="status 0x40"):
        sf.Flash(bus, allow_write=True).write_image(sf.OPERATIONAL_ADDR, OPERATIONAL, idcode=0x03636093)
    assert chip.opcodes[-1] == 0x30
    assert bus.cs_n == 1


def test_image_info_reads_the_multiboot_header():
    info = sf.image_info(GOLDEN)
    assert (info["wbstar"], info["iprog"], info["watchdog"], info["idcode"]) == (0x400000, True, True, 0x03636093)
    info = sf.image_info(OPERATIONAL)
    assert (info["wbstar"], info["iprog"], info["watchdog"]) == (0, False, True)
