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
DRAIN_S = 5.0  # a port that never goes quiet (noise, a design printing without end) is drained this long
ECHO_TIMEOUT_S = 1.0  # how long one typed byte is given to come back


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


def open_port(port, baud):
    import serial

    return serial.Serial(port, baud, timeout=1)


def run_script(test, title, board, port, baud, run):
    """A host test script's main: open the port, run(BiosConsole) -> the result's fields, report, exit code.

    Whatever happens to the port, the output ends with RESULT: PASS or FAIL and the RESULT_JSON line."""
    print(f"Opening {port} at {baud} baud...")
    print(f"Board: {board}")
    print()
    found = {"test": test, "board": board, "result": "fail"}
    try:
        ser = open_port(port, baud)
    except (OSError, ImportError) as e:  # no such port, port in use, no pyserial
        found["reason"] = f"cannot open {port}: {e}"
        print(f"FAIL: {found['reason']}")
    else:
        try:
            found = run(BiosConsole(ser, clock=time.monotonic))
        except OSError as e:  # the port went away (pyserial's SerialException is one)
            found["reason"] = f"the UART failed: {e}"
            print(f"FAIL: {found['reason']}")
        finally:
            close = getattr(ser, "close", None)
            if close:
                close()
    print()
    if found["result"] == "pass":
        print(f"RESULT: PASS — {title} completed successfully")
    else:
        print(f"RESULT: FAIL — {title} had failures")
    print_result_json(found)
    return 0 if found["result"] == "pass" else 1


class BiosConsole:
    def __init__(self, ser, clock=time.monotonic):
        self.ser = ser
        self.clock = clock
        self.stale = ""  # what was waiting in the port when attach() started

    def _drain(self):
        """Everything that arrives until the port is quiet, or for DRAIN_S at most."""
        self.ser.timeout = QUIET_S
        deadline = self.clock() + DRAIN_S
        data = b""
        while self.clock() < deadline:
            chunk = self.ser.read(4096)
            if not chunk:
                break
            data += chunk
        return strip_ansi(data.decode("utf-8", errors="replace"))

    def _until_prompt(self, timeout):
        """(text, whether it ends with the prompt): reads until the prompt is the last thing received."""
        self.ser.timeout = READ_S
        deadline = self.clock() + timeout
        data = b""
        while self.clock() < deadline:
            # One byte, or all that is already waiting: a read for more would sit out its whole timeout
            # after a short reply.
            chunk = self.ser.read(max(1, getattr(self.ser, "in_waiting", 0)))
            if not chunk:
                continue
            data += chunk
            tail = strip_ansi(data[-64:].decode("utf-8", errors="replace"))
            # With the space that ends it ("litex> "): the space can arrive after the read that brought the
            # ">", and one left in the port is read as the echo of the next byte typed.
            if tail.endswith(PROMPT + " "):
                return strip_ansi(data.decode("utf-8", errors="replace")), True
        return strip_ansi(data.decode("utf-8", errors="replace")), False

    def attach(self, timeout=ATTACH_TIMEOUT_S):
        """Get the BIOS to its prompt: discard what was waiting, then send newlines until a prompt answers.

        A design that only echoes does not pass: the prompt has to come back, not the newline. Nor does old
        output that ends with a prompt and arrives after the drain (the TT FPGA's bridge hands over what the
        design printed at start once the port is open): a prompt only counts once a second newline, sent
        with nothing left waiting, brings another."""
        self.stale = self._drain()
        deadline = self.clock() + timeout
        seen = ""
        while self.clock() < deadline:
            self.ser.write(b"\n")
            text, found = self._until_prompt(ATTACH_STEP_S)
            seen += text
            if not found:
                continue
            self._drain()  # the prompts of earlier newlines, if the BIOS was still booting
            self.ser.write(b"\n")
            text, found = self._until_prompt(ATTACH_STEP_S)
            seen += text
            if found:
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

    def echo(self, data, timeout=ECHO_TIMEOUT_S):
        """Type `data` a byte at a time, without ending the line, and read each byte's echo.

        Returns (sent, got) for every byte that did not come back as itself; `got` is None when nothing came
        back in `timeout` seconds. End the line with command("") afterwards."""
        self.ser.timeout = READ_S
        wrong = []
        for byte in bytes(data):
            self.ser.write(bytes([byte]))
            deadline = self.clock() + timeout
            got = b""
            while not got and self.clock() < deadline:
                got = self.ser.read(1)
            if got != bytes([byte]):
                wrong.append((byte, got[0] if got else None))
        return wrong

    def ident(self):
        """The SoC's identifier (SoCCore's ident plus the build time), or None if the BIOS has none."""
        for line in self.command("ident"):
            if line.startswith("Ident:"):
                return line[len("Ident:") :].strip()
        return None
