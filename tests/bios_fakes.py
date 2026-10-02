"""A fake serial port with a LiteX BIOS behind it, for the host test scripts' unit tests.

It echoes what is typed, runs a command on newline and ends every reply with the BIOS's coloured prompt, as
the BIOS on the Arty and NeTV2 does (transcripts taken on pi-sw2-p9 and pi-sw1-p12, 2026-10-02). Time is
faked: a read that finds nothing advances the clock by the port's timeout.

The failure modes have their own switches (`silent`, `deaf_newlines`, `stale`), since a fake that always
answers tests none of the code that waits or gives up.
"""

PROMPT = b"\x1b[92;1mlitex\x1b[0m> "
NL = b"\n\r"  # the BIOS's line ending


def lines(*text):
    return NL.join(t.encode() for t in text) + NL


class FakeBios:
    def __init__(self, replies=None, stale=b"", silent=False, deaf_newlines=0, chunk=None):
        self.replies = dict(replies or {})  # command -> the bytes printed before the next prompt
        self.rx = bytearray(stale)  # what the host will read: `stale` is output from before it opened the port
        self.silent = silent  # nothing is listening
        self.deaf_newlines = deaf_newlines  # still booting: this many newlines go unanswered
        self.chunk = chunk  # at most this many bytes per read, as a slow UART delivers them
        self.timeout = None
        self.now = 0.0
        self.typed = bytearray()
        self.commands = []

    def clock(self):
        return self.now

    def write(self, data):
        if self.silent:
            return len(data)
        for byte in bytes(data):
            if byte != 0x0A:
                self.typed.append(byte)
                self.rx.append(byte)  # echo
                continue
            command = bytes(self.typed).decode()
            self.typed.clear()
            if self.deaf_newlines:
                self.deaf_newlines -= 1
                continue
            self.commands.append(command)
            self.rx += NL
            if command:
                self.rx += self.reply(command)
            self.rx += PROMPT
        return len(data)

    def reply(self, command):
        return self.replies.get(command, lines("Command not found"))

    @property
    def in_waiting(self):
        return min(len(self.rx), self.chunk or len(self.rx))

    def read(self, size=1):
        if not self.rx:
            self.now += self.timeout or 0.0
            return b""
        size = min(size, self.chunk or size)
        out = bytes(self.rx[:size])
        del self.rx[:size]
        return out


# -- replies of the DDR test design, as the Welland boards gave them ----------------------------------------


def leveling(modules, good=True):
    """Read leveling of `modules` byte lanes: a window at bitslip 1 on each, or none anywhere."""
    out = ["Read leveling:"]
    for m in range(modules):
        for b in range(8):
            window = good and b == 1
            scan = "01111111111111111111111111111100" if window else "0" * 32
            out.append(f"  m{m}, b{b:02d}: |{scan}| delays: {'14+-14' if window else '-'}")
        out.append(f"  best: m{m}, b{1 if good else 0:02d} delays: {'14+-14' if good else '-'}")
    return out


def memtest(size="2.0MiB", ok=True, words=524288):
    progress = (
        f"  Write: 0x40000000-0x40000000 0B   \r  Write: 0x40000000-0x40200000 {size}   \r\n\r"
        f"   Read: 0x40000000-0x40000000 0B   \r   Read: 0x40000000-0x40200000 {size}   \r"
    ).encode() + NL
    head = lines(f"Memtest at 0x40000000 ({size})...") + progress
    if ok:
        return head + lines("Memtest OK")
    return head + lines(
        "  bus errors:  256/256", "  addr errors: 0/8192", f"  data errors: {words}/{words}", "Memtest KO"
    )


def sdram_init(modules, good=True):
    """`sdram_init`: leveling, the BIOS's 2 MiB memtest and, when that passes, its speed measurement."""
    head = lines("Initializing SDRAM @0x40000000...", "Switching SDRAM to software control.", *leveling(modules, good))
    tail = lines("Switching SDRAM to hardware control.") + memtest(ok=good)
    if good:
        tail += lines(
            "Memspeed at 0x40000000 (Sequential, 2.0MiB)...", "  Write speed: 27.2MiB/s", "   Read speed: 30.9MiB/s"
        )
    return head + tail + NL


MIB = 1024**2
# name in the ident, byte lanes, DRAM bytes
DDR_BOARDS = {
    "netv2": ("NeTV2", 4, 512 * MIB),
    "arty": ("Arty A7", 2, 256 * MIB),
    "acorn": ("Acorn/LiteFury", 2, 1024 * MIB),
}


def ddr_replies(board="netv2", good=True, ram=None):
    """The fixed replies of the DDR test design for `board`, built with `ram` bytes of DRAM."""
    name, modules, board_ram = DDR_BOARDS[board]
    ram = ram or board_ram
    test = f"{ram // 32 / MIB:.1f}MiB"
    return {
        "ident": lines(f"Ident: fpgas-online DDR Test SoC -- {name} 2026-10-01 11:00:01"),
        "mem_list": lines(
            "Available memory regions:",
            "ROM       0x00000000 0x20000 ",
            "SRAM      0x10000000 0x2000 ",
            f"MAIN_RAM  0x40000000 {ram:#x} ",
            "CSR       0xf0000000 0x10000 ",
        )
        + NL,
        "sdram_init": sdram_init(modules, good),
        "sdram_test": memtest(test, good, words=ram // 32 // 4) + NL,
    }


class FakeDdrBios(FakeBios):
    """The DDR test design's BIOS, with memory behind mem_write and mem_read.

    `declared` is the DRAM the design was built for, `real` what the board has: an address past `real`
    lands on the cell `real` bytes below it, as it does when the design drives an address bit the chip
    does not have. `stuck_bit` makes one address bit read as 0 (a broken address line). A write stays in
    the L2 cache, unseen by the DRAM, until flush_l2_cache.
    """

    BASE = 0x40000000

    def __init__(self, board="netv2", good=True, declared=None, real=None, stuck_bit=None, replies=None, **kwargs):
        self.declared = declared or DDR_BOARDS[board][2]
        self.real = real or self.declared
        self.stuck_bit = stuck_bit
        self.mem = {}
        self.cache = {}
        FakeBios.__init__(self, {**ddr_replies(board, good, self.declared), **(replies or {})}, **kwargs)

    def cell(self, addr):
        offset = (addr - self.BASE) % self.real
        if self.stuck_bit is not None:
            offset &= ~(1 << self.stuck_bit)
        return offset

    def reply(self, command):
        words = command.split()
        if words[0] == "mem_write":
            self.cache[int(words[1], 16)] = int(words[2], 16)
            return b""
        if words[0] == "flush_l2_cache":
            for addr, value in self.cache.items():
                self.mem[self.cell(addr)] = value
            self.cache.clear()
            return b""
        if words[0] == "mem_read":
            addr = int(words[1], 16)
            value = self.cache.get(addr, self.mem.get(self.cell(addr), 0))
            dump = " ".join(f"{b:02x}" for b in value.to_bytes(4, "little"))
            return lines("Memory dump:", f"{addr:#010x}  {dump}                                      ....")
        return FakeBios.reply(self, command)
