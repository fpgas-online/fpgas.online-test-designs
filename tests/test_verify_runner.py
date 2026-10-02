"""Tests for fpgas-verify's rules (fpgas_online_verify.runner, config and state), with stand-in boards.

* A host set up for one board checks only that board: not finding it is fatal, whatever else is attached,
  and nothing else is looked for.
* A host set up for `auto` looks for every installed board, passively (USB/PCI) before driving anything
  (the NeTV2's JTAG scan); finding none is fatal.
* With persistent state, a different board or a different flash from last time is fatal ("changed") until
  --update records it; an SRAM load or a package upgrade is not a change.
"""

import json
import subprocess

import pytest
from fpgas_online_verify import config, core, runner, state
from fpgas_online_verify.board import Board, installed
from fpgas_online_verify.core import Problem


class Fake(Board):
    """A board seen on USB with `seen`, or found by probing; check() reports `result` and the state given."""

    def __init__(self, name, seen=(), probes=False, probed=(), result="pass", flash="aaaa", weak=False):
        self.name = self.slug = name
        self.is_weak = weak
        self.title = name.title()
        self.probes, self.seen, self.probed = probes, list(seen), list(probed)
        self.result, self.flash = result, flash
        self.checked, self.probe_calls = [], 0

    def facts(self, port=None):
        return {"model": "Raspberry Pi 3 Model B Plus Rev 1.3", "port": port}

    def spot(self, host, usb, pci):
        return list(self.seen)

    def probe(self, host):
        self.probe_calls += 1
        return list(self.probed)

    def weak(self, found):
        return self.is_weak

    def check(self, host, found, options):
        self.checked.append(found)
        return {"board": self.name, "variant": found.get("variant"), "result": self.result,
                "state": {"serial": found.get("serial"), "flash": {"sha256": self.flash}}}  # fmt: skip


@pytest.fixture
def opts(tmp_path, monkeypatch):
    monkeypatch.setattr("fpgas_online_verify.runner.hold_lock", _no_lock)
    return {"state": tmp_path / "state.json", "no_publish": True}


class _no_lock:
    def __init__(self, *a):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _boards(*boards):
    return {b.name: b for b in boards}


# -- one board -----------------------------------------------------------------------------------------------


def test_one_board_that_is_there_passes(opts):
    arty = Fake("arty", seen=[{"variant": "a7-35", "serial": "210319A"}])
    report = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    assert report["result"] == "pass" and report["chosen_by"] == "configured: arty"
    assert arty.checked == [{"variant": "a7-35", "serial": "210319A"}]


def test_one_board_that_is_not_there_is_missing_even_with_another_board_attached(opts):
    arty = Fake("arty")
    fomu = Fake("fomu", seen=[{"variant": "evt"}])
    netv2 = Fake("netv2", probes=True, probed=[{"variant": "a7-35"}])
    report = runner.verify({**opts, "board": "arty"}, _boards(arty, fomu, netv2), usb=[], pci=[])
    assert report["result"] == "missing" and "nothing else is looked for" in report["reason"]
    assert fomu.checked == [] and netv2.probe_calls == 0 and netv2.checked == []


def test_a_configured_board_whose_module_is_not_installed_is_an_error(opts):
    report = runner.verify({**opts, "board": "netv2"}, _boards(Fake("arty")), usb=[], pci=[])
    assert report["result"] == "error" and "no such board module" in report["reason"]


def test_a_probing_board_configured_alone_is_probed(opts):
    netv2 = Fake("netv2", probes=True, probed=[{"variant": "a7-100", "idcode": "0x13631093"}])
    report = runner.verify({**opts, "board": "netv2"}, _boards(netv2), usb=[], pci=[])
    assert report["result"] == "pass" and netv2.probe_calls == 1


def test_the_board_can_be_named_by_its_package_slug(opts):
    tt = Fake("tt", seen=[{"variant": "tt-fpga"}])
    tt.slug = "tt-fpga"
    report = runner.verify({**opts, "board": "tt-fpga"}, _boards(tt), usb=[], pci=[])
    assert report["result"] == "pass"


# -- auto ------------------------------------------------------------------------------------------------------


def test_auto_finds_whichever_board_is_there_and_never_probes_when_one_is_seen(opts):
    arty, fomu = Fake("arty"), Fake("fomu", seen=[{"variant": "evt"}])
    netv2 = Fake("netv2", probes=True, probed=[{"variant": "a7-35"}])
    report = runner.verify(opts, _boards(arty, fomu, netv2), usb=[], pci=[], mode=("auto", "test"))
    assert [b["board"] for b in report["boards"]] == ["fomu"] and report["chosen_by"] == "auto: USB/PCI IDs"
    assert netv2.probe_calls == 0


def test_auto_probes_only_when_nothing_is_seen(opts):
    netv2 = Fake("netv2", probes=True, probed=[{"variant": "a7-35", "idcode": "0x0362d093"}])
    report = runner.verify(opts, _boards(Fake("arty"), netv2), usb=[], pci=[], mode=("auto", "test"))
    assert [b["board"] for b in report["boards"]] == ["netv2"] and report["chosen_by"] == "auto: probed (netv2)"


def test_auto_still_probes_when_every_claim_is_weak_and_keeps_the_claim(opts):
    """A Xilinx PCIe design the Acorn module cannot name may be a NeTV2 on PCIe: its JTAG is probed too."""
    acorn = Fake("acorn", seen=[{"kind": "vendor-xdma"}], weak=True, result="fail")
    netv2 = Fake("netv2", probes=True, probed=[{"variant": "a7-35", "idcode": "0x0362d093"}])
    report = runner.verify(opts, _boards(acorn, netv2), usb=[], pci=[], mode=("auto", "test"))
    assert [b["board"] for b in report["boards"]] == ["acorn", "netv2"]
    assert report["chosen_by"] == "auto: USB/PCI IDs and probed (netv2)" and report["result"] == "fail"
    alone = Fake("netv2", probes=True)
    weak = Fake("acorn", seen=[{"kind": "litex-other"}], weak=True)
    report = runner.verify(opts, _boards(weak, alone), usb=[], pci=[], mode=("auto", "test"))
    assert [b["board"] for b in report["boards"]] == ["acorn"] and alone.probe_calls == 1
    assert report["chosen_by"] == "auto: USB/PCI IDs, and probing found nothing more"


def test_a_probe_that_fails_beside_a_weak_claim_keeps_the_claim_and_says_why(opts):
    class Broken(Fake):
        def probe(self, host):
            raise Problem("error", "the JTAG chain answers with IDCODE 0x13636093, which is no NeTV2 part")

    acorn = Fake("acorn", seen=[{"kind": "litex-other"}], weak=True, result="fail")
    report = runner.verify(opts, _boards(acorn, Broken("netv2", probes=True)), usb=[], pci=[], mode=("auto", "test"))
    assert [b["board"] for b in report["boards"]] == ["acorn"] and report["result"] == "fail"
    assert "probing as well failed: the JTAG chain answers" in report["chosen_by"]


def test_auto_finding_nothing_is_missing(opts):
    netv2 = Fake("netv2", probes=True)
    report = runner.verify(opts, _boards(Fake("arty"), netv2), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "missing" and "none of the installed boards (arty, netv2)" in report["reason"]


def test_auto_without_probing_never_drives_anything(opts):
    netv2 = Fake("netv2", probes=True, probed=[{"variant": "a7-35"}])
    report = runner.verify({**opts, "no_probe": True}, _boards(netv2), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "missing" and netv2.probe_calls == 0


def test_two_boards_seen_are_both_checked_and_the_worst_wins(opts):
    arty = Fake("arty", seen=[{"variant": "a7-35"}])
    fomu = Fake("fomu", seen=[{"variant": "evt"}], result="fail")
    report = runner.verify(opts, _boards(arty, fomu), usb=[], pci=[], mode=("auto", "test"))
    assert [b["board"] for b in report["boards"]] == ["arty", "fomu"] and report["result"] == "fail"


# -- the recorded state ----------------------------------------------------------------------------------------


def test_the_first_run_records_the_state_and_passes(opts):
    arty = Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    report = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    assert report["result"] == "pass" and report["state"]["recorded"] == "first run"
    saved = json.loads(opts["state"].read_text())["boards"]
    assert saved == {"arty": {"serial": "A", "flash": {"sha256": "aaaa"}}}


def test_a_test_run_neither_records_nor_compares_the_state(opts):
    arty = WithTests("arty", ["uart"], seen=[{"variant": "a7-35", "serial": "A"}])
    report = runner.verify({**opts, "board": "arty", "tests": ["uart"]}, _boards(arty), usb=[], pci=[])
    assert report["state"]["recorded"] is False and not opts["state"].exists()
    full = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    assert full["result"] == "pass" and full["state"]["recorded"] == "first run"
    arty.flash = "bbbb"  # a partial run is no evidence either way
    assert (
        runner.verify({**opts, "board": "arty", "tests": ["uart"]}, _boards(arty), usb=[], pci=[])["result"] == "pass"
    )


class WithTests(Fake):
    """A Fake with selectable tests, which remembers the options its check was given."""

    def __init__(self, name, tests, **kw):
        super().__init__(name, **kw)
        self.tests, self.options = {t: {} for t in tests}, None

    def check(self, host, found, options):
        self.options = options
        return super().check(host, found, options)


def test_with_auto_a_board_skips_the_tests_it_does_not_have(opts):
    arty = WithTests("arty", ["uart", "ethernet"], seen=[{"variant": "a7-35", "serial": "A"}])
    tt = WithTests("tt", ["uart", "pin-id"], seen=[{"variant": "tt-fpga", "serial": "T"}])
    report = runner.verify({**opts, "tests": ["uart", "ethernet"]}, _boards(arty, tt), usb=[], pci=[],
                           mode=("auto", "test"))  # fmt: skip
    assert arty.options["tests"] == ["uart", "ethernet"] and tt.options["tests"] == ["uart"]
    assert [b.get("tests_skipped") for b in report["boards"]] == [None, ["ethernet"]]


def test_with_auto_a_board_with_none_of_the_tests_is_not_checked_and_not_passed(opts):
    arty = WithTests("arty", ["uart", "ddr"], seen=[{"variant": "a7-35", "serial": "A"}])
    tt = WithTests("tt", ["uart"], seen=[{"variant": "tt-fpga", "serial": "T"}], result="fail")
    report = runner.verify({**opts, "tests": ["ddr"]}, _boards(arty, tt), usb=[], pci=[], mode=("auto", "test"))
    assert tt.options is None and tt.checked == []
    assert [b["board"] for b in report["boards"]] == ["arty"] and report["not_checked"] == ["tt"]
    assert report["result"] == "pass"  # arty's ddr ran and passed


def test_with_auto_a_test_no_board_found_has_is_an_error(opts):
    tt = WithTests("tt", ["uart"], seen=[{"variant": "tt-fpga", "serial": "T"}])
    report = runner.verify({**opts, "tests": ["ddr"]}, _boards(tt), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "error" and "has the test ddr" in report["reason"]
    assert report["boards"] == [] and tt.checked == []


def test_with_auto_a_board_with_no_selectable_tests_is_not_checked(opts):
    acorn = Fake("acorn", seen=[{"variant": "cle-215+"}])
    report = runner.verify({**opts, "tests": ["uart"]}, _boards(acorn), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "error" and acorn.checked == []


def test_configured_for_a_board_with_no_selectable_tests_test_is_an_error(opts):
    acorn = Fake("acorn", seen=[{"variant": "cle-215+"}])
    report = runner.verify({**opts, "board": "acorn", "tests": ["uart"]}, _boards(acorn), usb=[], pci=[])
    assert report["result"] == "error" and "no selectable tests" in report["boards"][0]["reason"]
    assert acorn.checked == []


def test_configured_for_one_board_the_check_sees_every_test_asked_for(opts):
    arty = WithTests("arty", ["uart"], seen=[{"variant": "a7-35", "serial": "A"}])
    runner.verify({**opts, "board": "arty", "tests": ["uart", "nope"]}, _boards(arty), usb=[], pci=[])
    assert arty.options["tests"] == ["uart", "nope"]  # TestBoard.check makes "nope" an error


def test_the_same_board_and_flash_again_passes(opts):
    arty = Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    report = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    assert report["result"] == "pass" and "changes" not in report["state"] and "recorded" not in report["state"]


def test_a_rewritten_flash_is_changed_until_update(opts):
    arty = Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    arty.flash = "bbbb"
    report = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    assert report["result"] == "changed"
    assert report["state"]["changes"] == ["arty.flash.sha256: was 'aaaa', now 'bbbb'"]
    assert "--update" in runner.summary(report)
    assert json.loads(opts["state"].read_text())["boards"]["arty"]["flash"]["sha256"] == "aaaa"  # kept
    assert runner.verify({**opts, "board": "arty", "update": True}, _boards(arty), usb=[], pci=[])["result"] == "pass"
    assert runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])["result"] == "pass"


def test_a_swapped_board_is_changed(opts):
    arty = Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    arty.seen = [{"variant": "a7-35", "serial": "B"}]
    report = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    assert report["result"] == "changed" and report["state"]["changes"] == ["arty.serial: was 'A', now 'B'"]


def test_with_auto_a_different_kind_of_board_is_changed(opts):
    arty, fomu = Fake("arty", seen=[{"variant": "a7-35"}]), Fake("fomu")
    runner.verify(opts, _boards(arty, fomu), usb=[], pci=[], mode=("auto", "test"))
    arty.seen, fomu.seen = [], [{"variant": "evt"}]
    report = runner.verify(opts, _boards(arty, fomu), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "changed"
    assert report["state"]["changes"] == ["arty: recorded, not found now", "fomu: found now, not recorded before"]


def test_a_failed_test_is_not_a_state_change(opts):
    """Test results are not state: an SRAM load or a flaky UART must not need --update."""
    arty = Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    arty.result = "fail"
    report = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    assert report["result"] == "fail" and "changes" not in report["state"]


def test_a_missing_board_on_the_first_run_records_nothing(opts):
    report = runner.verify({**opts, "board": "arty"}, _boards(Fake("arty")), usb=[], pci=[])
    assert report["result"] == "missing" and not opts["state"].exists()


def test_a_flash_not_read_this_time_is_not_compared(opts):
    state.save({"arty": {"serial": "A", "flash": {"sha256": "aaaa"}}}, "then", opts["state"])
    assert state.differences(state.load(opts["state"]), {"arty": {"serial": "A"}}) == []


def test_an_unreadable_state_file_is_a_change_not_a_crash(opts):
    opts["state"].write_text("{broken")
    arty = Fake("arty", seen=[{"variant": "a7-35"}])
    report = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    assert report["result"] == "changed" and "cannot be read" in report["state"]["changes"][0]


# -- configuration ------------------------------------------------------------------------------------------


def test_the_mode_package_says_which_board(tmp_path):
    mode, admin = tmp_path / "mode.d", tmp_path / "etc"
    mode.mkdir()
    (mode / "fpgas-online-arty.ini").write_text("[verify]\nfpga-board = arty\n")
    assert config.configured(mode, admin) == ("arty", mode / "fpgas-online-arty.ini")


def test_the_admin_overrides_the_mode_package(tmp_path):
    mode, admin = tmp_path / "mode.d", tmp_path / "etc"
    mode.mkdir()
    admin.mkdir()
    (mode / "fpgas-online-multi-board.ini").write_text("[verify]\nfpga-board = auto\n")
    (admin / "local.ini").write_text("[verify]\nfpga-board = netv2\n")
    assert config.configured(mode, admin)[0] == "netv2"


def test_nothing_configured_is_an_error_that_says_what_to_install(tmp_path):
    with pytest.raises(Problem) as e:
        config.configured(tmp_path / "a", tmp_path / "b")
    assert e.value.result == "error" and "fpgas-online-<board>" in e.value.reason


def test_two_mode_files_that_disagree_are_an_error(tmp_path):
    (tmp_path / "a.ini").write_text("[verify]\nfpga-board = arty\n")
    (tmp_path / "b.ini").write_text("[verify]\nfpga-board = fomu\n")
    with pytest.raises(Problem, match="conflicting"):
        config.configured(tmp_path, tmp_path / "none")


def test_no_configuration_makes_fpgas_verify_fail_loudly(opts, tmp_path):
    report = runner.verify({**opts, "mode_dir": tmp_path / "x", "admin_dir": tmp_path / "y"}, _boards(Fake("arty")))
    assert report["result"] == "error" and "no FPGA board is configured" in report["reason"]


# -- telling people ------------------------------------------------------------------------------------------


def test_the_fleet_event_details_are_flat_strings(opts):
    arty = Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}], result="fail")
    report = runner.verify({**opts, "board": "arty"}, _boards(arty), usb=[], pci=[])
    d = runner.details(report)
    assert d["result"] == "fail" and d["mode"] == "arty" and d["board0"] == "arty a7-35 fail"
    assert d["board0_state_flash_sha256"] == "aaaa"
    assert all(isinstance(v, str) for v in d.values())


def test_a_failure_is_loud(opts):
    report = runner.verify({**opts, "board": "arty"}, _boards(Fake("arty")), usb=[], pci=[])
    assert "*** FPGA VERIFY: MISSING" in runner.summary(report)


def test_only_a_pass_exits_zero(opts, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(runner, "installed", lambda: _boards(Fake("arty", seen=[{"variant": "a7-35"}])))
    monkeypatch.setattr(runner, "usb_devices", lambda: [])
    monkeypatch.setattr(runner, "pci_devices", lambda: [])
    out = tmp_path / "r.json"
    assert runner.run({**opts, "board": "arty", "report": str(out)}) == 0
    assert json.loads(out.read_text())["result"] == "pass"
    assert runner.run({**opts, "board": "fomu", "report": str(out)}) == 1


def test_the_start_is_published_before_the_result(opts, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "installed", lambda: _boards(Fake("arty", seen=[{"variant": "a7-35"}])))
    monkeypatch.setattr(runner, "usb_devices", lambda: [])
    monkeypatch.setattr(runner, "pci_devices", lambda: [])
    sent = []
    monkeypatch.setattr(runner, "publish", lambda stage, details, *a, **k: sent.append((stage, details)))
    out = tmp_path / "r.json"
    assert runner.run({**opts, "board": "arty", "report": str(out), "no_publish": False}) == 0
    assert [s for s, _ in sent] == ["fpga-verifying", "fpga-verified"]
    assert sent[0][1]["started_at"] and sent[1][1]["result"] == "pass"
    sent.clear()
    runner.run({**opts, "board": "arty", "report": str(out), "no_publish": True})
    assert sent == []


def test_a_test_run_is_never_published_nor_written_over_the_boot_report(opts, monkeypatch, capsys):
    arty = WithTests("arty", ["uart"], seen=[{"variant": "a7-35"}])
    monkeypatch.setattr(runner, "installed", lambda: _boards(arty))
    monkeypatch.setattr(runner, "usb_devices", lambda: [])
    monkeypatch.setattr(runner, "pci_devices", lambda: [])
    sent, written = [], []
    monkeypatch.setattr(runner, "publish", lambda stage, details, *a, **k: sent.append(stage))
    monkeypatch.setattr(runner, "write", lambda report, where: written.append(where) or where)
    assert runner.run({**opts, "board": "arty", "tests": ["uart"], "no_publish": False}) == 0
    assert sent == [] and written == ["-"]
    written.clear()
    runner.run({**opts, "board": "arty", "tests": ["uart"], "report": "elsewhere.json"})
    assert written == ["elsewhere.json"]  # --report still says where


def test_a_publish_that_times_out_is_said_and_changes_nothing(monkeypatch, capsys):
    seen = {}

    def hung(argv, check, timeout):
        seen["timeout"] = timeout
        raise subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(core.subprocess, "run", hung)
    assert core.publish("fpga-verifying", {"started_at": "now"}, timeout=15) is False
    assert seen["timeout"] == 15
    err = capsys.readouterr().err
    assert "could not publish fpga-verifying" in err and "the report is in" not in err
    assert core.publish("fpga-verified", {"result": "pass"}, "/run/fpgas-online/verify.json") is False
    assert seen["timeout"] == 60
    assert "the report is in /run/fpgas-online/verify.json" in capsys.readouterr().err


def test_every_board_module_is_found():
    assert set(installed()) == {"acorn", "arty", "fomu", "netv2", "tt"}


# -- the progress events ---------------------------------------------------------------------------------------


class Busy(Fake):
    """A board whose check runs two tests and says so through options["event"], as the board modules do."""

    def check(self, host, found, options):
        for test, result in (("uart", "pass"), ("ddr", self.result)):
            options["event"]("fpga-test-started", {"test": test})
            options["event"]("fpga-test-finished", {"test": test, "result": result, "reason": ""})
        return super().check(host, found, options)


def test_the_site_hears_each_board_found_and_each_test_with_its_board(opts):
    events = []
    arty = Busy("arty", seen=[{"variant": "a7-35", "usb": "1-1"}], result="fail")
    runner.verify({**opts, "event": lambda s, d: events.append((s, d))}, _boards(arty), usb=[], pci=[],
                  mode=("auto", "test"))  # fmt: skip
    assert events[0] == ("fpga-board-found", {"board": "arty", "variant": "a7-35", "where": "1-1"})
    assert events[1:] == [
        ("fpga-test-started", {"board": "arty", "test": "uart"}),
        ("fpga-test-finished", {"board": "arty", "test": "uart", "result": "pass", "reason": ""}),
        ("fpga-test-started", {"board": "arty", "test": "ddr"}),
        ("fpga-test-finished", {"board": "arty", "test": "ddr", "result": "fail", "reason": ""}),
    ]


def test_two_boards_of_a_kind_are_told_apart_in_the_events(opts):
    events = []
    acorns = Busy("acorn", seen=[{"variant": "cle-215+", "bdf": "0001:01:00.0"},
                                    {"variant": "cle-101", "bdf": "0002:01:00.0"}])  # fmt: skip
    runner.verify({**opts, "event": lambda s, d: events.append((s, d))}, _boards(acorns), usb=[], pci=[],
                  mode=("auto", "test"))  # fmt: skip
    found = [d["board"] for s, d in events if s == "fpga-board-found"]
    assert found == ["acorn@0001:01:00.0", "acorn@0002:01:00.0"]
    assert {d["board"] for s, d in events if s == "fpga-test-started"} == set(found)


def test_no_board_is_an_event_too(opts):
    events = []
    runner.verify({**opts, "event": lambda s, d: events.append((s, d))}, _boards(Fake("arty")), usb=[], pci=[],
                  mode=("auto", "test"))  # fmt: skip
    assert [s for s, _ in events] == ["fpga-no-board"]
    assert "none of the installed boards" in events[0][1]["reason"]


def test_the_events_go_out_in_order_and_a_dead_broker_stops_the_progress_ones(opts, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "installed", lambda: _boards(Busy("arty", seen=[{"variant": "a7-35"}])))
    monkeypatch.setattr(runner, "usb_devices", lambda: [])
    monkeypatch.setattr(runner, "pci_devices", lambda: [])
    sent = []
    monkeypatch.setattr(runner, "publish", lambda stage, details, *a, **k: sent.append((stage, details)) or True)
    out = tmp_path / "r.json"
    runner.run({**opts, "board": "arty", "report": str(out), "no_publish": False})
    assert [s for s, _ in sent] == ["fpga-verifying", "fpga-board-found", "fpga-test-started", "fpga-test-finished",
                                    "fpga-test-started", "fpga-test-finished", "fpga-verified"]  # fmt: skip
    assert all(isinstance(v, str) for _, d in sent for v in d.values())
    assert sent[1][1] == {"board": "arty", "variant": "a7-35", "where": "-"}
    sent.clear()
    monkeypatch.setattr(runner, "publish", lambda stage, details, *a, **k: sent.append(stage) and False)
    runner.run({**opts, "board": "arty", "report": str(out), "no_publish": False})
    assert sent == ["fpga-verifying", "fpga-verified"]  # one timeout, not one per test; the result is still tried


def test_the_gate_events_are_the_ones_the_site_reads():
    """fpgas.online-site's fpga_states() reads only fpga-verifying and fpga-verified (FPGA_STAGES); the rest are
    progress, and must not be mistaken for them."""
    assert {"fpga-verifying", "fpga-verified"} <= set(runner.EVENTS)
    assert all(s.startswith("fpga-") for s in runner.EVENTS)


class Crashes(Fake):
    def check(self, host, found, options):
        raise IndexError("list index out of range")


def test_a_board_check_that_crashes_is_an_error_and_the_others_are_still_checked(opts):
    bad, good = Crashes("acorn", seen=[{"variant": "cle-215+"}]), Fake("arty", seen=[{"variant": "a7-35"}])
    report = runner.verify(opts, _boards(bad, good), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "error"
    assert report["boards"][0]["reason"] == "the check crashed: IndexError: list index out of range"
    assert report["boards"][1]["result"] == "pass"


def test_even_a_crash_outside_any_board_gives_a_report_and_fpga_verified(opts, tmp_path, monkeypatch):
    def broken(options):
        raise KeyError("boards")

    monkeypatch.setattr(runner, "verify", broken)
    sent = []
    monkeypatch.setattr(runner, "publish", lambda stage, details, *a, **k: sent.append((stage, details)) or True)
    out = tmp_path / "r.json"
    assert runner.run({**opts, "report": str(out), "no_publish": False}) == 1
    report = json.loads(out.read_text())
    assert report["result"] == "error" and "KeyError" in report["reason"]
    assert sent[-1][0] == "fpga-verified" and sent[-1][1]["result"] == "error"


def test_a_fact_the_old_record_lacks_is_added_quietly_not_a_change(opts):
    """An upgrade that reads more (the Acorn's DNA) must not make every stateful host report "changed" once."""
    old = Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}])
    runner.verify(opts, _boards(old), usb=[], pci=[], mode=("auto", "test"))
    _record(opts, state.load(opts["state"]), 1)  # recorded by the version before dna

    class Reads(Fake):
        def check(self, host, found, options):
            report = super().check(host, found, options)
            report["state"]["dna"] = "0x54b48664b04854"
            return report

    report = runner.verify(opts, _boards(Reads("arty", seen=[{"variant": "a7-35", "serial": "A"}])), usb=[], pci=[],
                           mode=("auto", "test"))  # fmt: skip
    assert report["result"] == "pass" and "changes" not in report["state"] and report["state"]["added"]
    assert state.load(opts["state"])["arty"]["dna"] == "0x54b48664b04854"
    # and the next run sees the same facts: nothing to add, nothing changed
    report = runner.verify(opts, _boards(Reads("arty", seen=[{"variant": "a7-35", "serial": "A"}])), usb=[], pci=[],
                           mode=("auto", "test"))  # fmt: skip
    assert report["result"] == "pass" and "added" not in report["state"]


def test_a_fact_that_differs_is_still_a_change(opts):
    runner.verify(opts, _boards(Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}])), usb=[], pci=[],
                  mode=("auto", "test"))  # fmt: skip
    report = runner.verify(opts, _boards(Fake("arty", seen=[{"variant": "a7-35", "serial": "A"}], flash="bbbb")),
                           usb=[], pci=[], mode=("auto", "test"))  # fmt: skip
    assert report["result"] == "changed"


class Seen(Fake):
    """A board whose state this run is `facts`."""

    def __init__(self, name, facts, **kw):
        super().__init__(name, seen=[{"variant": "cle-215+"}], **kw)
        self.now = facts

    def check(self, host, found, options):
        return {"board": self.name, "variant": "cle-215+", "result": self.result, "state": dict(self.now)}


def _record(opts, boards, version):
    state.save(boards, "then", opts["state"])
    data = json.loads(opts["state"].read_text())
    data["schema_version"] = version
    opts["state"].write_text(json.dumps(data))


def test_a_swapped_board_whose_flash_was_not_read_last_time_is_changed(opts):
    """Recorded when BAR0 could not be read (no flash, no DNA); then the Acorn was swapped for another of the
    same variant. Its flash IDs were never recorded, so they are not an upgrade's new facts: changed."""
    _record(opts, {"acorn": {"bdf": "0001:01:00.0", "variant": "cle-215+"}}, state.SCHEMA_VERSION)
    now = Seen("acorn", {"bdf": "0001:01:00.0", "variant": "cle-215+", "dna": "0x1", "flash": {"jedec": "0x010219"}})
    report = runner.verify(opts, _boards(now), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "changed"
    assert any("flash: not recorded before" in c for c in report["state"]["changes"])
    assert any("dna: not recorded before" in c for c in report["state"]["changes"])  # the record's version has dna


def test_on_a_record_from_before_dna_only_dna_is_added_quietly(opts):
    _record(opts, {"acorn": {"bdf": "0001:01:00.0", "flash": {"jedec": "0x010219"}}}, 1)
    now = Seen("acorn", {"bdf": "0001:01:00.0", "flash": {"jedec": "0x010219"}, "dna": "0x1"})
    report = runner.verify(opts, _boards(now), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "pass" and report["state"]["added"]
    boards, version = state.load_record(opts["state"])
    assert boards["acorn"]["dna"] == "0x1" and version == state.SCHEMA_VERSION
    _record(opts, {"acorn": {"bdf": "0001:01:00.0"}}, 1)
    report = runner.verify(opts, _boards(now), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "changed"  # the flash is not one of the version's new facts


def test_an_idcode_recorded_without_its_version_gets_its_version_quietly(opts):
    """Before schema 3 a NeTV2 on a Pi 5 recorded openFPGALoader's masked IDCODE; now the whole one is read."""
    _record(opts, {"netv2": {"variant": "a7-35", "idcode": "0x0362d093"}}, 2)
    now = Seen("netv2", {"variant": "a7-35", "idcode": "0x1362d093"})
    report = runner.verify(opts, _boards(now), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "pass" and report["state"]["added"]
    boards, version = state.load_record(opts["state"])
    assert boards["netv2"]["idcode"] == "0x1362d093" and version == state.SCHEMA_VERSION


def test_an_idcode_of_another_part_or_version_is_still_a_change(opts):
    _record(opts, {"netv2": {"variant": "a7-35", "idcode": "0x03631093"}}, 2)  # another part, old record
    now = Seen("netv2", {"variant": "a7-35", "idcode": "0x1362d093"})
    assert runner.verify(opts, _boards(now), usb=[], pci=[], mode=("auto", "test"))["result"] == "changed"
    _record(opts, {"netv2": {"variant": "a7-35", "idcode": "0x0362d093"}}, 3)  # a whole IDCODE: another chip
    report = runner.verify(opts, _boards(now), usb=[], pci=[], mode=("auto", "test"))
    assert report["state"]["changes"] == ["netv2.idcode: was '0x0362d093', now '0x1362d093'"]


def test_an_arty_idcode_on_a_record_from_before_it_is_added_quietly(opts):
    _record(opts, {"arty": {"variant": "a7-35", "serial": "A"}}, 2)
    now = Seen("arty", {"variant": "a7-35", "serial": "A", "idcode": "0x0362d093"})
    report = runner.verify(opts, _boards(now), usb=[], pci=[], mode=("auto", "test"))
    assert report["result"] == "pass" and report["state"]["added"]


def test_a_run_that_errs_adds_nothing_to_the_record(opts):
    _record(opts, {"acorn": {"bdf": "0001:01:00.0"}}, 1)
    now = Seen("acorn", {"bdf": "0001:01:00.0", "dna": "0x1"}, result="error")
    report = runner.verify(opts, _boards(now), usb=[], pci=[], mode=("auto", "test"))
    assert "added" not in report["state"]
    assert "dna" not in state.load(opts["state"])["acorn"]
