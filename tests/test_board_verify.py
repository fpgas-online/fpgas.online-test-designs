"""Tests for the Arty/NeTV2/Fomu/TT boot check (designs/_host/board_verify.py) and its debug tool.

No hardware: detection reads a fake sysfs, and every command the check would run (openFPGALoader, openocd, the
host test scripts) goes through a fake runner that records it and answers as the hardware would.
"""

import hashlib
import importlib.util
import json
import pathlib
import struct

import pytest

_HOST = pathlib.Path(__file__).resolve().parents[1] / "designs" / "_host"
_spec = importlib.util.spec_from_file_location("board_verify", _HOST / "board_verify.py")
bv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bv)
_spec = importlib.util.spec_from_file_location("board_debug", _HOST / "board_debug.py")
bdbg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bdbg)

PI3 = "Raspberry Pi 3 Model B Plus Rev 1.3"
PI5 = "Raspberry Pi 5 Model B Rev 1.0"


def _host(board, model=PI3, base=0x3F000000):
    return {"model": model, "port": bv.BOARDS[board]["port"], "lib": pathlib.Path("/lib/x"), "base": base}


def _install(tmp_path, board, corrupt=None):
    """Installed bitstreams for every test and variant of `board`, as fpgas-online-<board>-bitstreams has them."""
    images = tmp_path / "images"
    files = []
    for test in bv.BOARDS[board]["tests"]:
        for variant in bv.BOARDS[board]["variants"]:
            path = bv.artifact_path(board, test, variant)
            data = path.encode()
            (images / path).parent.mkdir(parents=True, exist_ok=True)
            (images / path).write_bytes(b"tampered" if path == corrupt else data)
            files.append({"path": path, "test": test, "variant": variant, "size": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})  # fmt: skip
    (images / "manifest.json").write_text(json.dumps({"board": board, "version": "0.0.post9", "files": files}))
    return images


class Runner:
    """Stands in for _run: records argv, answers from `answers` (first matching substring wins)."""

    def __init__(self, answers=()):
        self.calls, self.answers = [], list(answers)

    def __call__(self, argv, timeout, **kw):
        self.calls.append([str(a) for a in argv])
        line = " ".join(str(a) for a in argv)
        for needle, answer in self.answers:
            if needle in line:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return 0, "ok"


# -- the board table -------------------------------------------------------------------------------------


def test_every_board_has_a_verify_test_and_known_scripts():
    for board, cfg in bv.BOARDS.items():
        assert bv.verify_tests(board), board
        for test in cfg["tests"].values():
            assert test["script"] in bv.SCRIPTS
            assert (_HOST.parents[1] / bv.SCRIPTS[test["script"]]).is_file()


def test_the_board_is_known_from_the_command_it_was_run_as():
    assert bv.board_for_program("/usr/bin/fpgas-arty-verify") == "arty"
    assert bv.board_for_program("fpgas-tt-fpga-debug") == "tt"
    assert bv.board_for_program("fpgas-netv2-verify") == "netv2"
    assert bv.board_for_program("board_verify.py") is None
    assert bv.board_for_program("fpgas-acorn-verify") is None  # the Acorn has its own


def test_artifact_paths_match_the_collect_bitstreams_bundle():
    """As seen in the all-bitstreams artifact of main at cb8191e."""
    assert bv.artifact_path("arty", "uart", "a7-35") == "uart-test-arty/digilent_arty.bit"
    assert bv.artifact_path("arty", "ethernet", "a7-35") == "ethernet-test-arty-a7-35t/digilent_arty.bit"
    assert bv.artifact_path("netv2", "ddr", "a7-100") == "ddr-test-netv2-a7-100t/kosagi_netv2.bit"
    assert bv.artifact_path("fomu", "pmod", "evt") == "gpio-loopback-fomu-evt/top.bin"
    assert bv.artifact_path("tt", "pin-id", "tt-fpga") == "pmod-pin-id-tt-fpga/top.bin"


def test_the_fomu_boot_check_runs_one_test_since_loading_one_leaves_the_bootloader():
    assert bv.verify_tests("fomu") == ["uart"]


# -- detection -------------------------------------------------------------------------------------------


def test_usb_boards_are_found_by_their_ids(tmp_path):
    for name, (v, p) in {"1-1": ("0403", "6010"), "1-2": ("2e8a", "0009")}.items():
        (tmp_path / name).mkdir()
        (tmp_path / name / "idVendor").write_text(v + "\n")
        (tmp_path / name / "idProduct").write_text(p + "\n")
    (tmp_path / "1-1:1.0").mkdir()  # an interface: no IDs
    devices = bv.usb_devices(tmp_path)
    assert devices == [("0403", "6010"), ("2e8a", "0009")]
    assert bv.detect("arty", _host("arty"), devices=devices)["present"]
    assert bv.detect("tt", _host("tt"), devices=devices)["variant"] == "tt-fpga"
    assert not bv.detect("fomu", _host("fomu"), devices=devices)["present"]


def test_idcodes_are_read_from_openocd_and_openfpgaloader():
    openocd = "Info : JTAG tap: xc7.tap tap/device found: 0x0362d093 (mfg: 0x049 (Xilinx), part: 0x362d, ver: 0x0)"
    ofl = "index 0:\n\tidcode 0x13631093\n\tmanufacturer xilinx\n\tfamily artix a7 100t"
    assert bv.xc7_variant(bv.parse_idcodes(openocd)) == ("a7-35", 0x0362D093)
    assert bv.xc7_variant(bv.parse_idcodes(ofl)) == ("a7-100", 0x13631093)  # version nibble ignored
    assert bv.xc7_variant(bv.parse_idcodes("Error: JTAG scan chain interrogation failed: all zeroes")) == (None, None)


def test_the_netv2_is_scanned_with_openocd_on_a_pi3_and_rp1pio_on_a_pi5():
    run = Runner([("--detect", (0, "idcode 0x0362d093"))])
    assert bv.detect("netv2", _host("netv2", PI5, None), run=run)["variant"] == "a7-35"
    assert run.calls[-1][:5] == ["openFPGALoader", "-c", "rp1pio", "--pins", "27:22:4:17"]
    run = Runner([("init; exit", (1, "tap/device found: 0x03631093"))])
    assert bv.detect("netv2", _host("netv2"), run=run)["variant"] == "a7-100"
    argv = run.calls[-1]
    assert argv[0] == "openocd" and "bcm2835gpio peripheral_base 0x3f000000" in argv[2]
    assert "bcm2835gpio jtag_nums 4 17 27 22" in argv[2]  # TCK TMS TDI TDO


def test_the_peripheral_base_is_read_from_the_device_tree(tmp_path):
    pi3, pi4 = tmp_path / "pi3", tmp_path / "pi4"
    pi3.write_bytes(struct.pack(">6I", 0x7E000000, 0x3F000000, 0x01000000, 0x40000000, 0x40000000, 0x1000))
    pi4.write_bytes(struct.pack(">8I", 0x7E000000, 0, 0xFE000000, 0x01800000, 0x7C000000, 0, 0xFC000000, 0x2000000))
    assert bv.peripheral_base(pi3) == 0x3F000000
    assert bv.peripheral_base(pi4) == 0xFE000000


# -- verify ------------------------------------------------------------------------------------------------


def test_no_board_is_none_and_exits_zero(tmp_path):
    report = bv.verify("arty", _host("arty"), _install(tmp_path, "arty"), devices=[])
    assert report["result"] == "none" and bv.exit_code(report) == 0
    assert report["tests"] == []


def test_a_netv2_check_off_a_pi_is_none_not_an_error(tmp_path):
    run = Runner()
    report = bv.verify("netv2", _host("netv2", model="", base=None), _install(tmp_path, "netv2"), run=run)
    assert report["result"] == "none" and "not a Raspberry Pi" in report["reason"]
    assert run.calls == []  # nothing was driven


def test_an_arty_that_passes_loads_each_test_then_runs_it(tmp_path):
    images = _install(tmp_path, "arty")
    run = Runner()
    report = bv.verify("arty", _host("arty"), images, run=run, devices=[("0403", "6010")])
    assert report["result"] == "pass" and bv.exit_code(report) == 0
    assert [t["test"] for t in report["tests"]] == ["uart", "ddr", "spiflash"]
    loads = [c for c in run.calls if c[0] == "openFPGALoader"]
    assert loads[0] == ["openFPGALoader", "-b", "arty", str(images / "uart-test-arty/digilent_arty.bit")]
    tests = [c for c in run.calls if c[1].endswith(".py")]
    assert tests[1][1:] == ["/lib/x/test_ddr.py", "--port", "/dev/ttyUSB1", "--board", "arty"]


def test_a_failing_test_fails_the_check_and_keeps_its_output(tmp_path):
    run = Runner([("test_ddr.py", (1, "Memtest KO\nRESULT: FAIL"))])
    report = bv.verify("arty", _host("arty"), _install(tmp_path, "arty"), run=run, devices=[("0403", "6010")])
    assert report["result"] == "fail" and bv.exit_code(report) == 1
    ddr = report["tests"][1]
    assert ddr["result"] == "fail" and ddr["output"][-1] == "RESULT: FAIL"
    assert report["tests"][2]["result"] == "pass"  # the others still run
    assert "fpgas-arty-debug" in bv.summary(report)


def test_a_load_that_fails_skips_that_test(tmp_path):
    run = Runner([("uart-test-arty", (1, "JTAG init failed"))])
    report = bv.verify("arty", _host("arty"), _install(tmp_path, "arty"), run=run, devices=[("0403", "6010")])
    uart = report["tests"][0]
    assert uart["result"] == "fail" and "programming failed" in uart["reason"]
    assert not any(c[1].endswith("test_uart.py") for c in run.calls if len(c) > 1)


def test_a_damaged_bitstream_is_never_loaded(tmp_path):
    images = _install(tmp_path, "arty", corrupt="ddr-test-arty/digilent_arty.bit")
    run = Runner()
    report = bv.verify("arty", _host("arty"), images, run=run, devices=[("0403", "6010")])
    assert report["tests"][1]["result"] == "error" and "does not match the manifest" in report["tests"][1]["reason"]
    assert not any("ddr-test-arty" in " ".join(c) for c in run.calls)
    assert report["result"] == "error"


def test_a_missing_programmer_is_an_error_not_a_failed_board(tmp_path):
    run = Runner([("openFPGALoader", bv.Problem("error", "openFPGALoader is not installed"))])
    report = bv.verify("arty", _host("arty"), _install(tmp_path, "arty"), run=run, devices=[("0403", "6010")])
    assert {t["result"] for t in report["tests"]} == {"error"}


def test_a_netv2_uses_the_bitstreams_of_the_part_it_found(tmp_path):
    run = Runner([("init; exit", (0, "tap/device found: 0x03631093"))])
    images = _install(tmp_path, "netv2")
    report = bv.verify("netv2", _host("netv2"), images, run=run)
    assert report["variant"] == "a7-100" and report["result"] == "pass"
    loads = [c for c in run.calls if c[0] == "openocd" and "pld load" in c[-1]]
    assert f"pld load 0 {images}/uart-test-netv2-a7-100t/kosagi_netv2.bit" in loads[0][-1]
    assert ["systemctl", "stop", "serial-getty@ttyAMA0.service"] in run.calls


def test_an_unknown_part_on_the_chain_is_an_error(tmp_path):
    run = Runner([("init; exit", (0, "tap/device found: 0x13636093"))])  # an XC7A200T
    report = bv.verify("netv2", _host("netv2"), _install(tmp_path, "netv2"), run=run)
    assert report["result"] == "error" and "0x13636093" in report["reason"]


def test_the_tt_board_is_programmed_through_the_rp2350_bridge(tmp_path):
    images = _install(tmp_path, "tt")
    run = Runner()
    report = bv.verify("tt", _host("tt"), images, run=run, devices=[("2e8a", "0009")])
    assert report["result"] == "pass"
    first = run.calls[0]
    assert first[1:4] == [
        "/lib/x/tt_test_wrapper.py",
        "/dev/ttyACM0",
        str(images / "uart-test-tt-fpga/tt_fpga_platform.bin"),
    ]
    assert first[5:] == ["/lib/x/test_uart.py", "--port", "/dev/ttyACM0", "--board", "tt", "--skip-banner"]
    assert not any("tt_fpga_program.py" in " ".join(c) for c in run.calls)  # the bridge programs it


def test_the_fleet_event_is_flat():
    report = {"result": "fail", "board": "arty", "variant": "a7-35", "bitstreams": "0.0.post9",
              "tests": [{"test": "uart", "result": "pass"},
                        {"test": "ddr", "result": "fail", "reason": "exit 1"}]}  # fmt: skip
    argv = bv.fleet_event_argv(report)
    assert argv[:2] == ["fleet-event", "fpga-verified"]
    details = dict(argv[i + 1].split("=", 1) for i in range(2, len(argv), 2))
    assert details == {"result": "fail", "board": "arty", "variant": "a7-35", "bitstreams": "0.0.post9",
                       "test_uart": "pass", "test_ddr": "fail", "test_ddr_reason": "exit 1"}  # fmt: skip


def test_main_writes_the_report_and_takes_the_board_from_its_name(tmp_path, monkeypatch):
    monkeypatch.setattr(bv, "RUN", tmp_path / "run")
    monkeypatch.setattr(bv, "host_facts", lambda board, port=None: _host(board))
    monkeypatch.setattr(bv, "usb_devices", lambda root=None: [])
    out = tmp_path / "r.json"
    rc = bv.main(["--images", str(_install(tmp_path, "fomu")), "--report", str(out), "--no-publish"],
                 prog="fpgas-fomu-verify")  # fmt: skip
    assert rc == 0 and json.loads(out.read_text())["board"] == "fomu"


# -- the debug tool ------------------------------------------------------------------------------------------


def test_debug_list_shows_every_test_and_whether_the_boot_check_runs_it(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bdbg.bv, "host_facts", lambda board, port=None: _host(board))
    assert bdbg.main(["--images", str(_install(tmp_path, "arty")), "list"], prog="fpgas-arty-debug") == 0
    out = capsys.readouterr().out
    assert "ddr        a7-35    boot check" in out and "pin-id     a7-35    debug only" in out
    assert "(not installed)" not in out


def test_debug_check_finds_a_damaged_bitstream(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(bdbg.bv, "host_facts", lambda board, port=None: _host(board))
    images = _install(tmp_path, "fomu", corrupt="gpio-loopback-fomu-evt/top.bin")
    assert bdbg.main(["--images", str(images), "check"], prog="fpgas-fomu-debug") == 1
    assert "BAD" in capsys.readouterr().out


def test_debug_test_loads_then_runs_with_extra_arguments(tmp_path, monkeypatch):
    monkeypatch.setattr(bdbg.bv, "host_facts", lambda board, port=None: _host(board))
    monkeypatch.setattr(bdbg.bv, "RUN", tmp_path / "run")
    ran = []
    monkeypatch.setattr(bdbg, "_live", lambda argv: ran.append([str(a) for a in argv]) or 0)
    images = _install(tmp_path, "arty")
    rc = bdbg.main(["--images", str(images), "test", "pin-id", "--", "--hat-port", "JA"], prog="fpgas-arty-debug")
    assert rc == 0
    assert ran[0] == ["rmmod", "spidev", "spi_bcm2835"]
    assert ran[1] == ["openFPGALoader", "-b", "arty", str(images / "pmod-pin-id-arty-a7-35t/top.bit")]
    assert ran[2][1:] == ["/lib/x/identify_pmod_pins.py", "--hat-port", "JA"]


def test_debug_refuses_a_test_the_board_does_not_have(tmp_path):
    with pytest.raises(SystemExit):
        bdbg.main(["test", "ddr"], prog="fpgas-fomu-debug")
