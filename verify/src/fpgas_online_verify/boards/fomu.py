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
import re
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
# The kernel's lines about a USB device or port ("usb 1-1.2: …", "usb 1-1-port2: disabled by hub …", a root hub's
# "usb usb1-port2: …"), kept when foboot does not come back: how the reset went on the USB side. In mainline hub.c
# the enumeration messages print with the device or port ("usb 1-1-port3: unable to enumerate USB device", "usb
# 1-1.2: New USB device found, idVendor=1209 …"), so that prefix is the pattern. It leaves out the drivers'
# registration lines ("usbcore: registered …"), a 1209 in a timestamp or a hostname, and the hub's own lines
# ("hub 1-0:1.0: …", e.g. over-current), which are about the hub, not the Fomu.
USB_KERNEL_RE = re.compile(r"\busb (?:usb\d+|\d+-[\d.]+)(?:-port\d+)?:")
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


def foboots():
    """{(USB path, device number)} of every foboot on USB now. The device number is new at each enumeration; one
    that cannot be read (sysfs devnum) would make every look the same, so it is an error, said, not a timeout."""
    found = usb_matching(usb_devices(), (FOBOOT,))
    unread = [d["path"] for d in found if not d.get("devnum")]
    if unread:
        raise Problem("error", f"the USB device number (sysfs devnum) of the foboot at {', '.join(unread)} could not "
                               "be read, so whether it enumerated again after the reset cannot be told")  # fmt: skip
    return {(d["path"], d["devnum"]) for d in found}


def new_foboot(before):
    """Wait up to FOBOOT_WAIT for a foboot that was not on USB before the reset (`before`, from foboots()):
    (seconds, its USB path), or None. #347: right after the reset the foboot from before can still be listed, with
    its old device number, until the hub notices it left; a DFU load sent to it then finds no device."""
    start = _clock()
    while True:
        new = sorted(foboots() - before)
        if new:
            return round(_clock() - start, 1), new[0][0]
        if _clock() - start >= FOBOOT_WAIT:
            return None
        _sleep(0.5)


STALE = "only the foboot from before the reset is still listed (the same USB device number): no new one enumerated"


def kernel_usb_lines(runner, keep=6):
    """The kernel's last USB lines this boot, for a foboot that did not come back. A journal that cannot be read
    gives none: it only explains a failure, which stands without it."""
    try:
        rc, text = runner(["journalctl", "-k", "-b", "--no-pager", "-o", "short-monotonic"], 10)
    except Problem:
        return []
    return [line.strip() for line in text.splitlines() if USB_KERNEL_RE.search(line)][-keep:] if rc == 0 else []


def foboot_check(variant, facts, found):
    """The `foboot` test: did foboot answer on USB after the reset? The tests' DFU loads need it."""
    seconds = found.get("foboot_seconds")
    if "foboot_error" in found:
        return "error", found["foboot_error"], []
    if seconds is not None:
        return "pass", None, [f"foboot (1209:5bf0) on USB {seconds} s after the reset"]
    if "header" not in found:
        return "error", "not looked for: the header was not read, so the Fomu was not reset", []
    # What tells the cases apart: foboot there before the reset and gone after it is the reset's doing; not there
    # before either means a design with no USB was running (#135), which only a power cycle ends.
    before = ("it was on USB before the reset" if found.get("foboot_before_reset")
              else "it was not on USB before the reset either: a design with no USB was running")  # fmt: skip
    reading = found["header"]
    # the kernel's lines first and CDONE last: the console shows a failed test's last 8 lines (runner.summary)
    output = [*found.get("usb_kernel", []), f"CDONE before {reading.get('cdone_before')}, in reset "
              f"{reading.get('cdone_in_reset')}, after {reading.get('cdone_after')}"]  # fmt: skip
    stale = f"; {STALE}" if found.get("foboot_stale") else ""
    return "fail", (f"foboot (1209:5bf0) did not appear on USB within {FOBOOT_WAIT:g} s of the reset, so no "
                    f"design can be loaded over DFU ({before}{stale}): look at the Fomu's USB path (an OpenVizsla, "
                    "when one is inline, is on it)"), output  # fmt: skip


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
    yields_to = ("netv2",)  # GPIO17 is the NeTV2's TMS and GPIO27 its TDI: a NeTV2 found by its IDCODE explains it
    yield_reason = "GPIO17 high is the NeTV2's TMS, not a Fomu's CDONE"
    port = "/dev/serial0"
    flash_note = "not read back: every verify rewrites the user image by DFU; its IDs are read over the header"
    fact_tests: ClassVar[dict] = {
        # `reads`: what the check runs to have the facts the test judges (docs/verify/checks.md says it)
        "header": {
            "variants": ("evt",),
            "check": header_check,
            "reads": "before the tests, `fomu_header_id.py` over the Pi's header: it holds the iCE40 in reset "
            "(CRESET), reads the SPI flash's JEDEC and unique IDs, then lets it boot into foboot",
        },
        "foboot": {
            "variants": ("evt",),
            "check": foboot_check,
            "reads": "after that reset, the Pi's USB is watched for foboot (1209:5bf0); nothing is loaded",
        },
    }
    # Every test loads its design over DFU, which needs foboot on USB: when `foboot` did not pass, they are not run.
    tests: ClassVar[dict] = {
        "uart": {"artifact": "uart-test-fomu/kosagi_fomu_evt.bin", "script": "test_uart.py",
                 "args": ["--port", "{port}", "--board", "fomu", "--skip-banner"], "verify": True,
                 "needs": ("foboot",)},
        # Its firmware prints the JEDEC ID once, as it starts: the script listens from before the load (listen.py).
        # It runs after uart's design, which has no USB: before_test resets the iCE40 back into foboot first (#342),
        # through the header, so it needs `header` to have passed too.
        "flash": {"artifact": "spiflash-test-fomu/kosagi_fomu_evt.bin", "script": "test_spiflash.py",
                  "args": ["--port", "{port}", "--board", "fomu", "--timeout", "120"], "verify": True,
                  "listen": True, "says": "FAIL:", "needs": ("header", "foboot")},
        "pmod": {"artifact": "gpio-loopback-fomu-{v}/kosagi_fomu_evt.bin", "script": "test_pmod_loopback.py",
                 "args": ["--board", "fomu"], "pre": PMOD_PRE, "needs": ("foboot",)},
        # The Pmod pin-ID scan, -debug only (#202: it cannot pass on the EVT). Its `wiring` is derived (derives).
        "pmod-pin-id": {"artifact": "pmod-pin-id-fomu-{v}/kosagi_fomu_evt.bin", "script": "identify_pmod_pins.py",
                   "args": [], "pre": PMOD_PRE, "needs": ("foboot",)},
    }  # fmt: skip
    closing_test = "foboot-after"
    # It sits on the Pi's header: its wiring is the header and uart tests' (checks.derive).
    derives: ClassVar[dict] = {
        "evt": {"wiring": (("header", "uart"), "it sits on the Pi's header: its reset, CDONE and SPI flash lines "
                                               "(header) and its UART lines (uart)")}
    }  # fmt: skip
    abouts: ClassVar[dict] = {
        "header": "over the Pi's header: CDONE, the iCE40 held in reset, the SPI flash's JEDEC and unique IDs",
        "foboot": "foboot, its USB DFU bootloader, enumerates again after the reset",
        "uart": "a design loaded over DFU echoes printable text back over the header's UART",
        "flash": "a test design loaded over DFU reads the SPI flash's JEDEC ID: the EVT's W25Q128JV (ef7018)",
        "foboot-after": "the closing reset brings foboot back on USB, so the next user can load a design",
        "pmod": "the Pmod loopback wiring reads back (-debug only)",
        "pmod-pin-id": "the Pmod pin-ID scan (-debug only: it cannot pass on the EVT, #202)",
    }
    cannot: ClassVar[dict] = {
        "evt": {
            "jtag": "the iCE40UP5K has no JTAG port: the Fomu is loaded over USB DFU, by foboot",
            "ddr": "the Fomu EVT has no DRAM",
            "ethernet": "the Fomu EVT has no Ethernet",
        }
    }

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
            before = foboots()
        except Problem as p:  # nothing is reset: the header and foboot tests say why
            found["header_error"] = p.reason
            return {"flash_error": f"not read over the header: {p.reason}"}
        found["foboot_before_reset"] = bool(before)
        try:
            reading = read_header(host, runner)
        except Problem as p:
            found["header_error"] = p.reason
            return {"flash_error": f"not read over the header: {p.reason}"}
        found["header"] = reading
        facts = flash_identity(reading)
        found.update({k: facts[k] for k in ("flash_jedec", "flash_uid") if k in facts})
        try:
            came = new_foboot(before)
            stale = not came and bool(before & foboots())
        except Problem as p:
            found["foboot_error"] = p.reason
            return facts
        if came:
            found["foboot_seconds"], found["usb"] = came
        else:
            found["usb_kernel"] = kernel_usb_lines(runner)
            found["foboot_stale"] = stale
        return facts

    # What a run of tests by name leaves (#135): said by fpgas-fomu-debug after `program` and `test`, and by the
    # check as a warning, since only the boot check's own run ends with the closing reset.
    by_name_note = (
        "the Fomu now runs a design with no USB, so nothing can be loaded over DFU: `sudo fpgas-fomu-debug reset` "
        "puts foboot back on USB (a power cycle of the Pi, by the site operator, does too)"
    )

    def finish(self, variant, host, found, report, runner=run):
        """#135: the tests leave a design with no USB running, so the next user could not load one over DFU until
        the Fomu was power-cycled. The check ends by resetting the iCE40 through the header (reset_to_foboot) and
        fails loud if foboot does not come back. Only when `header` and `foboot` both passed: the reset drives
        CRESET and SPI0, which must be a Fomu's, and without foboot no design was loaded (the tests need it).
        Tests asked for by name run without the fact tests, so the header is not known to be a Fomu's: no reset
        then (the safe default), and the report says how to put foboot back."""
        results = {t["test"]: t["result"] for t in report["tests"]}
        if "header" not in results:
            if any(t["test"] in self.tests for t in report["tests"]):
                report.setdefault("warnings", []).append(self.by_name_note)
            return None
        if results["header"] != "pass" or results.get("foboot") != "pass":
            report.setdefault("not_run", {})[self.closing_test] = "it needs header and foboot to pass first"
            return None
        return self.reset_to_foboot(host, runner)

    def before_test(self, test, variant, host, report, runner=run):
        """#342: each test design replaces foboot with a design that has no USB, so the next DFU load would find no
        device. Before each test after the first that loaded a design, the iCE40 is reset back into foboot through
        the header (reset_to_foboot, as at the end of the check), only when `header` and `foboot` passed in this
        check: the reset drives CRESET and SPI0, which must be a Fomu's. A reset that does not bring foboot back is
        that test's result, with the reason."""
        if not any(t["test"] in self.tests for t in report["tests"]):
            return None
        entry = {"test": test, "bitstream": self.artifact(test, variant)}
        results = {t["test"]: t["result"] for t in report["tests"]}
        if results.get("header") != "pass" or results.get("foboot") != "pass":
            return {**entry, "result": "error",
                    "reason": "not loaded: the design loaded before it has no USB, and the reset back into foboot is "
                              "done only once header and foboot have passed in this check (tests asked for by name "
                              "run without them)"}  # fmt: skip
        reset = self.reset_to_foboot(host, runner)
        if reset["result"] == "pass":
            return None
        return {**entry, "result": reset["result"], "output": reset["output"],
                "reason": f"the reset back into foboot before it: {reset['reason']}"}  # fmt: skip

    def reset_to_foboot(self, host, runner=None):
        """Reset the iCE40 through the header with fomu_header_id.py (the same safe reset as before the tests, every
        line checked to be an input afterwards), then wait for foboot on USB (sw1 p17, 11 Oct 2026: about 1 s).
        A test entry, `foboot-after`: pass, fail with the kernel's USB lines, or error when the reset could not be
        done. fpgas-fomu-debug reset runs it by name."""
        runner = runner or run
        entry = {"test": "foboot-after", "output": []}
        try:
            before = foboots()  # a test design has no USB, so normally none
        except Problem as p:
            return {**entry, "result": p.result, "reason": f"the closing reset was not done: {p.reason}"}
        try:
            read_header(host, runner)
        except Problem as p:
            return {**entry, "result": p.result, "reason": f"the closing reset could not be done: {p.reason}"}
        try:
            came = new_foboot(before)
            stale_now = not came and before & foboots()
        except Problem as p:
            return {**entry, "result": p.result, "reason": f"after the closing reset: {p.reason}"}
        if came:
            said = f"foboot (1209:5bf0) back on USB {came[0]} s after the closing reset: the next user can load"
            return {**entry, "result": "pass", "output": [said + " over DFU"]}
        stale = f"; {STALE}" if stale_now else ""
        return {
            **entry,
            "result": "fail",
            "output": kernel_usb_lines(runner),
            "reason": (
                f"foboot (1209:5bf0) did not come back on USB within {FOBOOT_WAIT:g} s of the closing reset{stale}: "
                "no design can be loaded over DFU until the Fomu is power-cycled (#135)"
            ),
        }

    def identity(self, found):
        """The state: the variant and the flash's IDs read over the header (foboot has no USB serial)."""
        return {**super().identity(found), **{k: found[k] for k in ("flash_jedec", "flash_uid") if k in found}}

    def program_argv(self, bitstream, host, test):
        return ["openFPGALoader", "-b", "fomu", bitstream]


BOARD = Fomu()
