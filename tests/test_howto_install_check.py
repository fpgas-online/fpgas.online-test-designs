"""packaging/debs/howto_install_check.py reads the install how-tos and judges apt's output (#307). These tests need
no network and no container: the pages' parsing and the verdicts. The run itself is CI's job (howto-install.yml).

Run: uv run --no-project --with pytest pytest tests/test_howto_install_check.py
"""

import importlib.util
import pathlib
import shutil

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("howto_install_check", REPO / "packaging/debs/howto_install_check.py")
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


def test_the_setup_is_installing_md_s_repositories_then_one_update():
    for suite in ("bookworm", "trixie"):
        plan = check.setup_plan(suite)
        assert [k for _n, k, _c in plan] == [
            "mkdir",
            "key",
            "source",
            "keycheck",
            "key",
            "source",
            "keycheck",
            "update",
        ]
        assert [n for n, _k, _c in plan] == [1, 1, 1, 1, 2, 2, 2, 3]
        assert "apt.fpgas.online" in plan[2][2] and "fpgas.online-fpga-tools" in plan[5][2]


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
    assert [n for n, _k, _c in bookworm] == [1] * 6 + [2] * 6 + [3]
    assert [n for n, _k, _c in trixie] == [1] * 6 + [3]
    assert bookworm[-2][2] == "sudo apt install -t bookworm-backports micropython-mpremote"
    assert all("backports" not in c for _n, _k, c in trixie)


def test_commands_join_continuations_and_drop_comments():
    code = '# a comment\nsudo apt install fpgas-online-arty         # the package for your board\necho "a" \\\n  | b\n'
    assert check.commands(code) == ["sudo apt install fpgas-online-arty", 'echo "a" | b']
    with pytest.raises(ValueError, match="continuation"):
        check.commands("echo a \\\n")


def test_the_install_steps_end_at_the_first_board_command_and_only_board_commands_may_follow():
    steps = [
        check.Step("p", 1, "", "sudo apt install fpgas-online-x"),
        check.Step("p", 2, "", "sudo fpgas-x-verify --no-publish"),
        check.Step("p", 3, "", "sudo fpgas-x-debug detect       # a comment"),
    ]
    assert check.install_plan("p", steps, "bookworm") == [(1, "install", "sudo apt install fpgas-online-x")]
    steps.append(check.Step("p", 4, "", "sudo apt install fpgas-online-x-debug"))
    with pytest.raises(
        ValueError, match="p step 4: 'sudo apt install fpgas-online-x-debug' after 'sudo fpgas-x-verify"
    ):
        check.install_plan("p", steps, "bookworm")


@pytest.mark.parametrize(
    "command",
    [
        # the 32-bit fault of #266: a Debian source with no key of its own
        'echo "deb http://deb.debian.org/debian bookworm-backports main" | sudo tee '
        "/etc/apt/sources.list.d/bookworm-backports.list",
        "sudo apt-get install -y openocd",  # the review's mutation: it used to end the plan unseen
        "pip install something",
    ],
)
def test_a_command_the_check_does_not_know_is_refused_wherever_it_is(command):
    assert check.kind(command) is None
    for steps in (
        [check.Step("p", 1, "", command)],
        [check.Step("p", 1, "", "sudo apt install fpgas-online-x"), check.Step("p", 2, "", command)],
    ):
        with pytest.raises(ValueError, match="is a command this check does not know"):
            check.install_plan("p", steps, "bookworm")


@pytest.mark.parametrize(
    "command",
    [
        # round 2's F12: a second command chained onto a known one, which `.*` let ride along unseen
        "sudo fpgas-arty-verify --no-publish && sudo apt-get install -y openocd",
        "sudo fpgas-arty-verify --no-publish; sudo apt-get install -y openocd",
        "sudo fpgas-arty-verify $(sudo apt-get install -y openocd)",
        'echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/bookworm/ ./"; sudo apt-get install '
        '-y openocd; echo "x" | sudo tee /etc/apt/sources.list.d/apt.list',
        'echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(sudo apt-get install -y openocd)/ '
        './" | sudo tee /etc/apt/sources.list.d/apt.list',
        "sudo curl -fsSL --remove-on-error -o /etc/apt/keyrings/apt.gpg https://apt.fpgas.online/apt.gpg;sudo "
        "apt-get install -y openocd",
        "sudo curl -fsSL --remove-on-error -o /etc/apt/keyrings/apt.gpg https://apt.fpgas.online/$(id)",
        "ls -l /etc/apt/keyrings/apt.gpg; sudo apt-get install -y openocd",
    ],
)
def test_a_known_command_with_another_chained_on_is_refused(command):
    assert check.kind(command) is None


KEY = "sudo curl -fsSL --remove-on-error -o /etc/apt/keyrings/k.gpg https://example.org/k.gpg"


@pytest.mark.parametrize(
    "command",
    [
        # the old form: a failed download left a missing or empty key, and `> /dev/null` hid tee (ps1, 14 Oct 2026)
        "curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null",
        # a download that can leave half a file, or that is not root's
        "sudo curl -fsSL -o /etc/apt/keyrings/apt.gpg https://apt.fpgas.online/apt.gpg",
        "curl -fsSL --remove-on-error -o /etc/apt/keyrings/apt.gpg https://apt.fpgas.online/apt.gpg",
        "sudo curl -fsSL --remove-on-error -o /etc/apt/keyrings/apt.gpg http://apt.fpgas.online/apt.gpg",
        "ls -l /etc/apt/keyrings/apt.gpg > /dev/null",
    ],
)
def test_a_key_is_fetched_only_the_loud_way(command):
    assert check.kind(command) is None


def test_every_key_a_step_fetches_is_listed_before_its_apt_update():
    listed = [check.Step("p", 1, "", f"{KEY}\nls -l /etc/apt/keyrings/k.gpg\nsudo apt update")]
    assert [k for _n, k, _c in check.install_plan("p", listed, "trixie")] == ["key", "keycheck", "update"]
    after = [check.Step("p", 1, "", f"{KEY}\nsudo apt update\nls -l /etc/apt/keyrings/k.gpg")]
    with pytest.raises(
        ValueError, match=r"p step 1: 'sudo apt update' before an `ls -l` lists \['/etc/apt/keyrings/k.gpg'\]"
    ):
        check.install_plan("p", after, "trixie")
    other = [check.Step("p", 1, "", f"{KEY}\nls -l /etc/apt/keyrings/other.gpg")]
    with pytest.raises(ValueError, match=r"p step 1: no `ls -l` lists the key \['/etc/apt/keyrings/k.gpg'\]"):
        check.install_plan("p", other, "trixie")


def test_a_listed_key_that_is_empty_fails(tmp_path):
    key = tmp_path / "k.gpg"
    key.write_bytes(b"")
    failures = []
    check.execute([(1, "keycheck", f"ls -l {key}")], "p", failures)
    assert failures == [f"p step 1: ls -l {key}: empty: ['{key}']"]
    key.write_bytes(b"x")
    failures = []
    check.execute([(1, "keycheck", f"ls -l {key}")], "p", failures)
    assert failures == []
    failures = []
    check.execute([(1, "keycheck", f"ls -l {tmp_path / 'missing.gpg'}")], "p", failures)
    assert len(failures) == 1 and "exit 2" in failures[0] and "No such file or directory" in failures[0]


def test_the_acorn_check_pages_add_the_keys_as_installing_md_does():
    # The Compute Blade and Pi 5 check pages are generated from check/after-a-boot.md, not read by the container run.
    # Their commands must be ones this check knows, and their key lines installing.md's (the page CI runs).
    text = (REPO / "docs/wiring/acorn/check/after-a-boot.md").read_text()
    code = text[text.index("```bash\n") + 8 : text.index("\n# 4. ")]
    acorn = check.install_plan("after-a-boot.md", [check.Step("after-a-boot.md", 1, "", code)], "trixie")
    assert [k for _n, k, _c in acorn] == ["mkdir", "key", "source", "key", "source", "keycheck", "update", "install"]
    setup = check.setup_plan("trixie")
    assert [c for _n, k, c in acorn if k == "key"] == [c for _n, k, c in setup if k == "key"]


def test_every_command_the_pages_have_is_known():
    # the tightened forms still take every command the pages write
    for suite in ("bookworm", "trixie"):
        setup, own = check.installing_plan(suite)
        plans = [setup, own] + [check.board_plan(page, suite) for page, _p in check.boards().values()]
        assert all(k for plan in plans for _n, k, _c in plan)


def test_a_command_that_names_a_release_must_be_in_a_step_limited_to_it():
    line = (
        'echo "deb [signed-by=/etc/apt/keyrings/k.asc] http://deb.debian.org/debian bookworm-backports main" \\\n'
        "  | sudo tee /etc/apt/sources.list.d/b.list"
    )
    with pytest.raises(ValueError, match="names \\['bookworm'\\], but the step is not limited"):
        check.install_plan("p", [check.Step("p", 2, "Add bookworm-backports.", line)], "trixie")
    limited = [check.Step("p", 2, "On bookworm only, add it.", line)]
    assert [k for _n, k, _c in check.install_plan("p", limited, "bookworm")] == ["source"]
    assert check.install_plan("p", limited, "trixie") == []
    with pytest.raises(ValueError, match="names \\['bookworm'\\]"):
        check.install_plan("p", [check.Step("p", 2, "On trixie only, add it.", line)], "trixie")


def test_a_step_s_lead_holds_for_every_code_block_in_it():
    lines = [
        "**2.** On bookworm only, do two things.",
        "```bash",
        "sudo apt update",
        "```",
        "Then:",
        "```bash",
        "sudo apt install -t bookworm-backports x",
        "```",
        "**3.** Next.",
        "```bash",
        "sudo apt install y",
        "```",
    ]
    found = check.steps("p", lines)
    assert [(s.number, check.only_on(s.lead)) for s in found] == [(2, "bookworm"), (2, "bookworm"), (3, None)]
    with pytest.raises(ValueError, match="~~~ code block"):
        check.steps("p", ["**1.** x", "~~~bash", "sudo apt update", "~~~"])


def test_a_page_with_two_install_sections_is_refused(monkeypatch):
    fake = REPO / "tmp" / "test-howto-install-check"
    (fake / "docs/hardware").mkdir(parents=True, exist_ok=True)
    section = "## Installing the X Packages\n\n**1.** Install.\n\n```bash\nsudo apt install fpgas-online-x\n```\n\n"
    (fake / "docs/hardware/x.md").write_text("# X\n\n" + section + section.replace("X Packages", "X Packages Again"))
    monkeypatch.setattr(check, "REPO", fake)
    try:
        with pytest.raises(ValueError, match=r"expected one '## Installing the \.\.\. Packages' section, found \["):
            check.boards()
    finally:
        shutil.rmtree(fake)


def test_update_problems_are_the_error_and_warning_lines():
    out = "Hit:1 http://x bookworm InRelease\nW: GPG error: http://y: NO_PUBKEY 82B1\nErr:2 http://z\nE: failed\n"
    assert check.update_problems(out) == ["W: GPG error: http://y: NO_PUBKEY 82B1", "Err:2 http://z", "E: failed"]
    assert check.update_problems("Hit:1 http://x\nAll packages are up to date.\n") == []
    # apt 3 (trixie) words them in full; its Notice: lines are not problems
    out = "Notice: Some sources can be modernized.\nWarning: http://y: NO_PUBKEY 82B1\nError: failed\n"
    assert check.update_problems(out) == ["Warning: http://y: NO_PUBKEY 82B1", "Error: failed"]
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


def test_install_problems_are_apt_s_errors_and_unmet_dependencies():
    out = (
        "Reading package lists...\n"
        "Some packages could not be installed.\n"
        "The following packages have unmet dependencies:\n"
        " fpgas-online-arty-tools : Depends: openfpgaloader-fpgasonline but it is not installable or\n"
        "                                    openfpgaloader (>= 0.13.0) but it is not going to be installed\n"
        "E: Unable to correct problems, you have held broken packages.\n"
    )
    assert check.install_problems(out) == [
        "fpgas-online-arty-tools : Depends: openfpgaloader-fpgasonline but it is not installable or",
        "E: Unable to correct problems, you have held broken packages.",
    ]


def test_a_repository_without_the_pi_s_architecture_is_a_problem_in_either_apt_s_words():
    # round 2's F14: apt says this as a notice, so a page repository with no armhf build passed its update
    for prefix in ("N:", "Notice:"):
        line = (
            f"{prefix} Skipping acquire of configured file 'main/binary-armhf/Packages' as repository "
            "'https://x bookworm InRelease' doesn't support architecture 'armhf'"
        )
        assert check.update_problems(line + "\n") == [line]
    assert check.update_problems("Notice: Some sources can be modernized.\n") == []


def test_install_problems_include_apt_3_s_errors():
    assert check.install_problems("Error: Unable to locate package nonesuch\n") == [
        "Error: Unable to locate package nonesuch"
    ]


def test_named_is_what_the_install_commands_ask_for():
    plan = [
        (1, "update", "sudo apt update"),
        (1, "install", "sudo apt install python3-rpi-hwid"),
        (2, "install", "sudo apt install -t bookworm-backports micropython-mpremote"),
    ]
    assert check.named(plan) == {"python3-rpi-hwid", "micropython-mpremote"}


def test_page_uris_are_the_files_from_the_pages_repositories_whatever_hash_apt_prints():
    # as apt-get --print-uris printed them in a bookworm container (MD5Sum, not SHA256)
    out = (
        "'https://fpgas.online/fpgas.online-fpga-tools/bookworm/./librp1jtag0_0.0.post107%2bfpgasonline.0.0.post101"
        "%7edeb12_arm64.deb' librp1jtag0_0.0.post107+fpgasonline.0.0.post101~deb12_arm64.deb 9332 "
        "MD5Sum:395392992c992f828912136ac257d703\n"
        "'https://apt.fpgas.online/bookworm/./fpgas-online-arty_0.0.post1652_all.deb' "
        "fpgas-online-arty_0.0.post1652_all.deb 1842 MD5Sum:2f4820e7b62ae4346b1057463ef837d6\n"
        "'http://archive.raspberrypi.com/debian/pool/main/z/zlib/zlib1g_1.2.13.dfsg-1%2brpt1_arm64.deb' "
        "zlib1g_1%3a1.2.13.dfsg-1+rpt1_arm64.deb 94290 MD5Sum:774312206118f372f3a9bf2b15f601b9\n"
        "'https://apt.fpgas.online/bookworm/./x_1%3a2.0_all.deb' x_1%3a2.0_all.deb 10 SHA256:ab\n"
        # a bookworm-backports file, byte for byte as apt printed it in a 32-bit bookworm container: the size, a
        # space, and no hash
        "'http://deb.debian.org/debian/pool/main/m/micropython-mpremote/micropython-mpremote_1.24.0-1%7ebpo12%2b1"
        "_all.deb' micropython-mpremote_1.24.0-1~bpo12+1_all.deb 28656 \n"
    )
    sources = [
        "https://apt.fpgas.online/bookworm/",
        "https://fpgas.online/fpgas.online-fpga-tools/bookworm/",
        "http://deb.debian.org/debian/",
    ]
    got = check.page_uris(out, sources)
    assert [(p, v) for _u, p, v in got] == [
        ("librp1jtag0", "0.0.post107+fpgasonline.0.0.post101~deb12"),
        ("fpgas-online-arty", "0.0.post1652"),
        ("x", "1:2.0"),  # an epoch, written %3a in the file name
        ("micropython-mpremote", "1.24.0-1~bpo12+1"),
    ]


def test_a_print_uris_file_line_that_cannot_be_read_is_refused_not_skipped():
    with pytest.raises(ValueError, match="cannot read"):
        check.page_uris("'https://apt.fpgas.online/bookworm/./a_1_all.deb' a_1_all.deb size?\n", [])


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
    # a board's own debug package, and sudo, only when the page asks for them (install_test.sh forbids them)
    assert check.foreign("arty", ["fpgas-online-arty-debug", "sudo"], boards) == ["fpgas-online-arty-debug", "sudo"]
    assert check.foreign("arty", ["fpgas-online-arty-debug"], boards, {"fpgas-online-arty-debug"}) == []
    # but a page asking for another board's package or tool does not make it this board's
    assert check.foreign(
        "acorn", ["openocd", "fpgas-online-netv2-tools"], boards, {"openocd", "fpgas-online-netv2-tools"}
    ) == [
        "openocd",
        "fpgas-online-netv2-tools",
    ]


def test_a_keyring_must_hold_exactly_the_pinned_primary_key():
    colons = (
        "pub:-:4096:1:82B129927FA3303E:1339944591:::-:::scSC::::::23::0:\n"
        "fpr:::::::::CF8A1AF502A2AA2D763BAE7E82B129927FA3303E:\n"
        "uid:-::::1339944591::ADB5::Raspberry Pi Archive Signing Key::::::::::0:\n"
        "sub:-:4096:1:F7BB0489EDD83D6C:1339944591::::::e::::::23:\n"
        "fpr:::::::::DE5C1FD28F18825391E92B58F7BB0489EDD83D6C:\n"
    )
    assert check.primary_fingerprints(colons) == ["CF8A1AF502A2AA2D763BAE7E82B129927FA3303E"]
    two = colons + "pub:-:4096:1:1111:1::::::scSC::::::23::0:\nfpr:::::::::" + "1" * 40 + ":\n"
    assert len(check.primary_fingerprints(two)) == 2


def test_it_needs_a_container_and_root(monkeypatch):
    monkeypatch.setattr(check.pathlib.Path, "exists", lambda self: str(self) == "/.dockerenv")
    monkeypatch.setattr(check.os, "geteuid", lambda: 1000)
    assert not check.in_container()
    monkeypatch.setattr(check.os, "geteuid", lambda: 0)
    assert check.in_container()


def test_it_refuses_to_run_outside_a_container(monkeypatch):
    monkeypatch.setattr(check, "in_container", lambda: False)
    monkeypatch.setattr("sys.argv", ["howto_install_check.py", "rpios32"])
    with pytest.raises(SystemExit, match="refusing to run outside a container"):
        check.main()
