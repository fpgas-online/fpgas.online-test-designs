"""Unit tests for designs/uart/host/test_uart.py: against a fake BIOS (the Arty, NeTV2 and Acorn designs) and
against the iCE40 firmware itself, run on tests/rv32_fakes.py (the Fomu and TT FPGA designs)."""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "_host"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "uart" / "host"))

import bios_console
import ice40_firmware
import test_uart

from .bios_fakes import PROMPT, FakeBios, ddr_replies, lines
from .rv32_fakes import FirmwarePort, Machine

UART_BASE = 0xF0001800
NETV2 = {"ident": lines("Ident: fpgas-online UART Test SoC -- NeTV2 2026-10-01 11:00:01")}


def run(port, board):
    return test_uart.run_uart_test(bios_console.BiosConsole(port, clock=port.clock), board, attach_timeout=10)


def firmware_port(ident, stale=False):
    return FirmwarePort(Machine(ice40_firmware.generate_uart_firmware(UART_BASE, ident), UART_BASE), stale)


def result_json(out):
    last = out.strip().splitlines()[-1]
    assert last.startswith("RESULT_JSON ")
    return json.loads(last[len("RESULT_JSON ") :])


# -- the BIOS designs ---------------------------------------------------------------------------------------


def test_a_bios_design_passes_on_what_it_was_asked():
    fake = FakeBios(NETV2)
    found = run(fake, "netv2")
    assert found["result"] == "pass"
    assert found["ident"] == "fpgas-online UART Test SoC -- NeTV2 2026-10-01 11:00:01"
    assert (found["echo_bytes"], found["echo_errors"]) == (95, 0)
    assert found["commands"] == ["ident", "echo"]
    # The 95 bytes were typed as two lines, each ended so the prompt came back.
    typed = [c for c in fake.commands if c not in ("", "ident")]
    assert "".join(typed).encode() == test_uart.ECHO_TEST_BYTES
    assert all(len(line) <= test_uart.LINE_BYTES for line in typed)


def test_the_boot_log_is_not_what_is_judged():
    # A finished boot log of the UART design is waiting in the port, but another design answers now.
    stale = lines("fpgas-online UART Test SoC -- NeTV2", "--=============== Console ================--") + PROMPT
    found = run(FakeBios(ddr_replies("netv2"), stale=stale), "netv2")
    assert found["result"] == "fail"
    assert "DDR Test SoC" in found["reason"]


def test_the_design_for_another_board_is_not_accepted():
    found = run(FakeBios(NETV2), "arty")
    assert found["result"] == "fail"
    assert "Arty A7" in found["reason"]


def test_a_design_with_no_ident_fails():
    found = run(FakeBios(), "netv2")
    assert found["result"] == "fail"
    assert "None" in found["reason"]


def test_nothing_on_the_uart_fails_and_says_so():
    found = run(FakeBios(silent=True), "netv2")
    assert found["result"] == "fail"
    assert "no BIOS prompt" in found["reason"]
    assert "echo_bytes" not in found


def test_a_byte_that_comes_back_changed_fails_and_is_named():
    class BitFlip(FakeBios):
        def write(self, data):
            before = len(self.rx)
            n = FakeBios.write(self, data)
            if bytes(data) == b"A":
                self.rx[before] = ord("C")  # bit 1 stuck high on the way back
            return n

    found = run(BitFlip(NETV2), "netv2")
    assert found["result"] == "fail"
    assert found["echo_errors"] == 1
    assert "0x41 came back as 0x43" in found["reason"]


def test_a_byte_that_does_not_come_back_fails_and_is_named():
    class Drop(FakeBios):
        def write(self, data):
            before = len(self.rx)
            n = FakeBios.write(self, data)
            if bytes(data) == b"z":
                del self.rx[before:]
            return n

    found = run(Drop(NETV2), "netv2")
    assert found["result"] == "fail"
    assert found["echo_errors"] == 1
    assert "0x7A came back as nothing" in found["reason"]


def test_a_design_that_stops_answering_after_the_echo_fails():
    class Hangs(FakeBios):
        def write(self, data):
            if self.commands[-1:] == ["ident"] and bytes(data) == b"\n":
                return len(data)  # the line is never ended: no prompt
            return FakeBios.write(self, data)

    found = run(Hangs(NETV2), "netv2")
    assert found["result"] == "fail"
    assert "did not return to the prompt" in found["reason"]


# -- the iCE40 firmware -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "board, ident",
    [("fomu", "fpgas-online UART Test SoC -- Fomu EVT"), ("tt", "fpgas-online UART Test SoC -- TT FPGA")],
)
def test_the_ice40_firmware_passes_on_a_port_opened_after_it_started(board, ident):
    found = run(firmware_port(ident), board)
    assert found["result"] == "pass"
    assert found["ident"] == ident
    assert (found["echo_bytes"], found["echo_errors"]) == (95, 0)


def test_the_ice40_firmware_passes_with_its_start_output_waiting_in_the_port():
    ident = "fpgas-online UART Test SoC -- Fomu EVT"
    assert run(firmware_port(ident, stale=True), "fomu")["result"] == "pass"


def test_the_ice40_firmware_of_another_board_is_not_accepted():
    found = run(firmware_port("fpgas-online UART Test SoC -- TT FPGA"), "fomu")
    assert found["result"] == "fail"
    assert "Fomu EVT" in found["reason"]


def test_a_design_that_only_echoes_fails():
    # The firmware before it answered a newline, or a loopback plug: every byte comes back, nothing answers.
    class Echo(FakeBios):
        def write(self, data):
            self.rx += data
            return len(data)

    found = run(Echo(), "fomu")
    assert found["result"] == "fail"
    assert "nothing on the UART answers a newline" in found["reason"]


# -- main ---------------------------------------------------------------------------------------------------


def test_main_ends_with_the_result_line_and_exits_by_the_result(capsys, monkeypatch):
    fake = FakeBios(NETV2)
    monkeypatch.setattr(bios_console, "open_port", lambda port, baud: fake)
    monkeypatch.setattr(bios_console.time, "monotonic", lambda: fake.now)
    assert test_uart.main(["--port", "/dev/ttyAMA0", "--board", "netv2", "--skip-banner"]) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out
    found = result_json(out)
    assert found["test"] == "uart" and found["board"] == "netv2" and found["result"] == "pass"
    assert found["echo_errors"] == 0


def test_main_fails_on_another_design(capsys, monkeypatch):
    fake = FakeBios(ddr_replies("netv2"))
    monkeypatch.setattr(bios_console, "open_port", lambda port, baud: fake)
    monkeypatch.setattr(bios_console.time, "monotonic", lambda: fake.now)
    assert test_uart.main(["--port", "/dev/ttyAMA0", "--board", "netv2"]) == 1
    out = capsys.readouterr().out
    assert "RESULT: FAIL" in out
    assert result_json(out)["result"] == "fail"


def test_a_port_that_cannot_be_opened_still_ends_with_a_result(capsys, monkeypatch):
    def opener(port, baud):
        raise OSError(2, "No such file or directory", port)

    monkeypatch.setattr(bios_console, "open_port", opener)
    assert test_uart.main(["--port", "/dev/ttyUSB9", "--board", "arty"]) == 1
    found = result_json(capsys.readouterr().out)
    assert found["result"] == "fail"
    assert "/dev/ttyUSB9" in found["reason"]


def test_a_port_that_dies_before_the_prompt_still_ends_with_a_result(capsys, monkeypatch):
    fake = FakeBios(NETV2)

    def dead_read(size=1):
        raise OSError(5, "Input/output error")

    fake.read = dead_read
    monkeypatch.setattr(bios_console, "open_port", lambda port, baud: fake)
    assert test_uart.main(["--port", "/dev/ttyUSB1", "--board", "arty"]) == 1
    found = result_json(capsys.readouterr().out)
    assert found["result"] == "fail"
    assert "Input/output error" in found["reason"]
