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


@pytest.mark.parametrize("spec", ["1-40", "1:", "x:1-2", "1:a-b"])
def test_a_bad_ports_spec_is_refused(spec):
    with pytest.raises(ValueError, match="expected SWITCH:PORTS"):
        cvs.parse_ports(spec)


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


def test_ssh_goes_through_the_jump_host_and_checks_the_shared_netboot_key():
    argv = cvs.ssh_argv("10.21.2.47", jump="ansible@10.99.21.2", ssh_config="ssh.cfg", known_hosts="/k/nb")
    assert argv[:3] == ["ssh", "-F", "ssh.cfg"]
    for option in ("BatchMode=yes", "UserKnownHostsFile=/k/nb", "HostKeyAlias=fpgas-netboot-pi", "CheckHostIP=no",
                   "StrictHostKeyChecking=accept-new", "HashKnownHosts=no", "ForwardAgent=no"):  # fmt: skip
        assert option in argv
    assert "StrictHostKeyChecking=no" not in argv and "UserKnownHostsFile=/dev/null" not in argv
    assert argv[argv.index("-J") + 1] == "ansible@10.99.21.2"
    assert argv[-3:] == ["root@10.21.2.47", "python3", "-"]


def test_ssh_without_jump_or_config():
    argv = cvs.ssh_argv("10.21.2.47", jump="", ssh_config=None, user="pi")
    assert "-J" not in argv and "-F" not in argv
    assert argv[-3] == "pi@10.21.2.47"


def test_the_jump_host_check_runs_nothing_but_true():
    assert cvs.jump_argv("ansible@10.99.21.2", "ssh.cfg", 5)[-2:] == ["ansible@10.99.21.2", "true"]


def test_the_remote_side_only_reads():
    for word in ("--update", "systemctl stop", "systemctl start", "restart", "reboot", "rmmod", "openFPGALoader"):
        assert word not in cvs.REMOTE
    assert "fpgas-verify" not in cvs.REMOTE.replace("fpgas-verify.service", "")


class FakeSSH:
    """Stands in for subprocess.run: the jump host answers `jump_rc`; each Pi address answers from `pis`
    (an Exception is raised; a string is the stdout of a successful run; a (rc, stderr) pair fails)."""

    def __init__(self, pis=(), jump_rc=0):
        self.pis, self.jump_rc, self.calls = dict(pis), jump_rc, []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        if argv[-1] == "true":
            return cvs.subprocess.CompletedProcess(argv, self.jump_rc, "", "" if self.jump_rc == 0 else "refused")
        ip = argv[-3].split("@")[1]
        answer = self.pis.get(ip, (255, "channel 0: open failed: connect failed: No route to host\n"
                                      "stdio forwarding failed\n"))  # fmt: skip
        if isinstance(answer, Exception):
            raise answer
        if isinstance(answer, str):
            return cvs.subprocess.CompletedProcess(argv, 0, answer, "")
        return cvs.subprocess.CompletedProcess(argv, answer[0], "", answer[1])


def _main(monkeypatch, tmp_path, fake, *args):
    monkeypatch.setattr(cvs.subprocess, "run", fake)
    return cvs.main(["--known-hosts", str(tmp_path / "kh"), *args])


@pytest.mark.parametrize(
    ("answer", "no_pi"),
    [
        ((255, "channel 0: open failed: connect failed: No route to host\nstdio forwarding failed\n"), True),
        ((255, "stdio forwarding failed\n"), True),
        ((255, "root@10.21.2.30: Permission denied (publickey).\n"), False),
        ((255, "ssh: connect to host 10.21.2.30 port 22: Connection timed out\n"), False),
        (cvs.subprocess.TimeoutExpired("ssh", 60), False),
    ],
)
def test_only_the_jump_hosts_forward_failures_mean_no_pi(answer, no_pi, monkeypatch):
    monkeypatch.setattr(cvs.subprocess, "run", FakeSSH({"10.21.2.30": answer}))
    options = cvs.argparse.Namespace(jump="j", ssh_config=None, user="root", connect_timeout=1, known_hosts="kh")
    record = cvs.collect_one("10.21.2.30", options)
    assert "error" in record and cvs.is_unreachable(record) is no_pi


def test_main_exits_2_when_the_jump_host_cannot_be_reached(monkeypatch, tmp_path, capsys):
    fake = FakeSSH(jump_rc=255)
    assert _main(monkeypatch, tmp_path, fake) == 2
    assert len(fake.calls) == 1 and "cannot reach the jump host" in capsys.readouterr().err


def test_main_exits_1_when_no_pi_was_read(monkeypatch, tmp_path, capsys):
    assert _main(monkeypatch, tmp_path, FakeSSH(), "--ports", "1:1-3") == 1
    assert "no Pi could be read" in capsys.readouterr().err


def test_main_exits_0_when_every_pi_answered_and_the_rest_have_none(monkeypatch, tmp_path):
    fake = FakeSSH({"10.21.1.10": answer(netv2_report())})
    assert _main(monkeypatch, tmp_path, fake, "--ports", "1:9-11") == 0
    assert (tmp_path / "kh").parent.is_dir()


def test_main_exits_1_when_a_pi_answered_badly_or_timed_out(monkeypatch, tmp_path):
    fake = FakeSSH({"10.21.1.10": answer(netv2_report()), "10.21.1.11": cvs.subprocess.TimeoutExpired("ssh", 60)})
    assert _main(monkeypatch, tmp_path, fake, "--ports", "1:10-11") == 1


def test_main_exits_1_when_a_named_host_did_not_answer(monkeypatch, tmp_path):
    fake = FakeSSH({"10.21.1.10": answer(netv2_report())})
    assert _main(monkeypatch, tmp_path, fake, "--host", "10.21.1.10", "--host", "10.21.1.11") == 1


def test_main_skips_the_excluded_ports(monkeypatch, tmp_path):
    fake = FakeSSH({"10.21.2.29": answer(acorn_report())})
    assert _main(monkeypatch, tmp_path, fake, "--ports", "2:29-31") == 0
    assert not any(c[-3] == "root@10.21.2.30" for c in fake.calls[1:])


def test_main_refuses_a_bad_ports_spec_with_a_usage_error(monkeypatch, tmp_path, capsys):
    with pytest.raises(SystemExit) as e:
        _main(monkeypatch, tmp_path, FakeSSH(), "--ports", "1:a-b")
    assert e.value.code == 2 and "expected SWITCH:PORTS" in capsys.readouterr().err


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
    assert cvs.parse_remote("10.21.1.10", json.dumps(raw))["error"] == "/run/fpgas-online/verify.json is not JSON"
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


def test_a_board_with_no_tests_shows_a_dash():
    board = {"board": "acorn", "kind": "litex-other", "result": "fail", "reason": "not a design we built"}
    report = {"schema_version": 2, "result": "fail", "checked_at": "2026-09-30T18:06:51+00:00", "boards": [board]}
    row = cvs.rows([cvs.parse_remote("10.21.2.37", answer(report))])[0]
    assert row[2:7] == ["Unrecognised PCIe FPGA", "-", "fail", "-", "not a design we built"]
