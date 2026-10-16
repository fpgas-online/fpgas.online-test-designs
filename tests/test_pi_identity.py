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


def ran(text, rc=0):
    def run(argv, timeout):
        assert argv == list(pi_identity.ARGV) and timeout == pi_identity.TIMEOUT
        return rc, text

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


def test_rpi_hwids_progress_on_stderr_before_the_document_is_not_the_document():
    text = "i2c-dev loaded; dtparam i2c_vc=on\n" + json.dumps(PI5_DOC, indent=1) + "\n"
    assert pi_identity.read(ran(text), installed)["facts"]["power_class"] == "gpio-poe-hat"


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


def test_a_long_reason_is_cut_saying_so():
    d = pi_identity.details({"reader": "rpi-hwid", "reader_error": "x" * 1000})
    assert len(d["reader_error"]) == pi_identity.REASON_MAX and d["reader_error"].endswith("…")


# -- in the check -------------------------------------------------------------------------------------------


def checked(read, board_result="pass"):
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
            return [{"usb": "1-1", "variant": "v"}]

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


def test_a_pi_whose_facts_were_not_read_makes_the_boot_an_error_saying_why(monkeypatch):
    monkeypatch.setattr(runner, "hold_lock", lambda lock, title: __import__("contextlib").nullcontext())
    monkeypatch.setattr(runner, "compare_state", lambda *a: {})
    monkeypatch.setattr(runner, "plan", lambda *a: None)
    report, events = checked({"reader": "rpi-hwid", "reader_error": "rpi-hwid label-input --pi-only exited 1: x"})
    assert report["result"] == "error"
    assert report["reason"] == "the Pi's own facts were not read: rpi-hwid label-input --pi-only exited 1: x"
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
