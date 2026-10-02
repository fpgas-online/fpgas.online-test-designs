"""Blocks between the Pi's RAM and the Acorn's DDR3, over LitePCIe's DMA and the SoC's PCIeDRAMBridge.

The gateware side is designs/_shared/pcie_dram_bridge.py: it sits at the far end of the SoC's one DMA channel and
moves `length` 64-bit words between that channel's streams and DRAM words `base`, `base`+1, ... The host side
is litepcie.ko, whose DMA is made for streaming, not for blocks:

  * each direction is a ring of DMA_BUFFER_COUNT buffers of DMA_BUFFER_SIZE bytes, which the FPGA walks in order
    for as long as that direction is enabled;
  * the driver learns how far the FPGA has got only from an interrupt, raised once every DMA_BUFFER_PER_IRQ
    buffers (after buffers 0, 32, 64, ...), and read() hands over only the buffers it knows are complete.

So a block is moved like this.

  to DRAM    With the DMA reader off, write() the block into the ring from buffer 0. Tell the bridge the base and
             the exact word count and start it. Only then enable the reader: the FPGA fetches the ring from
             buffer 0, the bridge takes its words and stops taking, and the rest of the ring (padding) stays in
             LitePCIe's FIFOs. Disabling the reader resets those FIFOs, so nothing is left for the next block.
  from DRAM  Enable the DMA writer first: its FIFOs are held in reset while it is off, and a bridge started
             before it would lose words in them. Start the bridge for the block, then start it again for
             padding that brings the total to 32k+1 buffers: that last buffer raises the interrupt which tells
             the driver the block's buffers are complete. read() them, then disable the writer.

read() and write() copy through the kernel's own mapping of the DMA buffers. The driver's mmap() gives a cached
user mapping of memory the kernel maps for DMA, which is not safe on a host whose PCIe is not cache coherent
(a Pi 5), so it is not used.

CSRs are read and written through the driver's register ioctl, so nothing here maps BAR0 while litepcie.ko
holds it. `csrs` is anything with `.addr(name)` (check.Csrs, from the running build's csr.json).

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import fcntl
import os
import random
import struct
import time

DEVICE = "/dev/litepcie0"
MODULE_PACKAGE = "fpgas-online-acorn-litepcie-module"  # virtual: the DKMS package or a prebuilt -modules-<kver>

# litepcie's kernel/config.h. The driver packages are built from the same litepcie (uv.lock), and
# tests/test_acorn_dma.py holds these equal to the generated driver's config.h.
DMA_BUFFER_SIZE = 8192
DMA_BUFFER_COUNT = 256
DMA_BUFFER_PER_IRQ = 32
WORD = 8  # the bridge's DRAM ports and the DMA streams are 64 bits wide
BUFFER_WORDS = DMA_BUFFER_SIZE // WORD

# write() fills the ring only while fewer than half of it is waiting, and read() drops buffers once more than
# half of it is waiting. A block is moved in chunks that stay well inside both.
TO_DRAM_CHUNK_BUFFERS = 64
FROM_DRAM_CHUNK_BUFFERS = 2 * DMA_BUFFER_PER_IRQ  # with the padding: 65 buffers in the ring

BIG_BYTES = 32 << 20  # the timed block of the boot check: about a second on a Pi 5
SEED = 29

MODE_TO_DRAM, MODE_FROM_DRAM = 1, 2  # pcie_dram_bridge.py
DFII_CONTROL_SEL = 1  # sdram_dfii_control bit 0: the controller, not the BIOS, drives the DRAM

USED_CSRS = (
    *(f"pcie_dram_{reg}" for reg in ("base", "length", "mode", "start", "done", "count")),
    "sdram_dfii_control",
)


def _ioc(direction, nr, size):
    return (direction << 30) | (size << 16) | (ord("S") << 8) | nr


_IOC_WRITE, _IOC_READ = 1, 2
# kernel/litepcie.h. The structs have the same layout for 32-bit ARM and arm64 (packaging/acorn-litepcie/
# struct_layout.c asserts it), so one format serves an armhf Python on an arm64 kernel.
REG = struct.Struct("=IIB3x")  # addr, val, is_write
DMA = struct.Struct("=B")  # loopback_enable
DMA_DIR = struct.Struct("=B7xqq")  # enable, hw_count, sw_count
LOCK = struct.Struct("=6B")  # reader/writer request, reader/writer release, reader/writer status
IOCTL_REG = _ioc(_IOC_READ | _IOC_WRITE, 0, REG.size)
IOCTL_DMA = _ioc(_IOC_WRITE, 20, DMA.size)
IOCTL_DMA_WRITER = _ioc(_IOC_READ | _IOC_WRITE, 21, DMA_DIR.size)
IOCTL_DMA_READER = _ioc(_IOC_READ | _IOC_WRITE, 22, DMA_DIR.size)
IOCTL_LOCK = _ioc(_IOC_READ | _IOC_WRITE, 25, LOCK.size)


class DMAError(Exception):
    """A transfer that did not do what was asked: the message says what was seen."""


INSTALL = (
    f"install {MODULE_PACKAGE}: the prebuilt fpgas-online-acorn-litepcie-modules-<kernel> package for this "
    "kernel (`uname -r`), or fpgas-online-acorn-litepcie-dkms"
)


def module_missing(device=DEVICE, exists=os.path.exists):
    """Why the DMA cannot be used on this host, or None: litepcie.ko gives /dev/litepcie0 when it is bound."""
    if exists(device):
        return None
    return f"{device} is not there: litepcie.ko is not loaded. To have it, {INSTALL}, then `modprobe litepcie`"


def chunks(nwords, chunk_buffers):
    """(offset, words) pieces of a block of `nwords`, each at most `chunk_buffers` DMA buffers."""
    step = chunk_buffers * BUFFER_WORDS
    return [(at, min(step, nwords - at)) for at in range(0, nwords, step)]


def padded_buffers(nwords):
    """How many buffers a from-DRAM chunk of `nwords` is padded to: the first 32k+1 that covers it, so that
    the interrupt after buffer 32k tells the driver every buffer of the chunk is complete."""
    need = -(-nwords // BUFFER_WORDS)
    return -(-need // DMA_BUFFER_PER_IRQ) * DMA_BUFFER_PER_IRQ + 1


class Bridge:
    """litepcie.ko's device and the SoC's PCIeDRAMBridge. `opener(path) -> fd` and `ioctl(fd, request, buf)`
    are os.open and fcntl.ioctl unless a test says otherwise."""

    def __init__(self, csrs, device=DEVICE, opener=None, ioctl=None, clock=time.monotonic, sleep=time.sleep,
                 read=os.read, write=os.write, close=os.close):  # fmt: skip
        self.csrs = csrs
        self._ioctl = ioctl or fcntl.ioctl
        self._clock, self._sleep, self._read, self._write, self._close = clock, sleep, read, write, close
        self.fd = (opener or (lambda path: os.open(path, os.O_RDWR)))(device)
        self.locked = False

    # -- the driver ------------------------------------------------------------------------------------

    def reg_read(self, addr):
        buf = bytearray(REG.pack(addr, 0, 0))
        self._ioctl(self.fd, IOCTL_REG, buf)
        return REG.unpack(buf)[1]

    def reg_write(self, addr, value):
        self._ioctl(self.fd, IOCTL_REG, bytearray(REG.pack(addr, value, 1)))

    read, write = reg_read, reg_write  # a bus, as check.py's readers take one

    def __getitem__(self, name):
        return self.reg_read(self.csrs.addr(name))

    def __setitem__(self, name, value):
        self.reg_write(self.csrs.addr(name), value)

    def lock(self):
        """Take both directions of the channel: the driver then stops them when this file is closed, however
        it is closed. Raises if another process has either."""
        buf = bytearray(LOCK.pack(1, 1, 0, 0, 0, 0))
        self._ioctl(self.fd, IOCTL_LOCK, buf)
        *_, reader, writer = LOCK.unpack(buf)
        if not (reader and writer):
            # the driver took whichever was free: give it back
            self._ioctl(self.fd, IOCTL_LOCK, bytearray(LOCK.pack(0, 0, reader, writer, 0, 0)))
            raise DMAError("another process is using the DMA channel")
        self.locked = True

    def loopback(self, enable):
        self._ioctl(self.fd, IOCTL_DMA, bytearray(DMA.pack(1 if enable else 0)))

    def _direction(self, request, enable):
        buf = bytearray(DMA_DIR.pack(1 if enable else 0, 0, 0))
        self._ioctl(self.fd, request, buf)
        return DMA_DIR.unpack(buf)[1]  # hw_count

    def reader(self, enable):
        """The DMA reader: host RAM to the FPGA."""
        return self._direction(IOCTL_DMA_READER, enable)

    def writer(self, enable):
        """The DMA writer: the FPGA to host RAM. Returns the buffers the driver knows are complete."""
        return self._direction(IOCTL_DMA_WRITER, enable)

    def close(self):
        if self.fd is None:
            return
        try:
            self.reader(False)
            self.writer(False)
        finally:
            self._close(self.fd)
            self.fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- the bridge ------------------------------------------------------------------------------------

    def dram_ready(self):
        """The BIOS has handed the DRAM to the controller. Until it has, the bridge's ports do nothing."""
        return bool(self["sdram_dfii_control"] & DFII_CONTROL_SEL)

    def _start(self, base, nwords, mode):
        self["pcie_dram_base"] = base
        self["pcie_dram_length"] = nwords
        self["pcie_dram_mode"] = mode
        self["pcie_dram_start"] = 1

    def _wait_done(self, nwords, what, timeout_s):
        deadline = self._clock() + timeout_s
        while not self["pcie_dram_done"]:
            if self._clock() > deadline:
                moved = self["pcie_dram_count"]
                raise DMAError(f"{what}: not done after {timeout_s} s, {moved} of {nwords} words moved")
            self._sleep(0.0005)
        count = self["pcie_dram_count"]
        if count != nwords:
            raise DMAError(f"{what}: done with {count} words moved, not {nwords}")

    def _to_dram_chunk(self, base, data, timeout_s):
        nwords = len(data) // WORD
        what = f"{nwords} words to DRAM word {base:#x}"
        padded = data + bytes(-len(data) % DMA_BUFFER_SIZE)
        wrote = self._write(self.fd, padded)  # the reader is off: this fills the ring from buffer 0
        if wrote != len(padded):
            raise DMAError(f"{what}: the driver took {wrote} of {len(padded)} bytes")
        self._start(base, nwords, MODE_TO_DRAM)
        self.reader(True)
        try:
            self._wait_done(nwords, what, timeout_s)
        finally:
            self.reader(False)

    def to_dram(self, base, data, timeout_s=10.0):
        """Write `data` (whole 64-bit words) to DRAM words base, base+1, ..."""
        if len(data) % WORD:
            raise ValueError(f"{len(data)} bytes is not a whole number of {WORD}-byte words")
        data = bytes(data)
        if not data:
            self._start(base, 0, MODE_TO_DRAM)
            self._wait_done(0, f"0 words to DRAM word {base:#x}", timeout_s)
        for at, n in chunks(len(data) // WORD, TO_DRAM_CHUNK_BUFFERS):
            self._to_dram_chunk(base + at, data[at * WORD : (at + n) * WORD], timeout_s)

    def _from_dram_chunk(self, base, nwords, timeout_s):
        what = f"{nwords} words from DRAM word {base:#x}"
        need = -(-nwords // BUFFER_WORDS)
        total = padded_buffers(nwords)
        self.writer(True)
        try:
            self._start(base, nwords, MODE_FROM_DRAM)
            self._wait_done(nwords, what, timeout_s)
            pad = total * BUFFER_WORDS - nwords
            self._start(0, pad, MODE_FROM_DRAM)  # padding: read again from the bottom of the DRAM
            self._wait_done(pad, f"{what}: its {pad} words of padding", timeout_s)
            deadline = self._clock() + timeout_s
            while (complete := self.writer(True)) < need:
                if self._clock() > deadline:
                    raise DMAError(f"{what}: the driver saw {complete} of {need} buffers complete in {timeout_s} s")
                self._sleep(0.0005)
            got = bytearray()
            while len(got) < need * DMA_BUFFER_SIZE:
                piece = self._read(self.fd, need * DMA_BUFFER_SIZE - len(got))
                if not piece:
                    raise DMAError(f"{what}: the driver gave {len(got)} of {need * DMA_BUFFER_SIZE} bytes")
                got += piece
        finally:
            self.writer(False)
        return bytes(got[: nwords * WORD])

    def from_dram(self, base, nwords, timeout_s=10.0):
        """Read DRAM words base, base+1, ... (`nwords` of them)."""
        if nwords == 0:
            self._start(base, 0, MODE_FROM_DRAM)
            self._wait_done(0, f"0 words from DRAM word {base:#x}", timeout_s)
        pieces = chunks(nwords, FROM_DRAM_CHUNK_BUFFERS)
        return b"".join(self._from_dram_chunk(base + at, n, timeout_s) for at, n in pieces)


# -- the check ---------------------------------------------------------------------------------------------


def first_difference(got, want):
    """Where two blocks differ, as a sentence; None if they are the same."""
    if len(got) != len(want):
        return f"{len(got)} bytes came back, not {len(want)}"
    for i in range(0, len(want), WORD):
        if got[i : i + WORD] != want[i : i + WORD]:
            return f"word {i // WORD} is {got[i : i + WORD].hex()}, not {want[i : i + WORD].hex()}"
    return None


def exercise(bridge, dram_words, big_bytes=BIG_BYTES, seed=SEED, clock=time.monotonic):
    """Blocks written to the DRAM and read back, every byte compared. Returns (measurements, faults).

      * short blocks whose ends fall part-way through a DMA buffer and part-way through a controller word, at
        the bottom, in the middle and at the very top of the DRAM;
      * a block in which every word holds its own address, read back from part-way in: a bridge that ignored
        the base passes a round trip and fails this;
      * `big_bytes` in one block, timed in each direction.

    A transfer that does not finish ends the check there: the bridge is then mid-transfer and takes no other.
    """
    rng = random.Random(seed)
    b = BUFFER_WORDS
    out, faults = {"bytes": big_bytes}, []

    def round_trip(base, nwords):
        data = rng.randbytes(nwords * WORD)
        bridge.to_dram(base, data)
        diff = first_difference(bridge.from_dram(base, nwords), data)
        if diff:
            faults.append(f"{nwords} words written to DRAM word {base:#x} read back wrong: {diff}")

    try:
        for nwords, base in ((1, 1), (b + 1, dram_words // 2 + 1), (2 * b + 3, max(0, dram_words - (2 * b + 3)))):
            round_trip(base, nwords)
        base = dram_words // 4 + 7
        bridge.to_dram(base, b"".join(struct.pack("<Q", w) for w in range(base, base + 2 * b)))
        for offset, n in ((5, 3), (b - 1, 2)):
            want = b"".join(struct.pack("<Q", w) for w in range(base + offset, base + offset + n))
            diff = first_difference(bridge.from_dram(base + offset, n), want)
            if diff:
                faults.append(f"{n} words read from DRAM word {base + offset:#x} are not the words there: {diff}")
        data = rng.randbytes(big_bytes - big_bytes % WORD)
        base = dram_words // 2
        t0 = clock()
        bridge.to_dram(base, data)
        t1 = clock()
        back = bridge.from_dram(base, len(data) // WORD)
        t2 = clock()
        diff = first_difference(back, data)
        if diff:
            faults.append(f"{len(data)} bytes written to DRAM word {base:#x} read back wrong: {diff}")
        out["to_dram_MBps"] = round(len(data) / (t1 - t0) / 1e6, 1) if t1 > t0 else 0.0
        out["from_dram_MBps"] = round(len(data) / (t2 - t1) / 1e6, 1) if t2 > t1 else 0.0
    except DMAError as e:
        faults.append(str(e))
    return out, faults


# -- the driver --------------------------------------------------------------------------------------------

MODULES = ("litepcie", "liteuart")  # in the order they are removed


def loaded_modules(run):
    """Which of the driver's modules the kernel has loaded."""
    rc, out = run(["lsmod"], 10)
    names = {line.split()[0] for line in out.splitlines()[1:] if line.split()} if rc == 0 else set()
    return [m for m in MODULES if m in names]


def load_driver(run, device=DEVICE, exists=os.path.exists, sleep=time.sleep, wait_s=5.0):
    """Have litepcie.ko bound and its device there. Returns (note, why_not): `note` says what was done, for
    unload_driver(); `why_not` is why the DMA cannot be used here, naming the package to install."""
    before = loaded_modules(run)
    if exists(device):
        return {"driver": "was loaded", "loaded": []}, None
    rc, out = run(["modprobe", "litepcie"], 30)
    note = {"driver": "loaded for the test", "loaded": [m for m in loaded_modules(run) if m not in before]}
    if rc != 0:
        said = " ".join(out.split())[:200]
        return note, f"litepcie.ko could not be loaded ({said}). To have it, {INSTALL}"
    waited = 0.0
    while not exists(device) and waited < wait_s:  # udev makes the node
        sleep(0.05)
        waited += 0.05
    if not exists(device):
        return note, f"litepcie.ko loaded but {device} did not appear within {wait_s} s: it did not bind to the board"
    note["loaded"] = [m for m in loaded_modules(run) if m not in before]
    return note, None


def unload_driver(run, note):
    """Remove the modules load_driver() loaded, so the host is left as it was found. Returns the faults."""
    faults = []
    for module in note.get("loaded", []):
        rc, out = run(["rmmod", module], 30)
        if rc != 0:
            faults.append(f"{module}.ko, loaded for the DMA test, could not be removed: {out.strip()[:200]}")
    return faults
