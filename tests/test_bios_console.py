"""Unit tests for designs/_host/bios_console.py: attaching to a LiteX BIOS and running commands on it."""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "designs" / "_host"))

import bios_console

from .bios_fakes import PROMPT, FakeBios, lines

IDENT = "fpgas-online DDR Test SoC -- NeTV2 2026-10-01 11:00:01"
REPLIES = {"ident": lines("Ident: " + IDENT), "mem_list": lines("Available memory regions:", "ROM  0x0 0x20000 ")}


def console(fake):
    return bios_console.BiosConsole(fake, clock=fake.clock)


def test_strip_ansi_takes_the_colour_out_of_the_prompt():
    assert bios_console.strip_ansi(PROMPT.decode()) == "litex> "


def test_attach_finds_the_coloured_prompt():
    fake = FakeBios(REPLIES)
    console(fake).attach()
    assert fake.commands == [""]


def test_attach_discards_boot_output_that_was_waiting_in_the_port():
    # An FTDI UART (the Arty's) hands over the finished boot log when the port is opened.
    fake = FakeBios(REPLIES, stale=lines("Memtest at 0x40000000 (2.0MiB)...", "Memtest OK") + PROMPT)
    bios = console(fake)
    bios.attach()
    assert "Memtest OK" in bios.stale
    assert bios.command("ident") == ["Ident: " + IDENT]


def test_attach_waits_for_a_bios_that_is_still_booting():
    fake = FakeBios(REPLIES, deaf_newlines=3)
    console(fake).attach(timeout=30)
    assert fake.commands == [""]


def test_attach_gives_up_when_nothing_answers():
    fake = FakeBios(silent=True)
    with pytest.raises(bios_console.NoPrompt) as e:
        console(fake).attach(timeout=10)
    assert "no BIOS prompt" in str(e.value)
    assert 10 <= fake.now < 15


def test_attach_does_not_take_an_echo_for_a_prompt():
    # A design that only echoes (the iCE40 UART firmware, a loopback plug) is not a BIOS.
    class Echo(FakeBios):
        def write(self, data):
            self.rx += data
            return len(data)

    fake = Echo()
    with pytest.raises(bios_console.NoPrompt):
        console(fake).attach(timeout=5)


def test_command_returns_the_reply_without_echo_or_prompt():
    fake = FakeBios(REPLIES)
    bios = console(fake)
    bios.attach()
    assert bios.command("mem_list") == ["Available memory regions:", "ROM  0x0 0x20000"]


def test_command_keeps_the_last_state_of_a_progress_line():
    # memtest rewrites its progress line with bare carriage returns.
    progress = b"  Write: 0x40000000-0x40000000 0B   \r  Write: 0x40000000-0x40200000 2.0MiB   \r" + lines("")
    fake = FakeBios({"sdram_test": lines("Memtest at 0x40000000 (2.0MiB)...") + progress + lines("Memtest OK")})
    bios = console(fake)
    bios.attach()
    assert bios.command("sdram_test") == [
        "Memtest at 0x40000000 (2.0MiB)...",
        "Write: 0x40000000-0x40200000 2.0MiB",
        "Memtest OK",
    ]


def test_command_that_never_returns_to_the_prompt_times_out_with_what_it_printed():
    fake = FakeBios()
    bios = console(fake)
    bios.attach()
    fake.replies["sdram_init"] = lines("Initializing SDRAM @0x40000000...")
    fake_write = fake.write

    def write_without_prompt(data):
        n = fake_write(data)
        del fake.rx[-len(PROMPT) :]
        return n

    fake.write = write_without_prompt
    with pytest.raises(bios_console.NoPrompt) as e:
        bios.command("sdram_init", timeout=5)
    assert "sdram_init" in str(e.value)
    assert "Initializing SDRAM" in e.value.output


def test_ident_reads_the_identifier():
    fake = FakeBios(REPLIES)
    bios = console(fake)
    bios.attach()
    assert bios.ident() == IDENT


def test_ident_is_none_when_the_command_is_unknown():
    fake = FakeBios()
    bios = console(fake)
    bios.attach()
    assert bios.ident() is None


def test_result_json_is_one_parseable_line(capsys):
    bios_console.print_result_json({"test": "ddr", "result": "pass", "errors": 0})
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 1
    marker, _, payload = out[0].partition(" ")
    assert marker == "RESULT_JSON"
    assert json.loads(payload) == {"test": "ddr", "result": "pass", "errors": 0}


def test_a_prompt_that_arrives_a_byte_at_a_time_is_still_found():
    # A read can end inside the prompt's colour codes; the reply must come out the same.
    fake = FakeBios(REPLIES, chunk=1)
    bios = console(fake)
    bios.attach()
    assert bios.command("mem_list") == ["Available memory regions:", "ROM  0x0 0x20000"]
    assert bios.ident() == IDENT
