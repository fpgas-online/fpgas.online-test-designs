"""The Pi's own facts for its label: `rpi-hwid label-input --pi-only` at boot, sent as `pi-identified` (#76).

Tim, 16 Oct 2026 (coord-74): "Why are there no RPi labels on https://welland.fpgas.online/fleet/55effc3376226b41/"
"""

import copy
import json
import pathlib
from typing import ClassVar

import pytest
from fpgas_online_verify import pi_identity, runner
from fpgas_online_verify.core import Problem

# What `rpi-hwid label-input --pi-only` printed on the fleet's Pi 5 1 GB 55effc3376226b41 (acorn-linden's host, a
# Waveshare PoE M.2 HAT+ (B) on its ID bus), with rpi-hwid #92 (0.0.post597), 17 Oct 2026 00:11 ACDT.
PI5_DOC = json.loads((pathlib.Path(__file__).parent / "data" / "pi-only-pi5.json").read_text())


def ran(text, rc=0, err=""):
    """A stand-in for pi_identity.run_apart: rpi-hwid printed `text` on stdout and `err` on stderr."""

    def run(argv, timeout):
        assert argv == list(pi_identity.ARGV) and timeout == pi_identity.TIMEOUT
        return rc, text, err

    return run


def installed(name):
    return f"/usr/bin/{name}"


def test_a_good_read_gives_the_fields_the_site_takes_and_nothing_else():
    read = pi_identity.read(ran(json.dumps(PI5_DOC, indent=1)), installed)
    assert read["reader"] == "rpi-hwid" and "reader_error" not in read
    assert set(read["facts"]) == set(pi_identity.FIELDS)
    assert read["facts"]["header"] == ["Waveshare PoE M.2 HAT+ (B)"] and read["facts"]["fan"] is True


def test_the_event_is_encoded_as_the_label_contract_says():
    """rpi-hwid LABEL-CONTRACT.md section 3: lists one key of compact sorted JSON, booleans true/false, none "-"."""
    doc = copy.deepcopy(PI5_DOC)
    doc["summary"].update(hat_uuid=None, rtc_battery=None)
    d = pi_identity.details(pi_identity.read(ran(json.dumps(doc)), installed))
    assert d["schema"] == "pi-identity/1" and d["reader"] == "rpi-hwid"
    assert d["header"] == '["Waveshare PoE M.2 HAT+ (B)"]' and d["usb_net"] == "[]"
    assert d["macs"] == '[{"kind":"eth","mac":"98:fe:54:13:e0:75","signal":"driver"}]'
    assert (d["fan"], d["rtc_battery"], d["hat_uuid"]) == ("true", "-", "-")
    assert (d["max_current_ma"], d["ext5v_v"], d["power_class"]) == ("3000", "5.14962", "gpio-poe-hat")
    assert not {"model", "serial", "revision", "memory", "fpga", "cameras"} & set(d)  # the registration has those
    assert all(isinstance(v, str) for v in d.values())


def test_a_header_nobody_read_is_left_out_never_sent_as_none_or_empty():
    doc = copy.deepcopy(PI5_DOC)
    doc["summary"]["header"] = None
    d = pi_identity.details(pi_identity.read(ran(json.dumps(doc)), installed))
    assert "header" not in d


@pytest.mark.parametrize("err", ["", "reading the ID bus over GPIO0/1\n", "a\nb\n{not the document}\n"])
def test_what_rpi_hwid_says_on_stderr_is_never_part_of_the_document(err):
    """#365 review B1: stdout and stderr are kept apart, so nothing rpi-hwid says on stderr, before or after the
    document, breaks a good read."""
    read = pi_identity.read(ran(json.dumps(PI5_DOC, indent=1) + "\n", err=err), installed)
    assert read["facts"]["power_class"] == "gpio-poe-hat"


def test_a_failure_names_what_rpi_hwid_said_on_stderr():
    read = pi_identity.read(ran("", 1, "label-input: GPIO0/1 are in use by i2c0mux\n"), installed)
    assert read["reader_error"].endswith("exited 1: label-input: GPIO0/1 are in use by i2c0mux")


def test_without_rpi_hwid_the_event_says_reader_none_and_nothing_else():
    read = pi_identity.read(ran("unused"), lambda name: None)
    assert read == {"reader": "none"}
    assert pi_identity.details(read) == {"schema": "pi-identity/1", "reader": "none"}


@pytest.mark.parametrize(
    ("text", "rc", "said"),
    [
        ("Error: cannot open /dev/i2c-0\n", 1, "exited 1: Error: cannot open /dev/i2c-0"),
        ("", 0, "printed no JSON document"),
        ("{not json\n", 0, "does not parse"),
        (json.dumps({**PI5_DOC, "version": 2}), 0, "label input version 2, not 1"),
        (json.dumps({**PI5_DOC, "schema": "rpi-hwid/probe"}), 0, "no rpi-hwid/label-input document"),
        (json.dumps({**PI5_DOC, "summary": None}), 0, "no summary"),
        (json.dumps({**PI5_DOC, "summary": {**PI5_DOC["summary"], "macs": "88:a2"}}), 0, "macs as str, not a list"),
        (json.dumps({**PI5_DOC, "summary": {**PI5_DOC["summary"], "ext5v_v": float("nan")}}), 0, "ext5v_v as nan"),
    ],
)
def test_a_read_that_fails_is_a_reader_error_naming_why(text, rc, said):
    read = pi_identity.read(ran(text, rc), installed)
    assert read["reader"] == "rpi-hwid" and said in read["reader_error"] and "facts" not in read
    d = pi_identity.details(read)
    assert d == {"schema": "pi-identity/1", "reader": "rpi-hwid", "reader_error": read["reader_error"]}


def test_rpi_hwid_that_does_not_finish_is_a_reader_error():
    def slow(argv, timeout):
        raise Problem("fail", f"rpi-hwid did not finish within {timeout} s: ")

    assert "did not finish within 120 s" in pi_identity.read(slow, installed)["reader_error"]


def test_a_long_reason_keeps_its_end_where_the_cause_is():
    d = pi_identity.details({"reader": "rpi-hwid", "reader_error": "x" * 1000 + " the cause"})
    assert len(d["reader_error"]) == pi_identity.REASON_MAX
    assert d["reader_error"].startswith("…") and d["reader_error"].endswith(" the cause")


def test_a_crash_in_the_read_is_a_reader_error_never_an_exception():
    """#365 review N4: whatever goes wrong reading the Pi, the boards are still checked."""

    def broken(argv, timeout):
        raise KeyError("summary")

    read = pi_identity.read(broken, installed)
    assert read == {"reader": "rpi-hwid", "reader_error": "reading the Pi's facts crashed: KeyError: 'summary'"}


def test_rpi_hwid_runs_with_stdout_and_stderr_apart_and_a_bounded_timeout(tmp_path):
    """#365 review N5: run_apart keeps the two streams apart, and a child that does not finish is killed and
    waited for a bounded time, then a Problem, never a hang."""
    import sys

    rc, out, err = pi_identity.run_apart(
        [sys.executable, "-c", "import sys; print('{}'); print('noise', file=sys.stderr)"], 30
    )
    assert (rc, out, err) == (0, "{}\n", "noise\n")
    with pytest.raises(Problem, match=r"did not finish within 1 s; it was killed"):
        pi_identity.run_apart([sys.executable, "-c", "import time; time.sleep(30)"], 1)
    with pytest.raises(Problem, match="could not be run"):
        pi_identity.run_apart([str(tmp_path / "rpi-hwid")], 1)


# -- in the check -------------------------------------------------------------------------------------------


def checked(read, board_result="pass", spotted=True):
    """The report and the events of verify() with one fake board, and `read` as the Pi's facts."""
    events = []

    class Board:
        name = slug = "fake"
        title = "Fake"
        probes = False
        lock = None
        debug_usb: ClassVar[dict] = {}

        def facts(self, port):
            return {}

        def spot(self, host, usb, pci):
            return [{"usb": "1-1", "variant": "v"}] if spotted else []

        def weak(self, found):
            return False

        def check(self, host, found, options):
            assert [s for s, _ in events][:1] == ["pi-identified"]  # before any board's check (and its lock)
            return {"board": "fake", "found": found, "result": board_result}

        def planned(self, variant, options=None, found=None):
            return []

        def not_applicable(self, variant, found=None):
            return {}

    options = {"mode": None, "board": "auto", "event": lambda s, d: events.append((s, d)), "read_pi": lambda: read,
               "state": "/nonexistent/state.json", "update": False, "tests": None}  # fmt: skip
    report = runner.verify(options, boards={"fake": Board()}, usb=[], pci=[], mode=("auto", "test"))
    return report, events


def test_the_check_sends_pi_identified_first_and_keeps_the_read_in_the_report(monkeypatch):
    monkeypatch.setattr(runner, "hold_lock", lambda lock, title: __import__("contextlib").nullcontext())
    monkeypatch.setattr(runner, "compare_state", lambda *a: {})
    monkeypatch.setattr(runner, "plan", lambda *a: None)
    read = {"reader": "rpi-hwid", "facts": {"header": [], "fan": None}}
    report, events = checked(read)
    assert events[0] == ("pi-identified", {"schema": "pi-identity/1", "reader": "rpi-hwid", "header": "[]",
                                           "fan": "-"})  # fmt: skip
    assert report["pi"] == read and report["result"] == "pass"
    assert "the Pi's own facts (rpi-hwid --pi-only): header=[], fan=-" in runner.summary(report)


def test_a_pi_whose_facts_were_not_read_says_so_and_leaves_the_boards_result_alone(monkeypatch):
    """The coordinator's decision of 17 Oct 2026, from Tim's rules of 5 and 16 Oct: a Pi-label read is not a board
    test. Its failure is in the pi-identified event and the report, said loudly, and the boards are still offered
    on their own result."""
    monkeypatch.setattr(runner, "hold_lock", lambda lock, title: __import__("contextlib").nullcontext())
    monkeypatch.setattr(runner, "compare_state", lambda *a: {})
    monkeypatch.setattr(runner, "plan", lambda *a: None)
    report, events = checked({"reader": "rpi-hwid", "reader_error": "rpi-hwid label-input --pi-only exited 1: x"})
    assert report["result"] == "pass" and "reason" not in report
    assert report["pi"]["reader_error"].endswith("exited 1: x")
    assert events[0][1]["reader_error"].endswith("exited 1: x")
    assert "the Pi's own facts: NOT READ: " in runner.summary(report)


def test_only_the_whole_check_on_a_pi_reads_the_pi(monkeypatch):
    seen = []
    monkeypatch.setattr(runner, "verify", lambda options: seen.append(options.get("read_pi")) or {
        "schema_version": 2, "result": "pass", "checked_at": "now", "boards": []})  # fmt: skip
    monkeypatch.setattr(runner, "pi_model", lambda: "Raspberry Pi 5 Model B Rev 1.1")
    runner.run({"no_publish": True, "report": "-"})
    runner.run({"no_publish": True, "tests": ["uart"]})
    monkeypatch.setattr(runner, "pi_model", lambda: "")
    runner.run({"no_publish": True, "report": "-"})
    assert seen == [pi_identity.read, None, None]


def test_a_pi_with_no_board_and_its_facts_unread_is_missing_and_says_the_read_failed(monkeypatch):
    """#365 review N6: no board is "missing", as ever; the failed read is said in its event and the report."""
    monkeypatch.setattr(runner, "compare_state", lambda *a: {})
    report, events = checked({"reader": "rpi-hwid", "reader_error": "rpi-hwid label-input --pi-only exited 1: x"},
                             spotted=False)  # fmt: skip
    assert report["result"] == "missing"
    assert "the Pi's own facts" not in report["reason"]
    assert report["pi"]["reader_error"].endswith("exited 1: x")
    assert [s for s, _ in events][:2] == ["pi-identified", "fpga-no-board"]
