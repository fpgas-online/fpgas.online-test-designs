"""The Acorn check: every test that can run, in order, with every fault kept.

There is one result, pass or fail (docs/verify-goals.md): any fault fails the board, and the check goes on
after a fault wherever it can, so the report lists all of them. A test that cannot run because of an
earlier fault (no BAR0 on a board running SQRL's factory image, say) is listed in `not_run` with why; the
fault that stopped it is already in the report.

The safety rules hold throughout: nothing past the identifier read is sent over BAR0 or over the P2 UART
unless that identifier is a build of the installed release, whose CSR map is then read from the release's
csr.json; nothing at all is sent to the BARs of a design whose PCI IDs are not ours; the flash is only ever
read; and the FPGA is never reconfigured.

  pcie-link  the link speed and width in sysfs, against the setup's expected figures (expected.toml)
  pcie-bar0  over BAR0: which build runs (golden is a fault: the operational slot did not boot), the
             flash's identity, the device DNA and the XADC temperature and voltages
  rp1-pio    on a Pi 5 / CM5: the RP1 PIO openfpgaloader-rp1pio uses, /dev/pio0 there and openable (links.py)
  jtag       IDCODE and device DNA over P1 (links.py); the DNA must be BAR0's
  flash      both flash slots read whole and compared with the release's images
  ddr        the BIOS console read out (it lets the BIOS finish DRAM set-up, #47), then the DRAM BIST over
             the whole DRAM, two passes (bist.py): no errors, and write and read bandwidth at least the
             variant's minimum (expected.toml)
  p2-uart    the UARTBone bridge on P2 at both baud rates: identifier, DNA, XADC (links.py)
  p2-serial  J2/K2 in both directions through the p2_serial switch, then the UARTBone again (links.py)
  scratch    the ctrl scratch register written and read back over BAR0 and over the P2 UART
  p2-gpio    J5/H5 in both directions (links.py), on a setup whose cable carries them

The golden image has no DRAM and no P2 switch or spare GPIO: on it `ddr`, `p2-serial` and `p2-gpio` are
not run, and running it is already a fault (`pcie-bar0`).

A kernel driver holding BAR0 (litepcie.ko) is unbound for the check, only when a test asked for needs BAR0,
and bound again after it. No events are sent while it is unbound: they are held and sent once it is bound
again.

A test that raises something unexpected is recorded as an error with what it raised, and the rest still run.
"""

import contextlib
import time

from ... import identity
from ...core import Problem, pi_model, run, worst
from . import bist, check, links
from . import setup as setups

TESTS = ("pcie-link", "pcie-bar0", "rp1-pio", "jtag", "flash", "ddr", "p2-uart", "p2-serial", "scratch", "p2-gpio")
# Opt-in (options["power_cycle_check"], the `power-cycle-check` setting): not a test at all unless switched on.
POWER_CYCLE = "power-cycle"
# The tests fpgas-verify --identify runs: they only read (BAR0's identifier, DNA, XADC and the flash's identity;
# IDCODE and DNA over P1 JTAG).
IDENTIFY_TESTS = ("pcie-bar0", "jtag")
NEEDS_BAR0 = ("pcie-bar0", POWER_CYCLE, "flash", "ddr", "p2-serial", "scratch", "p2-gpio")
CONSOLE_TAIL = 8  # BIOS console lines kept in the ddr test's output
GOLDEN = "running the golden image: the operational slot did not boot"


def _quiet(stage, details):
    pass


def _problem(e, what):
    """A Problem as it is, anything else as the error it is (a malformed file, say)."""
    if isinstance(e, Problem):
        return e
    return Problem("error", f"{what} could not be read: {type(e).__name__}: {e}")


class _Suite:
    def __init__(self, found, options):
        self.found = found
        self.options = options
        self.images = options.get("images") or check.IMAGES
        self.root = options.get("sysfs_pci", check.SYSFS_PCI)
        self._send = options.get("event") or _quiet
        self._held = []  # events held while a driver is unbound
        self.run = options.get("run", run)
        self.power_cycle_check = bool(options.get("power_cycle_check"))
        self.tests = (*TESTS[:2], POWER_CYCLE, *TESTS[2:]) if self.power_cycle_check else TESTS
        self.wanted = list(options.get("tests") or self.tests)
        self.marker = None  # this boot's scratch marker, once the power-cycle test has passed
        self.report = {"board": "acorn", "found": found, "variant": found["variant"], "tests": []}
        self.faults = []  # (result, reason) that belong to no one test
        self.not_run = {}
        self.setup = self.figures = self.release = self.uart_builds = None
        self.bus = self.csrs = None
        self.bar0 = {}  # what BAR0 gave: identifier, build, dna
        self.gate_problem = self.bar0_problem = None
        self.driver = {}  # a kernel driver unbound for the check (check.driver_released)
        self.flash_error = None  # why the flash did not identify itself

    # -- helpers ---------------------------------------------------------------------------------------

    def fault(self, problem):
        self.faults.append((problem.result, problem.reason))

    def event(self, stage, details):
        """Send an event, or hold it while a kernel driver is unbound from the board."""
        if self.driver.get("unbound") and not ("rebound" in self.driver or "rebind_error" in self.driver):
            self._held.append((stage, details))
        else:
            self._send(stage, details)

    def _flush(self):
        held, self._held = self._held, []
        for stage, details in held:
            self._send(stage, details)

    def test(self, name, why_not, fn):
        """Run test `name` if it was asked for and nothing stops it; record it and say so as it goes."""
        if name not in self.wanted:
            return
        if why_not:
            self.not_run[name] = why_not
            return
        self.event("fpga-test-started", {"test": name})
        try:
            entry = fn()
        except Problem as p:
            entry = {"test": name, "result": p.result, "reason": p.reason}
        except Exception as e:  # anything else is the check's own fault: say so, and go on with the rest
            entry = {"test": name, "result": "error", "reason": f"{type(e).__name__}: {e}"}
        self.report["tests"].append(entry)
        self.event("fpga-test-finished", {"test": name, "result": entry["result"], "reason": entry.get("reason", "")})

    def _needs_setup(self):
        return None if self.setup else "this host's setup is not known"

    def _needs_bar0(self):
        if self.bus is not None:
            return None
        return (self.gate_problem or self.bar0_problem).reason

    # -- the parts --------------------------------------------------------------------------------------

    def _load(self):
        try:
            self.figures = self.options.get("expected") or setups.load(setups.EXPECTED)
        except Problem as p:
            self.fault(p)
            self.figures = {}  # said once: the setup below is still found, with no figures
        try:
            model = self.options["model"] if "model" in self.options else pi_model()
            self.setup = setups.detect(model, self.options.get("wiring"), self.figures)
            self.report["setup"] = self.setup.name
        except Problem as p:
            self.fault(p)
        if self.found["kind"] != "fpgas-online":
            return
        try:
            manifest, files = check.load_release(self.images)
            builds, layout = check.expectations(manifest, files, self.found["variant"])
            self.release = (manifest, files, builds, layout)
            self.report["bitstreams"] = manifest.get("tag")
        except Exception as e:  # a damaged manifest: the tests that need no release still run
            self.release = None
            self.fault(_problem(e, "the installed release"))
            return
        try:
            self.uart_builds = {b["config_identifier"].casefold(): check.build_csrs(self.images, files, b)
                                for b in builds.values()}  # fmt: skip
        except Exception as e:
            self.fault(_problem(e, "the release's csr.json"))

    def _open_bar0(self, stack):
        """Release the driver, map BAR0 and pass the gate; on any failure, say why in bar0_problem."""
        reason = check.not_ours(self.found)
        if reason or self.release is None:
            self.bar0_problem = Problem("fail", reason or "the installed release could not be read")
            return
        if not set(self.wanted) & set(NEEDS_BAR0):  # nothing asked for needs it: leave the board and its driver be
            self.bar0_problem = Problem("pass", "no test asked for needs BAR0")
            return
        manifest, files, builds, _ = self.release
        self.bar0_problem = None
        try:
            stack.enter_context(check.driver_released(self.found, self.driver, self.root))
            bus = stack.enter_context(self.options.get("open_bar", check.open_bar0)(self.found["bdf"]))
            if self.options.get("identify_only"):  # --identify: only the flash's ID reads write anything
                bus = check.IdentifyBus(bus)
        except Problem as p:
            self.fault(p)
            self.bar0_problem = p
            return
        except OSError as e:
            self.bar0_problem = Problem("error", f"BAR0 of {self.found['bdf']} could not be opened: {e}")
            self.fault(self.bar0_problem)
            return
        try:
            seen, build, csrs = check.gate(bus, self.images, files, builds, manifest.get("tag"))
        except Problem as p:
            self.report.update(p.seen)
            self.gate_problem = p
            if "pcie-bar0" not in self.wanted:
                self.fault(p)
            return
        self.report.update(seen)
        self.bus, self.csrs = bus, csrs
        self.bar0.update(identifier=seen["running"]["identifier"], build=build)

    # -- the tests ---------------------------------------------------------------------------------------

    def pcie_link(self):
        status = check.link_status(self.found["bdf"], self.root)
        expected = self.setup.expected.get("pcie")
        if not expected:
            return {"test": "pcie-link", **status, "result": "error",
                    "reason": f"no expected PCIe figures for the {self.setup.name} setup"}  # fmt: skip
        faults = check.link_faults(status, expected)
        entry = {"test": "pcie-link", **status, "expected": expected, "result": "fail" if faults else "pass"}
        return {**entry, "reason": "; ".join(faults)} if faults else entry

    def pcie_bar0(self):
        if self.gate_problem:
            return {"test": "pcie-bar0", "result": self.gate_problem.result, "reason": self.gate_problem.reason,
                    **self.report.get("running", {})}  # fmt: skip
        faults, entry = [], {"test": "pcie-bar0", **self.report["running"]}
        if self.bar0["build"] == "golden":
            faults.append(GOLDEN)
        try:
            self.report["flash"] = check.flash_identity(check.spi_flash.Flash(self.bus))
        except check.spi_flash.FlashError as e:
            self.flash_error = f"the flash did not identify itself: {e}"
            faults.append(self.flash_error)
        sfdp_error = (self.report.get("flash") or {}).get("sfdp_error")
        if sfdp_error:
            faults.append(f"the flash's SFDP could not be read: {sfdp_error}")
        dna = check.read_dna(self.bus.read, self.csrs)
        self.bar0["dna"] = dna
        xadc = check.read_xadc(self.bus.read, self.csrs)
        entry.update(dna=f"{dna:#x}", xadc=xadc, flash=dict(self.report.get("flash") or {}))
        faults += check.dna_faults(dna, "BAR0")
        faults += check.xadc_faults(xadc, self.figures.get("xadc", {}), "BAR0")
        return {**entry, "result": "fail", "reason": "; ".join(faults)} if faults else {**entry, "result": "pass"}

    def rp1_pio(self):
        return self.options.get("rp1_pio", links.rp1_pio)(self.run)

    def jtag(self):
        return links.jtag(self.setup, self.found["variant"], self.run, self._good_bar0_dna(),
                          self.options.get("gpiochip"))  # fmt: skip

    def _good_bar0_dna(self):
        """BAR0's DNA, for the other paths to be compared with, unless it is stuck (check.dna_faults): that is
        pcie-bar0's own fault, not the JTAG's or the P2 UART's, so it is not compared at all."""
        dna = self.bar0.get("dna")
        return None if dna is None or check.dna_faults(dna, "BAR0") else dna

    def flash(self):
        manifest, files, _, layout = self.release
        slots = check.flash_slots(self.bus, self.images, files, layout)
        self.report.setdefault("flash", {})["slots"] = slots
        entry = {"test": "flash", "slots": [{k: s[k] for k in s if k != "sha256"} for s in slots]}
        bad = [s for s in slots if s["result"] != "match"]
        if not bad:
            return {**entry, "result": "pass"}
        where = ", ".join(f"{s['slot']} differs at {s['first_difference']}" for s in bad)
        return {**entry, "result": "fail", "reason": f"flash does not hold release {manifest.get('tag')}: {where}"}

    def p2_uart(self):
        bar0 = {"identifier": self.bar0.get("identifier"), "dna": self._good_bar0_dna()}
        return links.p2_uart(self.setup, self.uart_builds, self.figures, bar0, self.options.get("uart_opener"),
                             self.options.get("settle"))  # fmt: skip

    def power_cycle(self):
        """Opt-in: the FPGA was configured since the last check (check.power_cycle_verdict). Read only; the
        marker is written at the end of the check (_mark), after the scratch test has put the register back."""
        marker = check.boot_marker(self.options.get("boot_id") or check.boot_id())
        fault, found = check.power_cycle_verdict(self.bus.read(self.csrs.addr("ctrl_scratch")), marker)
        if fault:
            return {"test": POWER_CYCLE, "result": "fail", "reason": fault}
        self.marker = marker
        return {"test": POWER_CYCLE, "result": "pass", "output": [found]}

    def _mark(self):
        """Leave this boot's marker in the scratch register, so the next boot's check can tell whether the
        FPGA was configured in between. Only after the power-cycle test passed: a board that failed it is
        left as it was found, and fails again until it is power-cycled."""
        if self.marker is None or self.bus is None:
            return
        try:
            addr = self.csrs.addr("ctrl_scratch")
            self.bus.write(addr, self.marker)
            got = self.bus.read(addr)
            if got != self.marker:
                self.faults.append(
                    ("fail", f"power-cycle: wrote the marker {self.marker:#010x} to scratch, read {got:#010x}")
                )
        except Exception as e:  # the check's own fault: say so
            self.faults.append(("error", f"power-cycle: the marker could not be written: {type(e).__name__}: {e}"))

    def scratch(self):
        faults, done = [], []
        if self.bus is not None:
            faults += [("fail", f) for f in check.scratch_faults(self.bus.read, self.bus.write, self.csrs, "BAR0")]
            done.append("BAR0")
        else:
            self.not_run["scratch over BAR0"] = self._needs_bar0()
        if self.setup and self.uart_builds:
            faults += links.uart_scratch(self.setup, self.uart_builds, self.options.get("uart_opener"),
                                         self.options.get("settle"))  # fmt: skip
            done.append("P2 UART")
        else:
            self.not_run["scratch over P2 UART"] = self._needs_setup() or "no release builds to talk to"
        return links._entry("scratch", faults, over=done)

    def p2_gpio(self):
        return links.p2_gpio(self.setup, self.bus, self.csrs, self.run)

    def p2_serial(self):
        return links.p2_serial(self.setup, self.bus, self.csrs, self.run, self.bar0.get("identifier"),
                               self.options.get("uart_opener"), self.options.get("settle"),
                               self.options.get("sleep"))  # fmt: skip

    def ddr(self):
        regs = bist.Regs(self.bus.read, self.bus.write, self.csrs)
        sleep = self.options.get("sleep")
        started = time.monotonic()
        clock = self.options.get("clock", time.monotonic)
        text = bist.console(regs, quiet_s=self.options.get("console_quiet_s", 2.0), clock=clock, sleep=sleep)
        out = bist.dram(regs, self.options.get("ddr_bytes"), sleep=sleep, clock=clock)
        faults = out.pop("faults")
        entry = {"test": "ddr", **{k: out[k] for k in ("bytes", "passes", "errors") if k in out}}
        entry.update({k: out[k] for k in ("write_MBps", "read_MBps") if k in out})
        entry["seconds"] = round(time.monotonic() - started, 1)
        entry["bios_memtest"] = bist.memtest_line(text)
        entry["output"] = [line for line in text.splitlines() if line.strip()][-CONSOLE_TAIL:]
        least = self.figures.get("ddr", {}).get(self.found["variant"])
        if least is None:
            faults.append(f"no DDR figures for {self.found['variant']} in expected.toml")
        elif "write_MBps" in out:
            for what in ("write", "read"):
                got, want = out[f"{what}_MBps"], least[f"min_{what}_MBps"]
                if got < want:
                    faults.append(f"DRAM {what} {got} MB/s, below the {want} MB/s expected of {self.found['variant']}")
        return {**entry, "result": "fail", "reason": "; ".join(faults)} if faults else {**entry, "result": "pass"}

    # -- the whole check -------------------------------------------------------------------------------

    def identity(self):
        """Who the board is (identity.py), from what PCIe, BAR0 and JTAG read."""
        f, r = self.found, self.report
        out = identity.base(self.options.get("board_key", "acorn"), "acorn", f)
        running = r.get("running") or {}
        soc_model = check.soc_model(f["kind"], running.get("identifier"))
        if soc_model:
            out["soc_model"] = soc_model
        if running.get("identifier"):
            out["identifier"] = running["identifier"]
        if running.get("build"):
            out["build"] = running["build"]
        jtag = next((t for t in r["tests"] if t["test"] == "jtag"), None)
        # A DNA of all zeros or all ones is a DNA port not being read (check.dna_faults), so not a DNA: the other
        # path's is used if it is good, and otherwise dna_error says why neither was.
        dna, dna_errors = None, []
        if "dna" in self.bar0:
            dna_errors += check.dna_faults(self.bar0["dna"], "BAR0")
            dna = None if dna_errors else self.bar0["dna"]
        if dna is None and jtag:
            if "dna" in jtag:
                stuck = check.dna_faults(int(jtag["dna"], 16), "P1 JTAG")
                dna_errors += stuck
                dna = None if stuck else jtag["dna"]
            elif jtag.get("dna_error"):
                dna_errors.append(jtag["dna_error"])  # why the DNA read itself failed, not the IDCODE's faults
            elif jtag["result"] != "pass":  # the jtag test stopped before it said
                stopped = jtag.get("reason") or jtag["result"]
                dna_errors.append(f"not read over P1 JTAG: the jtag test stopped: {stopped}")
        if dna is not None:
            out["dna"] = identity.dna(dna)
        elif dna_errors:
            out["dna_error"] = "; ".join(dna_errors)
        if jtag:
            out.update(identity.idcode_fields(jtag))
        if (r.get("flash") or {}).get("rdid"):
            out.update(identity.flash_fields(r["flash"], "pcie"))
        elif self.flash_error:
            out.update(flash_error=self.flash_error, flash_source="pcie")
        return out

    def identified(self):
        """Put who the board is in the report, hand it to the runner and send fpga-board-identified."""
        self.report["identity"] = self.identity()
        identity.keep(self.options, self.report["identity"])
        self.event("fpga-board-identified", identity.details(self.report["identity"]))

    def check(self):
        unknown = [t for t in self.wanted if t not in self.tests]
        if unknown:
            raise Problem("error", f"the Acorn has no test {', '.join(unknown)} (it has {', '.join(self.tests)})")
        reason = check.not_ours(self.found)
        if reason:
            self.faults.append(("fail", reason))
        if not check.is_acorn(self.found):  # an FPGA we cannot name as an Acorn: nothing else is ours to test
            return self.finish()
        self._load()
        with contextlib.ExitStack() as stack:
            stack.callback(self._flush)  # whatever happens, the held events go out once the driver is back
            self._open_bar0(stack)
            no_bar0 = self._needs_bar0()
            no_variant = None if self.found["variant"] else "the variant is not known"
            no_uart = self._needs_setup() or (None if self.uart_builds else "the board does not run a known build")
            self.test("pcie-link", self._needs_setup(), self.pcie_link)
            self.test("pcie-bar0", None if self.gate_problem else no_bar0, self.pcie_bar0)
            if self.power_cycle_check:
                self.test(POWER_CYCLE, no_bar0, self.power_cycle)
            self.test("rp1-pio", self.options.get("rp1_host", links.not_rp1_host)(), self.rp1_pio)
            self.test("jtag", self._needs_setup() or no_variant, self.jtag)
            self.identified()
            golden = "the golden image has no {}" if self.bar0.get("build") == "golden" else None
            if golden and "pcie-bar0" not in self.wanted:  # pcie-bar0 says so when it runs
                self.faults.append(("fail", GOLDEN))
            self.test("flash", no_bar0, self.flash)
            self.test("ddr", no_bar0 or (golden and golden.format("DRAM")), self.ddr)
            self.test("p2-uart", no_uart, self.p2_uart)
            no_serial = self._needs_setup() or (
                None if self.setup.p2_serial else f"J2 and K2 are not wired on the {self.setup.name} setup"
            )
            self.test("p2-serial", no_serial or no_bar0 or (golden and golden.format("P2 serial switch")),
                      self.p2_serial)  # fmt: skip
            self.test("scratch", None if self.bus is not None or not no_uart else no_bar0, self.scratch)
            no_gpio = self._needs_setup() or (
                None if self.setup.p2_gpio else f"J5 and H5 are not wired on the {self.setup.name} setup"
            )
            self.test("p2-gpio", no_gpio or no_bar0 or (golden and golden.format("P2 spare GPIO")), self.p2_gpio)
            self._mark()
        self._flush()
        if self.driver:
            self.report["driver"] = self.driver
            if "rebind_error" in self.driver:
                self.faults.append(("error", self.driver["rebind_error"]))
        return self.finish()

    def finish(self):
        r = self.report
        if "identity" not in r:
            self.identified()
        if self.not_run:
            r["not_run"] = self.not_run
        asked = [t for t in self.wanted if t in self.tests]
        if check.is_acorn(self.found) and asked and not r["tests"]:
            # a check that tested nothing has not shown the board works, whatever else it found
            self.faults.append(("fail", f"none of the tests asked for ran ({', '.join(asked)})"))
        bad = [t for t in r["tests"] if t["result"] != "pass"]
        r["result"] = worst([*(res for res, _ in self.faults), *(t["result"] for t in r["tests"])])
        reasons = [reason for _, reason in self.faults] + [f"{t['test']} {t['result']}: {t.get('reason', '')}"
                                                           for t in bad]  # fmt: skip
        if reasons:
            r["reason"] = "; ".join(reasons)
        r["state"] = self.state()
        return r

    def state(self):
        f = self.found
        state = {"bdf": f["bdf"], "ids": f["ids"], "subsystem": f["subsystem"]}
        if f["variant"]:
            state["variant"] = f["variant"]
        dna = self.report.get("identity", {}).get("dna")  # 16 digits since state schema 4
        if dna:
            state["dna"] = dna
        flash = self.report.get("flash")
        if flash:
            state["flash"] = {k: flash[k] for k in ("part", "jedec", "unique_id") if k in flash}
            slots = {s["slot"]: s["sha256"] for s in flash.get("slots", []) if "sha256" in s}
            if slots:
                state["flash"]["slots"] = slots
        return state


def check_board(found, options):
    """The board's report: {board, found, variant, result, reason, tests, ...}."""
    return _Suite(found, options).check()
