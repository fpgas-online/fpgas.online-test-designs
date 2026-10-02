"""Unit tests for designs/spi-flash-id/host/test_spiflash.py against the SPI flash firmware itself, run on
tests/rv32_fakes.py with a bit-banged flash behind it."""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "_host"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "_shared"))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "spi-flash-id" / "host"))

import bios_console
import ice40_firmware
import test_spiflash

from .bios_fakes import FakeBios, ddr_replies
from .rv32_fakes import FirmwarePort, Machine, SpiFlash

UART_BASE = 0xF0001800
SPI_BASE = 0xF0002000
AT25SF161 = (0x1F, 0x86, 0x01)
W25Q128 = (0xEF, 0x40, 0x18)
IDENT = {
    "fomu": "fpgas-online SPI Flash Test SoC -- Fomu EVT",
    "netv2": "fpgas-online SPI Flash Test SoC -- NeTV2",
    "arty": "fpgas-online SPI Flash Test SoC -- Arty A7",
}


def port(board, jedec, stale=False):
    rom = ice40_firmware.generate_spiflash_firmware(UART_BASE, SPI_BASE, IDENT[board])
    return FirmwarePort(Machine(rom, UART_BASE, SPI_BASE, SpiFlash(jedec)), stale)


def run(fake, board, expected=None):
    console = bios_console.BiosConsole(fake, clock=fake.clock)
    return test_spiflash.run_spiflash_test(console, board, expected, attach_timeout=10)


def result_json(out):
    last = out.strip().splitlines()[-1]
    assert last.startswith("RESULT_JSON ")
    return json.loads(last[len("RESULT_JSON ") :])


def test_a_flash_read_on_a_port_opened_after_the_design_started_passes():
    fake = port("netv2", W25Q128)
    selects = fake.machine.flash.selects
    found = run(fake, "netv2")
    assert found["result"] == "pass"
    assert found["ident"] == IDENT["netv2"]
    assert found["rdid"] == "ef4018"
    assert found["manufacturer"] == "Winbond"
    assert found["capacity_bytes"] == 16 * 1024 * 1024
    assert found["commands"] == ["read", "read"]
    # The flash was asked again for the attach and for each reading: nothing printed at start was used.
    assert fake.machine.flash.selects == selects + 3


def test_the_fomu_s_known_flash_passes_and_has_no_capacity_claimed():
    found = run(port("fomu", AT25SF161), "fomu")
    assert found["result"] == "pass"
    assert found["rdid"] == "1f8601"
    assert "capacity_bytes" not in found  # Adesto's third byte is not a log2 size


def test_the_start_output_is_not_what_is_judged():
    # The reading printed at start is waiting in the port and was good; the flash does not answer now.
    fake = port("netv2", W25Q128, stale=True)
    fake.machine.flash.jedec = bytes((0xFF, 0xFF, 0xFF))
    found = run(fake, "netv2")
    assert found["result"] == "fail"
    assert "ffffff: no flash answered" in found["reason"]


@pytest.mark.parametrize("jedec, rdid", [((0x00, 0x00, 0x00), "000000"), ((0xFF, 0xFF, 0xFF), "ffffff")])
def test_no_flash_fails(jedec, rdid):
    found = run(port("arty", jedec), "arty")
    assert found["result"] == "fail"
    assert f"{rdid}: no flash answered" in found["reason"]
    assert "the firmware's verdict is FAIL" in found["reason"]


def test_another_flash_than_the_board_s_fails():
    found = run(port("fomu", W25Q128), "fomu")
    assert found["result"] == "fail"
    assert "ef4018, not the 1f8601 expected for the Fomu EVT" in found["reason"]


def test_an_expected_id_given_on_the_command_line_is_checked():
    assert run(port("netv2", W25Q128), "netv2", expected=(0xEF, 0x40, 0x18))["result"] == "pass"
    found = run(port("netv2", W25Q128), "netv2", expected=(0x20, 0xBA, 0x18))
    assert found["result"] == "fail"
    assert "not the 20ba18 expected" in found["reason"]


def test_two_readings_that_differ_fail():
    fake = port("netv2", W25Q128)
    write = fake.write
    asked = []

    def flaky_write(data):
        asked.append(data)
        if len(asked) == 3:  # the attach, the first reading, then this one
            fake.machine.flash.jedec = bytes((0xEF, 0x40, 0x10))
        return write(data)

    fake.write = flaky_write
    found = run(fake, "netv2")
    assert found["result"] == "fail"
    assert "the ID read again is ef4010, not ef4018" in found["reason"]


def test_the_design_for_another_board_is_not_accepted():
    found = run(port("arty", W25Q128), "netv2")
    assert found["result"] == "fail"
    assert "not the SPI Flash Test SoC for the NeTV2" in found["reason"]


def test_another_design_is_not_read_as_the_flash_test():
    found = run(FakeBios(ddr_replies("netv2")), "netv2")
    assert found["result"] == "fail"
    assert "None" in found["reason"]


def test_firmware_that_only_prints_at_start_fails_and_says_so():
    # The firmware before it answered a newline: its output is in the port, and nothing answers.
    stale = b"JEDEC_ID: 0xEF 0x40 0x18\r\nSPI_FLASH_TEST: PASS\r\nTest Complete\r\n"
    found = run(FakeBios(stale=stale, silent=True), "netv2")
    assert found["result"] == "fail"
    assert "nothing on the UART answers a newline" in found["reason"]
    assert "rdid" not in found


def test_main_ends_with_the_result_line_and_exits_by_the_result(capsys, monkeypatch):
    fake = port("netv2", W25Q128)
    monkeypatch.setattr(bios_console, "open_port", lambda port, baud: fake)
    monkeypatch.setattr(bios_console.time, "monotonic", lambda: fake.now)
    argv = ["--port", "/dev/ttyAMA0", "--board", "netv2", "--timeout", "180", "--expected-jedec", "EF4018"]
    assert test_spiflash.main(argv) == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out
    found = result_json(out)
    assert found["test"] == "spiflash" and found["result"] == "pass" and found["rdid"] == "ef4018"


def test_a_malformed_expected_id_is_a_usage_error(capsys):
    assert test_spiflash.main(["--port", "/dev/ttyAMA0", "--expected-jedec", "EF40"]) == 2


def test_a_port_that_cannot_be_opened_still_ends_with_a_result(capsys, monkeypatch):
    def opener(port, baud):
        raise OSError(2, "No such file or directory", port)

    monkeypatch.setattr(bios_console, "open_port", opener)
    assert test_spiflash.main(["--port", "/dev/ttyUSB9", "--board", "arty"]) == 1
    found = result_json(capsys.readouterr().out)
    assert found["result"] == "fail"
    assert "/dev/ttyUSB9" in found["reason"]
