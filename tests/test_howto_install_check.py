"""packaging/debs/howto_install_check.py reads the install how-tos and judges apt's output (#307). These tests need
no network and no container: the pages' parsing and the verdicts. The run itself is CI's job (howto-install.yml).

Run: uv run --no-project --with pytest pytest tests/test_howto_install_check.py
"""

import importlib.util
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("howto_install_check", REPO / "packaging/debs/howto_install_check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_the_setup_is_installing_md_s_repositories_then_one_update():
    for suite in ("bookworm", "trixie"):
        plan = check.setup_plan(suite)
        assert [k for _n, k, _c in plan] == ["mkdir", "key", "source", "key", "source", "update"]
        assert [n for n, _k, _c in plan] == [1, 1, 1, 2, 2, 3]
        assert "apt.fpgas.online" in plan[2][2] and "fpgas.online-fpga-tools" in plan[4][2]


def test_every_hardware_page_with_an_install_section_is_a_board():
    assert check.boards() == {
        "acorn": ("docs/hardware/acorn.md", "fpgas-online-acorn"),
        "arty": ("docs/hardware/arty-a7.md", "fpgas-online-arty"),
        "fomu": ("docs/hardware/fomu-evt.md", "fpgas-online-fomu"),
        "netv2": ("docs/hardware/netv2.md", "fpgas-online-netv2"),
        "tt-fpga": ("docs/hardware/tt-fpga.md", "fpgas-online-tt-fpga"),
    }


@pytest.mark.parametrize("board", ["acorn", "arty", "fomu", "netv2"])
def test_a_board_s_install_is_its_one_apt_install_and_stops_before_the_board_is_needed(board):
    page, package = check.boards()[board]
    for suite in ("bookworm", "trixie"):
        assert check.board_plan(page, suite) == [(1, "install", f"sudo apt install {package}")]


def test_the_tt_backports_step_runs_on_bookworm_only():
    page = "docs/hardware/tt-fpga.md"
    bookworm = check.board_plan(page, "bookworm")
    trixie = check.board_plan(page, "trixie")
    assert [n for n, _k, _c in bookworm] == [1] * 5 + [2] * 5 + [3]
    assert [n for n, _k, _c in trixie] == [1] * 5 + [3]
    assert bookworm[-2][2] == "sudo apt install -t bookworm-backports micropython-mpremote"
    assert all("backports" not in c for _n, _k, c in trixie)


def test_commands_join_continuations_and_drop_comments():
    code = '# a comment\nsudo apt install fpgas-online-arty         # the package for your board\necho "a" \\\n  | b\n'
    assert check.commands(code) == ["sudo apt install fpgas-online-arty", 'echo "a" | b']
    with pytest.raises(ValueError, match="continuation"):
        check.commands("echo a \\\n")


def test_a_command_the_check_does_not_know_ends_the_install_steps_and_no_apt_step_may_follow_it():
    steps = [
        check.Step("p", 1, "", "sudo apt install fpgas-online-x"),
        check.Step("p", 2, "", "sudo fpgas-x-verify --no-publish"),
    ]
    assert check.install_plan("p", steps, "bookworm") == [(1, "install", "sudo apt install fpgas-online-x")]
    steps.append(check.Step("p", 3, "", "sudo apt install fpgas-online-x-debug"))
    with pytest.raises(ValueError, match="after 'sudo fpgas-x-verify --no-publish'"):
        check.install_plan("p", steps, "bookworm")


def test_a_source_line_without_signed_by_is_not_a_known_command():
    # the 32-bit fault of #266: a Debian source with no key of its own; the check treats it as unknown, so a page
    # that writes one fails (an apt step after an unknown command) instead of passing on 64-bit
    assert (
        check.kind(
            'echo "deb http://deb.debian.org/debian bookworm-backports main" | sudo tee '
            "/etc/apt/sources.list.d/bookworm-backports.list"
        )
        is None
    )


def test_update_problems_are_the_error_and_warning_lines():
    out = "Hit:1 http://x bookworm InRelease\nW: GPG error: http://y: NO_PUBKEY 82B1\nErr:2 http://z\nE: failed\n"
    assert check.update_problems(out) == ["W: GPG error: http://y: NO_PUBKEY 82B1", "Err:2 http://z", "E: failed"]
    assert check.update_problems("Hit:1 http://x\nAll packages are up to date.\n") == []
    # the reason apt gives on the indented lines after an error is part of it
    out = (
        "Err:4 http://a trixie InRelease\n  Sub-process /usr/bin/sqv returned an error code (1)\nHit:5 http://b\n  x\n"
    )
    assert check.update_problems(out) == [
        "Err:4 http://a trixie InRelease Sub-process /usr/bin/sqv returned an error code (1)"
    ]


def test_installed_reads_apt_s_inst_lines():
    out = (
        "NOTE: This is only a simulation!\n"
        "Inst libc6 (2.36-9 Debian:12 [arm64])\n"
        "Conf libc6 (2.36-9)\n"
        "Inst fpgas-online-arty (0.1 [all])\n"
    )
    assert check.installed(out) == ["libc6", "fpgas-online-arty"]


def test_another_board_s_package_or_tool_is_foreign():
    boards = check.boards()
    assert check.foreign("arty", ["fpgas-online-arty-tools", "fpgas-online-verify", "libc6"], boards) == []
    assert check.foreign("arty", ["fpgas-online-netv2-tools", "openocd", "micropython-mpremote"], boards) == [
        "fpgas-online-netv2-tools",
        "openocd",
        "micropython-mpremote",
    ]
    assert check.foreign("netv2", ["openocd"], boards) == []
    assert check.foreign("tt-fpga", ["micropython-mpremote", "fpgas-online-tt-fpga-tools"], boards) == []
    assert check.foreign("acorn", ["python3-libgpiod", "fpgas-online-setup-pi"], boards) == [
        "python3-libgpiod",
        "fpgas-online-setup-pi",
    ]
    assert check.foreign("tt-fpga", ["fpgas-online-tt"], boards) == ["fpgas-online-tt"]  # the TT site's own package


def test_it_refuses_to_run_outside_a_container(monkeypatch):
    monkeypatch.setattr(check, "in_container", lambda: False)
    monkeypatch.setattr("sys.argv", ["howto_install_check.py", "rpios32"])
    with pytest.raises(SystemExit, match="refusing to run outside a container"):
        check.main()
