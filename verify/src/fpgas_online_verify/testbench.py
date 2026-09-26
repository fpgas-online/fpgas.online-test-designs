"""The check shared by the boards verified with the LiteX test designs: the Arty A7, NeTV2, Fomu EVT and TT FPGA.

For each of the board's boot-check tests (UART, DDR, SPI flash): check its bitstream against the manifest of
fpgas-online-<board>-bitstreams, load it (into SRAM, except the Fomu's DFU), run its host test script and keep
the tail of its output. Then, where the board can, read back the region of its flash that holds the boot
image, for the state (state.py): loading test designs into SRAM does not touch the flash, so a flash that
differs from the recorded one was written by someone.

The board is left running the last design loaded. A board module is a TestBoard with its detection, its
programmer and its tests; `tests` maps a test to:

  artifact      the CI artifact path in the all-bitstreams bundle; {v} is the variant's suffix
  script        the host test script (host_tests.py), args its arguments; {port} is the board's UART
  verify        True if the boot check runs it; the others need extra wiring (fpgas-<board>-debug runs them)
  pre           commands to run first (each may fail)
  runner        "tt-bridge": the script runs through the TT board's RP2350, which also loads the design
  program_args  extra arguments to the programmer
"""

import contextlib
import hashlib
import re
import sys
import tempfile
from typing import ClassVar

from . import bitstreams, host_tests
from .board import Board
from .core import Problem, host_facts, run, tail, usb_matching, worst

PROGRAM_TIMEOUT = 300
TEST_TIMEOUT = 300
DUMP_TIMEOUT = 900
JEDEC_RE = re.compile(r"JEDEC ID: 0x([0-9A-Fa-f]{2}) 0x([0-9A-Fa-f]{2}) 0x([0-9A-Fa-f]{2})")


class TestBoard(Board):
    usb = ()  # (vendor, product) pairs that mean this board, product None for any
    variants: ClassVar[dict] = {}  # variant -> artifact suffix
    port = ""
    tests: ClassVar[dict] = {}
    doc = ""

    # -- what varies by board ------------------------------------------------------------------------------

    def program_argv(self, bitstream, host, test):
        raise NotImplementedError

    def flash_dump_argv(self, host, variant, size, out):
        """openFPGALoader (or similar) reading `size` bytes of flash from 0 into `out`; None if not possible."""
        return None

    flash_region: ClassVar[dict] = {}  # variant -> bytes of flash holding the boot image (a whole .bit for that part)
    flash_note = ""  # when there is no readback: why the flash is not part of the state

    # -- detection -----------------------------------------------------------------------------------------

    def spot(self, host, usb, pci):
        variant = next(iter(self.variants))
        return [{"variant": variant, "usb": d["path"], "serial": d["serial"]} for d in usb_matching(usb, self.usb)]

    # -- the tests -----------------------------------------------------------------------------------------

    @property
    def verify_tests(self):
        return [name for name, t in self.tests.items() if t.get("verify")]

    @property
    def bitstreams_package(self):
        return f"fpgas-online-{self.slug}-bitstreams"

    def artifact(self, test, variant):
        return self.tests[test]["artifact"].format(v=self.variants[variant])

    def facts(self, port=None):
        return {**host_facts(), "port": port or self.port}

    def uart_pre(self, host):
        """Free the board's UART on the Pi: no login console on it."""
        import os

        port = host["port"]
        if not port.startswith(("/dev/tty", "/dev/serial")):
            return []
        return [["systemctl", "stop", f"serial-getty@{os.path.basename(os.path.realpath(port))}.service"]]

    def pre_steps(self, test, host):
        t = self.tests[test]
        steps = list(t.get("pre", []))
        if "{port}" in " ".join(t["args"]) and t.get("runner") != "tt-bridge":
            steps += self.uart_pre(host)
        return steps

    def test_argv(self, test, host, bitstream):
        t = self.tests[test]
        script = [sys.executable, host_tests.path(t["script"]), *(a.format(port=host["port"]) for a in t["args"])]
        if t.get("runner") == "tt-bridge":
            return [sys.executable, host_tests.path("tt_test_wrapper.py"), host["port"], bitstream, *script]
        return script

    def bitstream(self, images, manifest, test, variant):
        entry = bitstreams.entry_for(manifest, self.artifact(test, variant), self.bitstreams_package)
        return bitstreams.checked(images, entry)[0]

    def run_test(self, test, variant, host, images, manifest, runner=run):
        t = self.tests[test]
        out = {"test": test, "bitstream": self.artifact(test, variant)}
        try:
            bitstream = self.bitstream(images, manifest, test, variant)
            for step in self.pre_steps(test, host):
                with contextlib.suppress(Problem):
                    runner(step, 30)
            if t.get("runner") != "tt-bridge":  # the bridge loads the design itself
                rc, text = runner(self.program_argv(bitstream, host, test), PROGRAM_TIMEOUT)
                if rc != 0:
                    return {**out, "result": "fail", "reason": f"loading it failed (exit {rc})", "output": tail(text)}
            rc, text = runner(self.test_argv(test, host, bitstream), TEST_TIMEOUT)
        except Problem as p:
            return {**out, "result": p.result, "reason": p.reason}
        found = {"result": "pass" if rc == 0 else "fail", "output": tail(text)}
        if rc != 0:
            found["reason"] = f"the test exited {rc}"
        m = JEDEC_RE.search(text)
        if m:
            found["flash_jedec"] = "0x" + "".join(m.groups()).lower()
        return {**out, **found}

    # -- the flash -----------------------------------------------------------------------------------------

    def read_flash(self, host, variant, runner=run):
        """{"region_bytes", "sha256"} of the boot image region, read back over JTAG."""
        size = self.flash_region.get(variant)
        with tempfile.TemporaryDirectory() as tmp:
            out = f"{tmp}/flash.bin"
            argv = self.flash_dump_argv(host, variant, size, out) if size else None
            if argv is None:
                return None
            rc, text = runner(argv, DUMP_TIMEOUT)
            try:
                with open(out, "rb") as f:
                    data = f.read()
            except OSError:
                data = b""
            if rc != 0 or len(data) != size:
                raise Problem("error", f"reading back the flash failed (exit {rc}, {len(data)} of {size} bytes): "
                                       f"{' '.join(tail(text, 3))}")  # fmt: skip
            return {"region_bytes": size, "sha256": hashlib.sha256(data).hexdigest()}

    # -- the check -----------------------------------------------------------------------------------------

    def identity(self, found):
        return {k: v for k, v in found.items() if k in ("variant", "serial", "idcode") and v is not None}

    def check(self, host, found, options, runner=run):
        variant = options.get("variant") or found["variant"]
        report = {"board": self.name, "variant": variant, "found": found, "tests": []}
        images = bitstreams.images_dir(self.slug, options.get("images"))
        try:
            if variant not in self.variants:
                raise Problem("error", f"{found} is no {self.title} variant this package has bitstreams for "
                                       f"({', '.join(self.variants)})")  # fmt: skip
            manifest = bitstreams.load_manifest(images, self.bitstreams_package)
        except Problem as p:
            return {**report, "result": p.result, "reason": p.reason}
        report["bitstreams"] = manifest.get("version")
        for test in options.get("tests") or self.verify_tests:
            report["tests"].append(self.run_test(test, variant, host, images, manifest, runner))
        state = self.identity({**found, "variant": variant})
        jedec = next((t["flash_jedec"] for t in report["tests"] if "flash_jedec" in t), None)
        if jedec:
            state["flash_jedec"] = jedec
        results = [t["result"] for t in report["tests"]]
        try:
            flash = self.read_flash(host, variant, runner)
            if flash:
                state["flash"] = flash
            else:
                report["flash_note"] = self.flash_note
        except Problem as p:
            report["flash_error"] = p.reason
            results.append(p.result)
        report["state"] = state
        report["result"] = worst(results)
        bad = [t for t in report["tests"] if t["result"] != "pass"]
        if bad:
            report["reason"] = "; ".join(f"{t['test']} {t['result']}: {t.get('reason', '')}" for t in bad)
        elif "flash_error" in report:
            report["reason"] = report["flash_error"]
        return report
