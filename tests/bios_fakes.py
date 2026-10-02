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
    def __init__(self, replies=None, stale=b"", silent=False, deaf_newlines=0):
        self.replies = dict(replies or {})  # command -> the bytes printed before the next prompt
        self.rx = bytearray(stale)  # what the host will read: `stale` is output from before it opened the port
        self.silent = silent  # nothing is listening
        self.deaf_newlines = deaf_newlines  # still booting: this many newlines go unanswered
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

    def read(self, size=1):
        if not self.rx:
            self.now += self.timeout or 0.0
            return b""
        out = bytes(self.rx[:size])
        del self.rx[:size]
        return out
