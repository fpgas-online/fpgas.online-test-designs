"""TT FPGA Demo Board (iCE40UP5K behind an RP2350): found by the RP2350 on USB, loaded through it (tt_fpga_program.py,
over mpremote). The FPGA's UART reaches the Pi only through the RP2350, so the UART test runs
through tt_test_wrapper.py's bridge, which loads the design too. There is no SPI-flash test: the breakout has
no flash (docs/hardware/tt-fpga.md).

Nothing is written to the demo board: for every load the RP2350 reads the bitstream from the Pi over the serial
link (tt_fpga_program.py, `mpremote mount`). The board has no flash of its own to compare, so the state is the
RP2350's USB serial number. Loading needs mpremote (micropython-mpremote: in trixie, and only
bookworm-backports for bookworm).

Who the board is, for rpi-hwid's Tiny Tapeout label, comes from `rpi-hwid tinytapeout --json --no-stop-service`,
run while the check holds the RP2350's port (fpgas-tt.service stopped) and before any test loads a design: it
asks the Tiny Tapeout SDK on the RP2350 over its REPL. rpi-hwid is optional: it is found on PATH and run, never
imported. Without it those fields are not read and the identity says so in tinytapeout_note; the board does not
fail for it. When rpi-hwid is there but cannot say who the board is, the identity has tinytapeout_error and the
check is an error.

rpi-hwid reads only what the SDK built when the board started, so the board's SDK is started first
(tt_sdk_start.py: a soft reset from the friendly REPL, which runs the board's main.py). A board whose main.py is
not the SDK's does not start it, and that is an error with its own reason."""

import json
import shutil
import sys
from typing import ClassVar

from .. import host_tests, identity
from ..core import Problem, run, tail
from ..testbench import TestBoard

RPI_HWID = "rpi-hwid"
# The command reads every MicroPython RP2 board on USB, each REPL read with its own 10 s deadline.
RPI_HWID_TIMEOUT = 60
# --no-stop-service: the check has already stopped fpgas-tt.service, and starts it again itself.
RPI_HWID_ARGS = ("tinytapeout", "--json", "--no-stop-service")
NOT_INSTALLED = "not read: rpi-hwid is not installed (python3-rpi-hwid, or `uv tool install rpi-hwid`)"
# tt_sdk_start.py soft-resets the board from the friendly REPL and waits for the SDK's last boot line: its own
# limit is 45 s, and the SDK takes a few seconds.
SDK_START_TIMEOUT = 75
# tt_main_py.py reads two files on the board through mpremote; its own limit is 60 s.
MAIN_PY_TIMEOUT = 90
# The identity fields rpi-hwid gives: TinyTapeoutBoard's, less usb_serial, which finding the board gives.
RPI_HWID_FIELDS = tuple(f for f in identity.TINYTAPEOUT_FIELDS if f != "usb_serial")
# The fields every TT FPGA board has a value for: its RP2350, its chip (the FPGA), the demo board it sits on and
# the SDK that answered. rpi-hwid gives null for one of these only when its read failed (the machine string, the
# chip ROM or the demo board detection), so null here is an error, never "there is none". shuttle, repo, commit
# and demoboard_version can be null: the FPGA has no shuttle, so no ROM repository and no shuttle kit.
ALWAYS_THERE = ("mcu", "chip", "demoboard", "sdk")


def which(name):
    """shutil.which, here so the tests can say whether rpi-hwid is installed."""
    return shutil.which(name)


def _json_document(text):
    """The JSON object rpi-hwid printed: from the first line that starts one to the end of that object (its
    stderr, if any, follows it in `text`)."""
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.startswith("{")), None)
    if start is None:
        raise ValueError("no JSON document in its output")
    doc, _ = json.JSONDecoder().raw_decode("".join(lines[start:]))
    if not isinstance(doc, dict):
        raise ValueError("its output is not a JSON object")
    return doc


def main_py_changed(port, runner=run):
    """None when the board's main.py is the SDK's own (tt_main_py.py: a read of its SHA-256), else why not.

    Visitors have the board's Python prompt, so a visitor can replace or edit main.py; nothing of ours writes
    to the board. A changed main.py is said as that, before anything relies on it. Never raises."""
    try:
        rc, text = runner([sys.executable, host_tests.path("tt_main_py.py"), port], MAIN_PY_TIMEOUT)
    except Problem as p:
        return f"the demo board's main.py is not known to be the SDK's own: it could not be checked: {p.reason}"
    if rc == 0:
        return None
    said = [line for line in text.splitlines() if line.startswith("MAIN_PY:")] or tail(text, 2)
    return f"the demo board's main.py is not known to be the SDK's own: {' '.join(said)}"


def sdk_start(port, runner=run):
    """Start the Tiny Tapeout SDK on the board at `port` (tt_sdk_start.py); None when it came up, else why not.

    rpi-hwid only reads what the SDK built when the board started (its `tt` object, the chip ROM it cached, the
    demo board it detected), and that is gone after any raw-REPL soft reset, which is how the last check left the
    board. So the board is started again before it is asked who it is. Never raises."""
    try:
        rc, text = runner([sys.executable, host_tests.path("tt_sdk_start.py"), port], SDK_START_TIMEOUT)
    except Problem as p:
        return f"the Tiny Tapeout SDK could not be started on the demo board: {p.reason}"
    if rc == 0:
        return None
    said = [line for line in text.splitlines() if line.startswith("SDK_START:")] or tail(text, 2)
    return f"the Tiny Tapeout SDK did not start on the demo board: {' '.join(said)}"


def tinytapeout_fields(usb_serial, runner=run):
    """The TinyTapeoutBoard fields rpi-hwid reads for the board whose USB serial is `usb_serial`, under its
    names; {"tinytapeout_note": ...} when rpi-hwid is not installed; {"tinytapeout_error": ...} when it could
    not say. Never raises."""
    tool = which(RPI_HWID)
    if tool is None:
        return {"tinytapeout_note": NOT_INSTALLED}
    command = " ".join([RPI_HWID, *RPI_HWID_ARGS])
    try:
        rc, text = runner([tool, *RPI_HWID_ARGS], RPI_HWID_TIMEOUT)
    except Problem as p:
        return {"tinytapeout_error": f"{command}: {p.reason}"}
    if rc != 0:
        return {"tinytapeout_error": f"{command} exited {rc}: {' '.join(tail(text, 3))}"}
    try:
        boards = _json_document(text).get("boards")
    except ValueError as e:
        return {"tinytapeout_error": f"{command}: {e}: {' '.join(tail(text, 3))}"}
    if not isinstance(boards, list):
        return {"tinytapeout_error": f"{command}: its document has no list of boards"}
    board = next((b for b in boards if isinstance(b, dict) and b.get("usb_serial") == usb_serial), None)
    if board is None:
        return {"tinytapeout_error": f"{command} did not see the board with USB serial {usb_serial}"}
    if board.get("kind") != "tinytapeout":  # a MicroPython RP2 whose REPL did not answer as the SDK does
        return {"tinytapeout_error": f"{command}: not a Tiny Tapeout board: {board.get('how') or board.get('kind')}"}
    # Only the fields rpi-hwid gave: one it left out was not read, so it stays out (never null, which is "read,
    # and there is none"), and --identify says it is missing.
    out = {k: board[k] for k in RPI_HWID_FIELDS if k in board}
    bad = [k for k, v in out.items() if v is not None and not isinstance(v, str)]
    if bad:
        return {"tinytapeout_error": f"{command}: not text: {', '.join(f'{k}={out[k]!r}' for k in bad)}"}
    empty = [k for k, v in out.items() if v == ""]  # an identity field is never present and empty
    if empty:
        return {"tinytapeout_error": f"{command}: empty: {', '.join(empty)}"}
    unread = [k for k in ALWAYS_THERE if k in out and out[k] is None]
    if unread:
        return {"tinytapeout_error": f"{command}: rpi-hwid could not read {', '.join(unread)}"}
    return out


PMOD_PRE = [["rmmod", "spidev", "spi_bcm2835"]]


class TTFPGA(TestBoard):
    name = "tt"
    slug = "tt-fpga"  # fpgas-online-tt is the TT site's own package
    title = "TT FPGA Demo Board"
    doc = "tt-fpga.md"
    usb = (("2e8a", None),)  # any Raspberry Pi USB product: the RP2350 running MicroPython
    variants: ClassVar[dict] = {"tt-fpga": "tt-fpga"}
    # rpi-hwid's Tiny Tapeout label (its LABEL-CONTRACT.md, sections 1 and 7). Only the boot check reads the
    # fields rpi-hwid gives (it owns the port then): --identify takes them, and why they are missing, from the
    # boot report, matched by usb_serial.
    label_fields = ("usb_serial", "mcu", "chip", "demoboard", "demoboard_version", "sdk")
    report_fields = (*RPI_HWID_FIELDS, "tinytapeout_")
    port = "/dev/ttyACM0"
    services = ("fpgas-tt.service",)  # the TT site's bridge keeps the RP2350's port open while it runs
    flash_note = "none: the FPGA breakout has no SPI flash; the RP2350 loads each bitstream from the Pi"
    # Run in this order, and the board is left with the last design loaded (testbench.py): the pin-ID scan
    # comes first, so a UART-bridge design (one TX pin) is what stays, not one driving every Pmod line.
    tests: ClassVar[dict] = {
        # The Pmod HAT cabling, against identify_pmod_pins.BOARDS["tt"] (ui_in on HAT JA, uio JB, uo_out JC).
        "pin-id": {"artifact": "pmod-pin-id-{v}/tt_fpga_platform.bin", "script": "identify_pmod_pins.py",
                   "args": ["--board", "tt"], "pre": PMOD_PRE, "program_args": ["--gpio-release"],
                   "verify": True},
        "uart": {"artifact": "uart-test-tt-fpga/tt_fpga_platform.bin", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "tt", "--skip-banner"], "verify": True,
                 "runner": "tt-bridge"},
        "pmod": {"artifact": "gpio-loopback-{v}/tt_fpga_platform.bin", "script": "test_pmod_loopback.py",
                 "args": ["--board", "tt"], "pre": PMOD_PRE, "program_args": ["--gpio-release"]},
    }  # fmt: skip

    def port_facts(self, host, found, runner=run):
        if not found.get("serial"):
            return {}
        # Whether main.py is still the SDK's own needs only the port, so it is said with or without rpi-hwid.
        why_not = main_py_changed(host["port"], runner)
        if why_not:
            return {"tinytapeout_error": why_not}
        if which(RPI_HWID) is None:  # nothing would ask the board who it is: its SDK is not started
            return {"tinytapeout_note": NOT_INSTALLED}
        why_not = sdk_start(host["port"], runner)
        if why_not:
            return {"tinytapeout_error": why_not}
        return tinytapeout_fields(found["serial"], runner)

    def program_argv(self, bitstream, host, test):
        extra = self.tests.get(test, {}).get("program_args", [])
        return [sys.executable, host_tests.path("tt_fpga_program.py"), host["port"], bitstream, *extra]


BOARD = TTFPGA()
