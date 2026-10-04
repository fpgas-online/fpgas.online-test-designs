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
                self.rx += self.replies.get(command, lines("Command not found"))
            self.rx += PROMPT
        return len(data)

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


def ddr_replies(board="netv2", good=True):
    name, modules, ram, test = {
        "netv2": ("NeTV2", 4, 0x40000000, "32.0MiB"),
        "arty": ("Arty A7", 2, 0x10000000, "8.0MiB"),
        "acorn": ("Acorn/LiteFury", 2, 0x40000000, "32.0MiB"),
    }[board]
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
        "sdram_test": memtest(test, good, words=8388608) + NL,
    }
