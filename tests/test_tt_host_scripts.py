"""The Tiny Tapeout host scripts fpgas-verify ships (designs/_host): starting the demo board's SDK, putting the
SDK's main.py back, and the test wrapper leaving that main.py alone (issue #117)."""

import hashlib
import importlib.util
import pathlib
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
restore = _load("tt_restore_sdk_main")
wrapper = _load("tt_test_wrapper")

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
    assert "not the SDK's main.py" in reason and "tt_restore_sdk_main.py" in reason


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
    assert "SDK_START: FAIL: cannot open" in capsys.readouterr().out


def test_the_release_is_read_without_its_v():
    assert restore.release("3.1.0\r\n") == "3.1.0" and restore.release("v3.1.0\n") == "3.1.0"
    assert restore.release("") is None


def test_only_the_recorded_main_py_of_the_boards_release_is_accepted(tmp_path, monkeypatch):
    good = tmp_path / "main.py"
    good.write_bytes(b"print('BOOT: Tiny Tapeout SDK')\n")
    monkeypatch.setitem(restore.MAIN_PY_SHA256, "9.9.9", hashlib.sha256(good.read_bytes()).hexdigest())
    assert restore.check_file(good, "9.9.9") is None
    other = tmp_path / "other.py"
    other.write_bytes(b"print('TT FPGA board ready')\n")
    assert "is not SDK 9.9.9's main.py" in restore.check_file(other, "9.9.9")
    assert "no main.py is recorded for SDK release '1.2.2'" in restore.check_file(good, "1.2.2")


def test_a_wrong_file_is_refused_before_anything_is_written(tmp_path, monkeypatch, capsys):
    calls = []

    def mpremote(port, *args, timeout=60):
        calls.append(args)
        return 0, "3.1.0\n", ""

    monkeypatch.setattr(restore, "mpremote", mpremote)
    wrong = tmp_path / "main.py"
    wrong.write_text("print('TT FPGA board ready')\n")
    assert restore.main(["/dev/ttyACM0", str(wrong)]) == 1
    assert "RESTORE: FAIL" in capsys.readouterr().out
    assert not any(a[0] == "cp" for a in calls)  # nothing was copied to the board


def test_uploading_a_bitstream_leaves_the_boards_main_py_alone(monkeypatch):
    """The wrapper used to overwrite main.py with a no-op after every upload, so the SDK never started again."""
    commands = []
    monkeypatch.setattr(wrapper, "reset_rp2350", lambda port: None)
    monkeypatch.setattr(wrapper.subprocess, "call", lambda argv, **kw: commands.append(argv) or 0)
    monkeypatch.setattr(wrapper.subprocess, "run", lambda argv, **kw: commands.append(argv))
    assert wrapper.upload_bitstream("/dev/ttyACM0", "design.bin") is True
    assert commands and not any("main.py" in " ".join(map(str, argv)) for argv in commands)
    assert [argv[3] for argv in commands] == ["exec", "cp"]  # make /bitstreams, copy the bitstream: nothing else
