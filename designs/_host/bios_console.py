"""Talk to the LiteX BIOS on a board's UART: find its prompt, then run commands and read their replies.

The host test scripts use this so that a test asks the design for what it checks, instead of reading what
the BIOS printed while it booted. That output is gone by the time a test opens the Pi's own UART (the
NeTV2's ttyAMA0 only receives while the port is open), and is old output on an FTDI UART (the Arty's chip
hands over the finished boot log when the port is opened).

    bios = BiosConsole(serial.Serial(port, 115200))
    bios.attach()                    # NoPrompt if no BIOS answers
    bios.ident()                     # "fpgas-online DDR Test SoC -- NeTV2 2026-10-01 11:00:01"
    bios.command("sdram_test", 120)  # the reply's lines, without the echo and the prompt

The BIOS prints its prompt in colour ("\\x1b[92;1mlitex\\x1b[0m> "), so "litex>" is only found once the
escape sequences are taken out.
"""

import json
import re
import time

PROMPT = "litex>"
ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
QUIET_S = 0.3  # the port is idle once nothing arrives for this long
READ_S = 0.2  # one read's timeout while waiting for a prompt
ATTACH_STEP_S = 2.0  # how long a newline is given to bring a prompt before the next one is sent
ATTACH_TIMEOUT_S = 30.0  # the BIOS waits a few seconds for a serial boot before its first prompt
COMMAND_TIMEOUT_S = 10.0


class NoPrompt(Exception):
    """The BIOS prompt did not appear. `output` is what did arrive, colour codes removed."""

    def __init__(self, message, output=""):
        Exception.__init__(self, message)
        self.output = output


def strip_ansi(text):
    return ANSI_RE.sub("", text)


def print_result_json(fields):
    """The script's result as one machine-readable line, for fpgas-verify: RESULT_JSON {...}"""
    print("RESULT_JSON " + json.dumps(fields, sort_keys=True), flush=True)


class BiosConsole:
    def __init__(self, ser, clock=time.monotonic):
        self.ser = ser
        self.clock = clock
        self.stale = ""  # what was waiting in the port when attach() started

    def _drain(self):
        """Everything that arrives until the port is quiet."""
        self.ser.timeout = QUIET_S
        data = b""
        while True:
            chunk = self.ser.read(4096)
            if not chunk:
                return strip_ansi(data.decode("utf-8", errors="replace"))
            data += chunk

    def _until_prompt(self, timeout):
        """(text, whether it ends with the prompt): reads until the prompt is the last thing received."""
        self.ser.timeout = READ_S
        deadline = self.clock() + timeout
        data = b""
        while self.clock() < deadline:
            chunk = self.ser.read(4096)
            if not chunk:
                continue
            data += chunk
            tail = strip_ansi(data[-64:].decode("utf-8", errors="replace"))
            if tail.rstrip(" ").endswith(PROMPT):
                return strip_ansi(data.decode("utf-8", errors="replace")), True
        return strip_ansi(data.decode("utf-8", errors="replace")), False

    def attach(self, timeout=ATTACH_TIMEOUT_S):
        """Get the BIOS to its prompt: discard what was waiting, then send newlines until a prompt answers.

        A design that only echoes does not pass: the prompt has to come back, not the newline."""
        self.stale = self._drain()
        deadline = self.clock() + timeout
        seen = ""
        while self.clock() < deadline:
            self.ser.write(b"\n")
            text, found = self._until_prompt(ATTACH_STEP_S)
            seen += text
            if found:
                self._drain()  # the prompts of earlier newlines, if the BIOS was still booting
                return
        raise NoPrompt(f"no BIOS prompt within {timeout:.0f} s", seen)

    def command(self, command, timeout=COMMAND_TIMEOUT_S):
        """Run one command; its reply as stripped, non-empty lines, without the echo and the next prompt.

        A line the BIOS rewrote with carriage returns (memtest's progress) is given as it ended."""
        self.ser.write(command.encode() + b"\n")
        text, found = self._until_prompt(timeout)
        if not found:
            raise NoPrompt(f"`{command}` did not return to the prompt within {timeout:.0f} s", text)
        text = text.rstrip(" ")[: -len(PROMPT)]
        reply = []
        for line in text.split("\n"):
            states = [s.strip() for s in line.split("\r") if s.strip()]
            if states:
                reply.append(states[-1])
        if reply and reply[0] == command:
            del reply[0]
        return reply

    def ident(self):
        """The SoC's identifier (SoCCore's ident plus the build time), or None if the BIOS has none."""
        for line in self.command("ident"):
            if line.startswith("Ident:"):
                return line[len("Ident:") :].strip()
        return None
