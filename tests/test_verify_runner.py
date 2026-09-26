"""Tests for fpgas-verify's rules (fpgas_online_verify.runner, config and state), with stand-in boards.

* A host set up for one board checks only that board: not finding it is fatal, whatever else is attached,
  and nothing else is looked for.
* A host set up for `auto` looks for every installed board, passively (USB/PCI) before driving anything
  (the NeTV2's JTAG scan); finding none is fatal.
* With persistent state, a different board or a different flash from last time is fatal ("changed") until
  --update records it; an SRAM load or a package upgrade is not a change.
"""

import json

import pytest
from fpgas_online_verify import config, runner, state
from fpgas_online_verify.board import Board, installed
from fpgas_online_verify.core import Problem


class Fake(Board):
    """A board seen on USB with `seen`, or found by probing; check() reports `result` and the state given."""

    def __init__(self, name, seen=(), probes=False, probed=(), result="pass", flash="aaaa"):
        self.name = self.slug = name
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


def test_every_board_module_is_found():
    assert set(installed()) == {"acorn", "arty", "fomu", "netv2", "tt"}
