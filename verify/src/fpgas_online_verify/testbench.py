"""The check shared by the boards verified with the LiteX test designs: the Arty A7, NeTV2, Fomu EVT and TT FPGA.

On a board with JTAG (the Arty and the NeTV2) its whole IDCODE is read first and decoded (idcode.py): a part
that is not the variant's fails the board, whatever its silicon version. Once that scan has found the one FPGA
expected, its device DNA is read over the same JTAG (`openFPGALoader --read-dna`, dna.py), which loads nothing:
a DNA that cannot be read, or reads all zeros or all ones, fails the board too. For each of the board's boot-check
tests (UART, DDR, SPI flash): check its bitstream against the manifest of fpgas-online-<board>-bitstreams,
load it (into SRAM, except the Fomu's DFU), run its host test script and keep the tail of its output. Then,
where the board can, read back the region of its flash that holds the boot image, for the state (state.py):
loading test designs into SRAM does not touch the flash, so a flash that differs from the recorded one was
written by someone.

The board is left running the last design loaded. A board module is a TestBoard with its detection, its
programmer and its tests; `tests` maps a test to:

  artifact      the CI artifact path in the all-bitstreams bundle; {v} is the variant's suffix
  script        the host test script (host_tests.py), args its arguments; {port} is the board's UART
  verify        True if the boot check runs it; the others need extra wiring (fpgas-<board>-debug runs them)
  pre           commands to run first (each may fail)
  runner        "tt-bridge": the script runs through the TT board's RP2350, which also loads the design
  listen        True if the script must have the UART open before the design starts (listen.py)
  program_args  extra arguments to the programmer
"""

import contextlib
import hashlib
import re
import sys
import tempfile
from typing import ClassVar

from . import bitstreams, dna, host_tests, idcode, identity
from .board import Board
from .core import Problem, host_facts, run, tail, usb_matching, worst

PROGRAM_TIMEOUT = 300
TEST_TIMEOUT = 300
DUMP_TIMEOUT = 900
JTAG_TIMEOUT = 60
# Why the device DNA was not read when the IDCODE scan did not pass.
DNA_SKIPPED = "not read: --read-dna runs only once the JTAG scan has found the one FPGA expected"
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

    # A board with JTAG: variant -> its FPGA's IDCODE at version 0. The check reads the whole IDCODE (from
    # `found`, when finding the board read it, else with idcode_argv) and fails a part that is not the variant's.
    # A `found` with an IDCODE also has the scan that read it: {"idcode_scan": {"tool", "exit", "output"}}, and
    # every IDCODE that scan saw on the chain, in order: {"idcodes": ["0x...", ...]}.
    idcodes: ClassVar[dict] = {}

    def idcode_argv(self, host):
        """The command that scans the board's JTAG chain and prints whole IDCODEs (idcode.parse)."""
        raise NotImplementedError

    def dna_argv(self, host):
        """openFPGALoader --read-dna over the board's JTAG: the same cable and pins as the IDCODE scan."""
        raise NotImplementedError

    @contextlib.contextmanager
    def jtag_driven(self, runner, faults):
        """Held around a JTAG read that drives the Pi's own pins (the NeTV2's), so they are put back afterwards;
        what goes wrong putting them back is added to `faults`. A board on USB drives none of the Pi's pins."""
        yield

    flash_region: ClassVar[dict] = {}  # variant -> bytes of flash holding the boot image (a whole .bit for that part)
    flash_note = ""  # when there is no readback: why the flash is not part of the state
    # systemd units that hold the board's port while they run (the TT site's bridge, fpgas-tt, holds the TT
    # board's /dev/ttyACM0): stopped for the tests, and started again after if they were running.
    services: ClassVar[tuple] = ()

    @contextlib.contextmanager
    def services_stopped(self, runner=run, later=None):
        """Stop whichever of `services` are running; start them again on the way out, whatever happened.

        With `later` (a list), the units stopped are added to it instead of being started: the caller starts
        them once it has written its report (runner.run), so a service that reads the report when it starts
        never reads the one before.

        Yields {"stopped": [...], "failed": [...]}: a unit that would not stop, or whose start could not be
        queued, is in "failed" (the check makes that an error: the service may be left down). The start is
        --no-block: fpgas-verify.service is ordered Before= fpgas-tt, so a blocking start from inside its
        ExecStart (a `systemctl restart fpgas-verify`) would wait on the verify's own start job; queued, it
        runs as soon as the verify is done. At boot the bridge is not running yet (its start waits for the
        verify), so nothing is stopped."""
        held = {"stopped": [], "failed": []}
        for unit in self.services:
            try:
                if runner(["systemctl", "is-active", "--quiet", unit], 30)[0] != 0:
                    continue
                rc, text = runner(["systemctl", "stop", unit], 60)
            except Problem as p:
                rc, text = 1, p.reason
            if rc == 0:
                held["stopped"].append(unit)
            else:
                held["failed"].append(f"{unit} would not stop: {' '.join(tail(text, 2))}")
        try:
            yield held
        finally:
            if later is not None:
                later.extend(unit for unit in held["stopped"] if unit not in later)
            for unit in held["stopped"] if later is None else ():
                try:
                    rc, text = runner(["systemctl", "start", "--no-block", unit], 60)
                except Problem as p:
                    rc, text = 1, p.reason
                if rc != 0:
                    held["failed"].append(f"{unit} was not started again: {' '.join(tail(text, 2))}")

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
            if t.get("listen"):  # the test must be listening before the design starts: listen.py
                test_argv = self.test_argv(test, host, bitstream)
                argv = [sys.executable, "-m", "fpgas_online_verify.listen", host["port"], str(len(test_argv)),
                        *test_argv, *self.program_argv(bitstream, host, test)]  # fmt: skip
                rc, text = runner(argv, PROGRAM_TIMEOUT + TEST_TIMEOUT + 60)  # more than listen.py allows itself
            else:
                if t.get("runner") != "tt-bridge":  # the bridge loads the design itself
                    rc, text = runner(self.program_argv(bitstream, host, test), PROGRAM_TIMEOUT)
                    if rc != 0:
                        return {**out, "result": "fail", "reason": f"loading it failed (exit {rc})",
                                "output": tail(text)}  # fmt: skip
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

    # -- JTAG ------------------------------------------------------------------------------------------------

    def jtag(self, host, found, variant, runner=run):
        """The board's IDCODE, decoded, against its variant's part, and then its device DNA:
        {result, reason?, idcode, idcode_version, ..., dna or dna_error}."""
        return self.read_dna(host, self.read_idcode(host, found, variant, runner), runner)

    def read_idcode(self, host, found, variant, runner=run):
        """The board's IDCODE, decoded, against its variant's part: {result, reason?, idcode, idcode_version, ...}."""
        want = self.idcodes[variant]
        output, scan_faults = [], []
        if found.get("idcode"):  # read when the board was found (the NeTV2's scan)
            codes = [int(c, 16) for c in found.get("idcodes") or [found["idcode"]]]
            scan = found["idcode_scan"]
            output = scan["output"]
            if scan["exit"] != 0:  # whatever it printed, a scan that failed is not trusted
                scan_faults.append(f"{scan['tool']} exited {scan['exit']} reading the IDCODE")
        else:
            argv = self.idcode_argv(host)
            try:
                rc, text = runner(argv, JTAG_TIMEOUT)
            except Problem as p:
                return {"result": p.result, "reason": f"the JTAG chain could not be scanned: {p.reason}"}
            codes = idcode.parse(text)
            output = (codes and rc == 0 and idcode.scan_lines(text)) or tail(text, 6)
            if rc != 0:  # whatever it printed, a scan that failed is not trusted
                scan_faults.append(f"{argv[0]} exited {rc} reading the IDCODE")
            if not codes:
                if idcode.empty_chain(text):
                    reason = "; ".join(["no device on the JTAG chain", *scan_faults])
                elif rc != 0:
                    reason = idcode.scan_failed(argv[0], rc, text)
                else:
                    reason = idcode.NO_RAW_SCAN
                return {"result": "fail", "reason": reason, "output": output}
        entry = {**idcode.decode(codes[0]), **({"output": output} if output else {})}
        faults = idcode.faults(codes[0])
        if len(codes) != 1:
            entry["idcode"] = ", ".join(f"{c:#010x}" for c in codes)
            faults.append(f"the JTAG chain has {len(codes)} devices ({entry['idcode']}), not one")
        elif not idcode.same_part(codes[0], want):
            faults.append(f"the JTAG IDCODE {entry['idcode']} is an {entry['idcode_device']}, not the {variant}'s "
                          f"{idcode.device(want)} (IDCODE {want:#010x}, any version)")  # fmt: skip
        faults += scan_faults
        return {**entry, "result": "fail", "reason": "; ".join(faults)} if faults else {**entry, "result": "pass"}

    def read_dna(self, host, entry, runner=run):
        """The JTAG entry with the device DNA added (dna, 16 hex digits), or dna_error saying why there is none.
        It is read only once the IDCODE scan passed (one device, the variant's part); FUSE_DNA reconfigures
        nothing. A DNA that cannot be read, or that reads all zeros or all ones (dna.faults), fails the entry."""
        if entry["result"] != "pass":
            return {**entry, "dna_error": DNA_SKIPPED}
        argv = self.dna_argv(host)
        faults, driven = [], []  # driven: what went wrong putting the Pi's JTAG pins back
        text = ""
        try:
            with self.jtag_driven(runner, driven):
                rc, text = runner(argv, JTAG_TIMEOUT)
        except Problem as p:
            faults.append((p.result, f"the device DNA could not be read: {p.reason}"))
        else:
            value = dna.parse(text) if rc == 0 else None
            if value is None:
                last = (tail(text, 1) or ["no output"])[0].strip()
                faults.append(("fail", f"openFPGALoader --read-dna read no device DNA (exit {rc}): {last}"))
            else:
                faults += [("fail", f) for f in dna.faults(value, "JTAG")]
        out = {**entry, "output": [*entry.get("output", []), *tail(text, 4)]}
        if faults:
            out["dna_error"] = "; ".join(reason for _, reason in faults)
        else:
            out["dna"] = identity.dna(value)
        faults += [("error", f) for f in driven]
        if not faults:
            return out
        result = "error" if all(r == "error" for r, _ in faults) else "fail"
        return {**out, "result": result, "reason": "; ".join(reason for _, reason in faults)}

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
        return {k: v for k, v in found.items() if k in ("variant", "serial", "idcode", "dna") and v is not None}

    def port_facts(self, host, found, runner=run):
        """Identity fields only the board's own port gives, read while `services` are stopped and before any
        test (the TT FPGA's, from rpi-hwid): {} for a board with none. A read that was tried and failed is a
        <field>_error, which makes the check an error."""
        return {}

    # A board whose variant finding it does not give (the Tiny Tapeout demo board: an RP2 on USB is the same
    # whatever chip it carries): `found` has no variant, and settle() decides it from what the board itself
    # said (port_facts), before any design is chosen. Other boards leave this False and nothing changes for
    # them.
    variant_from_board = False
    # Tests judged from what the board itself said (port_facts), which load nothing: test -> {"variants": the
    # variants it is for, "check": f(variant, facts) giving (result, the reason or None, lines for the report)}.
    # They run first, in the whole boot check only (not when single tests were asked for), and are the whole
    # check of a variant that no bitstream here is for (a demo board with a Tiny Tapeout chip).
    fact_tests: ClassVar[dict] = {}
    # variant -> {test: why}: a test that variant must have and the boot check does not run yet. It goes in the
    # report's `not_run`, and the board FAILS with that reason: a board is not passed on a check that leaves
    # out a test it needs (Tim, 2026-10-05: "Fail until wiring is tested"). Its other tests still run and are
    # reported, so the report shows what is known of the board.
    pending: ClassVar[dict] = {}

    # variant -> a design the check loads last and leaves running, which is no test: nothing reads it (the TT
    # FPGA's moving display, #139): {"design": its name, "artifact": as a test's, "program_args": as a test's}.
    # It is in the board's bitstreams package beside the tests' designs. A load that fails is a warning in the
    # report, never the board's result: the board was tested before it, and is left as its last test left it.
    left_running: ClassVar[dict] = {}

    def artifacts(self):
        """[(test or design name, variant, artifact path)]: every bitstream the bitstreams package holds."""
        out = [(test, variant, self.artifact(test, variant)) for test in self.tests for variant in self.variants]
        return out + [(spec["design"], variant, spec["artifact"]) for variant, spec in self.left_running.items()]

    def leave_running(self, variant, host, images, manifest, runner=run):
        """Load the variant's left_running design: (what the report says was left running, None), or
        (None, why it could not be loaded). Never raises."""
        spec = self.left_running[variant]
        try:
            entry = bitstreams.entry_for(manifest, spec["artifact"], self.bitstreams_package)
            bitstream = bitstreams.checked(images, entry)[0]
            argv = [*self.program_argv(bitstream, host, None), *spec.get("program_args", [])]
            rc, text = runner(argv, PROGRAM_TIMEOUT)
        except Problem as p:
            return None, p.reason
        if rc != 0:
            return None, f"loading it failed (exit {rc}): {' '.join(tail(text, 2))}"
        return {"design": spec["design"], "bitstream": spec["artifact"]}, None

    def settle(self, asked, found, facts):
        """The variant of a board with variant_from_board, from `facts`; `asked` is --variant, or None. It is one
        of `variants` or one a fact test is for, or a Problem saying why the board is not checked: then no test
        runs and nothing is loaded."""
        raise NotImplementedError

    def fact_tests_for(self, variant):
        return [name for name, t in self.fact_tests.items() if variant in t["variants"]]

    def run_fact_test(self, test, variant, facts):
        result, reason, output = self.fact_tests[test]["check"](variant, facts)
        return {"test": test, "result": result, **({"reason": reason} if reason else {}), "output": list(output)}

    def identified(self, report, found, options, facts=None):
        """Who the board is (identity.py), from how it was found, its JTAG IDCODE and DNA, and `facts`
        (port_facts): put in the report and sent as fpga-board-identified, before any test runs."""
        out = identity.base(options.get("board_key", self.name), self.name, found, report["variant"])
        if "jtag" in report:
            out.update(identity.idcode_fields(report["jtag"]))
            out.update(identity.dna_fields(report["jtag"]))
        out.update(facts or {})
        report["identity"] = out
        identity.keep(options, out)
        (options.get("event") or (lambda stage, details: None))("fpga-board-identified", identity.details(out))

    # The flash is read back with a design loaded (openFPGALoader's SPI-over-JTAG bridge): --identify takes it
    # from the boot report.
    report_fields = ("flash",)

    def identify(self, host, found, options, runner=run):
        """How the board was found, and its IDCODE and device DNA over JTAG on a board with JTAG: nothing is
        loaded and nothing is reconfigured."""
        variant = options.get("variant") or found["variant"]
        out = identity.base(options.get("board_key", self.name), self.name, found, variant)
        if self.idcodes and variant in self.idcodes:
            jtag = self.jtag(host, found, variant, runner)
            out.update(identity.idcode_fields(jtag))
            out.update(identity.dna_fields(jtag))
        return out

    def check(self, host, found, options, runner=run):
        late = self.variant_from_board  # the variant is settled from the board's own word, once its port is ours
        variant = options.get("variant") or found["variant"]
        report = {"board": self.name, "variant": None if late else variant, "found": found, "tests": []}
        images = bitstreams.images_dir(self.slug, options.get("images"))
        tests = self.verify_tests if options.get("tests") is None else options["tests"]
        manifest, refused = None, None
        try:
            unknown = [t for t in tests if t not in self.tests]
            if unknown:
                raise Problem(
                    "error", f"{self.title} has no test {', '.join(unknown)} (it has {', '.join(self.tests)})"
                )
            if not late:
                if variant not in self.variants:
                    raise Problem("error", f"{found} is no {self.title} variant this package has bitstreams for "
                                           f"({', '.join(self.variants)})")  # fmt: skip
                manifest = bitstreams.load_manifest(images, self.bitstreams_package)
        except Problem as p:
            self.identified(report, found, options)
            return {**report, "result": p.result, "reason": p.reason}
        if manifest is not None:
            report["bitstreams"] = manifest.get("version")
        if self.idcodes and not late:  # a JTAG part is a variant's: none is known yet for a late one
            report["jtag"] = self.jtag(host, found, variant, runner)
        event = options.get("event") or (lambda stage, details: None)
        with self.services_stopped(runner, options.get("restart_later")) as held:
            facts = self.port_facts(host, found, runner)
            if late:
                try:
                    variant = report["variant"] = self.settle(options.get("variant"), found, facts)
                    if variant in self.variants:
                        manifest = bitstreams.load_manifest(images, self.bitstreams_package)
                        report["bitstreams"] = manifest.get("version")
                    elif not options.get("tests"):  # no design is for it: its fact tests are its check
                        tests = []
                    else:
                        raise Problem("error", f"the board is a {variant}: {', '.join(tests)} "
                                               f"{'is' if len(tests) == 1 else 'are'} for a "
                                               f"{' or '.join(self.variants)}, so nothing was loaded")  # fmt: skip
                except Problem as p:  # not settled, or no bitstreams: no test runs and nothing is loaded
                    refused, tests = p, []
            self.identified(report, found, options, facts)
            # No test named (None, or an empty list, which names none): the board's own word is judged.
            for test in self.fact_tests_for(variant) if not options.get("tests") and not refused else ():
                event("fpga-test-started", {"test": test})
                report["tests"].append(self.run_fact_test(test, variant, facts))
                done = report["tests"][-1]
                event("fpga-test-finished", {"test": test, "result": done["result"], "reason": done.get("reason", "")})
            if not refused and self.pending.get(variant):
                report["not_run"] = dict(self.pending[variant])
            for test in tests:
                event("fpga-test-started", {"test": test})
                report["tests"].append(self.run_test(test, variant, host, images, manifest, runner))
                done = report["tests"][-1]
                event("fpga-test-finished", {"test": test, "result": done["result"], "reason": done.get("reason", "")})
            if not refused and manifest is not None and variant in self.left_running:  # last: nothing follows it
                left, why_not = self.leave_running(variant, host, images, manifest, runner)
                if left:
                    report["left_running"] = left
                else:
                    name = self.left_running[variant]["design"]
                    report["warnings"] = [f"the {name} design, which the check leaves running, could not be loaded "
                                          f"({why_not}): the board is left as its last test left it"]  # fmt: skip
        if held["stopped"]:
            report["services_stopped"] = held["stopped"]
        jtag = report.get("jtag", {})
        state = self.identity({**found, "variant": variant, "idcode": jtag.get("idcode") or found.get("idcode"),
                               "dna": jtag.get("dna")})  # fmt: skip
        jedec = next((t["flash_jedec"] for t in report["tests"] if "flash_jedec" in t), None)
        if jedec:
            state["flash_jedec"] = jedec
        results = [t["result"] for t in report["tests"]] + ([jtag["result"]] if jtag else [])
        facts_failed = [f"{k}: {v}" for k, v in facts.items() if k.endswith(identity.ERROR_SUFFIX)]
        if facts_failed:
            results.append("error")
        try:
            flash = self.read_flash(host, variant, runner)
            if flash:
                state["flash"] = flash
            else:
                report["flash_note"] = self.flash_note
        except Problem as p:
            report["flash_error"] = p.reason
            results.append(p.result)
        if held["failed"]:
            report["services_failed"] = held["failed"]
            results.append("error")
        if refused:
            results.append(refused.result)
        report["state"] = state
        untested = [f"{test} not run: {why}" for test, why in report.get("not_run", {}).items()]
        if untested:
            results.append("fail")
        report["result"] = worst(results)
        bad = [t for t in report["tests"] if t["result"] != "pass"]
        reasons = [f"{t['test']} {t['result']}: {t.get('reason', '')}" for t in bad] + untested + facts_failed
        reasons += held["failed"]
        if refused:
            reasons.insert(0, refused.reason)
        if jtag and jtag["result"] != "pass":
            reasons.insert(0, f"jtag {jtag['result']}: {jtag['reason']}")
        if reasons:
            report["reason"] = "; ".join(reasons)
        elif "flash_error" in report:
            report["reason"] = report["flash_error"]
        return report
