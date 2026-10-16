"""TT FPGA Demo Board (iCE40UP5K behind an RP2350): found by the RP2350 on USB, loaded through it (openFPGALoader's
tt_fpga board, over the RP2350's raw REPL). The FPGA's UART reaches the Pi only through the RP2350, so the UART test
runs through tt_test_wrapper.py's bridge, which loads the design too. There is no SPI-flash test: the breakout has
no flash (docs/hardware/tt-fpga.md).

Which Tiny Tapeout board it is, is the board's own word, never a guess (#124). The same demo board carries an
FPGA breakout or a Tiny Tapeout chip, and its microcontroller looks the same on USB either way (an FPGA board's
RP2350 and a chip board's RP2040 both read 2e8a:0005). So finding the board gives no variant: it is settled
once the check holds the board's port, from the `chip` rpi-hwid read there, before any design is chosen:

  chip "fpga"                      tt-fpga: the `sdk` test, then the designs below are loaded and tested
  chip "asic" and a shuttle        tt-asic: the `sdk` test, then the `wiring` test; nothing is loaded
  anything else                    no variant: an error saying what could not be read, and no test

An FPGA bitstream only ever goes to a board that said it is an FPGA board. An RP2 that is in its USB boot
loader (2e8a:0003) is found too, and fails as not running the Tiny Tapeout firmware. Other Raspberry Pi USB
products (a debug probe, a Pico running something else) are not Tiny Tapeout boards and are not looked at.

The `sdk` test (sdk_check) loads nothing and asks the board nothing more: it judges what the board already
said. Chip, shuttle, microcontroller and SDK release must be a combination the SDK's releases support
(SDK_SUPPORTED), since an SDK that does not know the board's chip cannot select a project on it.

The `wiring` test of a board with a Tiny Tapeout chip (tt_pmod_wiring.py, a script test: no bitstream) checks
its three Pmod ribbons to the Pi's Pmod HAT bit for bit: the board's RP2040 drives each ui_in and uio signal
from a command server run in RAM over its raw REPL, the Pi reads every HAT line, and the chip's own
tt_um_factory_test (uo_out = uio_in) carries the uio walk out on uo_out. A fault is named by its ribbon and
pin. The script then puts the board back from RAM as its SDK had it (tt_sdk_start.py only if that fails). Until this
test was here such a board failed as untested (Tim, 2026-10-05: "Fail until wiring is tested and prioritize
landing the setup which properly tests the wiring"). The FPGA board's wiring test (also `wiring`) loads a design.

Nothing is written to the demo board: for every load `openFPGALoader -b tt_fpga` (our build, the
openfpgaloader-fpgasonline packages of fpgas.online-fpga-tools) streams the bitstream to the RP2350 over its raw
REPL, which clocks it into the iCE40 from RAM. After each load it starts the TTDBv3 project clock (GPIO16, 50 MHz)
and leaves the SPI pins and the RP2350's ui_in, uo_out and uio pins (GPIO17-40) high-impedance, and it exits
non-zero when any of that did not happen (fpga-tools #18); a load that exits 0 without saying `SRAM programming
complete` fails too (load_failure). The board has no flash of its own to compare, so the state is the RP2350's
USB serial number. The board's other reads (tt_main_py.py, tt_dip_switches.py, tt_pmod_wiring.py) still need
mpremote (micropython-mpremote: in trixie, and only bookworm-backports for bookworm).

Who the board is, for rpi-hwid's Tiny Tapeout label, comes from `rpi-hwid tinytapeout --json --no-stop-service`,
run while the check holds the RP2350's port (fpgas-tt.service stopped) and before any test loads a design: it
asks the Tiny Tapeout SDK on the RP2350 over its REPL. rpi-hwid is found on PATH and run, never imported. Without it
the board cannot be asked who it is: the identity says so in tinytapeout_note, and the check is an error, since
the variant is not known. When rpi-hwid is there but cannot say who the board is, the identity has
tinytapeout_error and the check is an error.

rpi-hwid reads only what the SDK built when the board started, so the board's SDK is started first
(tt_sdk_start.py: a soft reset from the friendly REPL, which runs the board's main.py). A board whose main.py is
not the SDK's does not start it, and that is an error with its own reason."""

import json
import shutil
import sys
from typing import ClassVar

from .. import host_tests, identity
from ..core import Problem, run, tail, usb_matching
from ..testbench import TestBoard

RPI_HWID = "rpi-hwid"
# What openFPGALoader's tt_fpga load prints last when the stream, the clock and the pin release all succeeded.
LOADED = "SRAM programming complete"
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
# A board with a Tiny Tapeout chip is not held to that: rpi-hwid gives null for its demo board when the SDK did
# not detect one, and for a microcontroller it does not know, and neither is a failed read. What it must have
# said is its chip; whether it named a shuttle is settle()'s question, and whether its microcontroller and SDK
# release are ones for that chip is the `sdk` test's, which fails a board that named no microcontroller.
ALWAYS_THERE_ON_A_CHIP_BOARD = ("chip",)


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
    needed = ALWAYS_THERE_ON_A_CHIP_BOARD if out.get("chip") == "asic" else ALWAYS_THERE
    unread = [k for k in needed if k in out and out[k] is None]
    if unread:
        return {"tinytapeout_error": f"{command}: rpi-hwid could not read {', '.join(unread)}"}
    return out


# What the SDK's releases support: (chip, the shuttles, the microcontroller, the SDK release line). From the
# releases of TinyTapeout/tt-micropython-firmware, read 2026-10-05: 2.0.4 is the last release for the RP2040
# demo boards (TT04 to TT08); 3.x is built for the RP2350 demo board, which carries the FPGA breakout; the
# TT03p5 board (a Pico on the older demo board) runs 1.2.x, whose chip ROM reader names that shuttle itself.
# A combination that is not here fails the `sdk` test with what the board said: add its row when a release
# is known to support it.
SDK_SUPPORTED = (
    ("fpga", (None,), "RP2350", "3.1"),
    ("asic", ("tt03p5",), "RP2040", "1.2"),
    ("asic", ("tt04", "tt05", "tt06", "tt07", "tt08"), "RP2040", "2.0"),
)
# What the boot check of a variant must do and does not yet (a board fails until it does): nothing now. The
# wiring test of a board with a Tiny Tapeout chip was the last (`wiring`, below).
PENDING = {}
# tt_pmod_wiring.py stops itself at WIRING_TIME_LIMIT, then puts everything back (its TEARDOWN_SECONDS, 130) and, only
# when the board could not be put back from RAM, starts the SDK by a soft reset (its FALLBACK_SECONDS, 75): all of it
# inside the boot check's own limit, which kills it. That worst case is for a faulty board; the good path's time is
# what a visitor waits for: 22.7 s, measured on the TT07 board on 8 Oct 2026, in a passing run. WIRING_TIME_LIMIT
# is about four times that.
WIRING_TIME_LIMIT = 90
WIRING_TEARDOWN = 130 + 75
WIRING_TIMEOUT = 300


def sdk_line(release):
    """'2.0.4' -> '2.0': the release line of an SDK release; None for text that is not one."""
    parts = (release or "").lstrip("v").split(".")
    return ".".join(parts[:2]) if len(parts) >= 3 and all(p.isdigit() for p in parts[:2]) else None


def sdk_check(variant, facts, found=None):
    """The `sdk` test: (result, reason, lines). Passes when the board's chip, shuttle, microcontroller and SDK
    release are a row of SDK_SUPPORTED. Reads nothing: `facts` is what the board said (port_facts)."""
    chip, shuttle, mcu, sdk = (facts.get(k) for k in ("chip", "shuttle", "mcu", "sdk"))
    what = "the FPGA breakout" if chip == "fpga" else f"a {shuttle} chip"
    said = [f"chip: {chip}", f"shuttle: {shuttle or '-'}", f"microcontroller: {mcu or 'not read'}",
            f"SDK release: {sdk or 'not read'}"]  # fmt: skip
    missing = [name for name, value in (("its microcontroller", mcu), ("its SDK release", sdk)) if not value]
    if missing:
        return "fail", f"the board did not say {' or '.join(missing)}", said
    line = sdk_line(sdk)
    if line is None:
        return "fail", f"the board's SDK release reads {sdk!r}, which is not a release number", said
    rows = [row for row in SDK_SUPPORTED if row[0] == chip and shuttle in row[1]]
    if not rows:
        return "fail", f"no SDK release is recorded as supporting {what}: add its row to SDK_SUPPORTED", said
    if any(row[2] == mcu and row[3] == line for row in rows):
        return "pass", None, [*said, f"SDK {line}.x on an {mcu} supports {what}"]
    wanted = " or ".join(f"SDK {row[3]}.x on an {row[2]}" for row in rows)
    return "fail", f"{what} needs {wanted}, and the board runs SDK {sdk} on an {mcu}", said


PMOD_PRE = [["rmmod", "spidev", "spi_bcm2835"]]
# The common checks (checks.py) for parts no Tiny Tapeout demo board has, with an FPGA breakout or a chip.
NO_PART = {
    "ddr": "the demo board has no DRAM",
    "ethernet": "the demo board has no Ethernet",
}
VENDOR = "2e8a"  # Raspberry Pi
# The products a Tiny Tapeout demo board's microcontroller shows: MicroPython's USB serial (the two ids the
# fpgas-tt udev rule matches; an FPGA board's RP2350 has been read as 0005), and the RP2's boot loader, which is
# a board that cannot answer.
MICROPYTHON, BOOTLOADER = ("0005", "000f"), "0003"
NOT_TT_FIRMWARE = "a Raspberry Pi RP2 is on USB but is not running the Tiny Tapeout firmware"
NOT_SAID = "the board did not say which Tiny Tapeout board it is, so no test was run and nothing was loaded"
# The check talks to the demo board on one fixed port, and with two boards on a Pi that port is one of them and
# not known to be this one. Checking each on its own port is not written (no host has two): said, not guessed.
ONE_PORT = ("{n} Raspberry Pi RP2 boards that can be Tiny Tapeout demo boards are on this Pi's USB, and the check "
            "has one port for a demo board ({port}): it cannot tell which board that port is, so none was asked "
            "what it is, no test was run and nothing was loaded")  # fmt: skip


class TTFPGA(TestBoard):
    name = "tt"
    slug = "tt-fpga"  # fpgas-online-tt is the TT site's own package
    title = "TT FPGA Demo Board"
    doc = "tt-fpga.md"
    usb = tuple((VENDOR, product) for product in (*MICROPYTHON, BOOTLOADER))
    variants: ClassVar[dict] = {"tt-fpga": "tt-fpga"}  # the variants there are bitstreams for
    variant_from_board = True
    # `reads`: what the check runs to have the facts the test judges (docs/verify/checks.md says it)
    fact_tests: ClassVar[dict] = {
        "sdk": {
            "variants": ("tt-fpga", "tt-asic"),
            "check": sdk_check,
            "reads": "before the tests, over the board's USB serial: `tt_main_py.py` reads main.py's SHA-256 (a "
            "main.py that is not the SDK's stops it there); then, where rpi-hwid is installed, `tt_sdk_start.py` "
            "starts the SDK (a soft reset) and rpi-hwid asks the board what it is; nothing is loaded",
        }
    }
    # The Pmod cabling of a board with a Tiny Tapeout chip, against the cabling the boards have (ui_in on HAT
    # JA, uio JB, uo_out JC: identify_pmod_pins.BOARDS["tt"]). The check has stopped fpgas-tt itself, so
    # --no-daemon; tt_pmod_wiring.py unloads the SPI drivers itself and loads them again. It puts the board back
    # as the SDK left it from RAM (its mode, project and clock), and starts the SDK again by a soft reset only
    # when that fails. It needs `sdk` to have passed: a board whose SDK cannot select the chip's project cannot
    # be wiring-tested.
    script_tests: ClassVar[dict] = {
        "wiring": {"variants": ("tt-asic",), "script": "tt_pmod_wiring.py",
                   "args": ["--port", "{port}", "--controller", "rp2040", "--cabling", "asic", "--no-daemon",
                            "--time-limit", str(WIRING_TIME_LIMIT)],
                   "says": "WIRING:", "timeout": WIRING_TIMEOUT, "needs": ("sdk",)},
    }  # fmt: skip
    pending: ClassVar[dict] = PENDING
    # rpi-hwid's Tiny Tapeout label (its LABEL-CONTRACT.md, sections 1 and 7). Only the boot check reads the
    # fields rpi-hwid gives (it owns the port then): --identify takes them, and why they are missing, from the
    # boot report, matched by usb_serial.
    label_fields = ("usb_serial", "mcu", "chip", "demoboard", "demoboard_version", "sdk")
    # The variant too: only the boot check asks the board which Tiny Tapeout board it is.
    report_fields = ("variant", *RPI_HWID_FIELDS, "tinytapeout_")
    port = "/dev/ttyACM0"
    services = ("fpgas-tt.service",)  # the TT site's bridge keeps the RP2350's port open while it runs
    flash_note = ("none: nothing on the demo board is read back; the FPGA breakout has no SPI flash, and its "
                  "RP2350 loads each bitstream from the Pi")  # fmt: skip
    # Run in this order: the DIP switches first (#166), read under the display design, which drives only uo_out
    # and leaves ui_in and uio undriven without the iCE40's pull-up (tt_dip_switches.py says why); then the
    # pin-ID scan, so the UART-bridge designs (uart, then spram: one TX pin each) are the last test designs, not
    # one driving every Pmod line. What the board is left running is `left_running`, below.
    tests: ClassVar[dict] = {
        # Each of the demo board's DIP switches on ui_in is off: one that is on fails the board, named.
        "dip-switches": {"artifact": "tt-display-{v}/tt_fpga_platform.bin", "script": "tt_dip_switches.py",
                         "args": ["{port}"], "says": "DIP_SWITCHES:",
                         "verify": True},
        # The Pmod HAT cabling, against identify_pmod_pins.BOARDS["tt"] (ui_in on HAT JA, uio JB, uo_out JC). It
        # was `pin-id` until 15 Oct 2026 (#340): `wiring` is the cabling test's name on every board, as on a board
        # with a Tiny Tapeout chip (script_tests), which never runs this one.
        "wiring": {"artifact": "pmod-pin-id-{v}/tt_fpga_platform.bin", "script": "identify_pmod_pins.py",
                   "args": ["--board", "tt"], "pre": PMOD_PRE, "verify": True, "says": "PIN-ID:"},
        "uart": {"artifact": "uart-test-tt-fpga/tt_fpga_platform.bin", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "tt", "--skip-banner"], "verify": True,
                 "runner": "tt-bridge"},
        # The iCE40's 128 KB of SPRAM, written and read back by the design's own firmware on the script's word
        # (designs/spram, #343): through the same bridge as uart, so it too drives only the UART's TX pin.
        "spram": {"artifact": "spram-test-tt-fpga/tt_fpga_platform.bin", "script": "test_spram.py",
                  "args": ["--port", "{port}"], "verify": True, "runner": "tt-bridge", "says": "SPRAM:"},
        "pmod": {"artifact": "gpio-loopback-{v}/tt_fpga_platform.bin", "script": "test_pmod_loopback.py",
                 "args": ["--board", "tt"], "pre": PMOD_PRE},
    }  # fmt: skip

    # What the whole check is asked about (#340).
    cannot: ClassVar[dict] = {
        "tt-fpga": {**NO_PART, "jtag": "the iCE40UP5K has no JTAG port: it is loaded through the demo board's RP2350",
                    "flash": "the FPGA breakout has no configuration flash: the RP2350 streams each design from "
                             "the Pi"},
        "tt-asic": {"jtag": "a Tiny Tapeout chip is an ASIC, not an FPGA: nothing on it is configured over JTAG",
                    "flash": "a Tiny Tapeout chip is an ASIC: it has no configuration flash to test",
                    "uart": "a Tiny Tapeout chip's projects are fixed in silicon: no UART design can be loaded; the "
                            "wiring test checks its lines to the Pi",
                    **NO_PART},
        None: {"jtag": "neither a TT FPGA breakout (an iCE40UP5K, loaded through the RP2350) nor a Tiny Tapeout "
                       "chip has a JTAG port",
               "flash": "neither a TT FPGA breakout nor a Tiny Tapeout chip has a configuration flash",
               "uart": "only an FPGA board has a UART test, and the board did not say whether it carries an FPGA",
               **NO_PART},
    }  # fmt: skip
    abouts: ClassVar[dict] = {
        "sdk": "the board's chip, shuttle, microcontroller and SDK release are a combination the SDK supports",
        "dip-switches": "every DIP switch on ui_in is off",
        "uart": "printable text through the RP2350's bridge to the UART test design echoes back",
        "spram": "the iCE40's 128 KB of SPRAM reads back each word's address and its inverse, and each byte lane "
        "writes alone",
        "pmod": "the Pmod loopback wiring reads back (-debug only)",
    }
    abouts_by_variant: ClassVar[dict] = {
        "tt-fpga": {"wiring": "each Pmod HAT wire carries the FPGA pin the cabling map puts there (the pin-ID scan)"},
        "tt-asic": {
            "wiring": "the RP2040 drives each ui_in and uio line and the Pi reads it on its HAT pin, bit by bit"
        },
        None: {"wiring": "the three Pmod ribbons to the Pi's HAT, pin by pin (how depends on the board, not yet said)"},
    }
    # The variant is settled from the board's own word: one not settled would still have had its `sdk` test, and a
    # wiring test whichever board it is.
    planned_unsettled = ("sdk", "wiring")

    # #139: the check ends by streaming a design that moves the seven-segment display, so the board looks
    # alive on its camera until a visitor loads a design (designs/tt-display: clocked by the iCE40's own
    # oscillator, it needs nothing of the RP2350 afterwards and drives only uo_out). openFPGALoader leaves the
    # RP2350's own pins on ui_in, uo_out and uio high-impedance, so nothing but the FPGA drives the display.
    # It lasts until the board's SDK next starts (a visitor's Commander, the site's Run), which puts the SDK's
    # own default project into the FPGA.
    left_running: ClassVar[dict] = {
        "tt-fpga": {"design": "display", "artifact": "tt-display-tt-fpga/tt_fpga_platform.bin"},
    }  # fmt: skip

    def spot(self, host, usb, pci):
        """Every RP2 on USB that can be a Tiny Tapeout demo board, with no variant: settle() decides it. With
        more than one, each also has "beside": where the others are (ONE_PORT)."""
        found = [{"variant": None, "usb": d["path"], "serial": d["serial"], "usb_id": f"{d['vendor']}:{d['product']}"}
                 for d in usb_matching(usb, self.usb)]  # fmt: skip
        if len(found) > 1:
            found = [{**f, "beside": [o["usb"] for o in found if o is not f]} for f in found]
        return found

    def settle(self, asked, found, facts):
        if found.get("beside"):
            raise Problem("error", ONE_PORT.format(n=len(found["beside"]) + 1, port=self.port))
        if found.get("usb_id") == f"{VENDOR}:{BOOTLOADER}":
            raise Problem("fail", f"{NOT_TT_FIRMWARE}: it is in its USB boot loader ({found['usb_id']})")
        chip = facts.get("chip")
        if chip == "fpga":
            variant = "tt-fpga"
        elif chip == "asic" and facts.get("shuttle"):
            variant = "tt-asic"
        elif "tinytapeout_note" in facts:  # rpi-hwid is not installed: nothing asked the board
            raise Problem("error", f"{NOT_SAID}: {facts['tinytapeout_note']}")
        elif chip == "asic":
            raise Problem("error", f"{NOT_SAID}: it has a Tiny Tapeout chip whose shuttle could not be read")
        else:  # why is in the identity's tinytapeout_error, which the report's reason carries too
            raise Problem("error", NOT_SAID)
        if asked and asked != variant:
            raise Problem("error", f"--variant {asked} was asked for, but the board says it is a {variant}: "
                                   "nothing was loaded")  # fmt: skip
        return variant

    def port_facts(self, host, found, runner=run):
        if not found.get("serial") or found.get("usb_id") == f"{VENDOR}:{BOOTLOADER}" or found.get("beside"):
            return {}  # nothing is asked of a board that cannot answer, or that the port may not be the port of
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

    def uart_pre(self, host):
        """Nothing: the board's port is its RP2350's USB serial, which carries no login console to stop."""
        return []

    def program_argv(self, bitstream, host, test):
        """Every load is the same: openFPGALoader also starts the clock and leaves the RP2350's pins on ui_in,
        uo_out and uio high-impedance, so nothing but the FPGA and the Pi drives them (what the mpremote loader,
        tt_fpga_program.py, did with --gpio-release until 17 Oct 2026)."""
        return ["openFPGALoader", "-b", "tt_fpga", "-d", host["port"], bitstream]

    def load_failure(self, argv, text):
        """openFPGALoader's tt_fpga load exits non-zero when the stream, the clock or the pin release failed
        (fpga-tools #18); one that exits 0 must also have said it finished, or whether it did is not known.
        It cannot say whether the iCE40 configured: it does not read CDONE (fpga-tools #17); the designs' own
        tests do."""
        if argv and argv[0] == "openFPGALoader" and LOADED not in text:
            return f"openFPGALoader exited 0 but did not say '{LOADED}'"
        return None


BOARD = TTFPGA()
