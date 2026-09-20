#!/usr/bin/env python3
"""Talk to the fpgas.online Acorn SoC over its UARTBone link (`/dev/ttyAMA0` on the Pi).

The SoC's UART comes out of reset at 1200 baud. `connect()` sends a break
(which puts the FPGA back at 1200 whatever it was doing), proves the link by
reading the ident string, and then moves both ends to 921600.

Self-contained on purpose: the Pi hosts boot a tmpfs root with pyserial but
no LiteX, so this speaks the UARTBone wire protocol directly instead of going
through `litex_server`. Wire format checked against
`litex/tools/remote/comm_uart.py`.

Run it directly for a quick link check:
    python3 uartbone_link.py [--port /dev/ttyAMA0] [--slow]
"""

import argparse
import sys
import time

SYS_CLK_FREQ = 100e6
RESET_BAUD = 1200
FAST_BAUD = 921600

CSR_BASE = 0xF0000000
IDENT_ADDR = CSR_BASE + 0x0800  # csr_map: identifier_mem = 1
TUNING_WORD_ADDR = CSR_BASE + 0x1800  # csr_map: uartbone = 3
IDENT_PREFIX = "fpgas-online"
IDENT_MAX = 256

CMD_WRITE = 0x01  # burst, incrementing address
CMD_READ = 0x02

# The PL011 on a Pi has a 16-byte RX FIFO and this link has no RTS/CTS, so a
# reply that fits the FIFO cannot overrun however late the interrupt is served.
MAX_READ_WORDS = 4
MAX_WRITE_WORDS = 8

BREAK_S = 0.1  # the FPGA wants 50 ms
BRIDGE_TIMEOUT_S = 1.0  # UARTBONE_TIMEOUT_MS in the gateware


class LinkError(Exception):
    pass


def tuning_word(baud, clk_freq=SYS_CLK_FREQ):
    """The RS232PHY phase increment for `baud`; must match the gateware's formula exactly."""
    return int((baud / clk_freq) * 2**32)


def baud_of(word, clk_freq=SYS_CLK_FREQ):
    return round(word * clk_freq / 2**32)


def read_request(addr, words):
    return bytes([CMD_READ, words]) + (addr // 4).to_bytes(4, "big")


def write_request(addr, values):
    body = b"".join(v.to_bytes(4, "big") for v in values)
    return bytes([CMD_WRITE, len(values)]) + (addr // 4).to_bytes(4, "big") + body


class UARTBoneLink:
    """`open_port(baud)` returns a pyserial-like object; `settle(seconds)` is `time.sleep` unless testing."""

    def __init__(self, open_port, settle=time.sleep):
        self._open_port = open_port
        self._settle = settle
        self.port = None
        self.baud = None

    # -- transport ---------------------------------------------------------------------------------

    def _open(self, baud):
        if self.port is not None:
            self.port.close()
        self.port = self._open_port(baud)
        self.baud = baud

    def _read_exact(self, n):
        # Time on the wire plus generous slack; a pyserial read returns b"" when it expires.
        self.port.timeout = n * 10 / self.baud + 0.25
        data = b""
        while len(data) < n:
            chunk = self.port.read(n - len(data))
            if not chunk:
                raise LinkError(f"timeout: {len(data)} of {n} bytes at {self.baud} baud")
            data += chunk
        return data

    def read(self, addr, words=1):
        out = []
        while len(out) < words:
            n = min(MAX_READ_WORDS, words - len(out))
            self.port.reset_input_buffer()
            self.port.write(read_request(addr + 4 * len(out), n))
            raw = self._read_exact(4 * n)
            out += [int.from_bytes(raw[i : i + 4], "big") for i in range(0, 4 * n, 4)]
        return out

    def write(self, addr, values):
        values = list(values)
        for i in range(0, len(values), MAX_WRITE_WORDS):
            self.port.write(write_request(addr + 4 * i, values[i : i + MAX_WRITE_WORDS]))

    def ident(self):
        chars = []
        while len(chars) < IDENT_MAX:
            for word in self.read(IDENT_ADDR + 4 * len(chars), MAX_READ_WORDS):
                if word == 0:
                    return "".join(chars)
                chars.append(chr(word & 0xFF))
        return "".join(chars)

    def _alive(self):
        """True when the far end answers with the start of our ident string."""
        try:
            first = self.read(IDENT_ADDR, MAX_READ_WORDS)
        except LinkError:
            return False
        return "".join(chr(w & 0xFF) for w in first) == IDENT_PREFIX[:MAX_READ_WORDS]

    # -- session -----------------------------------------------------------------------------------

    def connect(self, fast=True):
        """Bring the link up and return the baud rate it ended at.

        Policy: always start with a break. It costs 100 ms but means the result
        never depends on what state the last session left the FPGA in.
        """
        self._open(RESET_BAUD)
        self.port.send_break(BREAK_S)
        self._settle(0.05)
        if not self._alive():
            # A stray byte may have left the bridge mid-command; it gives up after BRIDGE_TIMEOUT_S.
            self._settle(BRIDGE_TIMEOUT_S + 0.1)
            if not self._alive():
                raise LinkError(f"no fpgas.online SoC answered at {RESET_BAUD} baud after a break")
        if not fast:
            return self.baud

        self.write(TUNING_WORD_ADDR, [tuning_word(FAST_BAUD)])
        self._settle(10 * 10 / RESET_BAUD + 0.02)  # let the 10-byte write drain at 1200 before reopening
        self._open(FAST_BAUD)
        if not self._alive():
            self.port.send_break(BREAK_S)
            raise LinkError(f"link worked at {RESET_BAUD} baud but not at {FAST_BAUD}; sent a break to restore it")
        return self.baud

    def close(self):
        if self.port is not None:
            self.port.close()
            self.port = None


def _serial_opener(device):
    import serial  # imported here so the unit tests need no pyserial

    return lambda baud: serial.Serial(device, baud, timeout=1)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--port", default="/dev/ttyAMA0")
    parser.add_argument("--slow", action="store_true", help=f"stay at {RESET_BAUD} baud")
    args = parser.parse_args()

    lk = UARTBoneLink(_serial_opener(args.port))
    try:
        baud = lk.connect(fast=not args.slow)
        print(f"baud:  {baud}")
        print(f"ident: {lk.ident()}")
        print("RESULT: PASS")
    except LinkError as e:
        print(f"error: {e}")
        print("RESULT: FAIL")
        return 1
    finally:
        lk.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
