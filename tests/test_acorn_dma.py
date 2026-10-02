"""Blocks between the Pi's RAM and the Acorn's DDR3 (fpgas_online_verify.boards.acorn.dma).

FakeDriver is litepcie.ko and the SoC behind it, as far as dma.Bridge can tell: the two rings of DMA buffers,
the bridge's CSRs through the register ioctl, and the three things that make a block transfer more than a
write() and a read():

  * the FPGA fetches the reader's ring from buffer 0 each time the reader is enabled, and stops fetching when
    the bridge stops taking;
  * the driver's count of complete writer buffers only moves on an interrupt, raised when buffer 0, 32, 64, ...
    completes; read() gives no more than that count;
  * while the writer is off its FIFOs are held in reset, and words the bridge sends then are lost.

`irq_counts` picks what the interrupt after buffer i reports, i or i+1 buffers: LitePCIe's loop status is the
index of "the last descriptor executed", and the transfers must not depend on which of the two that means.
"""

import pathlib
import struct

import pytest
from fpgas_online_verify.boards.acorn import check, dma

FD = 7
BRIDGE_REGS = ("base", "length", "mode", "start", "done", "count")
REGS = {f"pcie_dram_{reg}": {"addr": 0xF000A800 + 4 * i, "size": 1, "type": "rw"} for i, reg in enumerate(BRIDGE_REGS)}
REGS["sdram_dfii_control"] = {"addr": 0xF0008800, "size": 1, "type": "rw"}
CSRS = check.Csrs({"csr_registers": REGS})
NAMES = {reg["addr"]: name for name, reg in REGS.items()}
DRAM_WORDS = 1 << 20


class FakeDriver:
    def __init__(self, irq_counts="next", stuck=False):
        self.irq_counts, self.stuck = irq_counts, stuck
        self.dram = {}  # word address -> 8 bytes
        self.regs = {name: 0 for name in REGS}
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
        self.closed = False
        self.now = 0.0

    # -- what dma.Bridge is given ----------------------------------------------------------------------

    def open(self, path):
        assert path == dma.DEVICE
        return FD

    def close(self, fd):
        self.reader_on = self.writer_on = False
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
        assert fd == FD
        if request == dma.IOCTL_REG:
            addr, value, is_write = dma.REG.unpack(buf)
            if is_write:
                self._reg_write(NAMES[addr], value)
            else:
                buf[:] = dma.REG.pack(addr, self.regs[NAMES[addr]], 0)
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
                    self.locks[which] = True
                if rel:
                    self.locks[which] = False
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
            self.dram[base + i] = bytes(self.tx[at : at + dma.WORD])
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


def bridge(driver):
    return dma.Bridge(CSRS, opener=driver.open, ioctl=driver.ioctl, clock=driver.clock, sleep=driver.sleep,
                      read=driver.read, write=driver.write, close=driver.close)  # fmt: skip


def words(first, n):
    return b"".join(struct.pack("<Q", w) for w in range(first, first + n))


B = dma.BUFFER_WORDS
LENGTHS = [1, 2, B - 1, B, B + 1, 5 * B + 7, 32 * B, 32 * B + 1, 64 * B, 64 * B + 1, 150 * B + 3]


@pytest.mark.parametrize("irq_counts", ["next", "last"])
@pytest.mark.parametrize("nwords", LENGTHS)
def test_a_block_goes_to_the_dram_and_comes_back(nwords, irq_counts):
    driver = FakeDriver(irq_counts)
    data = words(0x1000, nwords)
    with bridge(driver) as b:
        b.to_dram(0x40, data)
        assert [driver.dram[0x40 + i] for i in (0, nwords - 1)] == [data[:8], data[-8:]]
        assert len(driver.dram) == nwords  # exactly the block: nothing before the base or past the end
        assert b.from_dram(0x40, nwords) == data
    assert driver.lost == 0


def test_a_read_starts_at_its_base():
    driver = FakeDriver()
    with bridge(driver) as b:
        b.to_dram(100, words(100, 3 * B))
        assert b.from_dram(100 + B + 5, 3) == words(100 + B + 5, 3)


def test_the_writer_is_enabled_before_the_bridge_sends():
    """While the DMA writer is off its FIFOs are in reset: a bridge started first would lose words in them."""
    driver = FakeDriver()
    with bridge(driver) as b:
        b.to_dram(0, words(7, 2 * B))
        b.from_dram(0, 2 * B)
    assert driver.lost == 0


def test_a_zero_length_transfer_moves_nothing():
    driver = FakeDriver()
    with bridge(driver) as b:
        b.to_dram(5, b"")
        assert b.from_dram(5, 0) == b""
    assert driver.dram == {} and not driver.reader_on and not driver.writer_on


def test_data_must_be_whole_words():
    with bridge(FakeDriver()) as b, pytest.raises(ValueError, match="whole number"):
        b.to_dram(0, b"\0" * 12)


def test_a_bridge_that_never_finishes_is_reported_with_its_count():
    driver = FakeDriver(stuck=True)
    with bridge(driver) as b, pytest.raises(dma.DMAError, match=r"not done after 10.0 s, 0 of 4 words moved"):
        b.to_dram(0, words(0, 4))
    assert not driver.reader_on  # the reader is switched off whatever happened


def test_both_directions_are_off_after_close():
    driver = FakeDriver()
    b = bridge(driver)
    b.to_dram(0, words(0, B))
    b.close()
    assert driver.closed and not driver.reader_on and not driver.writer_on
    b.close()  # closing twice is harmless


def test_lock_refuses_a_channel_in_use_and_gives_back_what_it_took():
    driver = FakeDriver()
    driver.locks["writer"] = True  # another process has the writer
    with bridge(driver) as b, pytest.raises(dma.DMAError, match="another process"):
        b.lock()
    assert driver.locks == {"reader": False, "writer": True}  # the other process still has its writer


def test_dram_ready_reads_the_controller_select_bit():
    driver = FakeDriver()
    with bridge(driver) as b:
        assert b.dram_ready()
        driver.regs["sdram_dfii_control"] = 0xE  # the BIOS is driving the DRAM pins itself
        assert not b.dram_ready()


def test_padded_buffers_ends_on_an_interrupt():
    assert [dma.padded_buffers(n) for n in (1, B, B + 1, 32 * B, 32 * B + 1, 64 * B)] == [33, 33, 33, 33, 65, 65]
    for n in LENGTHS[:-1]:  # each from-DRAM chunk, with its padding, fits the half of the ring read() keeps
        assert dma.padded_buffers(min(n, dma.FROM_DRAM_CHUNK_BUFFERS * B)) <= dma.DMA_BUFFER_COUNT // 2 + 1


def test_a_missing_module_names_the_package():
    assert dma.module_missing(exists=lambda path: True) is None
    reason = dma.module_missing(exists=lambda path: False)
    assert "litepcie.ko is not loaded" in reason and dma.MODULE_PACKAGE in reason and "modprobe litepcie" in reason


def test_ioctl_numbers_are_litepcie_h():
    """_IOWR('S', 0, 12-byte reg), _IOW('S', 20, 1), _IOWR('S', 21/22, 24), _IOWR('S', 25, 6)."""
    assert (dma.IOCTL_REG, dma.IOCTL_DMA) == (0xC00C5300, 0x40015314)
    assert (dma.IOCTL_DMA_WRITER, dma.IOCTL_DMA_READER, dma.IOCTL_LOCK) == (0xC0185315, 0xC0185316, 0xC0065319)


def test_the_ring_constants_are_the_drivers():
    """dma.py's ring geometry against the litepcie the driver packages are built from (uv.lock)."""
    litepcie = pytest.importorskip("litepcie")
    config = (pathlib.Path(litepcie.__file__).parent / "software" / "kernel" / "config.h").read_text()

    def define(name):
        return int(next(line.split()[2] for line in config.splitlines() if line.startswith(f"#define {name} ")))

    ours = (dma.DMA_BUFFER_SIZE, dma.DMA_BUFFER_COUNT, dma.DMA_BUFFER_PER_IRQ)
    assert ours == tuple(define(name) for name in ("DMA_BUFFER_SIZE", "DMA_BUFFER_COUNT", "DMA_BUFFER_PER_IRQ"))
