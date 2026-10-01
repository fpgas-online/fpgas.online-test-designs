"""Pure-function tests for scripts/collect_verify_status.py (no network): reading what a Pi answers, and the
tables made from it."""

import importlib.util
import json
import pathlib

import pytest

_MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "collect_verify_status.py"
_spec = importlib.util.spec_from_file_location("collect_verify_status", _MOD_PATH)
cvs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cvs)

UNIT_DONE = {"LoadState": "loaded", "ActiveState": "failed", "Result": "exit-code", "ExecMainStatus": "1"}


def answer(report=None, unit=None, journal=None, hostname="pi-sw1-p10", model="Raspberry Pi 3 Model B Plus Rev 1.3"):
    """What REMOTE prints on a Pi."""
    return json.dumps({
        "hostname": hostname, "boot_id": "b1", "model": model, "unit": unit or UNIT_DONE,
        "version": "0.0.post673", "journal": journal,
        "report": None if report is None else json.dumps(report),
    })  # fmt: skip


def netv2_report():
    return {
        "schema_version": 2, "result": "fail", "checked_at": "2026-09-30T17:42:32+00:00", "mode": "auto",
        "boards": [{
            "board": "netv2", "variant": "a7-35", "result": "fail", "reason": "ddr fail: the test exited 1",
            "tests": [{"test": "uart", "result": "pass"}, {"test": "ddr", "result": "fail"},
                      {"test": "spiflash", "result": "pass"}],
        }],
    }  # fmt: skip


def acorn_report(kind="fpgas-online", result="pass"):
    board = {"board": "acorn", "variant": "cle-215+", "kind": kind, "result": result,
             "found": {"kind": kind}, "tests": [{"test": "jtag", "result": "pass"}]}  # fmt: skip
    return {"schema_version": 2, "result": result, "checked_at": "2026-09-30T18:11:30+00:00", "boards": [board]}


def missing_report():
    return {"schema_version": 2, "result": "missing", "checked_at": "2026-09-30T17:45:16+00:00", "boards": [],
            "reason": "none of the installed boards (acorn, arty, fomu, netv2, tt) was found"}  # fmt: skip


# -- which Pis ----------------------------------------------------------------------------------------------


def test_ports_spec_expands_ranges_and_lists():
    assert cvs.parse_ports("1:1-3 2:5,7-8") == [(1, 1), (1, 2), (1, 3), (2, 5), (2, 7), (2, 8)]


def test_ports_spec_without_a_switch_is_refused():
    with pytest.raises(ValueError):
        cvs.parse_ports("1-40")


def test_default_ports_are_every_access_port_on_both_switches():
    ports = cvs.parse_ports(cvs.DEFAULT_PORTS)
    assert len(ports) == 40 + 48
    assert cvs.address(*ports[-1]) == "10.21.2.48"


def test_name_and_sort_follow_switch_then_port():
    assert cvs.name_from_address("10.21.2.47") == "pi-sw2-p47"
    assert cvs.name_from_address("rpi5-netv2") == "rpi5-netv2"
    names = ["pi-sw2-p9", "pi-sw1-p38", "pi-sw2-p10", "other"]
    assert sorted(names, key=cvs.sort_key) == ["pi-sw1-p38", "pi-sw2-p9", "pi-sw2-p10", "other"]


def test_compact_groups_consecutive_ports():
    ips = ["10.21.1.1", "10.21.1.2", "10.21.1.3", "10.21.1.9", "10.21.2.5", "10.21.2.6"]
    assert cvs.compact(ips) == "sw1 p1-3,p9; sw2 p5-6"


# -- reaching a Pi -------------------------------------------------------------------------------------------


def test_ssh_goes_through_the_jump_host_and_never_records_the_pis_host_key():
    argv = cvs.ssh_argv("10.21.2.47", jump="ansible@10.99.21.2", ssh_config="ssh.cfg")
    assert argv[:3] == ["ssh", "-F", "ssh.cfg"]
    assert "StrictHostKeyChecking=no" in argv
    assert "UserKnownHostsFile=/dev/null" in argv
    assert "BatchMode=yes" in argv
    assert argv[argv.index("-J") + 1] == "ansible@10.99.21.2"
    assert argv[-3:] == ["root@10.21.2.47", "python3", "-"]


def test_ssh_without_jump_or_config():
    argv = cvs.ssh_argv("10.21.2.47", jump="", ssh_config=None, user="pi")
    assert "-J" not in argv and "-F" not in argv
    assert argv[-3] == "pi@10.21.2.47"


def test_the_remote_side_only_reads():
    for word in ("--update", "systemctl stop", "systemctl start", "restart", "reboot", "rmmod", "openFPGALoader"):
        assert word not in cvs.REMOTE
    assert "fpgas-verify" not in cvs.REMOTE.replace("fpgas-verify.service", "")


@pytest.mark.parametrize(
    ("error", "unreachable"),
    [
        ("channel 0: open failed: connect failed: No route to host; stdio forwarding failed", True),
        ("no answer within 60 s", True),
        ("root@10.21.2.30: Permission denied (publickey).", False),
    ],
)
def test_unreachable_ports_are_told_apart_from_pis_that_refuse(error, unreachable):
    assert cvs.is_unreachable({"address": "10.21.2.30", "error": error}) is unreachable


# -- what a Pi says --------------------------------------------------------------------------------------------


def test_a_report_gives_each_tests_result():
    r = cvs.parse_remote("10.21.1.10", answer(netv2_report()))
    assert r["host"] == "pi-sw1-p10"
    assert r["status"] == "fail"
    assert r["version"] == "0.0.post673"
    assert r["boards"] == [{"board": "netv2", "variant": "a7-35", "result": "fail",
                            "tests": [("uart", "pass"), ("ddr", "fail"), ("spiflash", "pass")],
                            "reason": "ddr fail: the test exited 1"}]  # fmt: skip


def test_a_pi_with_no_board_is_missing_with_the_reports_reason():
    r = cvs.parse_remote("10.21.1.17", answer(missing_report()))
    assert r["status"] == "missing"
    assert r["boards"] == []
    assert "none of the installed boards" in r["reason"]


def test_a_pcie_design_the_acorn_module_cannot_name_is_not_counted_as_an_acorn():
    r = cvs.parse_remote("10.21.2.37", answer(acorn_report(kind="litex-other", result="fail")))
    assert r["boards"][0]["board"] == "pcie-other"
    assert cvs.parse_remote("10.21.2.47", answer(acorn_report()))["boards"][0]["board"] == "acorn"


def test_no_report_while_the_check_runs_is_verifying():
    r = cvs.parse_remote("10.21.2.9", answer(unit={"LoadState": "loaded", "ActiveState": "activating"}))
    assert r["status"] == "verifying"


def test_no_unit_is_not_installed():
    r = cvs.parse_remote("10.21.2.9", answer(unit={"LoadState": "not-found", "ActiveState": "inactive"}))
    assert r["status"] == "not installed"


def test_no_report_says_the_journals_last_line():
    r = cvs.parse_remote("10.21.2.9", answer(journal="Starting...\nfpgas-verify: error: no FPGA board is configured\n"))
    assert r["status"] == "no report"
    assert r["reason"] == "fpgas-verify: error: no FPGA board is configured"


def test_an_old_report_while_a_new_check_runs_says_so():
    r = cvs.parse_remote(
        "10.21.1.10", answer(netv2_report(), unit={"LoadState": "loaded", "ActiveState": "activating"})
    )
    assert r["status"] == "fail"
    assert "previous report" in r["note"]


def test_a_broken_report_or_answer_is_an_error_not_a_crash():
    raw = json.loads(answer())
    raw["report"] = "{not json"
    assert cvs.parse_remote("10.21.1.10", json.dumps(raw))["status"] == "error"
    assert "error" in cvs.parse_remote("10.21.1.10", "Traceback (most recent call last):")


@pytest.mark.parametrize(
    ("model", "short"),
    [
        ("Raspberry Pi 3 Model B Plus Rev 1.3", "Pi 3B+"),
        ("Raspberry Pi 4 Model B Rev 1.5", "Pi 4B"),
        ("Raspberry Pi 5 Model B Rev 1.1", "Pi 5B"),
        ("Raspberry Pi Compute Module 5 Rev 1.0", "CM5"),
        ("Xunlong Orange Pi PC", "Orange Pi PC"),
        ("", "-"),
    ],
)
def test_model_short(model, short):
    assert cvs.model_short(model) == short


# -- the tables ----------------------------------------------------------------------------------------------


def test_markdown_summarises_by_board_and_lists_every_pi():
    records = [
        cvs.parse_remote("10.21.1.10", answer(netv2_report())),
        cvs.parse_remote("10.21.1.12", answer(netv2_report(), hostname="pi-sw1-p12")),
        cvs.parse_remote("10.21.1.17", answer(missing_report(), hostname="pi-sw1-p17")),
        cvs.parse_remote("10.21.2.47", answer(acorn_report(), hostname="pi-sw2-p47", model="Raspberry Pi 5 Model B")),
        {"address": "10.21.2.30", "error": "root@10.21.2.30: Permission denied (publickey)."},
    ]
    text = cvs.markdown(records, ["10.21.1.1", "10.21.1.2"], "2026-10-01T00:00:00Z")
    lines = text.splitlines()
    assert lines[0].startswith("Collected 2026-10-01T00:00:00Z from 4 Pis")
    assert "| NeTV2 | 2 | fail 2 | uart 2/2, ddr 0/2, spiflash 2/2 |" in lines
    assert "| Acorn | 1 | pass 1 | jtag 1/1 |" in lines
    assert "| (no board) | 1 | missing 1 | - |" in lines
    netv2_row = next(line for line in lines if line.startswith("| pi-sw1-p10 |"))
    assert "| Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass |" in netv2_row
    assert "2026-09-30T17:42:32Z" in netv2_row
    assert any(line.startswith("| pi-sw1-p17 | Pi 3B+ | - | - | missing |") for line in lines)
    assert "Could not be read: 10.21.2.30" in text
    assert lines[-1] == "No Pi answered on 2 ports: sw1 p1-2."


def test_reasons_are_one_line_and_cannot_break_the_table():
    assert cvs.short("a |\n b") == "a \\| b"
    assert len(cvs.short("x" * 500)) == cvs.REASON_MAX
