"""The Tiny Tapeout host scripts fpgas-verify ships (designs/_host): starting the demo board's SDK (issue #117),
and loading the FPGA without writing any file to the demo board."""

import ast
import fcntl
import importlib.util
import os
import pathlib
import re
import subprocess
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
main_py = _load("tt_main_py")

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


def test_a_port_another_process_holds_is_said_as_that(capsys):
    """pyserial and mpremote lock the port they have open; reading beside one would split the board's output."""
    theirs, name = os.openpty()
    held = os.open(os.ttyname(name), os.O_RDWR | os.O_NOCTTY)
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert sdk_start.main([os.ttyname(name), "--timeout", "1"]) == 1
    finally:
        for fd in (held, name, theirs):
            os.close(fd)
    assert "the port is held by another process" in capsys.readouterr().out


def test_a_soft_reset_in_the_raw_repl_is_said_as_that():
    """It runs no main.py, so waiting for the SDK would only end in the time limit."""
    text = ">\r\nMPY: soft reboot\r\nraw REPL; CTRL-B to exit\r\n>"
    assert sdk_start.verdict(text) == (False, "the board soft-reset in the raw REPL, which does not run main.py")


def test_a_prompt_that_ends_a_line_of_output_is_not_the_end():
    """A read can stop anywhere: only the prompt on a line of its own is the board back at the prompt."""
    text = ">>> \r\nMPY: soft reboot\r\nBOOT: Tiny Tapeout SDK\r\nat the prompt, type >>>"
    assert sdk_start.verdict(text) == (None, "the SDK is still starting")


# -- is the board's main.py still the SDK's own ---------------------------------------------------------------

SDK_SHA = main_py.MAIN_PY_SHA256["3.1.0"]


@pytest.mark.parametrize("release", ["3.1.0", "v3.1.0"])
def test_the_sdks_own_main_py_is_ok(release):
    out = f"SDK_RELEASE {release}\r\nMAIN_SHA256 {SDK_SHA}\r\n"
    assert main_py.verdict(0, out, "") == (True, "main.py is SDK 3.1.0's own")


def test_a_main_py_that_was_changed_is_said_with_its_hash():
    ok, why = main_py.verdict(0, "SDK_RELEASE 3.1.0\nMAIN_SHA256 " + "ab" * 32 + "\n", "")
    assert not ok and why.startswith("the board's main.py is not SDK 3.1.0's own (its SHA-256 is abab")
    assert "docs/hardware/tt-fpga.md" in why


def test_a_release_with_no_recorded_main_py_fails_and_says_what_to_do():
    ok, why = main_py.verdict(0, f"SDK_RELEASE 9.9.9\nMAIN_SHA256 {SDK_SHA}\n", "")
    assert not ok and why == (
        "no main.py is recorded for SDK release 9.9.9 (recorded: 3.1.0): add it to tt_main_py.py")  # fmt: skip


@pytest.mark.parametrize("rc, out, err, part", [
    (1, "", "Traceback (most recent call last):\nOSError: [Errno 2] ENOENT\n", "OSError: [Errno 2] ENOENT"),
    (0, "SDK_RELEASE 3.1.0\n", "", "could not be read (exit 0)"),  # half an answer is no answer
    (0, "", "", "it printed nothing"),
    (124, "", "mpremote did not finish within 60 s", "mpremote did not finish within 60 s"),
    (127, "", "mpremote is not installed", "mpremote is not installed"),
])  # fmt: skip
def test_a_board_that_could_not_be_read_fails_with_what_was_seen(rc, out, err, part):
    ok, why = main_py.verdict(rc, out, err)
    assert not ok and part in why


def test_reading_main_py_is_one_mpremote_exec_and_a_hang_or_no_mpremote_is_a_result(monkeypatch, capsys):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, f"SDK_RELEASE 3.1.0\nMAIN_SHA256 {SDK_SHA}\n", "")

    monkeypatch.setattr(main_py.subprocess, "run", run)
    assert main_py.main(["/dev/ttyACM0"]) == 0
    assert calls == [["mpremote", "connect", "/dev/ttyACM0", "exec", main_py.READ]]
    assert capsys.readouterr().out == "MAIN_PY: OK: main.py is SDK 3.1.0's own\n"

    def hangs(argv, timeout=None, **kw):
        raise subprocess.TimeoutExpired(argv, timeout)

    monkeypatch.setattr(main_py.subprocess, "run", hangs)
    assert main_py.read_board("/dev/ttyACM0", timeout=3) == (124, "", "mpremote did not finish within 3 s")

    def absent(argv, **kw):
        raise FileNotFoundError("mpremote")

    monkeypatch.setattr(main_py.subprocess, "run", absent)
    assert main_py.read_board("/dev/ttyACM0") == (127, "", "mpremote is not installed")
    assert main_py.main(["/dev/ttyACM0"]) == 1


# -- nothing is written to the demo board -------------------------------------------------------------------


def _bitstream(tmp_path):
    bitstream = tmp_path / "uart-test-tt-fpga" / "tt_fpga_platform.bin"
    bitstream.parent.mkdir()
    bitstream.write_bytes(b"\xff" * 16)
    (bitstream.parent / "beside.txt").write_text("not the board's business")
    return bitstream


def test_programming_is_one_mpremote_run_that_mounts_a_copy_of_the_bitstream_and_nothing_else(tmp_path, monkeypatch):
    bitstream = _bitstream(tmp_path)
    calls = []

    def run_mpremote(port, args, timeout=60):
        mounted = pathlib.Path(args[1])
        calls.append((port, args, pathlib.Path(args[3]).read_text(), sorted(f.name for f in mounted.iterdir()),
                      (mounted / "design.bin").read_bytes(), timeout))  # fmt: skip
        return 0, "PROGRAM_OK\n", ""

    monkeypatch.setattr(program, "run_mpremote", run_mpremote)
    assert program.program("/dev/ttyACM0", str(bitstream)) == (0, "PROGRAM_OK\n", "")
    ((port, args, script, mounted, data, timeout),) = calls
    assert port == "/dev/ttyACM0" and args[0] == "mount" and args[2] == "run"
    assert mounted == ["design.bin"] and data == b"\xff" * 16  # the board is given the bitstream and nothing else
    assert pathlib.Path(args[1]) != bitstream.parent
    assert 'open("/remote/design.bin", "rb")' in script
    assert timeout == program.PROGRAM_TIMEOUT
    assert not pathlib.Path(args[1]).exists() and not pathlib.Path(args[3]).exists()  # both temporary


def test_a_bitstream_reached_through_a_symlink_is_loaded(tmp_path, monkeypatch):
    """mpremote refuses a file that resolves outside the mounted directory; the copy is of what the link names."""
    bitstream = _bitstream(tmp_path)
    link = tmp_path / "link.bin"
    link.symlink_to(bitstream)
    seen = []
    monkeypatch.setattr(program, "run_mpremote", lambda port, args, timeout=60: (
        seen.append((pathlib.Path(args[1]) / "design.bin").is_symlink()) or (0, "PROGRAM_OK\n", "")))  # fmt: skip
    assert program.program("/dev/ttyACM0", str(link))[0] == 0 and seen == [False]


def test_a_bitstream_that_cannot_be_copied_is_a_result_with_the_reason(tmp_path, monkeypatch):
    monkeypatch.setattr(program, "run_mpremote", lambda *a, **k: pytest.fail("mpremote was run"))
    rc, out, err = program.program("/dev/ttyACM0", str(tmp_path / "gone.bin"))
    assert (rc, out) == (1, "") and err.startswith("the bitstream could not be copied for the board to read: ")


def test_mpremote_not_finishing_or_not_installed_is_a_result_not_an_exception(tmp_path, monkeypatch):
    bitstream = _bitstream(tmp_path)

    def hangs(port, args, timeout=60):
        raise subprocess.TimeoutExpired(["mpremote"], timeout, output=b"Programming iCE40")

    monkeypatch.setattr(program, "run_mpremote", hangs)
    assert program.program("/dev/ttyACM0", str(bitstream), timeout=7) == (
        124, "Programming iCE40", "mpremote did not finish within 7 s")  # fmt: skip

    def absent(port, args, timeout=60):
        raise FileNotFoundError("mpremote")

    monkeypatch.setattr(program, "run_mpremote", absent)
    assert program.program("/dev/ttyACM0", str(bitstream)) == (127, "", "mpremote is not installed")


def test_the_uart_wrapper_power_cycles_and_tries_again_after_a_load_that_hung(monkeypatch):
    calls = []
    results = iter([(124, "", "mpremote did not finish within 60 s"), (0, "PROGRAM_OK\n", "")])
    monkeypatch.setattr(wrapper, "reset_rp2350", lambda port: calls.append("reset"))
    monkeypatch.setattr(wrapper, "usb_power_cycle", lambda port: calls.append("power cycle"))
    monkeypatch.setattr(wrapper.tt_fpga_program, "program", lambda port, path: calls.append("load") or next(results))
    assert wrapper.program_fpga("/dev/ttyACM0", "design.bin") is True
    assert calls == ["reset", "load", "power cycle", "reset", "load"]


@pytest.mark.parametrize("rc, out, exit_code", [
    (0, "PROGRAM_OK\n", 0),
    (1, "PROGRAM_OK\n", 1),  # mpremote failing after the marker is still a failure
    (0, "Transmitted 12 bytes\n", 1),
    (124, "", 1),
])  # fmt: skip
def test_the_programmer_exits_nonzero_unless_mpremote_and_the_board_both_say_it_worked(
    tmp_path, monkeypatch, rc, out, exit_code
):
    bitstream = _bitstream(tmp_path)
    monkeypatch.setattr(program, "program", lambda *a, **k: (rc, out, ""))
    monkeypatch.setattr(sys, "argv", ["tt_fpga_program.py", "/dev/ttyACM0", str(bitstream)])
    assert program.main() == exit_code


@pytest.mark.parametrize("method, release", [("pio", False), ("pio", True), ("bitbang", False)])
def test_the_script_run_on_the_board_reads_the_mount_and_writes_no_file(method, release):
    script = program.board_script(method, release)
    assert 'open("/remote/design.bin", "rb")' in script and script.rstrip().endswith('os.chdir("/")')
    assert ("GPIO_RELEASED" in script) is release
    assert not board_writes(script)


# -- the guard: Tim, 2026-10-05: no code of ours modifies files on the Tiny Tapeout boards -------------------
# Everything these scripts send to a board, or give to mpremote, is a string in their source, wherever it sits
# (a module constant, an argument written in place, part of an f-string). So every string constant of every
# script in designs/_host, and of the check's own Tiny Tapeout module, is held to this.

# What MicroPython code would use to change the board's filesystem.
BOARD_WRITE = re.compile(
    r"""open\([^)]*,\s*(?:mode\s*=\s*)?["'][^"']*[wax+]"""  # open(path, "w"), open(path, mode="ab")
    r"""|open\([^),]*,\s*(?:mode\s*=\s*)?[A-Za-z_]"""  # open(path, mode): a mode that is not written out
    r"""|\bu?os\.(?:mkdir|remove|rename|rmdir|unlink|sync|mount|umount|VfsLfs2|VfsFat)\b"""
    r"""|\bfrom\s+u?os\s+import\b|\bimport\s+u?os\s+as\b|__import__|\b(?:mip|vfs)\."""
    r"""|open\([^)]*,\s*(?:mode\s*=\s*)?["'][^"']*\{"""  # a mode filled in by formatting
    r"""|\.write_(?:text|bytes)\(|\bFlash\(|\bwriteblocks\b|\bmkfs\b|\bioctl\("""
)
# The mpremote subcommands that change it, as an argument of their own or inside a command line.
# This errs on the eager side: a Pi-side ["rm", "-f", path] or a message that happens to read like one of
# these is flagged too. Reword it, or build it outside these files; do not loosen the guard for it.
MPREMOTE_WRITE_WORD = re.compile(r"^(?:cp|fs|mkdir|rm|rmdir|touch|edit|mip|romfs)$")
MPREMOTE_WRITE_LINE = re.compile(r"\bmpremote\b.*\s(?:cp|fs|mkdir|rm|rmdir|touch|edit|mip|romfs)(?:\s|$)", re.S)
GUARDED = [
    *sorted(_HOST.glob("*.py")),
    _HOST.parent.parent / "verify" / "src" / "fpgas_online_verify" / "boards" / "tt_fpga.py",
]


def board_writes(text):
    """What in `text` would change a file on the board: the first match of each kind, or []."""
    found = [m.group() for m in (BOARD_WRITE.search(text), MPREMOTE_WRITE_LINE.search(text)) if m]
    return (
        found
        + ([text] if MPREMOTE_WRITE_WORD.match(text) else [])
        + (["/bitstreams/custom.bin"] if "/bitstreams/custom.bin" in text else [])
    )


def strings_of(source):
    """Every string and bytes constant in Python `source`, as text; docstrings left out (they describe, they
    are not sent)."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef))
        and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)
    }  # fmt: skip
    # An f-string is one text: its written parts, with {} where a value goes.
    fstrings = [n for n in ast.walk(tree) if isinstance(n, ast.JoinedStr)]
    parts = {id(v) for f in fstrings for v in f.values}
    joined = ["".join(v.value if isinstance(v, ast.Constant) else "{}" for v in f.values) for f in fstrings]
    return joined + [
        n.value if isinstance(n.value, str) else n.value.decode("latin-1")  # raw serial writes are bytes
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, (str, bytes))
        and id(n) not in docstrings and id(n) not in parts
    ]  # fmt: skip


@pytest.mark.parametrize("path", GUARDED, ids=lambda p: p.name)
def test_no_tiny_tapeout_host_script_can_change_a_file_on_the_board(path):
    """The check used to copy each bitstream to /bitstreams/custom.bin and to overwrite main.py."""
    found = [(text[:80], board_writes(text)) for text in strings_of(path.read_text()) if board_writes(text)]
    assert not found, found


def test_the_guard_covers_every_tiny_tapeout_host_script():
    assert {
        "tt_fpga_program.py",
        "tt_test_wrapper.py",
        "tt_pmod_wrapper.py",
        "tt_sdk_start.py",
        "tt_main_py.py",
        "tt_fpga.py",
    } <= {p.name for p in GUARDED}


# What the scripts did before, and other ways of doing the same: the guard has to see each of them.
OLD_INSTALL_SAFE_MAIN = """
def _install_safe_main(port):
    subprocess.run(["mpremote", "connect", port, "exec",
                    "f = open('main.py', 'w'); f.write('print(1)'); f.close()"])
"""


@pytest.mark.parametrize("source", [
    OLD_INSTALL_SAFE_MAIN,
    'run_mpremote(port, ["cp", local, ":/bitstreams/custom.bin"])',
    'subprocess.run(f"mpremote connect {port} cp x.bin :/bitstreams/x.bin", shell=True)',
    'subprocess.run("mpremote connect /dev/ttyACM0 fs rm :main.py".split())',
    'run_mpremote(port, ["exec", "import os; os.mkdir(\'/bitstreams\')"])',
    'run_mpremote(port, ["exec", "import uos; uos.remove(\'main.py\')"])',
    'run_mpremote(port, ["exec", "from os import remove; remove(\'main.py\')"])',
    'run_mpremote(port, ["exec", "open(\'boot.py\', mode=\'a\').write(\'x\')"])',
    'run_mpremote(port, ["exec", "m = \'w\'; open(\'main.py\', m)"])',
    'run_mpremote(port, ["exec", "import rp2; rp2.Flash().writeblocks(0, b\'\')"])',
    'SCRIPT = "with open(\\"/bitstreams/custom.bin\\", \\"wb\\") as f: pass"',
    """os.write(fd, b"f = open('main.py', 'w'); f.write('x')\\x04")""",
    'subprocess.run([b"mpremote", b"cp", b"a", b":b"])',
    'run_mpremote(port, ["exec", "import os as o; o.remove(\'main.py\')"])',
    'run_mpremote(port, ["exec", "__import__(\'os\').remove(\'main.py\')"])',
    'run_mpremote(port, ["exec", "import mip; mip.install(\'x\')"])',
    'run_mpremote(port, ["exec", "import vfs; vfs.mount(bdev, \'/x\')"])',
    'run_mpremote(port, ["exec", "open(\'main.py\', \'{}\')".format("w")])',
    'subprocess.run("mpremote connect p fs".split() + ["rm", ":main.py"])',
])  # fmt: skip
def test_the_guard_sees_a_board_write_however_it_is_written(source):
    assert [text for text in strings_of(source) if board_writes(text)], source


def test_the_guard_passes_reading_and_the_pi_side_of_the_scripts():
    source = 'SCRIPT = "with open(\\"/remote/design.bin\\", \\"rb\\") as f: f.read(128)"\nopen(script_path, "w")\n'
    assert not [text for text in strings_of(source) if board_writes(text)]


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
