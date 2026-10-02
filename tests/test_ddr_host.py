"""Unit tests for designs/ddr-memory/host/test_ddr.py against a fake BIOS (tests/bios_fakes.py).

The replies are the ones the Welland boards gave on 2026-10-02: the passing ones from the installed DDR test
designs, the failing ones from a NeTV2 DDR image built before #57 (no read-leveling window, Memtest KO). The
aliasing is the NeTV2's from before #91: a design built for 1 GiB on a board with 512 MiB.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "_host"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "ddr-memory" / "host"))

import bios_console
import test_ddr

from .bios_fakes import MIB, PROMPT, FakeBios, FakeDdrBios, ddr_replies, lines, memtest

ADDRESS_TEST = ["mem_write", "flush_cpu_dcache", "flush_l2_cache", "mem_read"]
COMMANDS = ["ident", "mem_list", "sdram_init", "sdram_test", *ADDRESS_TEST]


def run(fake, board="netv2"):
    return test_ddr.run_ddr_test(bios_console.BiosConsole(fake, clock=fake.clock), board, attach_timeout=10)


def result_json(out):
    payload = [line for line in out.splitlines() if line.startswith("RESULT_JSON ")]
    assert len(payload) == 1
    return json.loads(payload[0].split(" ", 1)[1])


# -- a working board ------------------------------------------------------------------------------------------


def test_a_working_netv2_passes_on_a_run_it_asked_for():
    fake = FakeDdrBios("netv2")
    found = run(fake)
    assert found["result"] == "pass"
    assert found["commands"] == COMMANDS
    assert fake.commands[:5] == ["", "ident", "mem_list", "sdram_init", "sdram_test"]
    assert found["ident"] == "fpgas-online DDR Test SoC -- NeTV2 2026-10-01 11:00:01"
    assert found["leveling"] == {"m0": "b01 14+-14", "m1": "b01 14+-14", "m2": "b01 14+-14", "m3": "b01 14+-14"}
    assert found["bytes_tested"] == 16 * MIB
    assert found["errors"] == 0
    assert (found["write_mib_per_s"], found["read_mib_per_s"]) == (27.2, 30.9)
    assert (found["main_ram_base"], found["main_ram_bytes"]) == (0x40000000, 512 * MIB)
    # Offset 0, then every address bit from 4 bytes to half the DRAM: bits 2..28 of 512 MiB.
    assert found["address_bits_tested"] == 27


def test_a_working_arty_passes():
    found = run(FakeDdrBios("arty"), "arty")
    assert found["result"] == "pass"
    assert sorted(found["leveling"]) == ["m0", "m1"]
    assert found["bytes_tested"] == 8 * MIB
    assert found["main_ram_bytes"] == 256 * MIB


def test_both_acorn_memories_are_accepted_for_the_acorn():
    assert run(FakeDdrBios("acorn"), "acorn")["result"] == "pass"  # CLE-215+: 1 GiB
    assert run(FakeDdrBios("acorn", declared=512 * MIB), "acorn")["result"] == "pass"  # CLE-101


def test_a_port_that_was_opened_after_the_boot_log_passes():
    # The NeTV2's ttyAMA0: nothing is waiting, and nothing of the boot is ever seen.
    assert run(FakeDdrBios("netv2", stale=b""))["result"] == "pass"


# -- what must not pass ---------------------------------------------------------------------------------------


def test_the_boot_log_is_not_what_is_judged():
    # A finished boot log saying Memtest OK is waiting in the port, but the memory fails when asked now.
    stale = lines("Switching SDRAM to software control.", "Memtest at 0x40000000 (2.0MiB)...", "Memtest OK") + PROMPT
    assert run(FakeDdrBios("netv2", good=False, stale=stale))["result"] == "fail"


def test_no_leveling_window_and_memtest_ko_fail_with_the_error_counts():
    found = run(FakeDdrBios("netv2", good=False))
    assert found["result"] == "fail"
    assert "read leveling found no window on m0, m1, m2, m3" in found["reason"]
    assert "sdram_init: Memtest KO" in found["reason"]
    assert "sdram_test: Memtest KO" in found["reason"]
    assert "data errors 4194304/4194304" in found["reason"]
    assert found["errors"] == 256 + 4194304
    assert found["leveling"] == {"m0": None, "m1": None, "m2": None, "m3": None}
    assert "write_mib_per_s" not in found


def test_a_memory_that_fails_only_the_larger_test_fails():
    fake = FakeDdrBios("netv2", replies={"sdram_test": memtest("16.0MiB", ok=False, words=4194304)})
    found = run(fake)
    assert found["result"] == "fail"
    assert found["reason"].startswith("sdram_test: Memtest KO")


def test_a_design_built_for_more_memory_than_the_board_has_fails_twice_over():
    # The NeTV2 before #91: MT41K256M16 makes 1 GiB, the board has 512 MiB.
    found = run(FakeDdrBios("netv2", declared=1024 * MIB, real=512 * MIB))
    assert found["result"] == "fail"
    assert "the design has 1024 MiB of DRAM; the NeTV2 has 512 MiB" in found["reason"]
    assert "0x40000000 holds the word written to 0x60000000" in found["reason"]


def test_a_design_built_for_less_memory_than_the_board_has_fails():
    found = run(FakeDdrBios("netv2", declared=256 * MIB, real=512 * MIB))
    assert found["result"] == "fail"
    assert "the design has 256 MiB of DRAM; the NeTV2 has 512 MiB" in found["reason"]
    assert "holds the word" not in found["reason"]


def test_a_board_with_half_its_memory_fails_the_address_test():
    # The design is right for the board, but an address bit does not reach the chip.
    found = run(FakeDdrBios("arty", real=128 * MIB), "arty")
    assert found["result"] == "fail"
    assert "address test: 0x40000000 holds the word written to 0x48000000" in found["reason"]


def test_a_stuck_address_line_fails_the_address_test():
    found = run(FakeDdrBios("arty", stuck_bit=12), "arty")
    assert found["result"] == "fail"
    assert "address test: 0x40000000 holds the word written to 0x40001000" in found["reason"]


def test_an_address_line_stuck_high_fails_the_address_test():
    # Offset 0 lands on the cell of offset 2**20, which is written later.
    found = run(FakeDdrBios("arty", stuck_high_bit=20), "arty")
    assert found["result"] == "fail"
    assert "address test: 0x40000000 holds the word written to 0x40100000" in found["reason"]


def test_two_address_lines_shorted_fail_the_address_test():
    found = run(FakeDdrBios("arty", short=(14, 21)), "arty")
    assert found["result"] == "fail"
    assert "address test: 0x40004000 holds the word written to 0x40200000" in found["reason"]


def test_the_address_test_reads_the_dram_not_the_caches():
    # Without the flushes the words would come back from the CPU's data cache or the L2 cache, whatever
    # the DRAM did with them: the fake's caches answer a read until they are flushed.
    fake = FakeDdrBios("arty", real=128 * MIB)
    run(fake, "arty")
    writes = [i for i, c in enumerate(fake.commands) if c.startswith("mem_write")]
    reads = [i for i, c in enumerate(fake.commands) if c.startswith("mem_read")]
    dcache, l2 = fake.commands.index("flush_cpu_dcache"), fake.commands.index("flush_l2_cache")
    assert max(writes) < dcache < l2 < min(reads)


def test_a_byte_lane_missing_from_the_leveling_fails():
    fake = FakeDdrBios("netv2", replies={"sdram_init": ddr_replies("arty")["sdram_init"]})  # two lanes
    found = run(fake)
    assert found["result"] == "fail"
    assert "read leveling reported 2 byte lanes; the NeTV2 has 4" in found["reason"]


def test_a_memtest_that_covered_nothing_fails():
    found = run(FakeDdrBios("netv2", replies={"sdram_test": memtest("0B")}))
    assert found["result"] == "fail"
    assert "sdram_test: Memtest OK over 0 bytes" in found["reason"]


def test_a_memtest_smaller_than_the_design_s_share_fails():
    found = run(FakeDdrBios("netv2", replies={"sdram_test": memtest("8.0MiB")}))  # 512 MiB: 16 MiB is 1/32
    assert found["result"] == "fail"
    assert "sdram_test: Memtest OK over 8 MiB, less than 1/32 of the DRAM (16 MiB)" in found["reason"]


# -- the console ----------------------------------------------------------------------------------------------


def test_nothing_answering_is_reported_as_no_console():
    found = run(FakeBios(silent=True))
    assert found["result"] == "fail"
    assert "no BIOS prompt" in found["reason"]
    assert "ident" not in found


def test_another_design_is_not_tested_as_if_it_were_the_ddr_design():
    ident = lines("Ident: fpgas-online UART Test SoC -- NeTV2 2026-10-01 11:00:01")
    fake = FakeDdrBios("netv2", replies={"ident": ident})
    found = run(fake)
    assert found["result"] == "fail"
    assert "UART Test SoC" in found["reason"]
    assert "sdram_init" not in fake.commands


def test_another_board_is_not_accepted():
    found = run(FakeDdrBios("arty"), "netv2")
    assert found["result"] == "fail"
    assert "Arty A7" in found["reason"]


def test_a_command_that_hangs_fails_and_says_which(monkeypatch):
    fake = FakeDdrBios("netv2")
    write = fake.write

    def hang_in_sdram_init(data):
        n = write(data)
        if fake.commands and fake.commands[-1] == "sdram_init":
            del fake.rx[-len(PROMPT) :]
        return n

    fake.write = hang_in_sdram_init
    monkeypatch.setitem(test_ddr.COMMAND_TIMEOUT_S, "sdram_init", 5)
    found = run(fake)
    assert found["result"] == "fail"
    assert "`sdram_init` did not return to the prompt" in found["reason"]


def test_parse_size():
    assert test_ddr.parse_size("2.0MiB") == 2 * MIB
    assert test_ddr.parse_size("8.0KiB") == 8 * 1024
    assert test_ddr.parse_size("1.0GiB") == 1024**3
    assert test_ddr.parse_size("0B") == 0


def test_parse_word_reads_the_dump_little_endian():
    dump = ["Memory dump:", "0x40000000  78 56 34 12                                      xV4."]
    assert test_ddr.parse_word(dump) == 0x12345678
    assert test_ddr.parse_word(["Memory dump:"]) is None


# -- main() ---------------------------------------------------------------------------------------------------


def test_main_prints_one_result_json_line_and_exits_by_the_result(capsys, monkeypatch):
    fakes = []

    def opener(port, baud, timeout):
        fakes.append(FakeDdrBios("netv2", good=not fakes))
        return fakes[-1]

    monkeypatch.setattr(test_ddr, "open_port", opener)
    monkeypatch.setattr(test_ddr.time, "monotonic", lambda: fakes[-1].now)
    assert test_ddr.main(["--port", "/dev/ttyAMA0", "--board", "netv2"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out
    found = result_json(out)
    assert found["test"] == "ddr" and found["result"] == "pass" and found["board"] == "netv2"
    assert found["commands"] == COMMANDS

    assert test_ddr.main(["--port", "/dev/ttyAMA0", "--board", "netv2"]) == 1
    out = capsys.readouterr().out
    assert "RESULT: FAIL" in out
    assert result_json(out)["result"] == "fail"


def test_a_port_that_cannot_be_opened_still_ends_with_a_result(capsys, monkeypatch):
    def opener(port, baud, timeout):
        raise OSError(2, "No such file or directory", port)

    monkeypatch.setattr(test_ddr, "open_port", opener)
    assert test_ddr.main(["--port", "/dev/ttyUSB9", "--board", "arty"]) == 1
    found = result_json(capsys.readouterr().out)
    assert found["result"] == "fail"
    assert "/dev/ttyUSB9" in found["reason"]


def test_a_port_that_dies_mid_test_still_ends_with_a_result(capsys, monkeypatch):
    fake = FakeDdrBios("arty")
    read = fake.read

    def dying_read(size=1):
        if "sdram_init" in fake.commands:
            raise OSError(5, "Input/output error")
        return read(size)

    fake.read = dying_read
    monkeypatch.setattr(test_ddr, "open_port", lambda port, baud, timeout: fake)
    monkeypatch.setattr(test_ddr.time, "monotonic", lambda: fake.now)
    assert test_ddr.main(["--port", "/dev/ttyUSB1", "--board", "arty"]) == 1
    found = result_json(capsys.readouterr().out)
    assert found["result"] == "fail"
    assert "Input/output error" in found["reason"]
    assert found["commands"] == ["ident", "mem_list", "sdram_init"]


def test_a_port_that_dies_before_the_prompt_still_ends_with_a_result(capsys, monkeypatch):
    fake = FakeDdrBios("arty")

    def dead_read(size=1):
        raise OSError(5, "Input/output error")

    fake.read = dead_read
    monkeypatch.setattr(test_ddr, "open_port", lambda port, baud, timeout: fake)
    assert test_ddr.main(["--port", "/dev/ttyUSB1", "--board", "arty"]) == 1
    found = result_json(capsys.readouterr().out)
    assert found["result"] == "fail"
    assert "Input/output error" in found["reason"]


def test_a_port_that_dies_on_the_first_command_still_ends_with_a_result(capsys, monkeypatch):
    fake = FakeBios(ddr_replies("arty"))
    read = fake.read

    def dying_read(size=1):
        if fake.commands[-1:] == ["ident"]:
            raise OSError(5, "Input/output error")
        return read(size)

    fake.read = dying_read
    monkeypatch.setattr(test_ddr, "open_port", lambda port, baud, timeout: fake)
    monkeypatch.setattr(test_ddr.time, "monotonic", lambda: fake.now)
    assert test_ddr.main(["--port", "/dev/ttyUSB1", "--board", "arty"]) == 1
    found = result_json(capsys.readouterr().out)
    assert found["result"] == "fail"
    assert "during `ident`" in found["reason"]
