"""Fomu EVT (iCE40UP5K): found through the Pi's GPIO header it sits on, identified by its SPI flash read over that
header, and loaded with openFPGALoader over foboot's DFU on USB (#200).

The EVT plugs onto the Pi's 40-pin header (im-tomu/fomu-hardware, branch evt, tomu-fpga.sch): the iCE40's
CRESET on GPIO27, its CDONE on GPIO17, and its SPI flash (a W25Q128JV) on the Pi's SPI0 pins, shared with the
iCE40's configuration port. So:

  * Finding it reads CDONE with pinctrl and drives nothing: high means an iCE40 on the header has loaded a
    design. foboot's DFU bootloader on USB (`1209:5bf0`) finds it too, but is not needed: a Fomu whose USB is
    being analysed, or that runs a design with no USB, is still the Fomu.
  * The check identifies it (port_facts, before any test): fomu_header_id.py holds the iCE40 in reset, reads
    the flash's JEDEC ID and 64-bit unique ID, puts every line back to an input and lets the iCE40 boot from
    its flash again, into foboot, as at power-up. That stops whatever design was running, so only the check
    does it, never finding the board or --identify. The `header` test judges what it read.
  * After the reset the check waits for foboot on USB, which the tests' DFU loads need (the `foboot` test).

A DFU load writes the design into the flash's user image, so the flash's contents are not part of the state;
its IDs are. foboot has no USB serial number (its iSerialNumber is 0), so the label is the flash's unique ID.

The OpenVizsla OV3 that may sit inline on the Fomu's USB to debug its USB stack is a debug tool (debug_usb):
named in the report, never taken for a board or for "no board"."""

import json
import sys
import time
from typing import ClassVar

from .. import host_tests, identity
from ..core import Problem, is_pi, pin_states, run, tail, usb_devices, usb_matching
from ..testbench import TestBoard

PMOD_PRE = [["rmmod", "spidev", "spi_bcm2835"]]
FOBOOT = ("1209", "5bf0")
CRESET, CDONE = 27, 17
HEADER_GPIOS = (8, 9, 10, 11, 17, 24, 25, 27)  # the lines fomu_header_id.py takes
HEADER_TIMEOUT = 60
FOBOOT_WAIT = 10.0  # s for foboot to appear on USB after the reset
# The EVT's flash, U4: a Winbond W25Q128JV-IM (tomu-fpga.sch), RDID EFh 70h 18h.
FLASH_JEDEC = "ef7018"
FLASH_PART, FLASH_BYTES = "W25Q128JV", 16 * 1024 * 1024
SAID, SAID_ERROR = "fomu-header: ", "fomu-header-error: "
_sleep, _clock = time.sleep, time.monotonic  # the wait for foboot (tests replace them)


def read_header(host, runner=run):
    """fomu_header_id.py's reading (a dict), with every line it took checked to be an input again afterwards.
    A Problem (an error) when it could not be run, or a line was left driven."""
    if not is_pi(host["model"]):
        raise Problem("error", "not a Raspberry Pi: there is no header to read the Fomu through")
    rc, text = runner([sys.executable, host_tests.path("fomu_header_id.py")], HEADER_TIMEOUT)
    faults = []
    try:
        left = pin_states(runner, HEADER_GPIOS)
    except Problem as p:
        faults.append(f"whether the header's lines were left as inputs could not be read: {p.reason}")
    else:
        faults += [f"GPIO{g} was left {func}, not an input" for g, (func, _, _) in sorted(left.items()) if func != "ip"]
    said = [line[len(SAID) :] for line in text.splitlines() if line.startswith(SAID)]
    said_error = [line[len(SAID_ERROR) :] for line in text.splitlines() if line.startswith(SAID_ERROR)]
    if rc != 0 or not said:
        why = said_error[-1] if said_error else f"fomu_header_id.py exited {rc}: {' '.join(tail(text, 2))}"
        faults.insert(0, why)
    if faults:
        raise Problem("error", "; ".join(faults))
    try:
        return json.loads(said[-1])
    except ValueError:
        raise Problem("error", f"fomu_header_id.py printed a reading that is not JSON: {said[-1][:200]}") from None


def flash_identity(reading):
    """The identity's flash fields from a reading, {} when the flash was not read."""
    flash = reading.get("flash")
    if not flash:
        return {}
    known = flash["jedec"] == FLASH_JEDEC
    return identity.flash_fields({"rdid": flash["jedec"], "part": FLASH_PART if known else None,
                                  "size_bytes": FLASH_BYTES if known else None, "status": flash["status"][0],
                                  "unique_id": flash["uid"], "unique_id_opcode": 0x4B}, "header")  # fmt: skip


def header_check(variant, facts, found):
    """The `header` test: (result, reason, lines), from the reading port_facts left in `found`."""
    reading = found.get("header")
    if reading is None:
        return "error", found.get("header_error", "the header was not read"), []
    flash = reading.get("flash")
    lines = [f"CDONE before {reading['cdone_before']}, in reset {reading.get('cdone_in_reset', '-')}, "
             f"after {reading.get('cdone_after', '-')} (rose in {reading.get('boot_seconds')} s)"]  # fmt: skip
    if flash:
        lines.append(f"flash JEDEC ID {flash['jedec']}, unique ID {flash['uid']}, status {' '.join(flash['status'])}")
    if reading["cdone_before"] != 1:
        return "fail", ("CDONE was low before the reset: no iCE40 on the header has loaded a design, so the header "
                        "was not driven and the flash not read"), lines  # fmt: skip
    if reading["cdone_in_reset"] != 0:
        return "fail", ("CDONE stayed high with CRESET held low: no iCE40 is on the header's reset (GPIO27), so "
                        "the flash was not read"), lines  # fmt: skip
    faults = []
    if flash["jedec"] in ("000000", "ffffff"):
        faults.append(f"the flash did not answer over the header (JEDEC ID {flash['jedec']})")
    elif flash["jedec"] != FLASH_JEDEC:
        faults.append(f"the flash's JEDEC ID is {flash['jedec']}, not the EVT's {FLASH_PART} ({FLASH_JEDEC})")
    if set(flash["uid"]) <= {"0"} or set(flash["uid"]) <= {"f"}:
        faults.append(f"the flash's unique ID reads {flash['uid']}, which is no ID")
    if flash.get("busy_after_wait"):
        faults.append("the flash was still busy with an erase or a write when it was read")
    if reading.get("boot_seconds") is None:
        faults.append("the iCE40 did not load a design from its flash after the reset (CDONE stayed low)")
    return ("fail", "; ".join(faults), lines) if faults else ("pass", None, lines)


def foboot_check(variant, facts, found):
    """The `foboot` test: did foboot answer on USB after the reset? The tests' DFU loads need it."""
    seconds = found.get("foboot_seconds")
    if seconds is not None:
        return "pass", None, [f"foboot (1209:5bf0) on USB {seconds} s after the reset"]
    if "header" not in found:
        return "error", "not looked for: the header was not read, so the Fomu was not reset", []
    return "fail", (f"foboot (1209:5bf0) did not appear on USB within {FOBOOT_WAIT:g} s of the reset, so no "
                    "design can be loaded over DFU: look at the Fomu's USB path (an OpenVizsla, when one is "
                    "inline, is on it)"), []  # fmt: skip


class Fomu(TestBoard):
    name = slug = "fomu"
    title = "Fomu EVT"
    doc = "fomu-evt.md"
    usb = (FOBOOT,)
    probes = True  # reads CDONE on the header: nothing is driven
    debug_usb: ClassVar[dict] = {("1d50", "607c"): "OpenVizsla OV3"}
    variants: ClassVar[dict] = {"evt": "evt"}
    label_fields = ("flash_uid",)  # --identify takes it from the boot report: reading it resets the FPGA
    one_per_host = True  # on the Pi's header
    port = "/dev/serial0"
    flash_note = "not read back: every verify rewrites the user image by DFU; its IDs are read over the header"
    fact_tests: ClassVar[dict] = {
        "header": {"variants": ("evt",), "check": header_check},
        "foboot": {"variants": ("evt",), "check": foboot_check},
    }
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-fomu/kosagi_fomu_evt.bin", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "fomu", "--skip-banner"], "verify": True},
        "spiflash": {"artifact": "spiflash-test-fomu/kosagi_fomu_evt.bin", "script": "test_spiflash.py",
                     "args": ["--port", "{port}", "--board", "fomu"]},
        "pmod": {"artifact": "gpio-loopback-fomu-{v}/kosagi_fomu_evt.bin", "script": "test_pmod_loopback.py",
                 "args": ["--board", "fomu"], "pre": PMOD_PRE},
        "pin-id": {"artifact": "pmod-pin-id-fomu-{v}/kosagi_fomu_evt.bin", "script": "identify_pmod_pins.py",
                   "args": [], "pre": PMOD_PRE},
    }  # fmt: skip

    def probe(self, host, runner=run):
        """A Fomu on the header: CDONE (GPIO17) high, read with pinctrl, which drives nothing. GPIO17 is also the
        NeTV2's TMS (and GPIO27 its TDI): on a host with both boards' packages, a NeTV2 whose TMS reads high would
        be taken for a Fomu too, and fail its `header` test (CDONE does not fall, so its bus is never driven)."""
        if not is_pi(host["model"]):
            return []
        cdone = pin_states(runner, (CDONE,))[CDONE]
        if cdone[0] != "ip" or cdone[2] != "hi":
            return []
        return [{"variant": "evt", "cdone": "hi"}]

    def port_facts(self, host, found, runner=run):
        """The flash's IDs over the header (the iCE40 reset; see the module's docstring), then foboot on USB.
        The whole reading is left in found["header"] for the `header` test and the report, and the IDs in
        found for the state."""
        try:
            reading = read_header(host, runner)
        except Problem as p:
            found["header_error"] = p.reason
            return {"flash_error": f"not read over the header: {p.reason}"}
        found["header"] = reading
        facts = flash_identity(reading)
        found.update({k: facts[k] for k in ("flash_jedec", "flash_uid") if k in facts})
        start = _clock()
        while True:
            dfu = usb_matching(usb_devices(), (FOBOOT,))
            if dfu:
                found["foboot_seconds"] = round(_clock() - start, 1)
                found["usb"] = dfu[0]["path"]
                break
            if _clock() - start >= FOBOOT_WAIT:
                break
            _sleep(0.5)
        return facts

    def identity(self, found):
        """The state: the variant and the flash's IDs read over the header (foboot has no USB serial)."""
        return {**super().identity(found), **{k: found[k] for k in ("flash_jedec", "flash_uid") if k in found}}

    def program_argv(self, bitstream, host, test):
        return ["openFPGALoader", "-b", "fomu", bitstream]


BOARD = Fomu()
