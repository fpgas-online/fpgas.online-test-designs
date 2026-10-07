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
dip = _load("tt_dip_switches")

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


# What SDK 1.2.2's main.py prints (tt-micropython-firmware src/main.py at v1.2.2: no "BOOT:" line and no
# tt.sdk_version line; the release in colour, then the board object). From the source, not from a board.
SDK_1_BOOT = (
    ">>> \r\nMPY: soft reboot\r\n\x1b[36mDetected TT04/TT05 demoboard \x1b[0m\r\n\r\n\r\n"
    "The '\x1b[31mtt\x1b[0m' object is available.\r\n\r\n\x1b[36mTT SDK v1.2.2\x1b[0m\r\n\r\n\r\n"
    "<DemoBoard in ASIC_RP_CONTROL tt03p5 project 'None'>\r\n\r\n"
    "MicroPython v1.22.2 on 2024-02-22; Raspberry Pi Pico with RP2040\r\n"
    'Type "help()" for more information.\r\n>>> '
)


def test_a_1_x_sdk_which_has_no_last_boot_line_started_when_it_built_the_board_and_reached_the_prompt():
    started, reason = sdk_start.verdict(SDK_1_BOOT)
    assert started is True and reason.startswith("the SDK started: TT SDK v1.2.2")
    still = SDK_1_BOOT[: SDK_1_BOOT.index("<DemoBoard")]
    assert sdk_start.verdict(still) == (None, "the SDK is still starting")
    raised = SDK_1_BOOT.replace("<DemoBoard in", "Traceback (most recent call last):\r\nOSError: 5\r\n<DemoBoard in")
    assert sdk_start.verdict(raised) == (False, "the board's main.py raised: OSError: 5")
    # a later release printing the same line without its last one did not finish
    later = SDK_1_BOOT.replace("MPY: soft reboot\r\n", "MPY: soft reboot\r\nBOOT: Tiny Tapeout SDK\r\n")
    assert sdk_start.verdict(later)[0] is False


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
        "no main.py is recorded for SDK release 9.9.9 (recorded: 1.0.0 to 3.1.1): add it to tt_main_py.py")  # fmt: skip


@pytest.mark.parametrize("release, digest", [
    ("1.2.2", "b7c5e0509847674318a4c7350d24f9efb0fa1d75f7b6399c6a03d71f3dd62ffc"),  # what a TT03p5 board runs
    ("2.0.4", "b4989604534cf4fe63f459b4da882d737cc6d9ad7bfab9bdb146f5372096423f"),  # the last for TT04 to TT08
    ("3.1.0", "9ebe551a54715dd730261201ff4f21ad8ecbcd518b4809aa81675cca161e0cb4"),  # the FPGA boards'
])  # fmt: skip
def test_the_releases_chip_boards_run_have_their_main_py_recorded(release, digest):
    assert main_py.MAIN_PY_SHA256[release] == digest
    assert main_py.verdict(0, f"SDK_RELEASE {release}\nMAIN_SHA256 {digest}\n", "") == (
        True, f"main.py is SDK {release}'s own")  # fmt: skip
    other = main_py.MAIN_PY_SHA256["2.0.3"]  # another release's own main.py is not this release's
    assert main_py.verdict(0, f"SDK_RELEASE {release}\nMAIN_SHA256 {other}\n", "")[0] is False


def test_every_recorded_release_is_a_release_number_recorded_once():
    releases = [r for group in main_py._MAIN_PY_RELEASES.values() for r in group]
    assert len(releases) == len(set(releases)) == len(main_py.MAIN_PY_SHA256) == 21
    assert all(len(d) == 64 and int(d, 16) >= 0 for d in main_py._MAIN_PY_RELEASES)
    assert sorted(releases, key=main_py._release_key)[0] == "1.0.0"


@pytest.mark.parametrize("rc, out, err, part", [
    (1, "", "Traceback (most recent call last):\nOSError: [Errno 2] ENOENT\n", "OSError: [Errno 2] ENOENT"),
    (0, "SDK_RELEASE 3.1.0\n", "", "could not be read (exit 0)"),  # half an answer is no answer
    (0, f"SDK_RELEASE \r\nMAIN_SHA256 {SDK_SHA}\r\n", "", "could not be read (exit 0)"),  # a key with no value
    (0, "SDK_RELEASE 3.1.0\nMAIN_SHA256 \r\n", "", "could not be read (exit 0)"),
    (0, "SDK_RELEASE\nMAIN_SHA256\n", "", "could not be read (exit 0)"),
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
        "tt_dip_switches.py",
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


def _load_pin_id():
    path = _HOST.parent / "pmod-pin-id" / "host" / "identify_pmod_pins.py"
    spec = importlib.util.spec_from_file_location("identify_pmod_pins", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# -- the DIP switches (#166) -----------------------------------------------------------------------------------

# pinctrl get in the form a Raspberry Pi 4 prints it (core.PIN_RE's comment: no drive on an output, "--"), with
# the SPI driver loaded: its chip select on GPIO8 as a GPIO output (cs-gpios), GPIO9 to 11 SPI0, the rest
# inputs. Made up in that form, not a recorded read.
PINCTRL_GET = "\n".join([
    " 8: op -- pu | hi // GPIO8 = output",
    "10: a0    pd | lo // GPIO10 = SPI0_MOSI",
    " 9: a0    pd | lo // GPIO9 = SPI0_MISO",
    "11: a0    pd | lo // GPIO11 = SPI0_SCLK",
    "19: ip    pd | lo // GPIO19 = input",
    "21: ip    pd | lo // GPIO21 = input",
    "20: ip    pd | lo // GPIO20 = input",
    "18: ip    pd | lo // GPIO18 = input",
]) + "\n"


class FakeRun:
    """Stands in for subprocess.run: records argv; pinctrl get answers PINCTRL_GET, mpremote answers `board`."""

    def __init__(self, board=(0, "DIP 00000000\n", ""), get=(0, PINCTRL_GET), set_rc=0):
        self.calls, self.board, self.get, self.set_rc = [], board, get, set_rc

    def __call__(self, argv, **kw):
        self.calls.append(list(argv))
        if argv[0] == "mpremote":
            rc, out, err = self.board
        elif argv[:2] == ["pinctrl", "get"]:
            (rc, out), err = self.get, ""
        else:
            rc, out, err = self.set_rc, "", ""
        return subprocess.CompletedProcess(argv, rc, out, err)


@pytest.mark.parametrize("bits, code, line", [
    ("00000000", 0, "all 8 DIP switches are off"),
    ("00010000", 1, "switch 4 is on: set all DIP switches off"),
    ("10010000", 1, "switch 1 is on, switch 4 is on: set all DIP switches off"),
    ("11111111", 1, ", ".join(f"switch {n} is on" for n in range(1, 9)) + ": set all DIP switches off"),
])  # fmt: skip
def test_each_switch_that_reads_on_is_named_switch_1_first(bits, code, line):
    assert dip.verdict(0, f"DIP {bits}\n", "") == (code, line)


@pytest.mark.parametrize("rc, out, err, part", [
    (1, "", "mpremote: no device found on /dev/ttyACM0", "(exit 1): mpremote: no device found"),
    (0, "DIP 0101\n", "", "DIP 0101"),
    (0, "", "", "it printed nothing"),
    (124, "", "mpremote did not finish within 60 s", "(exit 124)"),
])  # fmt: skip
def test_a_read_that_did_not_give_eight_switches_is_an_error_not_a_pass(rc, out, err, part):
    code, line = dip.verdict(rc, out, err)
    assert code == 2 and line.startswith("the DIP switches could not be read from the board") and part in line


def test_the_pi_pins_are_made_inputs_with_their_pull_down_for_the_read_and_put_back_as_they_were():
    run = FakeRun(board=(0, "DIP 00010000\n", ""))
    assert dip.check("/dev/ttyACM0", run) == (1, "switch 4 is on: set all DIP switches off")
    sets = [(i, c) for i, c in enumerate(run.calls) if c[:2] == ["pinctrl", "set"]]
    read = next(i for i, c in enumerate(run.calls) if c[0] == "mpremote")
    before, after = [c for i, c in sets if i < read], [c for i, c in sets if i > read]
    assert sorted(c[2] for c in before) == sorted(str(g) for g in dip.PI_GPIOS)
    assert all(c[3:] == ["ip", "pd"] for c in before)
    assert ["pinctrl", "set", "10", "a0", "pd"] in after and ["pinctrl", "set", "18", "ip", "pd"] in after
    assert ["pinctrl", "set", "8", "op", "pu", "dh"] in after  # an output goes back at its level
    assert len(after) == len(dip.PI_GPIOS)
    assert run.calls[read][:4] == ["mpremote", "connect", "/dev/ttyACM0", "exec"]


def test_without_pinctrl_nothing_is_read_and_it_is_an_error():
    calls = []

    def missing(argv, **kw):
        calls.append(argv)
        if argv[0] == "pinctrl":
            raise FileNotFoundError(argv[0])
        raise AssertionError(f"nothing else is run: {argv}")

    code, line = dip.check("/dev/ttyACM0", missing)
    assert code == 2 and "pinctrl is not installed" in line and line.endswith("the DIP switches were not read")
    assert calls == [["pinctrl", "get", ",".join(map(str, dip.PI_GPIOS))]]


def test_pins_that_could_not_be_put_back_turn_a_pass_into_an_error():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["pinctrl", "get"]:
            return subprocess.CompletedProcess(argv, 0, PINCTRL_GET, "")
        if argv[0] == "mpremote":
            return subprocess.CompletedProcess(argv, 0, "DIP 00000000\n", "")
        back = len([c for c in calls if c[0] == "mpremote"]) > 0
        return subprocess.CompletedProcess(argv, 1 if back else 0, "", "pinctrl: busy" if back else "")

    code, line = dip.check("/dev/ttyACM0", run)
    assert code == 2 and line.startswith(
        "all 8 DIP switches are off; and the Pi's GPIOs on HAT JA were not put back as they were "
        "(GPIO8 could not be set to op pu dh: pinctrl: busy")


def test_a_switch_that_is_on_and_pins_not_put_back_says_both():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if argv[:2] == ["pinctrl", "get"]:
            return subprocess.CompletedProcess(argv, 0, PINCTRL_GET, "")
        if argv[0] == "mpremote":
            return subprocess.CompletedProcess(argv, 0, "DIP 01000000\n", "")
        back = any(c[0] == "mpremote" for c in calls)
        return subprocess.CompletedProcess(argv, 1 if back else 0, "", "pinctrl: busy" if back else "")

    code, line = dip.check("/dev/ttyACM0", run)
    assert code == 2 and line.startswith("switch 2 is on: set all DIP switches off; and the Pi's GPIOs on HAT JA")


def test_a_pi_whose_pinctrl_cannot_read_a_pull_is_refused_before_anything_is_changed():
    """A Pi 3 prints "--" for every pull (core.PIN_RE's comment): the pull-down set for the read could not be undone."""
    run = FakeRun(get=(0, PINCTRL_GET.replace(" pd |", " -- |").replace(" pu |", " -- |")))
    code, line = dip.check("/dev/ttyACM0", run)
    assert code == 2 and "cannot read the pull of GPIO8, GPIO9" in line and line.endswith("were not read")
    assert run.calls == [["pinctrl", "get", ",".join(map(str, dip.PI_GPIOS))]]


def test_a_check_stopped_during_the_read_still_puts_the_pis_pins_back():
    run = FakeRun()

    def stopped(argv, **kw):
        if argv[0] == "mpremote":
            run.calls.append(list(argv))
            raise SystemExit("stopped by signal 15")
        return run(argv, **kw)

    with pytest.raises(SystemExit):
        dip.check("/dev/ttyACM0", stopped)
    read = next(i for i, c in enumerate(run.calls) if c[0] == "mpremote")
    assert len([c for c in run.calls[read:] if c[:2] == ["pinctrl", "set"]]) == len(dip.PI_GPIOS)


def test_the_read_on_the_board_drives_each_line_low_then_reads_it_with_the_pull_down_and_writes_no_file():
    assert "Pin.PULL_DOWN" in dip.READ and "Pin.OUT, value=0" in dip.READ
    # ui_in[1..3] are joined to uio[1..3] at the HAT: their RP2350 pads (GPIO26 to 28) are set the same way
    assert dip.JOINED == {1: 26, 2: 27, 3: 28} and "joined = {1: 26, 2: 27, 3: 28}" in dip.READ
    assert not board_writes(dip.READ)
    assert dip.FIRST_GPIO == 17 and dip.SWITCHES == 8  # ui_in[0] is the RP2350's GPIO17 (tt-demo-pcb README)
    namespace = {}
    exec(compile("def f():\n" + "".join("    " + line + "\n" for line in dip.READ.splitlines()), "READ", "exec"),
         {}, namespace)  # it is Python the board can run (compiled here, not run)


def test_the_pi_gpios_are_hat_ja_as_the_pin_id_scan_has_ui_in():
    pin_id = _load_pin_id()
    ja = [gpio for gpio, _pin, where in pin_id.BOARDS["tt"]["pins"] if "ui_in[" in where]
    assert tuple(ja) == dip.PI_GPIOS
