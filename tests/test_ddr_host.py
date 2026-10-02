"""Unit tests for designs/ddr-memory/host/test_ddr.py against a fake BIOS (tests/bios_fakes.py).

The replies are the ones the Welland boards gave on 2026-10-02: the passing ones from the installed DDR test
designs, the failing ones from a NeTV2 DDR image built before #57 (no read-leveling window, Memtest KO).
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "_host"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "ddr-memory" / "host"))

import bios_console
import test_ddr

from .bios_fakes import PROMPT, FakeBios, ddr_replies, lines, memtest


def run(fake, board="netv2"):
    return test_ddr.run_ddr_test(bios_console.BiosConsole(fake, clock=fake.clock), board, attach_timeout=10)


def test_a_working_netv2_passes_on_a_run_it_asked_for():
    fake = FakeBios(ddr_replies("netv2"))
    found = run(fake)
    assert found["result"] == "pass"
    assert fake.commands == ["", "ident", "mem_list", "sdram_init", "sdram_test"]
    assert found["ident"] == "fpgas-online DDR Test SoC -- NeTV2 2026-10-01 11:00:01"
    assert found["leveling"] == {"m0": "b01 14+-14", "m1": "b01 14+-14", "m2": "b01 14+-14", "m3": "b01 14+-14"}
    assert found["bytes_tested"] == 32 * 1024 * 1024
    assert found["errors"] == 0
    assert (found["write_mib_per_s"], found["read_mib_per_s"]) == (27.2, 30.9)
    assert (found["main_ram_base"], found["main_ram_bytes"]) == (0x40000000, 0x40000000)


def test_a_working_arty_passes():
    found = run(FakeBios(ddr_replies("arty")), "arty")
    assert found["result"] == "pass"
    assert sorted(found["leveling"]) == ["m0", "m1"]
    assert found["bytes_tested"] == 8 * 1024 * 1024


def test_the_boot_log_is_not_what_is_judged():
    # A finished boot log saying Memtest OK is waiting in the port, but the memory fails when asked now.
    stale = lines("Switching SDRAM to software control.", "Memtest at 0x40000000 (2.0MiB)...", "Memtest OK") + PROMPT
    found = run(FakeBios(ddr_replies("netv2", good=False), stale=stale))
    assert found["result"] == "fail"


def test_a_port_that_was_opened_after_the_boot_log_passes():
    # The NeTV2's ttyAMA0: nothing is waiting, and nothing of the boot is ever seen.
    assert run(FakeBios(ddr_replies("netv2"), stale=b""))["result"] == "pass"


def test_no_leveling_window_and_memtest_ko_fail_with_the_error_counts():
    found = run(FakeBios(ddr_replies("netv2", good=False)))
    assert found["result"] == "fail"
    assert "read leveling found no window on m0, m1, m2, m3" in found["reason"]
    assert "sdram_init: Memtest KO" in found["reason"]
    assert "sdram_test: Memtest KO" in found["reason"]
    assert "data errors 8388608/8388608" in found["reason"]
    assert found["errors"] == 256 + 8388608
    assert found["leveling"] == {"m0": None, "m1": None, "m2": None, "m3": None}
    assert "write_mib_per_s" not in found


def test_a_memory_that_fails_only_the_larger_test_fails():
    replies = ddr_replies("netv2")
    replies["sdram_test"] = memtest("32.0MiB", ok=False, words=8388608)
    found = run(FakeBios(replies))
    assert found["result"] == "fail"
    assert found["reason"].startswith("sdram_test: Memtest KO")


def test_nothing_answering_is_reported_as_no_console():
    found = run(FakeBios(silent=True))
    assert found["result"] == "fail"
    assert "no BIOS prompt" in found["reason"]
    assert "ident" not in found


def test_another_design_is_not_tested_as_if_it_were_the_ddr_design():
    replies = ddr_replies("netv2")
    replies["ident"] = lines("Ident: fpgas-online UART Test SoC -- NeTV2 2026-10-01 11:00:01")
    fake = FakeBios(replies)
    found = run(fake)
    assert found["result"] == "fail"
    assert "UART Test SoC" in found["reason"]
    assert "sdram_init" not in fake.commands


def test_another_board_is_not_accepted():
    found = run(FakeBios(ddr_replies("arty")), "netv2")
    assert found["result"] == "fail"
    assert "Arty A7" in found["reason"]


def test_a_command_that_hangs_fails_and_says_which():
    replies = ddr_replies("netv2")
    fake = FakeBios(replies)
    write = fake.write

    def hang_in_sdram_init(data):
        n = write(data)
        if fake.commands and fake.commands[-1] == "sdram_init":
            del fake.rx[-len(PROMPT) :]
        return n

    fake.write = hang_in_sdram_init
    test_ddr.COMMAND_TIMEOUT_S["sdram_init"] = 5
    found = run(fake)
    assert found["result"] == "fail"
    assert "`sdram_init` did not return to the prompt" in found["reason"]


def test_parse_size():
    assert test_ddr.parse_size("2.0MiB") == 2 * 1024 * 1024
    assert test_ddr.parse_size("8.0KiB") == 8 * 1024
    assert test_ddr.parse_size("1.0GiB") == 1024**3
    assert test_ddr.parse_size("0B") == 0


def test_main_prints_one_result_json_line_and_exits_by_the_result(capsys, monkeypatch):
    fakes = []

    def opener(port, baud, timeout):
        fakes.append(FakeBios(ddr_replies("netv2", good=not fakes)))
        return fakes[-1]

    monkeypatch.setattr(test_ddr, "open_port", opener)
    monkeypatch.setattr(test_ddr.time, "monotonic", lambda: fakes[-1].now)
    assert test_ddr.main(["--port", "/dev/ttyAMA0", "--board", "netv2"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out
    payload = [line for line in out.splitlines() if line.startswith("RESULT_JSON ")]
    assert len(payload) == 1
    found = json.loads(payload[0].split(" ", 1)[1])
    assert found["test"] == "ddr" and found["result"] == "pass" and found["board"] == "netv2"
    assert found["commands"] == ["ident", "mem_list", "sdram_init", "sdram_test"]

    assert test_ddr.main(["--port", "/dev/ttyAMA0", "--board", "netv2"]) == 1
    out = capsys.readouterr().out
    assert "RESULT: FAIL" in out
    assert (
        json.loads(next(x for x in out.splitlines() if x.startswith("RESULT_JSON ")).split(" ", 1)[1])["result"]
        == "fail"
    )
