"""Tests for fpgas-verify --identify (fpgas_online_verify.identify) and the nesting rpi-hwid's labels need.

* --identify prints exactly one identity document (identity.document()), read live with the reads that
  disturb nothing, each board under its own lock; fields only the boot check can read come from the boot
  report when the board there is this one, and are named in "from_report".
* It exits 0 only when every board's identity is whole; the document is printed either way.
* With FPGAS_VERIFY_IDENTITY set (inside fpgas-verify --label), --identify prints that file unchanged and
  touches nothing: no lock, no board module, no hardware, even when the file is missing or bad. Every other
  mode refuses.
"""

import functools
import json
import pathlib

import pytest
from fpgas_online_verify import cli, debug, identify, identity
from fpgas_online_verify.boards.acorn import BOARD as ACORN
from fpgas_online_verify.core import Problem

from tests import acorn_fakes as fk
from tests.test_acorn_verify import Rig
from tests.test_spi_flash import sf
from tests.test_verify_boards import ARTY, ARTY_FOUND, NETV2, Runner, _host
from tests.test_verify_runner import Fake

GOLDEN = pathlib.Path(__file__).parent / "data" / "identity-v1-acorn-p48.json"
WRITES = {0x06, 0x12, 0x21, 0xDC, 0x01, 0xC7, 0x60}  # WREN, program, erase, write registers, chip erase


@pytest.fixture
def images(tmp_path):
    return fk.release(tmp_path / "images")


class Identified(Fake):
    """A Fake board whose identify() adds `read` to how it was found."""

    def __init__(self, name, read=None, label_fields=(), report_fields=(), **kw):
        super().__init__(name, **kw)
        self.read, self.label_fields, self.report_fields = dict(read or {}), label_fields, report_fields
        self.identified = []

    def identify(self, host, found, options):
        self.identified.append(options["board_key"])
        return {**identity.base(options["board_key"], self.name, found), **self.read}


class Locks:
    """Stands in for core.hold_lock: records each lock taken (and in `log`, when it was), and which are held."""

    def __init__(self, log=None):
        self.taken, self.held, self.log = [], [], log if log is not None else []

    def __call__(self, path, what, timeout=None):
        outer = self
        assert timeout == identify.LOCK_WAIT  # --identify never waits without a bound

        class _Held:
            def __enter__(self):
                outer.taken.append(path)
                outer.held.append(path)
                outer.log.append(["lock", path])

            def __exit__(self, *a):
                outer.held.remove(path)
                outer.log.append(["unlock", path])
                return False

        return _Held()


@pytest.fixture
def locks(monkeypatch):
    held = Locks()
    monkeypatch.setattr(identify, "hold_lock", held)
    monkeypatch.delenv(identify.ENV, raising=False)
    return held


def _read(boards, tmp_path, **options):
    return identify.read({"board": next(iter(boards)), "boot_report": tmp_path / "verify.json", **options},
                         boards, usb=[], pci=[])  # fmt: skip


# -- the document --------------------------------------------------------------------------------------------


def test_the_document_is_identity_document_with_every_board(tmp_path, locks):
    arty = Identified("arty", seen=[{"variant": "a7-35", "serial": "210319B", "usb": "1-1"}],
                      read={"idcode": "0x0362d093"}, label_fields=("idcode",))  # fmt: skip
    doc, gaps = _read({"arty": arty}, tmp_path)
    assert gaps == []
    assert {k: doc[k] for k in ("schema", "identity_version", "source")} == {
        "schema": "fpgas-verify/identity", "identity_version": 1, "source": "live"}  # fmt: skip
    assert doc["tool"].startswith("fpgas-online-verify ") and doc["read_at"].endswith("+00:00")
    assert doc["boards"] == [{"board": "arty", "kind": "arty", "variant": "a7-35", "serial": "210319B",
                              "usb": "1-1", "idcode": "0x0362d093"}]  # fmt: skip
    assert arty.checked == []  # the check itself never runs


def test_each_board_is_read_under_its_own_lock(tmp_path, locks):
    class Seen(Identified):
        def identify(self, host, found, options):
            assert locks.held == [self.lock]
            return super().identify(host, found, options)

    a = Seen("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    f = Seen("fomu", seen=[{"variant": "evt", "serial": "F"}])
    doc, _ = _read_auto({"arty": a, "fomu": f}, tmp_path)
    assert [b["board"] for b in doc["boards"]] == ["arty", "fomu"]
    assert locks.taken == [a.lock, f.lock]


class LockedAt(Identified):
    """An Identified board whose lock is a file of the test's."""

    def __init__(self, name, lock, **kw):
        super().__init__(name, **kw)
        self._lock = str(lock)

    @property
    def lock(self):
        return self._lock


@pytest.fixture
def held_lock(tmp_path):
    """A lock file someone else holds (flock is per open file, so this process's own open of it waits too)."""
    import fcntl

    path = tmp_path / "board.lock"
    with open(path, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        yield path


def test_a_board_whose_lock_is_held_is_busy_within_the_bound(tmp_path, held_lock, monkeypatch):
    import time

    monkeypatch.delenv(identify.ENV, raising=False)
    arty = LockedAt("arty", held_lock, seen=[{"variant": "a7-35", "serial": "A"}], read={"idcode": "0x0362d093"},
                    label_fields=("idcode", "dna"))  # fmt: skip
    started = time.monotonic()
    doc, gaps = _read({"arty": arty}, tmp_path, lock_wait=0.5)
    assert 0.5 <= time.monotonic() - started < 5
    assert arty.identified == []  # nothing of the board ran
    assert doc["boards"] == [{"board": "arty", "kind": "arty", "variant": "a7-35", "serial": "A"}]
    assert gaps == ["arty: idcode: board busy", "arty: dna: board busy"]


def test_a_sigterm_during_the_read_exits_143_with_everything_put_back(tmp_path, locks):
    import os
    import signal

    before = signal.getsignal(signal.SIGTERM)
    put_back = []

    class Killed(Identified):
        def identify(self, host, found, options):
            try:
                os.kill(os.getpid(), signal.SIGTERM)  # rpi-hwid gave up on a slow --identify
                raise AssertionError("SIGTERM did not stop the read")
            finally:
                os.kill(os.getpid(), signal.SIGTERM)  # a second one does not cut the putting back short
                put_back.append(locks.held == [self.lock])  # pins, PCI COMMAND: still under the lock

    arty = Killed("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    with pytest.raises(SystemExit) as stopped:
        _read({"arty": arty}, tmp_path)
    assert stopped.value.code == 128 + signal.SIGTERM
    assert put_back == [True] and locks.held == []  # the board's finally ran, then its lock was let go
    assert signal.getsignal(signal.SIGTERM) == before
    _read({"arty": Identified("arty", seen=[{"variant": "a7-35", "serial": "A"}])}, tmp_path)
    assert signal.getsignal(signal.SIGTERM) == before


def test_identify_waits_30_s_at_most_and_the_boot_check_without_a_bound():
    import inspect

    from fpgas_online_verify import core, runner

    assert identify.LOCK_WAIT == 30
    assert inspect.signature(core.hold_lock).parameters["timeout"].default is None
    # the boot check waits for its board however long it takes
    assert "hold_lock(board.lock, board.title):" in inspect.getsource(runner)


def test_a_bounded_lock_gives_up_with_busy_and_an_unbounded_one_waits(tmp_path, held_lock):
    import fcntl
    import threading

    from fpgas_online_verify import core

    ticks = iter(range(100))
    with pytest.raises(core.Busy, match="board busy"), \
            core.hold_lock(held_lock, "board", timeout=3, clock=lambda: next(ticks), sleep=lambda s: None):  # fmt: skip
        pass
    free = tmp_path / "free.lock"
    with core.hold_lock(free, "board", timeout=3):  # free: taken at once
        pass
    other = open(free, "w")  # noqa: SIM115
    fcntl.flock(other, fcntl.LOCK_EX)
    threading.Timer(0.3, other.close).start()
    with core.hold_lock(free, "board"):  # no bound: it waits until the other user lets go
        pass


class Probed(Identified):
    """A board found only by driving its pins (as the NeTV2's JTAG scan): its probe checks its lock is held."""

    def __init__(self, name, locks, **kw):
        super().__init__(name, probes=True, **kw)
        self.locks = locks

    def probe(self, host):
        assert self.lock in self.locks.held, "a board's pins were driven before its lock was held"
        return super().probe(host)

    def identify(self, host, found, options):
        assert self.lock in self.locks.held
        return super().identify(host, found, options)


def test_a_board_found_by_driving_its_pins_is_looked_for_under_its_lock(tmp_path, locks):
    netv2 = Probed("netv2", locks, probed=[{"variant": "a7-35", "idcode": "0x0362d093"}])
    doc, _ = _read({"netv2": netv2}, tmp_path)  # configured
    assert netv2.probe_calls == 1 and [b["board"] for b in doc["boards"]] == ["netv2"]
    assert locks.taken == [netv2.lock]  # taken once, before the scan, and kept for the read
    locks.taken.clear()
    netv2 = Probed("netv2", locks, probed=[{"variant": "a7-35", "idcode": "0x0362d093"}])
    doc, _ = _read_auto({"arty": Identified("arty"), "netv2": netv2}, tmp_path)  # auto: nothing seen, so probed
    assert netv2.probe_calls == 1 and [b["board"] for b in doc["boards"]] == ["netv2"]
    assert locks.taken == [netv2.lock] and locks.held == []


def test_a_busy_board_found_by_driving_its_pins_is_never_driven(tmp_path, held_lock, monkeypatch):
    monkeypatch.delenv(identify.ENV, raising=False)

    class Busy(LockedAt):
        def __init__(self, *a, **kw):
            super().__init__(*a, probes=True, **kw)

    netv2 = Busy("netv2", held_lock, probed=[{"variant": "a7-35"}], label_fields=("idcode",))
    doc, gaps = _read({"netv2": netv2}, tmp_path, lock_wait=0.2)
    assert netv2.probe_calls == 0 and netv2.identified == []
    assert doc["boards"] == [{"board": "netv2", "kind": "netv2"}] and gaps == ["netv2: idcode: board busy"]
    netv2 = Busy("netv2", held_lock, probed=[{"variant": "a7-35"}], label_fields=("idcode",))
    doc, gaps = identify.read({"mode_dir": _auto_dir(tmp_path), "admin_dir": tmp_path / "admin", "lock_wait": 0.2,
                               "boot_report": tmp_path / "v.json"}, {"netv2": netv2}, usb=[], pci=[])  # fmt: skip
    assert netv2.probe_calls == 0 and doc["boards"] == [] and gaps == ["netv2: not looked for: board busy"]


def test_the_netv2_is_scanned_under_its_lock_and_its_pins_put_back_before_it_is_let_go(tmp_path, monkeypatch):
    log = []
    monkeypatch.setattr(identify, "hold_lock", Locks(log))
    monkeypatch.delenv(identify.ENV, raising=False)
    run = Runner([("pinctrl get", (0, "4: op dh pn | hi\n17: ip pu | hi\n27: ip pd | lo\n22: ip pd | lo\n")),
                  ("init; exit", (0, "tap/device found: 0x03631093"))])  # fmt: skip

    def logged(argv, timeout, **kw):
        log.append([str(a) for a in argv][:3])
        return run(argv, timeout, **kw)

    monkeypatch.setattr(NETV2, "probe", functools.partial(type(NETV2).probe, NETV2, runner=logged))
    monkeypatch.setattr(NETV2, "facts", lambda port=None: _host(NETV2))
    doc, _ = _read({"netv2": NETV2}, tmp_path)
    assert doc["boards"][0]["idcode"] == "0x03631093"
    assert log == [["lock", NETV2.lock], ["pinctrl", "get", "4,17,27,22"], ["openocd", "-c", log[2][2]],
                   ["pinctrl", "set", "4"], ["pinctrl", "set", "17"], ["pinctrl", "set", "22"],
                   ["pinctrl", "set", "27"], ["unlock", NETV2.lock]]  # fmt: skip
    assert run.calls[2] == ["pinctrl", "set", "4", "ip", "pn"]  # left driven by openocd: back to an input


def _auto_dir(tmp_path):
    mode = tmp_path / "mode"
    mode.mkdir(exist_ok=True)
    (mode / "auto.ini").write_text("[verify]\nfpga-board = auto\n")
    return mode


def _read_auto(boards, tmp_path):
    mode = tmp_path / "mode"
    mode.mkdir(exist_ok=True)
    (mode / "auto.ini").write_text("[verify]\nfpga-board = auto\n")
    return identify.read({"mode_dir": mode, "admin_dir": tmp_path / "admin", "boot_report": tmp_path / "v.json"},
                         boards, usb=[], pci=[])  # fmt: skip


def test_no_board_found_is_an_empty_document_and_says_why(tmp_path, locks):
    arty = Identified("arty")
    doc, gaps = _read({"arty": arty}, tmp_path)
    assert doc["boards"] == [] and gaps and gaps[0].startswith("missing: no Arty found")


def test_run_prints_one_document_and_exits_0_only_when_every_field_was_read(tmp_path, locks, capsys):
    whole = Identified("arty", seen=[{"variant": "a7-35", "serial": "A"}], read={"idcode": "0x0362d093"},
                       label_fields=("idcode",))  # fmt: skip
    options = {"board": "arty", "boot_report": tmp_path / "v.json"}
    assert identify.run(options, boards={"arty": whole}) == 0
    out = capsys.readouterr()
    assert json.loads(out.out)["boards"][0]["idcode"] == "0x0362d093" and out.err == ""
    part = Identified("arty", seen=[{"variant": "a7-35", "serial": "A"}], read={"idcode_error": "no chain"},
                      label_fields=("idcode", "dna"))  # fmt: skip
    assert identify.run(options, boards={"arty": part}) == 1
    out = capsys.readouterr()
    assert json.loads(out.out)["boards"][0]["idcode_error"] == "no chain"  # printed all the same
    # each field with why: a read that failed says its own error
    assert out.err.splitlines() == ["fpgas-verify --identify: arty: idcode: no chain",
                                    "fpgas-verify --identify: arty: dna: not read"]  # fmt: skip
    flash = Identified("arty", seen=[{"variant": "a7-35", "serial": "A"}], read={"flash_error": "no bridge"},
                       label_fields=("dna",))  # fmt: skip
    assert identify.run(options, boards={"arty": flash}) == 1
    assert capsys.readouterr().err.splitlines() == ["fpgas-verify --identify: arty: dna: not read",
                                                    "fpgas-verify --identify: arty: flash: no bridge"]  # fmt: skip


def test_a_board_whose_read_crashes_is_not_whole_and_the_others_are_still_read(tmp_path, locks):
    class Broken(Identified):
        def identify(self, host, found, options):
            raise RuntimeError("bug")

    a = Broken("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    f = Identified("fomu", seen=[{"variant": "evt", "serial": "F"}])
    doc, gaps = _read_auto({"arty": a, "fomu": f}, tmp_path)
    assert [b["board"] for b in doc["boards"]] == ["arty", "fomu"]
    assert gaps == ["arty: read: the read crashed: RuntimeError: bug"]
    a = Broken("arty", seen=[{"variant": "a7-35", "serial": "A"}], label_fields=("idcode",))
    assert _read({"arty": a}, tmp_path)[1] == ["arty: idcode: the read crashed: RuntimeError: bug"]


# -- the boot report -----------------------------------------------------------------------------------------


def _boot_report(tmp_path, *identities):
    path = tmp_path / "verify.json"
    path.write_text(json.dumps({"schema_version": 2, "boards": [{"board": "arty", "identity": i} for i in identities]}))
    return path


ARTY_BOOT = {"board": "arty", "kind": "arty", "serial": "210319B", "idcode": "0x0362d093", "dna": "0x0011223344556677",
             "flash_jedec": "0xc22018", "flash_uid": "0123456789abcdef", "flash_source": "jtag"}  # fmt: skip


def test_what_only_a_loaded_design_reads_comes_from_the_boot_report_of_the_same_board(tmp_path, locks):
    _boot_report(tmp_path, ARTY_BOOT)
    arty = Identified("arty", seen=[ARTY_FOUND], read={"idcode": "0x0362d093"}, report_fields=("flash",))
    (board,) = _read({"arty": arty}, tmp_path)[0]["boards"]
    assert board["flash_jedec"] == "0xc22018" and board["flash_uid"] == "0123456789abcdef"
    assert board["from_report"] == ["flash_jedec", "flash_source", "flash_uid"]
    assert "dna" not in board  # only the report fields: a DNA is read live or not at all


def test_another_boards_boot_report_is_never_used(tmp_path, locks):
    _boot_report(tmp_path, {**ARTY_BOOT, "serial": "OTHER"})
    arty = Identified("arty", seen=[ARTY_FOUND], report_fields=("flash",))
    (board,) = _read({"arty": arty}, tmp_path)[0]["boards"]
    assert "flash_jedec" not in board and "from_report" not in board


def test_a_board_known_only_by_its_idcode_takes_nothing_from_the_boot_report(tmp_path, locks):
    netv2_boot = {"board": "netv2", "kind": "netv2", "idcode": "0x0362d093", "flash_jedec": "0xc22018"}
    _boot_report(tmp_path, netv2_boot)
    netv2 = Identified("netv2", seen=[{"variant": "a7-35", "idcode": "0x0362d093"}], read={"idcode": "0x0362d093"},
                       label_fields=("idcode", "flash_jedec"), report_fields=("flash",))  # fmt: skip
    doc, gaps = _read({"netv2": netv2}, tmp_path)
    (board,) = doc["boards"]
    assert board["kind"] == "netv2" and board["idcode"] == "0x0362d093"  # the same part, maybe not the same board
    assert "flash_jedec" not in board and "from_report" not in board
    assert gaps == ["netv2: flash_jedec: no board-unique match in the boot report"]


def test_the_arty_matches_by_usb_serial_and_the_acorn_by_pci_slot(tmp_path, locks):
    _boot_report(tmp_path, {**ARTY_BOOT, "idcode": "0x0362d093"},
                 {"board": "acorn", "kind": "acorn", "bdf": "0001:01:00.0", "flash_uid": "aa"})  # fmt: skip
    arty = Identified("arty", seen=[ARTY_FOUND], report_fields=("flash",), label_fields=("flash_uid",))
    assert _read({"arty": arty}, tmp_path)[0]["boards"][0]["flash_uid"] == "0123456789abcdef"
    acorn = Identified("acorn", seen=[{"variant": "cle-215+", "kind": "fpgas-online", "bdf": "0001:01:00.0"}],
                       report_fields=("flash",))  # fmt: skip
    (board,) = _read({"acorn": acorn}, tmp_path)[0]["boards"]
    assert board["from_report"] == ["flash_uid"]
    other = Identified("arty", seen=[{**ARTY_FOUND, "serial": "OTHER"}], report_fields=("flash",),
                       label_fields=("flash_uid",))  # fmt: skip
    assert _read({"arty": other}, tmp_path)[1] == ["arty: flash_uid: this board is not in the boot report"]


def test_a_live_read_is_never_replaced_by_the_report(tmp_path, locks):
    _boot_report(tmp_path, ARTY_BOOT)
    arty = Identified("arty", seen=[ARTY_FOUND], read={"flash_jedec": "0xef4018"}, report_fields=("flash",))
    (board,) = _read({"arty": arty}, tmp_path)[0]["boards"]
    assert board["flash_jedec"] == "0xef4018" and "flash_jedec" not in board["from_report"]


def test_no_boot_report_or_a_damaged_one_is_only_the_live_read(tmp_path, locks):
    arty = Identified("arty", seen=[ARTY_FOUND], report_fields=("flash",))
    assert "from_report" not in _read({"arty": arty}, tmp_path)[0]["boards"][0]
    (tmp_path / "verify.json").write_text("{not json")
    assert "from_report" not in _read({"arty": arty}, tmp_path)[0]["boards"][0]


# -- the boards' live reads ----------------------------------------------------------------------------------


def test_the_arty_reads_only_its_idcode_and_loads_nothing(tmp_path):
    run = Runner()
    out = ARTY.identify(_host(ARTY), ARTY_FOUND, {"board_key": "arty"}, runner=run)
    assert [c[-3:] for c in run.calls] == [["--detect", "--verbose-level", "2"]]
    assert out == {
        "board": "arty", "kind": "arty", "variant": "a7-35", "serial": "210319B", "usb": "1-1",
        "idcode": "0x0362d093", "idcode_version": 0, "idcode_part_number": "0x362d",
        "idcode_manufacturer_id": "0x049", "idcode_manufacturer": "Xilinx", "idcode_device": "XC7A35T",
    }  # fmt: skip
    assert ARTY.report_fields == ("flash",)


def test_an_arty_with_no_jtag_chain_is_an_idcode_error(tmp_path):
    run = Runner([("--detect", (1, "JTAG init failed"))])
    out = ARTY.identify(_host(ARTY), ARTY_FOUND, {"board_key": "arty"}, runner=run)
    assert "(exit 1)" in out["idcode_error"] and "idcode" not in out  # the check's own reason (testbench.jtag)


def test_the_netv2_uses_the_idcode_its_scan_found_and_runs_nothing():
    run = Runner()
    scan = {"tool": "openocd", "exit": 0, "output": ["tap/device found: 0x13631093"]}
    found = {"variant": "a7-100", "idcode": "0x13631093", "idcodes": ["0x13631093"], "idcode_scan": scan}
    out = NETV2.identify(_host(NETV2), found, {"board_key": "netv2"}, runner=run)
    assert run.calls == [] and out["idcode"] == "0x13631093" and out["idcode_device"] == "XC7A100T"


def test_the_acorn_reads_the_same_identity_as_its_check_without_reading_a_slot_or_writing(tmp_path, images,
                                                                                           monkeypatch):  # fmt: skip
    monkeypatch.setattr(sf, "SLOT_SIZE", 0x14000)
    full = Rig(tmp_path / "a", images).check(board_key="acorn")["identity"]
    rig = Rig(tmp_path / "b", images)
    live = ACORN.identify({}, rig.found(), rig.options(board_key="acorn"))
    assert live == full
    assert live["dna"] == "0x0054b48664b04854" and live["idcode"] == "0x13636093"
    assert live["flash_jedec"] == "0x010219" and live["flash_extended_id"] == "0x4d0180"
    assert sf.READ4 not in rig.soc.flash.opcodes  # identity only: no page of either slot is read
    assert not set(rig.soc.flash.opcodes) & WRITES
    assert all(not c[0].startswith("openFPGALoader") or "--detect" in c or "--read-dna" in c for c in rig.pi.calls)
    assert rig.events == []  # nothing is sent to the fleet
    assert not [f for f in ACORN.label_fields if f not in live]


def test_the_acorn_writes_only_the_spi_master_and_chip_select_over_bar0(tmp_path, images):
    from fpgas_online_verify.boards.acorn import check

    rig = Rig(tmp_path, images)
    written, write = [], rig.soc.write
    rig.soc.write = lambda addr, value: written.append(addr) or write(addr, value)
    live = ACORN.identify({}, rig.found(), rig.options(board_key="acorn"))
    assert live["flash_jedec"] == "0x010219" and written  # the flash's RDID and OTPR were sent
    assert set(written) <= check.IDENTIFY_WRITES
    assert fk.REGS["ctrl_scratch"] - 4 not in written  # ctrl_reset, the CSR before ctrl_scratch


def test_identify_refuses_any_other_write_ctrl_reset_above_all():
    from fpgas_online_verify.boards.acorn import check

    written = []

    class Bus:
        def read(self, addr):
            return 0

        def write(self, addr, value):
            written.append(addr)

    bus = check.IdentifyBus(Bus())
    ctrl_reset = fk.REGS["ctrl_scratch"] - 4
    for addr in (ctrl_reset, fk.REGS["ctrl_scratch"], fk.REGS["p2_gpio_oe"]):
        with pytest.raises(Problem, match="refused to write CSR"):
            bus.write(addr, 1)
    bus.write(sf.FLASH_CS_N, 1)
    assert written == [sf.FLASH_CS_N]


def test_the_acorn_never_touches_the_flash_of_a_build_it_does_not_know(tmp_path, images):
    rig = Rig(tmp_path, images, identifier="fpgas-online Acorn PCIe SoC cle-215+ 2026-10-01 09:00:00")
    live = ACORN.identify({}, rig.found(), rig.options(board_key="acorn"))
    assert not rig.soc.flash_touched and "flash" not in live


def test_the_acorn_never_opens_the_bar_of_a_factory_board(tmp_path, images):
    rig = Rig(tmp_path, images, ids=fk.FACTORY)
    live = ACORN.identify({}, rig.found(), rig.options(board_key="acorn", open_bar=fk.refuse))
    assert live["kind"] == "acorn" and "flash" not in live and "identifier" not in live
    assert live["dna"] == "0x0054b48664b04854"  # over P1 JTAG, which needs nothing of the design


def test_the_acorn_binds_a_driver_it_unbound_again(tmp_path, images):
    rig = Rig(tmp_path, images, driver="litepcie")
    ACORN.identify({}, rig.found(), rig.options(board_key="acorn"))
    assert (tmp_path / "sys" / "drivers" / "litepcie" / "bind").read_text() == "0001:01:00.0"


def test_fpgas_acorn_debug_identify_prints_what_fpgas_acorn_verify_identify_does(monkeypatch, capsys):
    monkeypatch.delenv(identify.ENV, raising=False)
    asked = []

    def read(options, boards=None, usb=None, pci=None):
        asked.append((options.get("board"), sorted(boards)))
        return identity.document([{"board": "acorn", "kind": "acorn"}], read_at="2026-10-02T00:00:00+00:00"), []

    monkeypatch.setattr(identify, "read", read)
    assert cli.board_main(["--identify"], "fpgas-acorn-verify") == 0
    verify_out = capsys.readouterr().out
    assert cli.board_main(["identify"], "fpgas-acorn-debug") == 0
    assert capsys.readouterr().out == verify_out
    assert asked == [("acorn", ["acorn"])] * 2
    assert debug.commands(ACORN)["identify"][0] is debug.acorn_identify


def test_identify_cannot_be_given_with_update_or_test(monkeypatch, capsys):
    monkeypatch.delenv(identify.ENV, raising=False)
    for argv in (["--identify", "--update"], ["--identify", "--test", "flash"]):
        with pytest.raises(SystemExit):
            cli.board_main(argv, "fpgas-acorn-verify")


# -- nesting -------------------------------------------------------------------------------------------------


def _outer(tmp_path):
    """The outer run's document: the golden fixture."""
    return GOLDEN


@pytest.fixture
def untouchable(monkeypatch):
    """Nothing but the file may be used: any lock, board module or board method fails the test."""

    def no(*a, **k):
        raise AssertionError("nested --identify must not touch locks, boards or hardware")

    for target in ("fpgas_online_verify.cli.installed", "fpgas_online_verify.identify.installed",
                   "fpgas_online_verify.identify.hold_lock", "fpgas_online_verify.runner.hold_lock",
                   "fpgas_online_verify.debug.hold_lock", "fpgas_online_verify.identify.read",
                   "fpgas_online_verify.runner.run", "fpgas_online_verify.debug.run",
                   "fpgas_online_verify.core.pci_devices", "fpgas_online_verify.core.usb_devices",
                   "fpgas_online_verify.board.Board.identify", "fpgas_online_verify.board.Board.check",
                   "fpgas_online_verify.board.Board.find", "fpgas_online_verify.board.Board.facts"):  # fmt: skip
        monkeypatch.setattr(target, no)
    for name in ("check", "identify", "find", "spot", "facts"):
        monkeypatch.setattr(ACORN, name, no, raising=False)
        monkeypatch.setattr(ARTY, name, no, raising=False)


@pytest.mark.parametrize(("main", "argv", "prog"), [
    (cli.verify_main, ["--identify"], None),
    (cli.verify_main, ["--identify", "--board", "acorn"], None),
    (cli.board_main, ["--identify"], "fpgas-acorn-verify"),
    (cli.board_main, ["--identify"], "fpgas-arty-verify"),
    (cli.board_main, ["identify"], "fpgas-acorn-debug"),
])  # fmt: skip
def test_nested_identify_prints_the_outer_document_byte_for_byte_and_touches_nothing(
    main, argv, prog, tmp_path, monkeypatch, untouchable, capsysbinary
):
    outer = _outer(tmp_path)
    monkeypatch.setenv(identify.ENV, str(outer))
    assert (main(argv) if prog is None else main(argv, prog)) == 0
    assert capsysbinary.readouterr().out == outer.read_bytes()


@pytest.mark.parametrize(("main", "argv", "prog"), [
    (cli.verify_main, [], None),
    (cli.verify_main, ["--update"], None),
    (cli.verify_main, ["--list"], None),
    (cli.verify_main, ["--test", "flash"], None),
    (cli.board_main, [], "fpgas-acorn-verify"),
    (cli.board_main, ["detect"], "fpgas-acorn-debug"),
    (cli.board_main, ["identify"], "fpgas-arty-debug"),
])  # fmt: skip
def test_nested_every_other_mode_refuses(main, argv, prog, tmp_path, monkeypatch, untouchable, capsys):
    monkeypatch.setenv(identify.ENV, str(_outer(tmp_path)))
    assert (main(argv) if prog is None else main(argv, prog)) == 2
    out = capsys.readouterr()
    assert out.out == "" and "only --identify may run" in out.err


@pytest.mark.parametrize(("content", "why"), [
    (None, "cannot read"),
    ("{not json", "is not JSON"),
    ("[]", "is not an identity document"),
    ('{"schema": "rpi-hwid/label-input", "identity_version": 1, "boards": []}', "is not an identity document"),
    ('{"schema": "fpgas-verify/identity", "identity_version": 2, "boards": []}', "identity_version 2"),
    ('{"schema": "fpgas-verify/identity", "identity_version": "1", "boards": []}', "identity_version '1'"),
    ('{"schema": "fpgas-verify/identity", "identity_version": true, "boards": []}', "identity_version True"),
    ('{"schema": "fpgas-verify/identity", "identity_version": 1}', "no list of boards"),
])  # fmt: skip
def test_nested_a_missing_or_bad_document_is_an_error_and_never_the_hardware(
    content, why, tmp_path, monkeypatch, untouchable, capsys
):
    path = tmp_path / "identity-1.json"
    if content is not None:
        path.write_text(content)
    monkeypatch.setenv(identify.ENV, str(path))
    assert cli.verify_main(["--identify"]) == 1
    out = capsys.readouterr()
    assert out.out == "" and why in out.err


def test_an_empty_variable_is_not_nested(tmp_path, monkeypatch):
    monkeypatch.setenv(identify.ENV, "")
    assert identify.outer_path() is None
    ran = []
    monkeypatch.setattr(identify, "run", lambda options, prog="fpgas-verify", boards=None: ran.append(prog) or 0)
    monkeypatch.setattr(cli.runner, "run", lambda options, prog="fpgas-verify": ran.append("check") or 0)
    assert cli.verify_main(["--identify"]) == 0
    assert cli.verify_main([]) == 0  # the boot unit's plain fpgas-verify runs the check, not exit 2
    assert cli.board_main(["--identify"], "fpgas-acorn-verify") == 0
    assert ran == ["fpgas-verify", "check", "fpgas-acorn-verify"]


def test_the_golden_document_is_one_this_reader_takes():
    assert identify.load_outer(GOLDEN) == GOLDEN.read_text()
    (board,) = json.loads(GOLDEN.read_text())["boards"]
    assert board["dna"] == "0x0054b48664b04854" and board["idcode"] == "0x13636093"


def test_a_live_document_is_printed_as_the_golden_one_is_written():
    assert identify.dumps(json.loads(GOLDEN.read_text())) == GOLDEN.read_text()
