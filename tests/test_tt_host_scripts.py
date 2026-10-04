"""The Tiny Tapeout host scripts fpgas-verify ships (designs/_host): starting the demo board's SDK (issue #117),
and loading the FPGA without writing any file to the demo board."""

import importlib.util
import pathlib
import re
import sys

import pytest

_HOST = pathlib.Path(__file__).resolve().parent.parent / "designs" / "_host"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HOST / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


sdk_start = _load("tt_sdk_start")
program = _load("tt_fpga_program")
wrapper = _load("tt_test_wrapper")
_load("tt_pmod_wrapper")

# What a demo board prints on a soft reset from the friendly REPL: with the SDK's main.py (its first and last
# boot lines, tt-micropython-firmware src/main.py), and with the no-op the test wrapper used to install.
SDK_BOOT = (
    ">>> \r\nMPY: soft reboot\r\nBOOT: Tiny Tapeout SDK\r\nDetected TTDBv3 [3.2] demoboard \r\n"
    "tt.sdk_revision=baaf0a2758b475d6e099b8ef65dbd1b5667ea0aa\r\ntt.sdk_version=3.1.0\r\n"
    "MicroPython b006887db6 on 2026-08-11; TinyTapeout RP2350B Core with RP2350\r\n"
    'Type "help()" for more information.\r\n>>> '
)
NO_OP_BOOT = (
    ">>> \r\nMPY: soft reboot\r\nTT FPGA board ready\r\n"
    "MicroPython b006887db6 on 2026-08-11; TinyTapeout RP2350B Core with RP2350\r\n"
    'Type "help()" for more information.\r\n>>> '
)


def test_the_sdks_last_boot_line_means_it_started():
    started, reason = sdk_start.verdict(SDK_BOOT)
    assert started is True and reason == "the SDK started: tt.sdk_version=3.1.0"


def test_a_main_py_that_reaches_the_prompt_without_the_sdk_did_not_start_it():
    started, reason = sdk_start.verdict(NO_OP_BOOT)
    assert started is False
    assert "it is not the SDK's" in reason and "docs/hardware/tt-fpga.md" in reason


def test_the_sdks_main_py_raising_is_said_as_that_not_as_a_wrong_file():
    text = (
        ">>> \r\nMPY: soft reboot\r\nBOOT: Tiny Tapeout SDK\r\nTraceback (most recent call last):\r\n"
        '  File "main.py", line 96, in <module>\r\n  File "main.py", line 58, in startup\r\n'
        "OSError: [Errno 5] EIO\r\nMicroPython b006887db6 on 2026-08-11; TinyTapeout RP2350B Core with RP2350\r\n"
        'Type "help()" for more information.\r\n>>> '
    )
    assert sdk_start.verdict(text) == (False, "the board's main.py raised: OSError: [Errno 5] EIO")


def test_the_sdks_main_py_reaching_the_prompt_without_its_last_line_did_not_finish():
    text = '>>> \r\nMPY: soft reboot\r\nBOOT: Tiny Tapeout SDK\r\nType "help()" for more information.\r\n>>> '
    started, reason = sdk_start.verdict(text)
    assert started is False and reason == "the SDK's main.py ran to the prompt without finishing its start-up"


def test_a_prompt_inside_the_boards_output_is_not_the_end():
    text = ">>> \r\nMPY: soft reboot\r\nBOOT: Tiny Tapeout SDK\r\ntry >>> tt.shuttle at the prompt\r\n"
    assert sdk_start.verdict(text) == (None, "the SDK is still starting")


def test_the_last_boot_line_is_not_judged_while_it_is_still_arriving():
    text = ">>> \r\nMPY: soft reboot\r\nBOOT: Tiny Tapeout SDK\r\ntt.sdk_version=3.1"
    assert sdk_start.verdict(text) == (None, "the SDK is still starting")
    assert sdk_start.verdict(text + ".0\r\n") == (True, "the SDK started: tt.sdk_version=3.1.0")


@pytest.mark.parametrize("text, why", [
    ("", "the board has not soft-reset yet"),
    (">>> ", "the board has not soft-reset yet"),  # the prompt before the reset is not a verdict
    ("tt.sdk_version=3.1.0\r\n>>> ", "the board has not soft-reset yet"),  # an old boot's line does not count
    (">>> \r\nMPY: soft reboot\r\nBOOT: Tiny Tapeout SDK\r\n", "the SDK is still starting"),
])  # fmt: skip
def test_nothing_is_decided_before_the_board_has_reset_and_finished(text, why):
    assert sdk_start.verdict(text) == (None, why)


def test_only_what_follows_the_last_soft_reset_counts():
    assert sdk_start.verdict(SDK_BOOT + "\r\nMPY: soft reboot\r\nTT FPGA board ready\r\n>>> ")[0] is False


def test_a_port_that_cannot_be_opened_fails_and_says_so(tmp_path, capsys):
    assert sdk_start.main([str(tmp_path / "no-such-tty")]) == 1
    assert "SDK_START: FAIL: " in capsys.readouterr().out


# -- nothing is written to the demo board -------------------------------------------------------------------


def test_programming_is_one_mpremote_run_that_mounts_the_bitstreams_directory(tmp_path, monkeypatch):
    bitstream = tmp_path / "uart-test-tt-fpga" / "tt_fpga_platform.bin"
    bitstream.parent.mkdir()
    bitstream.write_bytes(b"\xff" * 16)
    calls = []

    def run_mpremote(port, args, timeout=60):
        calls.append((port, args, pathlib.Path(args[3]).read_text()))  # the script exists while mpremote runs
        return 0, "PROGRAM_OK\n", ""

    monkeypatch.setattr(program, "run_mpremote", run_mpremote)
    assert program.program("/dev/ttyACM0", str(bitstream)) == (0, "PROGRAM_OK\n", "")
    ((port, args, script),) = calls
    assert port == "/dev/ttyACM0" and args[:2] == ["mount", str(bitstream.parent)] and args[2] == "run"
    assert 'open("/remote/tt_fpga_platform.bin", "rb")' in script
    assert not pathlib.Path(args[3]).exists()  # the script on the Pi is temporary


@pytest.mark.parametrize("method, release", [("pio", False), ("pio", True), ("bitbang", False)])
def test_the_script_run_on_the_board_reads_the_mount_and_writes_no_file(method, release):
    script = program.board_script(method, "design.bin", release)
    assert 'open("/remote/design.bin", "rb")' in script and script.rstrip().endswith('os.chdir("/")')
    assert ("GPIO_RELEASED" in script) is release
    assert not BOARD_WRITE.search(script)


# What a script run on the board would use to change the board's filesystem.
BOARD_WRITE = re.compile(
    r"""open\([^)]*,\s*["'][^"']*[wax+]|\bos\.(mkdir|remove|rename|rmdir|unlink)\b|\.write_(text|bytes)\("""
)
# The mpremote subcommands that change it: none may appear as an argument in the host scripts.
MPREMOTE_WRITES = re.compile(r"""["'](cp|fs|mkdir|rm|rmdir|touch|edit|mip|romfs)["']""")


@pytest.mark.parametrize("name", ["tt_fpga_program", "tt_test_wrapper", "tt_pmod_wrapper", "tt_sdk_start"])
def test_no_tiny_tapeout_host_script_can_change_a_file_on_the_board(name):
    """Tim, 2026-10-05: no code modifies files on the Tiny Tapeout boards. The check used to copy each bitstream
    to /bitstreams/custom.bin and to overwrite main.py."""
    source = (_HOST / f"{name}.py").read_text()
    assert not MPREMOTE_WRITES.search(source), MPREMOTE_WRITES.search(source)
    board_scripts = [value for value in vars(_load(name)).values() if isinstance(value, str) and "machine" in value]
    for script in board_scripts:
        assert not BOARD_WRITE.search(script), BOARD_WRITE.search(script)
    assert "/bitstreams/custom.bin" not in source


def test_the_uart_wrapper_programs_through_the_programmer_and_then_only_bridges(monkeypatch):
    calls = []
    monkeypatch.setattr(wrapper, "reset_rp2350", lambda port: calls.append(("reset", port)))
    monkeypatch.setattr(
        wrapper.tt_fpga_program,
        "program",
        lambda port, path: calls.append(("program", port, path)) or (0, "PROGRAM_OK", ""),
    )
    assert wrapper.program_fpga("/dev/ttyACM0", "design.bin") is True
    assert calls == [("reset", "/dev/ttyACM0"), ("program", "/dev/ttyACM0", "design.bin")]
    assert "open(" not in wrapper.BRIDGE_SCRIPT and "UART(1, 115200" in wrapper.BRIDGE_SCRIPT


def test_a_failed_program_is_retried_once_after_a_usb_power_cycle(monkeypatch):
    answers = [(1, "", "could not enter raw repl"), (0, "PROGRAM_OK", "")]
    cycled = []
    monkeypatch.setattr(wrapper, "reset_rp2350", lambda port: None)
    monkeypatch.setattr(wrapper, "usb_power_cycle", lambda port: cycled.append(port))
    monkeypatch.setattr(wrapper.tt_fpga_program, "program", lambda port, path: answers.pop(0))
    assert wrapper.program_fpga("/dev/ttyACM0", "design.bin") is True and cycled == ["/dev/ttyACM0"]
    answers[:] = [(1, "", "x"), (1, "", "x")]
    assert wrapper.program_fpga("/dev/ttyACM0", "design.bin") is False
