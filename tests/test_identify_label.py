"""Tests for fpgas-verify --identify (fpgas_online_verify.identify) and the nesting rpi-hwid's labels need.

* --identify prints exactly one identity document (identity.document()), read live with the reads that
  disturb nothing, each board under its own lock; fields only the boot check can read come from the boot
  report when the board there is this one, and are named in "from_report".
* It exits 0 only when every board's identity is whole; the document is printed either way.
* With FPGAS_VERIFY_IDENTITY set (inside fpgas-verify --label), --identify prints that file unchanged and
  touches nothing: no lock, no board module, no hardware, even when the file is missing or bad. Every other
  mode refuses.
"""

import json
import pathlib

import pytest
from fpgas_online_verify import cli, debug, identify, identity
from fpgas_online_verify.boards.acorn import BOARD as ACORN

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
    """Stands in for core.hold_lock: records each lock taken, and what is read while it is held."""

    def __init__(self):
        self.taken, self.held = [], None

    def __call__(self, path, what):
        outer = self

        class _Held:
            def __enter__(self):
                outer.taken.append(path)
                outer.held = path

            def __exit__(self, *a):
                outer.held = None
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
            assert locks.held == self.lock
            return super().identify(host, found, options)

    a = Seen("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    f = Seen("fomu", seen=[{"variant": "evt", "serial": "F"}])
    doc, _ = _read_auto({"arty": a, "fomu": f}, tmp_path)
    assert [b["board"] for b in doc["boards"]] == ["arty", "fomu"]
    assert locks.taken == [a.lock, f.lock]


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
    assert "arty: not read: idcode" in out.err and "arty: not read: dna" in out.err
    assert "arty: not read: idcode_error" in out.err


def test_a_board_whose_read_crashes_is_not_whole_and_the_others_are_still_read(tmp_path, locks):
    class Broken(Identified):
        def identify(self, host, found, options):
            raise RuntimeError("bug")

    a = Broken("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    f = Identified("fomu", seen=[{"variant": "evt", "serial": "F"}])
    doc, gaps = _read_auto({"arty": a, "fomu": f}, tmp_path)
    assert [b["board"] for b in doc["boards"]] == ["arty", "fomu"]
    assert gaps == ["arty: the read crashed: RuntimeError: bug"]


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
    assert "exited 1" in out["idcode_error"] and "idcode" not in out  # the check's own reason (testbench.jtag)


def test_the_netv2_uses_the_idcode_its_scan_found_and_runs_nothing():
    run = Runner()
    out = NETV2.identify(_host(NETV2), {"variant": "a7-100", "idcode": "0x13631093"}, {"board_key": "netv2"},
                         runner=run)  # fmt: skip
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
    """The outer run's document: the golden fixture once it is in tests/data, else one like it."""
    if GOLDEN.exists():
        return GOLDEN
    path = tmp_path / "identity-123.json"
    doc = identity.document([{"board": "acorn", "kind": "acorn", "dna": "0x0054b48664b04854"}],
                            tool="fpgas-online-verify 0.0.post1", read_at="2026-10-02T00:00:00+00:00")  # fmt: skip
    path.write_text(identify.dumps(doc))
    return path


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


def test_nested_an_empty_variable_is_still_nested(tmp_path, monkeypatch, untouchable, capsys):
    monkeypatch.setenv(identify.ENV, "")
    assert cli.verify_main(["--identify"]) == 1 and capsys.readouterr().out == ""


def test_the_golden_document_is_one_this_reader_takes():
    if not GOLDEN.exists():
        pytest.skip("tests/data/identity-v1-acorn-p48.json is not in this branch yet")
    assert identify.load_outer(GOLDEN) == GOLDEN.read_text()
    (board,) = json.loads(GOLDEN.read_text())["boards"]
    assert board["dna"] == "0x0054b48664b04854" and board["idcode"] == "0x13636093"


def test_a_live_document_is_printed_as_the_golden_one_is_written():
    assert identify.dumps(json.loads(GOLDEN.read_text())) == GOLDEN.read_text()
