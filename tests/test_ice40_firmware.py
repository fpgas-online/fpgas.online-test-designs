"""designs/_shared/ice40_firmware.py, run on a small RV32I machine (tests/rv32_fakes.py).

The firmware has to answer when asked, not only once at start: a host that opens the UART after the design
is loaded has missed whatever was printed then.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "_shared"))

import ice40_firmware

from .rv32_fakes import Machine, SpiFlash

UART_BASE = 0xF0001800
SPI_BASE = 0xF0002000
UART_IDENT = "fpgas-online UART Test SoC -- Fomu EVT"
SPI_IDENT = "fpgas-online SPI Flash Test SoC -- Fomu EVT"
ROM_WORDS = 256  # the designs' integrated_rom_size is 1 KB
AT25SF161 = (0x1F, 0x86, 0x01)


def uart_machine():
    machine = Machine(ice40_firmware.generate_uart_firmware(UART_BASE, UART_IDENT), UART_BASE)
    return machine, machine.run()


@pytest.fixture(scope="module")
def spi_boot():
    """(the ROM, what a fresh start prints): the start waits 0x40000 turns, so it is run once for the module."""
    rom = ice40_firmware.generate_spiflash_firmware(UART_BASE, SPI_BASE, SPI_IDENT)
    machine = Machine(rom, UART_BASE, SPI_BASE, SpiFlash(AT25SF161))
    return rom, machine.run()


def spi_machine(rom, jedec):
    """A machine past its start, idle at the prompt."""
    machine = Machine(rom, UART_BASE, SPI_BASE, SpiFlash(jedec))
    machine.run()
    return machine


# -- UART ---------------------------------------------------------------------------------------------------


def test_both_firmwares_fit_the_rom():
    assert len(ice40_firmware.generate_uart_firmware(UART_BASE, UART_IDENT)) <= ROM_WORDS
    assert len(ice40_firmware.generate_spiflash_firmware(UART_BASE, SPI_BASE, SPI_IDENT)) <= ROM_WORDS


def test_uart_start_prints_the_banner_the_ident_and_the_prompt():
    _, boot = uart_machine()
    assert boot == f"\r\nLiteX custom firmware\r\nIdent: {UART_IDENT}\r\nlitex> "


def test_uart_echoes_every_printable_byte():
    machine, _ = uart_machine()
    printable = bytes(range(0x20, 0x7F))
    assert machine.send(printable) == printable.decode()


def test_uart_newline_is_answered_with_the_ident_and_the_prompt():
    machine, _ = uart_machine()
    assert machine.send(b"\n") == f"\nIdent: {UART_IDENT}\r\nlitex> "
    # And again, with something typed before it: it is not a one-off.
    assert machine.send(b"ident\n") == f"ident\nIdent: {UART_IDENT}\r\nlitex> "


def test_uart_keeps_echoing_after_it_answered():
    machine, _ = uart_machine()
    machine.send(b"\n")
    assert machine.send(b"abc") == "abc"


# -- SPI flash ----------------------------------------------------------------------------------------------

SPI_REPLY = f"Ident: {SPI_IDENT}\r\nJEDEC_ID: 0x1F 0x86 0x01\r\nSPI_FLASH_TEST: PASS\r\nTest Complete\r\nlitex> "


def test_spiflash_start_prints_the_id_and_ends_at_the_prompt(spi_boot):
    _, boot = spi_boot
    assert boot == "\r\nLiteX custom firmware\r\n" + SPI_REPLY


def test_spiflash_newline_reads_the_id_again(spi_boot):
    rom, _ = spi_boot
    machine = spi_machine(rom, AT25SF161)
    selects = machine.flash.selects
    assert machine.send(b"\n") == SPI_REPLY
    assert machine.flash.selects == selects + 1  # the flash was asked again: the answer is not a stored one


def test_spiflash_answers_with_what_the_flash_says_now(spi_boot):
    # The flash that answers the second time is another one: the firmware must not repeat its first reading.
    rom, _ = spi_boot
    machine = spi_machine(rom, AT25SF161)
    machine.flash.jedec = bytes((0xEF, 0x40, 0x18))
    assert "JEDEC_ID: 0xEF 0x40 0x18\r\nSPI_FLASH_TEST: PASS" in machine.send(b"\n")


@pytest.mark.parametrize("jedec", [(0x00, 0x00, 0x00), (0xFF, 0xFF, 0xFF)])
def test_spiflash_no_flash_is_a_fail(spi_boot, jedec):
    rom, _ = spi_boot
    machine = spi_machine(rom, jedec)
    reply = machine.send(b"\n")
    assert "JEDEC_ID: 0x{:02X} 0x{:02X} 0x{:02X}\r\nSPI_FLASH_TEST: FAIL\r\n".format(*jedec) in reply
    assert reply.endswith("Test Complete\r\nlitex> ")


def test_spiflash_ignores_bytes_that_are_not_a_newline(spi_boot):
    rom, _ = spi_boot
    machine = spi_machine(rom, AT25SF161)
    assert machine.send(b"ident") == ""
    assert machine.send(b"\n") == SPI_REPLY
