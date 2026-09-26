"""Tests for the board modules (fpgas_online_verify.boards) and fpgas-<board>-debug, with no hardware.

Detection reads a fake sysfs, and every command a check would run (openFPGALoader, openocd, the host test
scripts) goes through a fake runner that records it and answers as the hardware would.
"""

import hashlib
import json
import struct

import pytest
from fpgas_online_verify import cli, core, debug, host_tests
from fpgas_online_verify.boards import arty, fomu, netv2, tt_fpga
from fpgas_online_verify.boards.acorn import BOARD as ACORN
from fpgas_online_verify.boards.acorn import check as acorn_check

PI3 = "Raspberry Pi 3 Model B Plus Rev 1.3"
PI5 = "Raspberry Pi 5 Model B Rev 1.0"
ARTY, NETV2, FOMU, TT = arty.BOARD, netv2.BOARD, fomu.BOARD, tt_fpga.BOARD


def _host(board, model=PI3, base=0x3F000000):
    return {"model": model, "port": board.port, "base": base}


def _install(tmp_path, board, corrupt=None):
    """Installed bitstreams for every test and variant, as fpgas-online-<board>-bitstreams has them."""
    images = tmp_path / "images"
    files = []
    for test in board.tests:
        for variant in board.variants:
            path = board.artifact(test, variant)
            data = path.encode()
            (images / path).parent.mkdir(parents=True, exist_ok=True)
            (images / path).write_bytes(b"tampered" if path == corrupt else data)
            files.append({"path": path, "test": test, "variant": variant, "size": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})  # fmt: skip
    (images / "manifest.json").write_text(json.dumps({"board": board.name, "version": "0.0.post9", "files": files}))
    return images


class Runner:
    """Stands in for core.run: records argv, answers from `answers` (the first needle found wins). A dump
    request writes `flash` to the output file."""

    def __init__(self, answers=(), flash=None):
        self.calls, self.answers, self.flash = [], list(answers), flash

    def __call__(self, argv, timeout, **kw):
        argv = [str(a) for a in argv]
        self.calls.append(argv)
        line = " ".join(argv)
        if "--dump-flash" in argv and self.flash is not None:
            with open(argv[-1], "wb") as f:
                f.write(self.flash)
        for needle, answer in self.answers:
            if needle in line:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return 0, "ok"


# -- what the boards are ---------------------------------------------------------------------------------


def test_every_test_names_a_known_host_script_that_exists():
    for board in (ARTY, NETV2, FOMU, TT):
        assert board.verify_tests, board.name
        for test in board.tests.values():
            assert host_tests.path(test["script"]).is_file(), test["script"]


def test_artifact_paths_match_the_collect_bitstreams_bundle():
    """As seen in the all-bitstreams artifact of main at cb8191e, and the DDR/SPI-flash artifacts beside it."""
    assert ARTY.artifact("uart", "a7-35") == "uart-test-arty/digilent_arty.bit"
    assert ARTY.artifact("ethernet", "a7-35") == "ethernet-test-arty-a7-35t/digilent_arty.bit"
    assert NETV2.artifact("ddr", "a7-100") == "ddr-test-netv2-a7-100t/kosagi_netv2.bit"
    assert FOMU.artifact("pmod", "evt") == "gpio-loopback-fomu-evt/top.bin"
    assert TT.artifact("pin-id", "tt-fpga") == "pmod-pin-id-tt-fpga/top.bin"


def test_the_fomu_boot_check_runs_one_test_since_a_load_uses_up_the_bootloader():
    assert FOMU.verify_tests == ["uart"]


# -- detection -------------------------------------------------------------------------------------------


def _usb(tmp_path, **devices):
    for name, (v, p, serial) in devices.items():
        d = tmp_path / name
        d.mkdir()
        (d / "idVendor").write_text(v + "\n")
        (d / "idProduct").write_text(p + "\n")
        if serial:
            (d / "serial").write_text(serial + "\n")
    (tmp_path / "1-1:1.0").mkdir()  # an interface: no IDs
    return core.usb_devices(tmp_path)


def test_usb_boards_are_found_with_their_serial(tmp_path):
    usb = _usb(tmp_path, **{"1-1": ("0403", "6010", "210319B0C2F1"), "1-2": ("2E8A", "0009", "E66164084")})
    assert ARTY.spot(_host(ARTY), usb, []) == [{"variant": "a7-35", "usb": "1-1", "serial": "210319B0C2F1"}]
    assert TT.spot(_host(TT), usb, [])[0]["serial"] == "E66164084"  # hex case normalised: 2E8A matches
    assert FOMU.spot(_host(FOMU), usb, []) == []


def test_the_acorn_is_spotted_on_pci_and_other_xilinx_designs_are_not_claimed():
    pci = [
        {"bdf": "0001:01:00.0", "vendor": 0x10EE, "device": 0x7021,
         "subsystem_vendor": 0x1E24, "subsystem_device": 0x021F},
        {"bdf": "0002:01:00.0", "vendor": 0x10EE, "device": 0x7021,
         "subsystem_vendor": 0x10EE, "subsystem_device": 0x0007},
        {"bdf": "0003:01:00.0", "vendor": 0x14E4, "device": 0x1234, "subsystem_vendor": 0, "subsystem_device": 0},
    ]  # fmt: skip
    (found,) = ACORN.spot({}, [], pci)
    assert found["bdf"] == "0001:01:00.0" and found["kind"] == "fpgas-online" and found["variant"] == "cle-215+"


def test_idcodes_are_read_from_openocd_and_openfpgaloader():
    openocd = "Info : JTAG tap: xc7.tap tap/device found: 0x0362d093 (mfg: 0x049 (Xilinx), part: 0x362d, ver: 0x0)"
    ofl = "index 0:\n\tidcode 0x13631093\n\tmanufacturer xilinx\n\tfamily artix a7 100t"
    assert netv2.part_of(netv2.parse_idcodes(openocd)) == ("a7-35", 0x0362D093)
    assert netv2.part_of(netv2.parse_idcodes(ofl)) == ("a7-100", 0x13631093)  # revision nibble ignored
    assert netv2.part_of(netv2.parse_idcodes("Error: JTAG scan chain interrogation failed: all zeroes")) == (None, None)


def test_the_netv2_is_scanned_with_openocd_on_a_pi3_and_rp1pio_on_a_pi5():
    run = Runner([("--detect", (0, "idcode 0x0362d093"))])
    assert NETV2.probe(_host(NETV2, PI5, None), runner=run) == [{"variant": "a7-35", "idcode": "0x0362d093"}]
    assert run.calls[-1][:5] == ["openFPGALoader", "-c", "rp1pio", "--pins", "27:22:4:17"]
    run = Runner([("init; exit", (1, "tap/device found: 0x03631093"))])
    assert NETV2.probe(_host(NETV2), runner=run)[0]["variant"] == "a7-100"
    argv = run.calls[-1]
    assert argv[0] == "openocd" and "bcm2835gpio peripheral_base 0x3f000000" in argv[2]
    assert "bcm2835gpio jtag_nums 4 17 27 22" in argv[2]  # TCK TMS TDI TDO


def test_the_netv2_is_not_scanned_off_a_pi_and_an_empty_chain_is_no_board():
    run = Runner()
    assert NETV2.probe(_host(NETV2, model=""), runner=run) == [] and run.calls == []
    assert NETV2.probe(_host(NETV2), runner=Runner([("init", (1, "all zeroes"))])) == []


def test_an_unknown_part_on_the_chain_is_an_error():
    with pytest.raises(core.Problem, match="0x13636093"):
        NETV2.probe(_host(NETV2), runner=Runner([("init", (0, "tap/device found: 0x13636093"))]))


def test_the_peripheral_base_is_read_from_the_device_tree(tmp_path):
    pi3, pi4 = tmp_path / "pi3", tmp_path / "pi4"
    pi3.write_bytes(struct.pack(">6I", 0x7E000000, 0x3F000000, 0x01000000, 0x40000000, 0x40000000, 0x1000))
    pi4.write_bytes(struct.pack(">8I", 0x7E000000, 0, 0xFE000000, 0x01800000, 0x7C000000, 0, 0xFC000000, 0x2000000))
    assert core.peripheral_base(pi3) == 0x3F000000
    assert core.peripheral_base(pi4) == 0xFE000000


# -- checks ------------------------------------------------------------------------------------------------


def _check(board, tmp_path, found, run, **options):
    return board.check(_host(board), found, {"images": _install(tmp_path, board, options.pop("corrupt", None)),
                                             **options}, runner=run)  # fmt: skip


ARTY_FOUND = {"variant": "a7-35", "usb": "1-1", "serial": "210319B"}


def test_an_arty_that_passes_loads_each_test_runs_it_and_records_its_flash(tmp_path):
    flash = b"\x5a" * ARTY.flash_region["a7-35"]
    run = Runner([("test_spiflash.py", (0, "JEDEC ID: 0x20 0xBA 0x18\nRESULT: PASS"))], flash=flash)
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "pass", report
    assert [t["test"] for t in report["tests"]] == ["uart", "ddr", "spiflash"]
    images = tmp_path / "images"
    assert run.calls[1] == ["openFPGALoader", "-b", "arty", str(images / "uart-test-arty/digilent_arty.bit")]
    assert run.calls[-1][:5] == ["openFPGALoader", "-b", "arty", "--dump-flash", "--file-size"]
    sha = hashlib.sha256(flash).hexdigest()
    assert report["state"] == {"variant": "a7-35", "serial": "210319B", "flash_jedec": "0x20ba18",
                               "flash": {"region_bytes": 0x220000, "sha256": sha}}  # fmt: skip


def test_a_failing_test_fails_the_check_and_keeps_its_output(tmp_path):
    run = Runner([("test_ddr.py", (1, "Memtest KO\nRESULT: FAIL"))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "fail" and "ddr fail" in report["reason"]
    ddr = report["tests"][1]
    assert ddr["output"][-1] == "RESULT: FAIL" and report["tests"][2]["result"] == "pass"


def test_a_load_that_fails_skips_that_test(tmp_path):
    run = Runner([("uart-test-arty", (1, "JTAG init failed"))], flash=b"\0" * ARTY.flash_region["a7-35"])
    uart = _check(ARTY, tmp_path, ARTY_FOUND, run)["tests"][0]
    assert uart["result"] == "fail" and "loading it failed" in uart["reason"]
    assert not any(c[1].endswith("test_uart.py") for c in run.calls if len(c) > 1)


def test_a_damaged_bitstream_is_never_loaded(tmp_path):
    run = Runner(flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run, corrupt="ddr-test-arty/digilent_arty.bit")
    assert report["tests"][1]["result"] == "error" and "does not match its manifest" in report["tests"][1]["reason"]
    assert not any("ddr-test-arty" in " ".join(c) for c in run.calls)


def test_a_flash_that_cannot_be_read_back_is_an_error(tmp_path):
    run = Runner([("--dump-flash", (1, "unable to open spiOverJtag"))])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "error" and "reading back the flash failed" in report["reason"]
    assert "flash" not in report["state"]  # so nothing is compared with a flash that was not read


def test_a_netv2_on_a_pi3_loads_with_openocd_and_frees_its_uart(tmp_path):
    run = Runner(flash=b"\0" * NETV2.flash_region["a7-100"])
    report = _check(NETV2, tmp_path, {"variant": "a7-100", "idcode": "0x13631093"}, run)
    assert report["result"] == "pass", report
    loads = [c for c in run.calls if c[0] == "openocd"]
    assert f"pld load 0 {tmp_path}/images/uart-test-netv2-a7-100t/kosagi_netv2.bit" in loads[0][-1]
    assert ["systemctl", "stop", "serial-getty@ttyAMA0.service"] in run.calls
    dump = run.calls[-1]
    assert dump[:3] == ["openFPGALoader", "--cable", "libgpiod"] and "xc7a100tfgg484" in dump
    assert report["state"]["idcode"] == "0x13631093"


def test_a_netv2_on_a_pi5_loads_with_rp1pio_and_muxes_its_uart(tmp_path):
    run = Runner(flash=b"\0" * NETV2.flash_region["a7-35"])
    report = NETV2.check(_host(NETV2, PI5, None), {"variant": "a7-35"},
                         {"images": _install(tmp_path, NETV2)}, runner=run)  # fmt: skip
    assert report["result"] == "pass"
    assert run.calls[1][:3] == ["pinctrl", "set", "14"]
    assert any(c[:3] == ["openFPGALoader", "-c", "rp1pio"] and c[-1].endswith("kosagi_netv2.bit") for c in run.calls)


def test_the_tt_board_loads_and_tests_through_the_rp2350_bridge_and_does_not_read_flash(tmp_path):
    run = Runner()
    report = _check(TT, tmp_path, {"variant": "tt-fpga", "usb": "1-2", "serial": "E6"}, run)
    assert report["result"] == "pass"
    first = run.calls[0]
    assert first[1].endswith("tt_test_wrapper.py") and first[2] == "/dev/ttyACM0"
    assert first[3].endswith("uart-test-tt-fpga/tt_fpga_platform.bin") and first[5].endswith("test_uart.py")
    assert not any("tt_fpga_program.py" in " ".join(c) for c in run.calls)  # the bridge loads it
    assert report["state"] == {"variant": "tt-fpga", "serial": "E6"} and "rewrites" in report["flash_note"]


def test_the_fomu_state_is_its_serial_only(tmp_path):
    report = _check(FOMU, tmp_path, {"variant": "evt", "usb": "1-3", "serial": "fomu-7"}, Runner())
    assert report["result"] == "pass" and report["state"] == {"variant": "evt", "serial": "fomu-7"}


def test_the_acorn_state_is_its_slot_and_flash_contents(tmp_path, monkeypatch):
    found = {"bdf": "0001:01:00.0", "ids": "10ee:7021", "subsystem": "1e24:021f", "kind": "fpgas-online",
             "variant": "cle-215+"}  # fmt: skip
    monkeypatch.setattr(acorn_check, "load_release", lambda images: ({"tag": "t"}, {}))
    flash = {"part": "S25FL256S", "jedec": "0x010219", "unique_id": "ab",
             "slots": [{"slot": "0x000000", "result": "match", "sha256": "g"},
                       {"slot": "0x400000", "result": "match", "sha256": "o"}]}  # fmt: skip
    monkeypatch.setattr(acorn_check, "check_board", lambda *a: {**found, "result": "pass", "flash": flash})
    report = ACORN.check({}, found, {"images": tmp_path})
    assert report["result"] == "pass" and report["bitstreams"] == "t"
    assert report["state"] == {"bdf": "0001:01:00.0", "ids": "10ee:7021", "subsystem": "1e24:021f",
                               "variant": "cle-215+", "flash": {"part": "S25FL256S", "jedec": "0x010219",
                               "unique_id": "ab", "slots": {"0x000000": "g", "0x400000": "o"}}}  # fmt: skip


# -- the commands and the debug tool ---------------------------------------------------------------------------


def test_the_board_commands_take_the_board_from_their_name(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.runner, "run", lambda options, prog: seen.update(options, prog=prog) or 0)
    assert cli.board_main(["--no-publish"], prog="fpgas-tt-fpga-verify") == 0
    assert seen["board"] == "tt" and seen["prog"] == "fpgas-tt-fpga-verify"
    with pytest.raises(SystemExit):
        cli.board_main([], prog="fpgas-nothing-verify")


def test_debug_list_shows_every_test_and_whether_the_boot_check_runs_it(tmp_path, capsys):
    args = cli.argparse.Namespace(command="list", images=_install(tmp_path, ARTY), variant=None, port=None)
    assert debug.run(ARTY, args) == 0
    out = capsys.readouterr().out
    assert "ddr        a7-35    boot check" in out and "pin-id     a7-35    debug only" in out
    assert "(not installed)" not in out


def test_debug_check_finds_a_damaged_bitstream(tmp_path, capsys):
    images = _install(tmp_path, FOMU, corrupt="gpio-loopback-fomu-evt/top.bin")
    args = cli.argparse.Namespace(command="check", images=images, variant=None, port=None)
    assert debug.run(FOMU, args) == 1
    assert "BAD" in capsys.readouterr().out


def test_debug_test_loads_then_runs_with_extra_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(ARTY, "facts", lambda port=None: _host(ARTY))
    monkeypatch.setattr(debug, "hold_lock", lambda *a: _Nothing())
    ran = []
    monkeypatch.setattr(debug, "_live", lambda argv: ran.append([str(a) for a in argv]) or 0)
    images = _install(tmp_path, ARTY)
    args = cli.argparse.Namespace(command="test", test="pin-id", extra=["--hat-port", "JA"], images=images,
                                  variant=None, port=None)  # fmt: skip
    assert debug.run(ARTY, args) == 0
    assert ran[0] == ["rmmod", "spidev", "spi_bcm2835"]
    assert ran[1] == ["openFPGALoader", "-b", "arty", str(images / "pmod-pin-id-arty-a7-35t/top.bit")]
    assert ran[2][1].endswith("identify_pmod_pins.py") and ran[2][2:] == ["--hat-port", "JA"]


def test_the_acorn_debug_tool_can_identify_and_has_no_test_loading():
    assert set(debug.commands(ACORN)) == {"detect", "identify"}
    assert {"detect", "list", "check", "program", "test"} == set(debug.commands(ARTY))


class _Nothing:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
