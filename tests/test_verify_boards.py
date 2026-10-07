"""Tests for the board modules (fpgas_online_verify.boards) and fpgas-<board>-debug, with no hardware.

Detection reads a fake sysfs, and every command a check would run (openFPGALoader, openocd, the host test
scripts) goes through a fake runner that records it and answers as the hardware would.
"""

import hashlib
import importlib.util
import json
import struct
import sys

import pytest
from fpgas_online_verify import (
    cli,
    conclusion,
    core,
    debug,
    host_tests,
    idcode,
    identify,
    identity,
    runner,
    testbench,
)
from fpgas_online_verify.boards import arty, fomu, netv2, tt_fpga
from fpgas_online_verify.boards.acorn import BOARD as ACORN

PI3 = "Raspberry Pi 3 Model B Plus Rev 1.3"
PI5 = "Raspberry Pi 5 Model B Rev 1.0"
ARTY, NETV2, FOMU, TT = arty.BOARD, netv2.BOARD, fomu.BOARD, tt_fpga.BOARD


@pytest.fixture(autouse=True)
def no_rpi_hwid(monkeypatch):
    """rpi-hwid is not installed unless a test says it is, whatever this machine has on PATH."""
    monkeypatch.setattr(tt_fpga, "which", lambda name: None)


def _host(board, model=PI3, base=0x3F000000):
    return {"model": model, "port": board.port, "base": base}


def _install(tmp_path, board, corrupt=None):
    """Installed bitstreams for every test and variant, as fpgas-online-<board>-bitstreams has them."""
    images = tmp_path / "images"
    files = []
    for test, variant, path in board.artifacts():
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
                if isinstance(answer, list):  # one answer for each call, in turn; the last for any after
                    answer = answer.pop(0) if len(answer) > 1 else answer[0]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        if "--detect" in argv:  # the Arty's JTAG scan
            return 0, ARTY_SCAN
        if "--read-dna" in argv:
            return 0, DNA_LINE
        if argv[:2] == ["pinctrl", "get"]:  # every pin an input, pulled down
            return 0, "".join(f"{g}: ip    pd | lo // GPIO{g} = input\n" for g in argv[2].split(","))
        return 0, "ok"


def _scan(*codes):
    """openFPGALoader --detect --verbose-level 2's raw scan of a chain of `codes`."""
    lines = [f"- {i} -> {c:#010x}" for i, c in enumerate([*codes, 0xFFFFFFFF])]
    return "Raw IDCODE:\n" + "\n".join(lines) + "\nFetched TDI, end-of-chain\n"


ARTY_SCAN = _scan(0x0362D093) + "index 0:\n\tidcode 0x362d093\n\tmanufacturer xilinx\n\tfamily artix a7 35t\n"
DNA = "0x0054b48664b04854"
DNA_LINE = '{"dna": "0x0054b48664b04854"}\n'  # openFPGALoader --read-dna's output


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
    assert FOMU.artifact("pmod", "evt") == "gpio-loopback-fomu-evt/kosagi_fomu_evt.bin"
    assert TT.artifact("pin-id", "tt-fpga") == "pmod-pin-id-tt-fpga/tt_fpga_platform.bin"


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
    usb = _usb(tmp_path, **{"1-1": ("0403", "6010", "210319B0C2F1"), "1-2": ("2E8A", "0005", "E66164084")})
    assert ARTY.spot(_host(ARTY), usb, []) == [{"variant": "a7-35", "usb": "1-1", "serial": "210319B0C2F1"}]
    # hex case normalised: 2E8A matches. No variant: an RP2 on USB does not say which Tiny Tapeout board it is.
    (tt,) = TT.spot(_host(TT), usb, [])
    assert tt == {"variant": None, "usb": "1-2", "serial": "E66164084", "usb_id": "2e8a:0005"}
    assert FOMU.spot(_host(FOMU), usb, []) == []


def test_the_acorn_claims_every_xilinx_endpoint_and_fails_a_design_it_did_not_build():
    """pi-sw2-p37 runs a LiteX PCIe design with the Xilinx default subsystem (10ee:0007): an FPGA is there,
    so it is a board that fails, never "missing"."""
    pci = [
        {"bdf": "0001:01:00.0", "vendor": 0x10EE, "device": 0x7021,
         "subsystem_vendor": 0x1E24, "subsystem_device": 0x021F},
        {"bdf": "0002:01:00.0", "vendor": 0x10EE, "device": 0x7021,
         "subsystem_vendor": 0x10EE, "subsystem_device": 0x0007},
        {"bdf": "0003:01:00.0", "vendor": 0x14E4, "device": 0x1234, "subsystem_vendor": 0, "subsystem_device": 0},
    ]  # fmt: skip
    ours, other = ACORN.spot({}, [], pci)
    assert ours["bdf"] == "0001:01:00.0" and ours["kind"] == "fpgas-online" and ours["variant"] == "cle-215+"
    assert other["bdf"] == "0002:01:00.0" and other["kind"] == "litex-other"
    report = ACORN.check({}, other, {"images": "/nonexistent"})
    assert report["result"] == "fail" and "not a design we built" in report["reason"]
    assert report["tests"] == []  # nothing is sent to a design we did not build


def test_a_pi_with_no_pci_or_usb_bus_has_no_devices_and_finds_no_acorn(tmp_path):
    """A Pi 3, or an Orange Pi, has no /sys/bus/pci at all (#43): no devices, not a crash."""
    assert core.pci_devices(tmp_path / "no-such-bus") == [] and core.usb_devices(tmp_path / "nor-this") == []
    assert ACORN.spot({}, [], core.pci_devices(tmp_path / "no-such-bus")) == []


def test_idcodes_are_read_whole_from_openocd_and_openfpgaloader():
    openocd = "Info : JTAG tap: xc7.tap tap/device found: 0x0362d093 (mfg: 0x049 (Xilinx), part: 0x362d, ver: 0x0)"
    ofl = _scan(0x13631093) + "index 0:\n\tidcode 0x3631093\n\tmanufacturer xilinx\n\tfamily artix a7 100t"
    assert netv2.part_of(idcode.parse(openocd)) == ("a7-35", 0x0362D093)
    assert netv2.part_of(idcode.parse(ofl)) == ("a7-100", 0x13631093)  # any version of the part
    assert netv2.part_of(idcode.parse("Error: JTAG scan chain interrogation failed: all zeroes")) == (None, None)


def test_the_netv2_is_scanned_with_openocd_on_a_pi3_and_rp1pio_on_a_pi5():
    run = Runner([("--detect", (0, _scan(0x1362D093)))])
    scan = {"tool": "openFPGALoader", "exit": 0, "output": ["- 0 -> 0x1362d093", "- 1 -> 0xffffffff"]}
    assert NETV2.probe(_host(NETV2, PI5, None), runner=run) == [
        {"variant": "a7-35", "idcode": "0x1362d093", "idcodes": ["0x1362d093"], "idcode_scan": scan}
    ]
    assert run.calls[1] == ["openFPGALoader", "-c", "rp1pio", "--pins", "27:22:4:17", "--detect",
                             "--verbose-level", "2"]  # fmt: skip
    run = Runner([("init; exit", (1, "tap/device found: 0x03631093"))])
    assert NETV2.probe(_host(NETV2), runner=run)[0]["variant"] == "a7-100"
    argv = run.calls[1]  # between reading the pins and putting them back
    assert argv[0] == "openocd" and "bcm2835gpio peripheral_base 0x3f000000" in argv[2]
    assert "bcm2835gpio jtag_nums 4 17 27 22" in argv[2]  # TCK TMS TDI TDO


def test_the_netv2_is_not_scanned_off_a_pi_and_an_empty_chain_is_no_board():
    run = Runner()
    assert NETV2.probe(_host(NETV2, model=""), runner=run) == [] and run.calls == []
    assert NETV2.probe(_host(NETV2), runner=Runner([("init", (1, "all zeroes"))])) == []


NETV2_PINS = "4: op dh pn | hi // GPIO4 = output\n17: ip pu | hi // GPIO17 = input\n" \
             "27: a3 pn | lo // GPIO27 = SPI\n22: ip pd | lo // GPIO22 = input\n"  # fmt: skip


def test_the_netv2_scan_puts_its_jtag_pins_back_as_they_were():
    run = Runner([("pinctrl get", (0, NETV2_PINS)), ("init; exit", (0, "tap/device found: 0x03631093"))])
    assert NETV2.probe(_host(NETV2), runner=run)[0]["variant"] == "a7-100"
    assert run.calls[0] == ["pinctrl", "get", "4,17,27,22"]
    assert run.calls[1][0] == "openocd"
    # an output goes back as an input (openocd leaves its outputs driven); the rest exactly as they were
    assert run.calls[2:] == [["pinctrl", "set", "4", "ip", "pn"], ["pinctrl", "set", "17", "ip", "pu"],
                             ["pinctrl", "set", "22", "ip", "pd"], ["pinctrl", "set", "27", "a3", "pn"]]  # fmt: skip


# A Pi 3's SoC cannot read a pin's pull back, so pinctrl prints "--" for it (pi-sw1-p10, 2026-10-04).
PI3_PINS = "4: ip    -- | hi // GPIO4 = input\n17: ip    -- | hi // GPIO17 = input\n" \
           "22: ip    -- | hi // GPIO22 = input\n27: op -- -- | lo // GPIO27 = output\n"  # fmt: skip


def test_the_netv2_is_scanned_on_a_pi_whose_pulls_cannot_be_read():
    """The pull pinctrl could not read is not set when the pin goes back: nothing here changes a pull."""
    run = Runner([("pinctrl get", (0, PI3_PINS)), ("init; exit", (0, "tap/device found: 0x0362d093"))])
    assert NETV2.probe(_host(NETV2), runner=run)[0]["variant"] == "a7-35"
    assert core.pin_states(Runner([("pinctrl get", (0, PI3_PINS))]), [4, 17, 22, 27]) == {
        4: ("ip", "--", "hi"), 17: ("ip", "--", "hi"), 22: ("ip", "--", "hi"), 27: ("op", "--", "lo")}  # fmt: skip
    assert run.calls[2:] == [["pinctrl", "set", "4", "ip"], ["pinctrl", "set", "17", "ip"],
                             ["pinctrl", "set", "22", "ip"], ["pinctrl", "set", "27", "ip"]]  # fmt: skip


def test_an_output_is_read_where_its_drive_cannot_be():
    """Only a Pi 5 (RP1) reads an output's drive back; a Pi 3 and a Pi 4 print "--" for it (pinctrl.c prints
    the drive, then the pull). The level column says what the pin is at."""
    pi4 = "8: op -- pd | lo // GPIO8 = output\n7: op -- pu | hi // GPIO7 = output\n"
    assert core.pin_states(Runner([("pinctrl get", (0, pi4))]), [8, 7]) == {
        8: ("op", "pd", "lo"), 7: ("op", "pu", "hi")}  # fmt: skip
    pi5 = "8: op dl pd | lo // GPIO8 = output\n"
    assert core.pin_states(Runner([("pinctrl get", (0, pi5))]), [8]) == {8: ("op", "pd", "lo")}


def test_an_output_whose_pull_cannot_be_read_goes_back_at_its_level():
    run = Runner()
    assert core.restore_pins(run, {27: ("op", "--", "lo"), 4: ("a0", "--", "hi")}) == []
    assert run.calls == [["pinctrl", "set", "4", "a0"], ["pinctrl", "set", "27", "op", "dl"]]


def test_the_netv2_pins_go_back_even_when_the_scan_fails():
    run = Runner([("pinctrl get", (0, NETV2_PINS)), ("init; exit", core.Problem("fail", "openocd hung"))])
    with pytest.raises(core.Problem, match="openocd hung"):
        NETV2.probe(_host(NETV2), runner=run)
    assert [c[:3] for c in run.calls[2:]] == [["pinctrl", "set", g] for g in ("4", "17", "22", "27")]


def test_the_netv2_is_not_scanned_when_its_pins_cannot_be_put_back():
    run = Runner([("pinctrl get", core.Problem("error", "pinctrl is not installed"))])
    with pytest.raises(core.Problem, match=r"not scanned.*pinctrl is not installed"):
        NETV2.probe(_host(NETV2), runner=run)
    assert run.calls == [["pinctrl", "get", "4,17,27,22"]]  # no openocd, nothing driven
    run = Runner([("pinctrl set", (1, "no such pin")), ("init; exit", (0, "tap/device found: 0x03631093"))])
    with pytest.raises(core.Problem, match="could not put GPIO4 back"):
        NETV2.probe(_host(NETV2), runner=run)


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


def _netv2_found(code):
    """The NeTV2 as finding it on a Pi 3 reports it: its OpenOCD scan answered `code`."""
    (found,) = NETV2.probe(_host(NETV2), runner=Runner([("init; exit", (0, f"tap/device found: {code}"))]))
    return found


def test_an_arty_that_passes_loads_each_test_runs_it_and_records_its_flash(tmp_path):
    flash = b"\x5a" * ARTY.flash_region["a7-35"]
    run = Runner([("test_spiflash.py", (0, "JEDEC ID: 0x20 0xBA 0x18\nRESULT: PASS"))], flash=flash)
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "pass", report
    assert [t["test"] for t in report["tests"]] == ["uart", "ddr", "spiflash", "ethernet", "pin-id"]
    images = tmp_path / "images"
    assert run.calls[0] == ["openFPGALoader", "-b", "arty", "--detect", "--verbose-level", "2"]
    assert run.calls[1] == ["openFPGALoader", "-b", "arty", "--read-dna"]  # same cable, before anything loads
    assert run.calls[3] == ["openFPGALoader", "-b", "arty", str(images / "uart-test-arty/digilent_arty.bit")]
    assert run.calls[-1][:5] == ["openFPGALoader", "-b", "arty", "--dump-flash", "--file-size"]
    assert {k: v for k, v in report["jtag"].items() if k != "output"} == {
        "result": "pass", "idcode": "0x0362d093", "idcode_version": 0, "idcode_part_number": "0x362d",
        "idcode_manufacturer_id": "0x049", "idcode_manufacturer": "Xilinx", "idcode_device": "XC7A35T",
        "dna": DNA}  # fmt: skip
    sha = hashlib.sha256(flash).hexdigest()
    assert report["state"] == {"variant": "a7-35", "serial": "210319B", "idcode": "0x0362d093", "dna": DNA,
                               "flash_jedec": "0x20ba18",
                               "flash": {"region_bytes": 0x220000, "sha256": sha}}  # fmt: skip


def test_an_arty_whose_jtag_answers_with_another_part_fails_and_says_which(tmp_path):
    run = Runner([("--detect", (0, _scan(0x13631093)))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "fail" and report["jtag"]["result"] == "fail"
    assert report["reason"].startswith(
        "jtag fail: the JTAG IDCODE 0x13631093 is an XC7A100T, not the a7-35's XC7A35T (IDCODE 0x0362d093, any version)"
    )
    assert report["state"]["idcode"] == "0x13631093"


def test_an_arty_whose_jtag_chain_is_empty_fails_and_an_arty_of_another_version_passes(tmp_path):
    scan = (1, "Raw IDCODE:\n- 0 -> 0xffffffff\nJTAG init failed: no device found\n")
    run = Runner([("--detect", scan)], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "fail"
    assert report["jtag"]["reason"] == "no device on the JTAG chain; openFPGALoader exited 1 reading the IDCODE"
    run = Runner([("--detect", (0, _scan(0x2362D093)))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "pass" and (report["jtag"]["idcode"], report["jtag"]["idcode_version"]) == (
        "0x2362d093",
        2,
    )


def test_an_arty_scan_without_the_raw_idcodes_says_so_not_that_the_chain_is_empty(tmp_path):
    part_table = "found 1 devices\nindex 0:\n\tidcode 0x362d093\n\tmanufacturer xilinx\n\tfamily artix a7 35t\n"
    run = Runner([("--detect", (0, part_table))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "fail"
    assert report["jtag"]["reason"] == "openFPGALoader printed no raw IDCODE scan (needs --verbose-level 2 output)"
    run = Runner([("--detect", (0, "found 0 devices\n"))], flash=b"\0" * ARTY.flash_region["a7-35"])
    assert _check(ARTY, tmp_path, ARTY_FOUND, run)["jtag"]["reason"] == "no device on the JTAG chain"


def test_an_arty_scan_that_fails_before_scanning_says_the_tool_failed_and_why(tmp_path):
    text = "write to ftdi failed\nunable to open ftdi device: -3 (device not found)\n\n"
    run = Runner([("--detect", (1, text))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "fail" and report["jtag"]["reason"] == (
        "openFPGALoader failed (exit 1) before scanning the JTAG chain: "
        "unable to open ftdi device: -3 (device not found)"
    )
    assert report["jtag"]["output"] == ["write to ftdi failed", "unable to open ftdi device: -3 (device not found)"]
    run = Runner([("--detect", (1, ""))], flash=b"\0" * ARTY.flash_region["a7-35"])
    reason = _check(ARTY, tmp_path, ARTY_FOUND, run)["jtag"]["reason"]
    assert reason == "openFPGALoader failed (exit 1) before scanning the JTAG chain: no output"


def test_an_arty_scan_that_exits_non_zero_fails_even_with_the_right_idcode(tmp_path):
    run = Runner([("--detect", (2, ARTY_SCAN))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "fail" and report["jtag"]["result"] == "fail"
    assert report["jtag"]["reason"] == "openFPGALoader exited 2 reading the IDCODE"
    assert report["jtag"]["idcode_device"] == "XC7A35T"  # still decoded, for the report


def test_an_arty_of_the_wrong_part_whose_scan_exits_non_zero_gives_both_faults(tmp_path):
    run = Runner([("--detect", (1, _scan(0x13631093)))], flash=b"\0" * ARTY.flash_region["a7-35"])
    reason = _check(ARTY, tmp_path, ARTY_FOUND, run)["jtag"]["reason"]
    assert reason.startswith("the JTAG IDCODE 0x13631093 is an XC7A100T") and reason.endswith(
        "; openFPGALoader exited 1 reading the IDCODE"
    )


@pytest.mark.parametrize(
    ("model", "needle", "text", "tool"),
    [
        (PI3, "init; exit", "Info : JTAG tap: xc7.tap tap/device found: 0x03631093 (mfg: 0x049 (Xilinx))", "openocd"),
        (PI5, "--detect", _scan(0x03631093), "openFPGALoader"),
    ],
    ids=["openocd-pi3", "rp1pio-pi5"],
)
def test_a_netv2_whose_finding_scan_exits_non_zero_fails_even_with_the_right_idcode(tmp_path, model, needle, text,
                                                                                    tool):  # fmt: skip
    host = _host(NETV2, model, None if model == PI5 else 0x3F000000)
    for rc in (0, 2):
        (found,) = NETV2.probe(host, runner=Runner([(needle, (rc, text))]))
        run = Runner(flash=b"\0" * NETV2.flash_region["a7-100"])
        report = NETV2.check(host, found, {"images": _install(tmp_path, NETV2)}, runner=run)
        assert not any(needle in " ".join(c) for c in run.calls)  # the check does not scan again
        assert report["jtag"]["idcode_device"] == "XC7A100T"
        if rc == 0:
            assert report["result"] == "pass" and report["jtag"]["result"] == "pass", report
        else:
            assert report["result"] == "fail" and report["jtag"]["result"] == "fail"
            assert report["jtag"]["reason"] == f"{tool} exited 2 reading the IDCODE"


def _openocd_chain(*codes):
    return "\n".join(f"Info : JTAG tap: xc7.tap{i} tap/device found: {c:#010x}" for i, c in enumerate(codes))


@pytest.mark.parametrize(
    ("model", "needle", "chain", "tool"),
    [(PI3, "init; exit", _openocd_chain, "openocd"), (PI5, "--detect", _scan, "openFPGALoader")],
    ids=["openocd-pi3", "rp1pio-pi5"],
)
def test_a_netv2_on_a_jtag_chain_of_two_devices_fails_as_the_other_boards_do(tmp_path, model, needle, chain, tool):
    """Finding the board takes the NeTV2 part from the chain; the JTAG check still counts every device on it."""
    host = _host(NETV2, model, None if model == PI5 else 0x3F000000)
    for codes, want in [((0x13631093, 0x0362D093), "a7-100"), ((0x0362D093, 0x13631093), "a7-35")]:
        (found,) = NETV2.probe(host, runner=Runner([(needle, (0, chain(*codes)))]))
        assert found["variant"] == want and found["idcodes"] == [f"{c:#010x}" for c in codes]
        run = Runner(flash=b"\0" * NETV2.flash_region[want])
        report = NETV2.check(host, found, {"images": _install(tmp_path, NETV2)}, runner=run)
        listed = ", ".join(f"{c:#010x}" for c in codes)
        assert report["result"] == "fail" and report["jtag"]["result"] == "fail", report
        assert report["jtag"]["reason"] == f"the JTAG chain has 2 devices ({listed}), not one"
        assert report["jtag"]["idcode"] == listed
    (found,) = NETV2.probe(host, runner=Runner([(needle, (0, chain(0x13631093)))]))
    run = Runner(flash=b"\0" * NETV2.flash_region["a7-100"])
    report = NETV2.check(host, found, {"images": _install(tmp_path, NETV2)}, runner=run)
    assert report["result"] == "pass" and report["jtag"]["result"] == "pass", report
    assert (report["jtag"]["idcode"], found["idcode_scan"]["tool"]) == ("0x13631093", tool)


def test_a_netv2_configured_as_the_other_variant_fails_on_its_idcode(tmp_path):
    run = Runner(flash=b"\0" * NETV2.flash_region["a7-100"])
    report = _check(NETV2, tmp_path, {**_netv2_found("0x13631093"), "variant": "a7-35"}, run, variant="a7-100")
    assert report["jtag"]["result"] == "pass" and report["jtag"]["idcode_device"] == "XC7A100T"
    report = _check(NETV2, tmp_path, _netv2_found("0x13631093"), run, variant="a7-35")
    assert report["jtag"]["result"] == "fail" and "is an XC7A100T, not the a7-35's XC7A35T" in report["reason"]


def test_a_failing_test_fails_the_check_and_keeps_its_output(tmp_path):
    run = Runner([("test_ddr.py", (1, "Memtest KO\nRESULT: FAIL"))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "fail" and "ddr fail" in report["reason"]
    ddr = report["tests"][1]
    assert ddr["output"][-1] == "RESULT: FAIL" and report["tests"][2]["result"] == "pass"


def test_only_the_tests_asked_for_run(tmp_path):
    run = Runner(flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run, tests=["ddr"])
    assert [t["test"] for t in report["tests"]] == ["ddr"]


def test_a_test_the_board_does_not_have_is_an_error_not_a_crash(tmp_path):
    run = Runner(flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run, tests=["uart", "nope"])
    assert report["result"] == "error" and "has no test nope" in report["reason"]
    assert run.calls == []  # nothing loaded


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
    report = _check(NETV2, tmp_path, _netv2_found("0x13631093"), run)
    assert report["result"] == "pass", report
    loads = [c for c in run.calls if c[0] == "openocd"]
    assert f"pld load 0 {tmp_path}/images/uart-test-netv2-a7-100t/kosagi_netv2.bit" in loads[0][-1]
    assert ["systemctl", "stop", "serial-getty@ttyAMA0.service"] in run.calls
    dump = run.calls[-1]
    assert dump[:3] == ["openFPGALoader", "--cable", "libgpiod"] and "xc7a100tfgg484" in dump
    assert report["state"]["idcode"] == "0x13631093"


def test_the_netv2_ddr_and_spi_flash_tests_listen_before_their_designs_are_loaded(tmp_path):
    """Both print what their test needs once, at start, onto ttyAMA0, which keeps nothing while it is closed:
    the SPI flash test its JEDEC ID (pi-sw1-p10, 2026-09-27), the DDR test's BIOS "Switching SDRAM to software
    control." (every Welland NeTV2, found 2026-10-08). listen.py; the test's timeout covers openocd's load on a
    Pi 3. The UART test needs no listening: it skips the banner and echoes."""
    run = Runner(flash=b"\0" * NETV2.flash_region["a7-35"])
    _check(NETV2, tmp_path, _netv2_found("0x0362d093"), run)
    listened = [c for c in run.calls if "fpgas_online_verify.listen" in c]
    assert len(listened) == 2 and not any("test_uart.py" in a for c in listened for a in c)
    for argv, script, design in zip(listened, ("test_ddr.py", "test_spiflash.py"), ("ddr-test", "spiflash-test")):
        assert argv[3] == "/dev/ttyAMA0"
        test, program = argv[5 : 5 + int(argv[4])], argv[5 + int(argv[4]) :]
        assert test[1].endswith(script) and test[-2:] == ["--timeout", "180"] and program[0] == "openocd"
        assert f"{design}-netv2-a7-35t/kosagi_netv2.bit" in program[-1]


def test_listen_loads_the_design_only_once_the_test_has_its_port_open(tmp_path):
    """The stand-in 'test' opens the port file, then waits for what the 'programmer' appends to it."""
    from fpgas_online_verify import listen

    port = tmp_path / "ttyFAKE"
    port.write_text("")
    test = [
        sys.executable,
        "-c",
        "import sys, time\nf = open(sys.argv[1])\nfor _ in range(200):\n"
        "    if 'STARTED' in f.read(): sys.exit(0)\n    f.seek(0); time.sleep(0.05)\nsys.exit(1)",
        str(port),
    ]
    program = [sys.executable, "-c", "import sys; open(sys.argv[1], 'a').write('STARTED')", str(port)]
    assert listen.main([str(port), str(len(test)), *test, *program]) == 0
    assert listen.main([str(port), str(len(test)), *test, sys.executable, "-c", "raise SystemExit(3)"]) == 3


def test_a_netv2_on_a_pi5_loads_with_rp1pio_and_muxes_its_uart(tmp_path):
    run = Runner(flash=b"\0" * NETV2.flash_region["a7-35"])
    report = NETV2.check(_host(NETV2, PI5, None), {"variant": "a7-35"},
                         {"images": _install(tmp_path, NETV2)}, runner=run)  # fmt: skip
    assert report["result"] == "pass"
    assert run.calls[0][-3:] == ["--detect", "--verbose-level", "2"] and report["jtag"]["idcode_device"] == "XC7A35T"
    assert run.calls[2] == ["openFPGALoader", "-c", "rp1pio", "--pins", "27:22:4:17", "--read-dna"]
    assert report["jtag"]["dna"] == DNA
    assert ["pinctrl", "set", "14", "a4"] in run.calls
    assert any(c[:3] == ["openFPGALoader", "-c", "rp1pio"] and c[-1].endswith("kosagi_netv2.bit") for c in run.calls)


def test_the_tt_board_loads_and_tests_through_the_rp2350_bridge_and_does_not_read_flash(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([E6_SAYS_FPGA])
    report = _check(TT, tmp_path, TT_E6, run)
    assert report["result"] == "pass"
    # the TT site's bridge holds /dev/ttyACM0 (pi-sw2-p33, 2026-09-27): stopped for the tests, started after
    assert run.calls[:2] == [
        ["systemctl", "is-active", "--quiet", "fpgas-tt.service"],
        ["systemctl", "stop", "fpgas-tt.service"],
    ]
    assert run.calls[-1] == ["systemctl", "start", "--no-block", "fpgas-tt.service"]
    assert report["services_stopped"] == ["fpgas-tt.service"]
    # the pin-ID scan loads its design itself and runs first; the bridge loads the UART design,
    # so the last design left on the board is one with a single TX pin, not one driving every Pmod line
    # first of all the board's own word is judged (sdk), which loads nothing
    assert [t["test"] for t in report["tests"]] == ["sdk", "dip-switches", "pin-id", "uart"]
    assert "bitstream" not in report["tests"][0] and "not_run" not in report
    _dip, load, _display = [c for c in run.calls if "tt_fpga_program.py" in " ".join(c)]
    assert load[3].endswith("pmod-pin-id-tt-fpga/tt_fpga_platform.bin") and load[4:] == ["--gpio-release"]
    bridged = [c for c in run.calls if "tt_test_wrapper.py" in " ".join(c)]
    assert [c[3].rsplit("/", 2)[-2] for c in bridged] == ["uart-test-tt-fpga"]
    assert bridged[0][2] == "/dev/ttyACM0" and bridged[0][5].endswith("test_uart.py")
    assert run.calls.index(load) < run.calls.index(bridged[0])
    assert report["state"] == {"variant": "tt-fpga", "serial": "E6"}
    assert report["flash_note"].startswith("none: nothing on the demo board is read back")


def test_a_stopped_bridge_is_left_stopped_and_a_failed_test_still_restarts_a_running_one(tmp_path, monkeypatch):
    _installed(monkeypatch)
    idle = Runner([("is-active", (3, "inactive")), E6_SAYS_FPGA])
    report = _check(TT, tmp_path, TT_E6, idle)
    assert not any(c[:2] == ["systemctl", "stop"] or c[:2] == ["systemctl", "start"] for c in idle.calls)
    assert "services_stopped" not in report
    failing = Runner([("tt_test_wrapper.py", (1, "could not enter raw repl")), E6_SAYS_FPGA])
    report = _check(TT, tmp_path, TT_E6, failing)
    assert report["result"] == "fail" and failing.calls[-1] == ["systemctl", "start", "--no-block", "fpgas-tt.service"]


def test_a_check_told_to_leave_the_start_to_its_caller_only_says_what_it_stopped(tmp_path, monkeypatch):
    _installed(monkeypatch)
    later = []
    run = Runner([E6_SAYS_FPGA])
    report = _check(TT, tmp_path, TT_E6, run, restart_later=later)
    assert later == ["fpgas-tt.service"] and report["services_stopped"] == ["fpgas-tt.service"]
    assert ["systemctl", "stop", "fpgas-tt.service"] in run.calls
    assert not any(c[:2] == ["systemctl", "start"] for c in run.calls)  # runner.run starts it, after the report


def test_a_bridge_that_will_not_stop_or_restart_makes_the_check_an_error(tmp_path, monkeypatch):
    _installed(monkeypatch)
    stuck = Runner([("systemctl stop", (1, "Failed to stop fpgas-tt.service: Access denied"))])
    report = _check(TT, tmp_path, TT_E6, stuck)
    assert report["result"] == "error" and "fpgas-tt.service would not stop" in report["reason"]
    assert not any(c[:2] == ["systemctl", "start"] for c in stuck.calls)  # it was never stopped
    gone = Runner([("systemctl start", (5, "Unit fpgas-tt.service not found.")), E6_SAYS_FPGA])
    report = _check(TT, tmp_path, TT_E6, gone)
    assert report["result"] == "error" and "fpgas-tt.service was not started again" in report["reason"]
    assert report["services_failed"] == ["fpgas-tt.service was not started again: Unit fpgas-tt.service not found."]


# -- the TT FPGA's identity, from rpi-hwid ---------------------------------------------------------------------

# As finding it gives it: no variant. The board says which Tiny Tapeout board it is (#124).
TT_FOUND = {"variant": None, "usb": "1-2", "serial": "E661", "usb_id": "2e8a:0005"}
TT_E6 = {**TT_FOUND, "serial": "E6"}
RPI_HWID_TT = ["/usr/bin/rpi-hwid", "tinytapeout", "--json", "--no-stop-service"]
SDK_START = "tt_sdk_start.py"
MAIN_PY = "tt_main_py.py"
# A board as rpi-hwid's tinytapeout_verdict() describes it (src/rpi_hwid/tinytapeout.py, origin/main 310cd23):
# the TT FPGA demo board, SDK 3.1.0, whose ROM says "FPGA", so chip fpga and no shuttle.
TT_BOARD = {
    "kind": "tinytapeout", "usb": "1-2", "usb_serial": "E661", "tty": "/dev/ttyACM0", "shuttle": None,
    "chip": "fpga", "repo": None, "commit": None, "demoboard": "TTDBv3 [3.2]", "demoboard_version": None,
    "sdk": "v3.1.0", "machine": "Raspberry Pi Pico2 with RP2350", "mcu": "RP2350", "chip_url": None,
    "how": "Tiny Tapeout SDK v3.1.0 on Raspberry Pi Pico2 with RP2350 (USB 1-2); chip ROM shuttle=FPGA",
}  # fmt: skip
TT_FIELDS = {"mcu": "RP2350", "shuttle": None, "chip": "fpga", "repo": None, "commit": None,
             "demoboard": "TTDBv3 [3.2]", "demoboard_version": None, "sdk": "v3.1.0"}  # fmt: skip


def _rpi_hwid(*boards, rc=0, stderr=""):
    """`rpi-hwid tinytapeout --json`'s answer: its document (indent 1), then whatever it said on stderr."""
    doc = {"usb": [], "repl": {}, "boards": list(boards), "summary": []}
    return "tinytapeout", (rc, json.dumps(doc, indent=1) + "\n" + stderr)


def _installed(monkeypatch):
    monkeypatch.setattr(tt_fpga, "which", lambda name: "/usr/bin/" + name)


E6_SAYS_FPGA = _rpi_hwid({**TT_BOARD, "usb_serial": "E6"})  # what the board with serial E6 answers rpi-hwid


def _nothing_loaded(report, run):
    """No test that loads a design ran and no design went to the board: neither loader was called."""
    return not any("bitstream" in t for t in report["tests"]) and not any(
        "tt_fpga_program.py" in " ".join(c) or "tt_test_wrapper.py" in " ".join(c) for c in run.calls)  # fmt: skip


def _restarted_last(run):
    stop = run.calls.index(["systemctl", "stop", "fpgas-tt.service"])
    return stop < len(run.calls) - 1 and run.calls[-1] == ["systemctl", "start", "--no-block", "fpgas-tt.service"]


def test_rpi_hwid_reads_the_tt_board_while_the_check_holds_its_port_and_before_any_test(tmp_path, monkeypatch):
    _installed(monkeypatch)
    events = []
    run = Runner([_rpi_hwid({**TT_BOARD, "usb_serial": "OTHER", "mcu": "RP2040"}, TT_BOARD,
                            stderr="warning: something\n")])  # fmt: skip
    report = _check(TT, tmp_path, TT_FOUND, run, event=lambda stage, d: events.append((stage, d)))
    assert report["result"] == "pass"
    # after fpgas-tt.service is stopped, the board's main.py is checked, its SDK is started, and then rpi-hwid
    # asks it who it is, all before the first design is loaded; the service is started again at the end
    assert run.calls[2][1].endswith(MAIN_PY) and run.calls[2][2] == "/dev/ttyACM0"
    assert run.calls[3][1].endswith(SDK_START) and run.calls[3][2] == "/dev/ttyACM0"
    assert run.calls[4] == RPI_HWID_TT and _restarted_last(run)
    assert sum(SDK_START in " ".join(c) for c in run.calls) == 1
    assert sum(MAIN_PY in " ".join(c) for c in run.calls) == 1
    assert all("rpi-hwid" not in " ".join(c) for c in run.calls[5:])  # once
    assert report["identity"] == {"board": "tt", "kind": "tt", "variant": "tt-fpga", "serial": "E661", "usb": "1-2",
                                  "usb_serial": "E661", **TT_FIELDS}  # fmt: skip
    stage, details = events[0]
    assert stage == "fpga-board-identified" and details == identity.details(report["identity"])
    shown = (details["mcu"], details["chip"], details["shuttle"], details["usb_serial"])
    assert shown == ("RP2350", "fpga", "-", "E661")  # None: read, and there is none
    assert report["state"] == {"variant": "tt-fpga", "serial": "E661"}  # what `changed` compares is unchanged


def test_a_board_whose_sdk_does_not_start_is_an_error_and_is_not_asked_who_it_is(tmp_path, monkeypatch):
    """The board's main.py was replaced (issue #117): no `tt`, so rpi-hwid would have nothing to read."""
    _installed(monkeypatch)
    said = (
        "  board: TT FPGA board ready\nSDK_START: FAIL: main.py ran to the prompt without starting the "
        "Tiny Tapeout SDK: it is not the SDK's (see \"The SDK's main.py\" in docs/hardware/tt-fpga.md)\n"
    )
    run = Runner([(SDK_START, (1, said)), _rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "error" and _restarted_last(run)
    assert not any("rpi-hwid" in " ".join(c) for c in run.calls)
    why = report["identity"]["tinytapeout_error"]
    assert why.startswith("the Tiny Tapeout SDK did not start on the demo board: SDK_START: FAIL: main.py ran")
    assert "docs/hardware/tt-fpga.md" in why and why in report["reason"]
    # a board that did not say what it is is not tested: no FPGA design goes to it
    assert _nothing_loaded(report, run) and report["variant"] is None and tt_fpga.NOT_SAID in report["reason"]


def test_a_board_whose_main_py_a_visitor_changed_is_an_error_with_that_reason(tmp_path, monkeypatch):
    """Visitors have the board's Python prompt (Tim, 2026-10-05: it stays), so the check reads main.py's hash."""
    _installed(monkeypatch)
    said = (
        "MAIN_PY: FAIL: the board's main.py is not SDK 3.1.0's own (its SHA-256 is 00ff): "
        'see "The SDK\'s main.py" in docs/hardware/tt-fpga.md\n'
    )
    run = Runner([(MAIN_PY, (1, said)), _rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "error" and _restarted_last(run)
    assert not any(SDK_START in " ".join(c) or "rpi-hwid" in " ".join(c) for c in run.calls)
    why = report["identity"]["tinytapeout_error"]
    assert why.startswith("the demo board's main.py is not known to be the SDK's own: MAIN_PY: FAIL: the board's")
    assert why in report["reason"]
    assert _nothing_loaded(report, run) and report["variant"] is None and tt_fpga.NOT_SAID in report["reason"]


def test_without_rpi_hwid_main_py_is_still_checked_but_the_sdk_is_not_started(tmp_path):
    run = Runner()
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert sum(MAIN_PY in " ".join(c) for c in run.calls) == 1
    assert not any(SDK_START in " ".join(c) for c in run.calls)
    assert report["result"] == "error" and "tinytapeout_note" in report["identity"]


def test_without_rpi_hwid_a_changed_main_py_is_still_an_error(tmp_path):
    run = Runner([(MAIN_PY, (1, "MAIN_PY: FAIL: the board's main.py is not SDK 3.1.0's own (its SHA-256 is 00ff)\n"))])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "error" and "is not SDK 3.1.0's own" in report["identity"]["tinytapeout_error"]
    assert "tinytapeout_note" not in report["identity"]


def test_a_main_py_check_that_could_not_run_is_an_error_and_nothing_is_loaded(tmp_path, monkeypatch):
    _installed(monkeypatch)
    calls = []

    def run(argv, timeout):
        calls.append([str(a) for a in argv])
        if MAIN_PY in " ".join(map(str, argv)):
            raise core.Problem("error", "tt_main_py.py did not finish within 90 s")
        return 0, ""

    report = _check(TT, tmp_path, TT_FOUND, run)
    why = report["identity"]["tinytapeout_error"]
    assert report["result"] == "error" and why.endswith(
        "it could not be checked: tt_main_py.py did not finish within 90 s"
    )
    assert report["tests"] == [] and not any("tt_fpga_program.py" in " ".join(c) for c in calls)


def test_a_field_rpi_hwid_left_out_stays_out_and_leaves_the_tt_identity_not_whole(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid({k: v for k, v in TT_BOARD.items() if k != "sdk"})])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert "sdk" not in report["identity"]  # not read: never null, which would be "read, and there is none"
    assert all(report["identity"][k] == v for k, v in TT_FIELDS.items() if k != "sdk")
    assert identify.missing(TT, report["identity"]) == [("sdk", "not read")]


def test_without_rpi_hwid_the_board_cannot_say_what_it_is_so_it_is_an_error_and_nothing_is_loaded(tmp_path):
    """Until #124 such a board passed as a tt-fpga it had never said it was."""
    run = Runner()
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "error" and report["variant"] is None and _nothing_loaded(report, run)
    assert report["reason"] == f"{tt_fpga.NOT_SAID}: {tt_fpga.NOT_INSTALLED}"
    assert not any("rpi-hwid" in " ".join(c) for c in run.calls) and _restarted_last(run)
    assert report["identity"] == {"board": "tt", "kind": "tt", "serial": "E661", "usb": "1-2",
                                  "usb_serial": "E661", "tinytapeout_note": tt_fpga.NOT_INSTALLED}  # fmt: skip
    assert tt_fpga.NOT_INSTALLED.startswith("not read: rpi-hwid is not installed")


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        ((1, "Traceback (most recent call last):\nOSError: boom\n"), "exited 1: Traceback (most recent call"),
        (core.Problem("fail", "rpi-hwid did not finish within 60 s: "), "did not finish within 60 s"),
        ((0, "usage: rpi-hwid\n"), "no JSON document in its output"),
        ((0, "{not json\n"), "rpi-hwid tinytapeout --json --no-stop-service: "),
        ((0, '{"boards": "none"}\n'), "its document has no list of boards"),
        (_rpi_hwid()[1], "did not see the board with USB serial E661"),
        (_rpi_hwid({**TT_BOARD, "usb_serial": "OTHER"})[1], "did not see the board with USB serial E661"),
        (_rpi_hwid({"kind": "rp2-micropython", "usb_serial": "E661", "how": "MicroPython RP2; REPL: no answer"})[1],
         "not a Tiny Tapeout board: MicroPython RP2; REPL: no answer"),
        (_rpi_hwid({**TT_BOARD, "sdk": 3})[1], "not text: sdk=3"),
        # null in a field every TT FPGA board has is a read that failed, never "there is none"
        (_rpi_hwid({**TT_BOARD, "mcu": None})[1], ": rpi-hwid could not read mcu"),
        (_rpi_hwid({**TT_BOARD, "chip": None, "how": "chip ROM not cached on the board"})[1],
         ": rpi-hwid could not read chip"),
        (_rpi_hwid({**TT_BOARD, "demoboard": None})[1], ": rpi-hwid could not read demoboard"),
        (_rpi_hwid({**TT_BOARD, "sdk": None})[1], ": rpi-hwid could not read sdk"),
        (_rpi_hwid({**TT_BOARD, "mcu": None, "sdk": None})[1], ": rpi-hwid could not read mcu, sdk"),
        # an identity field is never present and empty, nullable or not
        (_rpi_hwid({**TT_BOARD, "sdk": ""})[1], ": empty: sdk"),
        (_rpi_hwid({**TT_BOARD, "repo": "", "commit": ""})[1], ": empty: repo, commit"),
    ],
)  # fmt: skip
def test_rpi_hwid_that_cannot_say_who_the_tt_board_is_makes_the_check_an_error(tmp_path, monkeypatch, answer, why):
    _installed(monkeypatch)
    run = Runner([("tinytapeout", answer)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    error = report["identity"]["tinytapeout_error"]
    assert why in error and error.startswith("rpi-hwid tinytapeout --json --no-stop-service")
    assert not set(TT_FIELDS) & set(report["identity"]) and report["identity"]["usb_serial"] == "E661"
    assert report["result"] == "error" and f"tinytapeout_error: {error}" in report["reason"]
    assert _nothing_loaded(report, run) and report["variant"] is None and "variant" not in report["identity"]
    assert _restarted_last(run)


def test_rpi_hwid_runs_even_when_the_bridge_would_not_stop_and_a_failing_read_still_restarts_it(tmp_path,
                                                                                              monkeypatch):  # fmt: skip
    _installed(monkeypatch)
    held = "REPL: fpgas-tt.service holds /dev/ttyACM0 and --no-stop-service was given"
    stuck = Runner([("systemctl stop", (1, "Access denied")),
                    _rpi_hwid({"kind": "rp2-micropython", "usb_serial": "E661", "how": held})])  # fmt: skip
    report = _check(TT, tmp_path, TT_FOUND, stuck)
    assert report["result"] == "error" and "would not stop" in report["reason"]
    assert "--no-stop-service was given" in report["identity"]["tinytapeout_error"]
    assert not any(c[:2] == ["systemctl", "start"] for c in stuck.calls)  # never stopped, so never started
    crashing = Runner([("tinytapeout", core.Problem("error", "rpi-hwid is not installed"))])
    report = _check(TT, tmp_path, TT_FOUND, crashing)
    assert report["result"] == "error" and _restarted_last(crashing)


def test_the_tt_board_has_usb_serial_whenever_it_has_a_usb_serial():
    assert identity.base("tt", "tt", TT_FOUND)["usb_serial"] == "E661"
    assert "usb_serial" not in identity.base("tt", "tt", {"variant": "tt-fpga", "usb": "1-2"})
    assert "usb_serial" not in identity.base("arty", "arty", ARTY_FOUND)  # only a Tiny Tapeout board's
    assert TT.port_facts(_host(TT), {"variant": "tt-fpga"}, Runner()) == {}  # nothing to match rpi-hwid's by


def test_only_an_acorn_claim_on_a_design_it_cannot_name_is_weak():
    assert all(ACORN.weak({"kind": k}) for k in ("litex-other", "vendor-xdma", "pcileech", "xilinx-xdma", "unknown"))
    assert not ACORN.weak({"kind": "fpgas-online"}) and not ACORN.weak({"kind": "sqrl-factory"})


def test_the_fomu_state_is_its_serial_only(tmp_path):
    report = _check(FOMU, tmp_path, {"variant": "evt", "usb": "1-3", "serial": "fomu-7"}, Runner())
    assert report["result"] == "pass" and report["state"] == {"variant": "evt", "serial": "fomu-7"}


def test_a_test_board_says_when_each_test_starts_and_how_it_ended(tmp_path):
    events = []
    _check(FOMU, tmp_path, {"variant": "evt", "usb": "1-3", "serial": "fomu-7"}, Runner(),
           event=lambda stage, d: events.append((stage, d)))  # fmt: skip
    assert events == [("fpga-board-identified", {"board": "fomu", "kind": "fomu", "variant": "evt", "serial": "fomu-7",
                                                 "usb": "1-3", "schema": "fpga-identity/1"}),
                      ("fpga-test-started", {"test": "uart"}),
                      ("fpga-test-finished", {"test": "uart", "result": "pass", "reason": ""})]  # fmt: skip


def test_an_arty_says_who_it_is_before_its_tests_with_its_whole_idcode(tmp_path):
    events, kept = [], []
    report = _check(ARTY, tmp_path, ARTY_FOUND, Runner(), board_key="arty",
                    event=lambda stage, d: events.append((stage, d)), **{identity.KEEP: kept.append})  # fmt: skip
    assert events[0][0] == "fpga-board-identified" and events[1][0] == "fpga-test-started"
    assert kept == [report["identity"]]  # handed to the runner, so a crash after this keeps it
    assert report["identity"] == {
        "board": "arty", "kind": "arty", "variant": "a7-35", "serial": "210319B", "usb": "1-1",
        "idcode": "0x0362d093", "idcode_version": 0, "idcode_part_number": "0x362d", "idcode_manufacturer_id": "0x049",
        "idcode_manufacturer": "Xilinx", "idcode_device": "XC7A35T", "dna": DNA,
    }  # fmt: skip
    assert events[0][1] == identity.details(report["identity"])


def test_a_jtag_chain_with_nothing_on_it_is_an_idcode_error(tmp_path):
    report = _check(ARTY, tmp_path, ARTY_FOUND, Runner([("--detect", (1, "JTAG init failed"))]))
    assert report["identity"]["idcode_error"] == report["jtag"]["reason"]
    assert "idcode" not in report["identity"]


# -- the device DNA --------------------------------------------------------------------------------------------


def test_an_arty_with_a_good_dna_has_it_in_its_identity_event_and_state(tmp_path):
    events = []
    run = Runner([("--read-dna", (0, 'Jtag frequency : requested 6.00MHz\n{"dna": "0x54b48664b04854"}\n'))],
                 flash=b"\0" * ARTY.flash_region["a7-35"])  # fmt: skip
    report = _check(ARTY, tmp_path, ARTY_FOUND, run, event=lambda stage, d: events.append((stage, d)))
    assert report["result"] == "pass" and report["jtag"]["result"] == "pass"
    assert report["jtag"]["dna"] == report["identity"]["dna"] == report["state"]["dna"] == DNA  # 16 digits
    assert events[0] == ("fpga-board-identified", identity.details(report["identity"]))
    assert events[0][1]["dna"] == DNA and "dna_error" not in report["identity"]
    assert [c for c in run.calls if "--read-dna" in c] == [["openFPGALoader", "-b", "arty", "--read-dna"]]


@pytest.mark.parametrize("stuck", ["0x0000000000000000", "0x01ffffffffffffff"])
def test_a_dna_of_all_zeros_or_all_ones_is_no_dna_and_fails_the_board(tmp_path, stuck):
    run = Runner([("--read-dna", (0, f'{{"dna": "{stuck}"}}\n'))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    reason = f"device DNA over JTAG reads {int(stuck, 16):#x}: the DNA port is not being read"
    assert report["result"] == "fail" and report["jtag"]["result"] == "fail"
    assert report["jtag"]["reason"] == report["identity"]["dna_error"] == reason
    assert report["reason"].startswith(f"jtag fail: {reason}")
    assert "dna" not in report["identity"] and "dna" not in report["state"]
    assert report["identity"]["idcode"] == "0x0362d093"  # the IDCODE was read all the same


def test_a_dna_read_that_exits_non_zero_fails_the_board_and_says_why(tmp_path):
    text = "Error: Failed to claim FPGA device: read_dna only supported for 7-series style Xilinx FPGA\n"
    run = Runner([("--read-dna", (1, text))], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    reason = f"openFPGALoader --read-dna read no device DNA (exit 1): {text.strip()}"
    assert report["result"] == "fail" and report["jtag"]["reason"] == report["identity"]["dna_error"] == reason
    assert "dna" not in report["state"]
    # a DNA printed by a run that failed is not trusted, and a run that printed no DNA read none
    for rc, text in [(1, DNA_LINE), (0, "Jtag frequency : requested 6.00MHz\n")]:
        run = Runner([("--read-dna", (rc, text))], flash=b"\0" * ARTY.flash_region["a7-35"])
        report = _check(ARTY, tmp_path, ARTY_FOUND, run)
        assert report["result"] == "fail" and "dna" not in report["identity"], report["jtag"]
        assert report["identity"]["dna_error"].startswith(f"openFPGALoader --read-dna read no device DNA (exit {rc})")


def test_a_dna_read_that_cannot_run_is_its_problems_result(tmp_path):
    run = Runner([("--read-dna", core.Problem("error", "openFPGALoader is not installed"))],
                 flash=b"\0" * ARTY.flash_region["a7-35"])  # fmt: skip
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert report["result"] == "error" and report["jtag"]["result"] == "error"
    assert report["identity"]["dna_error"] == "the device DNA could not be read: openFPGALoader is not installed"


@pytest.mark.parametrize(
    "scan",
    [(1, "JTAG init failed"), (2, ARTY_SCAN), (0, _scan(0x13631093)), (0, _scan(0x0362D093, 0x0362D093))],
    ids=["no-chain", "scan-exit", "wrong-part", "two-devices"],
)
def test_the_dna_is_not_read_unless_the_scan_found_the_one_fpga_expected(tmp_path, scan):
    run = Runner([("--detect", scan)], flash=b"\0" * ARTY.flash_region["a7-35"])
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    assert not any("--read-dna" in c for c in run.calls)
    assert report["jtag"]["result"] == "fail" and report["identity"]["dna_error"] == testbench.DNA_SKIPPED
    assert "dna" not in report["state"] and "--read-dna" not in report["jtag"]["reason"]  # the scan's reason only


def test_the_netv2_reads_its_dna_on_its_scans_pins_and_puts_them_back(tmp_path):
    run = Runner([("pinctrl get", (0, NETV2_PINS))], flash=b"\0" * NETV2.flash_region["a7-100"])
    report = _check(NETV2, tmp_path, _netv2_found("0x13631093"), run)
    assert report["result"] == "pass" and report["identity"]["dna"] == report["state"]["dna"] == DNA
    read = run.calls.index(["openFPGALoader", "--cable", "libgpiod", "--pins", "27:22:4:17", "--read-dna"])
    assert run.calls[read - 1] == ["pinctrl", "get", "4,17,27,22"]
    assert run.calls[read + 1 : read + 5] == [["pinctrl", "set", *g.split()] for g in
                                              ("4 ip pn", "17 ip pu", "22 ip pd", "27 a3 pn")]  # fmt: skip


@pytest.mark.parametrize("problem", [core.Problem("fail", "openFPGALoader did not finish within 60 s: "),
                                     core.Problem("error", "openFPGALoader is not installed")])  # fmt: skip
def test_the_netv2_puts_its_pins_back_when_the_dna_read_itself_fails(tmp_path, problem):
    run = Runner([("pinctrl get", (0, NETV2_PINS)), ("--read-dna", problem)],
                 flash=b"\0" * NETV2.flash_region["a7-100"])  # fmt: skip
    report = _check(NETV2, tmp_path, _netv2_found("0x13631093"), run)
    read = run.calls.index(["openFPGALoader", "--cable", "libgpiod", "--pins", "27:22:4:17", "--read-dna"])
    assert run.calls[read + 1 : read + 5] == [["pinctrl", "set", *g.split()] for g in
                                              ("4 ip pn", "17 ip pu", "22 ip pd", "27 a3 pn")]  # fmt: skip
    assert report["jtag"]["result"] == problem.result and problem.reason in report["identity"]["dna_error"]
    assert "dna" not in report["state"]


def test_the_netv2_dna_is_not_read_when_its_pins_cannot_be_put_back(tmp_path):
    run = Runner([("pinctrl get", core.Problem("error", "pinctrl is not installed"))],
                 flash=b"\0" * NETV2.flash_region["a7-100"])  # fmt: skip
    report = _check(NETV2, tmp_path, _netv2_found("0x13631093"), run)
    assert not any("--read-dna" in c for c in run.calls)  # nothing driven
    assert report["jtag"]["result"] == "error" and "pinctrl is not installed" in report["identity"]["dna_error"]
    run = Runner([("pinctrl set 4", (1, "no such pin"))], flash=b"\0" * NETV2.flash_region["a7-100"])
    report = _check(NETV2, tmp_path, _netv2_found("0x13631093"), run)
    assert report["identity"]["dna"] == DNA  # read, but a pin left driven is still an error
    assert report["jtag"]["result"] == "error" and "could not put GPIO4 back" in report["jtag"]["reason"]


def test_a_board_whose_check_stops_before_its_tests_still_says_who_it_is(tmp_path, monkeypatch):
    _installed(monkeypatch)
    events, run = [], Runner()
    report = _check(TT, tmp_path, {"variant": "tt-fpga", "usb": "1-2", "serial": "E661"}, run, tests=["nope"],
                    event=lambda stage, d: events.append((stage, d)))  # fmt: skip
    assert report["result"] == "error"
    assert events == [("fpga-board-identified", {"board": "tt", "kind": "tt", "variant": "tt-fpga", "serial": "E661",
                                                 "usb": "1-2", "usb_serial": "E661",
                                                 "schema": "fpga-identity/1"})]  # fmt: skip
    assert run.calls == []  # the port was never taken, so rpi-hwid was not run either


# -- the commands and the debug tool ---------------------------------------------------------------------------


def test_the_board_commands_take_the_board_from_their_name(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.runner, "run", lambda options, prog: seen.update(options, prog=prog) or 0)
    assert cli.board_main(["--no-publish"], prog="fpgas-tt-fpga-verify") == 0
    assert seen["board"] == "tt" and seen["prog"] == "fpgas-tt-fpga-verify"
    with pytest.raises(SystemExit):
        cli.board_main([], prog="fpgas-nothing-verify")


def test_update_and_test_cannot_be_given_together(monkeypatch):
    monkeypatch.setattr(cli.runner, "run", lambda options, prog: 0)
    with pytest.raises(SystemExit):
        cli.board_main(["--update", "--test", "uart"], prog="fpgas-arty-verify")
    with pytest.raises(SystemExit):
        cli.verify_main(["--update", "--test", "uart"])


@pytest.mark.parametrize("prog", ["fpgas-verify", "fpgas-acorn-flash"] + [
    f"fpgas-{slug}-{kind}" for slug in ("acorn", "arty", "netv2", "fomu", "tt-fpga") for kind in ("verify", "debug")
])  # fmt: skip
def test_every_help_fits_an_80_column_console(prog, monkeypatch, capsys):
    from fpgas_online_verify.boards.acorn import spi_flash

    monkeypatch.setenv("COLUMNS", "80")
    monkeypatch.setattr(sys, "argv", [prog])
    with pytest.raises(SystemExit):
        if prog == "fpgas-verify":
            cli.verify_main(["--help"])
        elif prog == "fpgas-acorn-flash":
            spi_flash.main(["--help"])
        else:
            cli.board_main(["--help"], prog=prog)
    text = capsys.readouterr().out
    assert text.startswith(f"usage: {prog} ") and max(map(len, text.splitlines())) <= 80


def test_the_acorn_commands_offer_only_the_options_its_check_uses(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(cli.runner, "run", lambda options, prog: seen.update(options) or 0)
    cli.board_main(["--test", "jtag"], prog="fpgas-acorn-verify")
    assert seen["tests"] == ["jtag"]
    for option in (["--port", "/dev/ttyAMA0"], ["--variant", "cle-101"]):  # it loads nothing: no UART, no variant
        with pytest.raises(SystemExit):
            cli.board_main(option, prog="fpgas-acorn-verify")
    with pytest.raises(SystemExit):
        cli.board_main(["--help"], prog="fpgas-acorn-verify")
    out = capsys.readouterr().out
    always = " ".join(t for t in ACORN.tests if t != "power-cycle")
    assert f"tests in the boot check:\n  {always}\n" in out
    assert "in the boot check only with `power-cycle-check = on`:\n  power-cycle\n" in out
    assert "/etc/fpgas-verify/*.ini" in out and "power-cycle-check = on or off" in out
    assert all(len(line) <= 80 for line in out.splitlines())
    with pytest.raises(SystemExit):  # the debug tool has no per-test commands for the Acorn
        cli.board_main(["--help"], prog="fpgas-acorn-debug")
    out = capsys.readouterr().out
    assert "usage: fpgas-acorn-debug [options] COMMAND\n" in out and "tests in the boot check" not in out


def test_the_help_lists_every_result_the_check_gives():
    assert [r for r, _ in cli.RESULTS] == list(core.SEVERITY)


def test_the_report_goes_to_the_boot_path_only_when_not_given(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.runner, "run", lambda options, prog: seen.update(options) or 0)
    cli.board_main([], prog="fpgas-arty-verify")
    assert "report" not in seen  # runner.run picks: the boot report, or stdout for --test


def test_test_option_reaches_the_check_as_the_tests_to_run(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli.runner, "run", lambda options, prog: seen.update(options) or 0)
    cli.board_main(["--test", "uart", "--test", "ddr"], prog="fpgas-arty-verify")
    assert seen["tests"] == ["uart", "ddr"]  # what TestBoard.check reads


def test_debug_list_shows_every_test_and_whether_the_boot_check_runs_it(tmp_path, capsys):
    args = cli.argparse.Namespace(command="list", images=_install(tmp_path, ARTY), variant=None, port=None)
    assert debug.run(ARTY, args) == 0
    out = capsys.readouterr().out
    assert "ddr        a7-35    boot check" in out and "pin-id     a7-35    boot check" in out
    assert "pmod       a7-35    debug only" in out
    assert "(not installed)" not in out


def test_debug_check_finds_a_damaged_bitstream(tmp_path, capsys):
    images = _install(tmp_path, FOMU, corrupt="gpio-loopback-fomu-evt/kosagi_fomu_evt.bin")
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
    assert ran[1] == ["openFPGALoader", "-b", "arty", str(images / "pmod-pin-id-arty-a7-35t/digilent_arty.bit")]
    # the extra arguments follow the boot check's; identify_pmod_pins.py lets --hat-port win over --board
    assert ran[2][1].endswith("identify_pmod_pins.py") and ran[2][2:] == ["--board", "arty", "--hat-port", "JA"]


def test_the_acorn_debug_tool_can_identify_and_has_no_test_loading():
    assert set(debug.commands(ACORN)) == {"detect", "identify"}
    assert {"detect", "list", "check", "program", "test"} == set(debug.commands(ARTY))


class _Nothing:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


# -- which Tiny Tapeout board it is: the board's own word (#124) ------------------------------------------------

# A demo board with a Tiny Tapeout chip, as rpi-hwid's tinytapeout_verdict() gives one (chip "asic", a shuttle).
# Not read from a board: no chip board has been powered since rpi-hwid could read one. The values are what the
# SDK's sources give (2.0.4 is the last release for the RP2040 boards; its demo board detection says "TT06+").
TT_CHIP_BOARD = {**TT_BOARD, "shuttle": "tt06", "chip": "asic", "repo": "TinyTapeout/tinytapeout-06",
                 "commit": "abc1234", "demoboard": "TT06+", "sdk": "2.0.4", "mcu": "RP2040",
                 "machine": "Raspberry Pi Pico with RP2040",
                 "how": "Tiny Tapeout SDK 2.0.4 on Raspberry Pi Pico with RP2040; chip ROM shuttle=tt06"}  # fmt: skip


def test_a_board_that_says_it_is_an_fpga_board_is_a_tt_fpga_and_only_then_is_a_design_loaded(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "pass" and report["variant"] == report["identity"]["variant"] == "tt-fpga"
    asked = run.calls.index(RPI_HWID_TT)
    loaders = ("tt_fpga_program.py", "tt_test_wrapper.py")
    loads = [i for i, c in enumerate(run.calls) if any(name in " ".join(c) for name in loaders)]
    assert loads and min(loads) > asked  # the board is asked first


WIRING = "tt_pmod_wiring.py"
WRONG_RIBBON = "the ui_in ribbon (to HAT JA): ui_in[5] (Pmod pin 8) did not reach HAT JA pin 8"


def _wiring_said(rc, line):
    """tt_pmod_wiring.py's answer: its report, its WIRING: line, then RESULT."""
    return WIRING, (rc, f"== Wiring check: asic cabling ==\nWIRING: {line}\nRESULT: {'PASS' if rc == 0 else 'FAIL'}\n")


def _index(run, needle):
    return next(i for i, c in enumerate(run.calls) if needle in " ".join(c))


def _sdk_starts(run):
    return [i for i, c in enumerate(run.calls) if SDK_START in " ".join(c)]


def test_a_board_with_a_tiny_tapeout_chip_has_its_wiring_tested_and_passes_with_nothing_loaded(tmp_path, monkeypatch):
    """#132, and Tim on 2026-10-05: "Fail until wiring is tested". The `sdk` test, then the `wiring` test
    (tt_pmod_wiring.py, no bitstream) while the bridge is stopped. The script puts the board back from RAM itself:
    the check starts the SDK once only, before it asks the board who it is."""
    _installed(monkeypatch)
    events = []
    run = Runner([_rpi_hwid(TT_CHIP_BOARD), _wiring_said(0, "all 24 Pmod signals reached the Pi where they should")])
    report = _check(TT, tmp_path, TT_FOUND, run, event=lambda stage, d: events.append((stage, d)))
    assert report["variant"] == "tt-asic" and report["identity"]["variant"] == "tt-asic"
    assert report["identity"]["chip"] == "asic" and report["identity"]["shuttle"] == "tt06"
    assert report["result"] == "pass" and "reason" not in report and "not_run" not in report
    sdk, wiring = report["tests"]
    assert (sdk["test"], sdk["result"]) == ("sdk", "pass") and "reason" not in sdk
    assert sdk["output"][-1] == "SDK 2.0.x on an RP2040 supports a tt06 chip"
    assert (wiring["test"], wiring["result"]) == ("wiring", "pass") and "bitstream" not in wiring
    assert wiring["output"][-2] == "WIRING: all 24 Pmod signals reached the Pi where they should"
    assert _nothing_loaded(report, run) and "bitstreams" not in report and _restarted_last(run)
    # the wiring test runs on the board's port, against the cabling the boards have, after the board was asked
    argv = run.calls[_index(run, WIRING)]
    assert argv[0] == sys.executable and argv[1].endswith(WIRING)
    assert argv[2:] == ["--port", "/dev/ttyACM0", "--controller", "rp2040", "--cabling", "asic", "--no-daemon",
                        "--time-limit", str(tt_fpga.WIRING_TIME_LIMIT)]  # fmt: skip
    stop = run.calls.index(["systemctl", "stop", "fpgas-tt.service"])
    assert stop < run.calls.index(RPI_HWID_TT) < _index(run, WIRING)
    # one SDK start, before rpi-hwid asks the board; none after the wiring test (no second boot.log rewrite)
    (first,) = _sdk_starts(run)
    assert first < run.calls.index(RPI_HWID_TT)
    assert [stage for stage, _ in events] == ["fpga-board-identified", *["fpga-test-started", "fpga-test-finished"] * 2]
    assert events[4][1] == {"test": "wiring", "result": "pass", "reason": ""}
    assert report["state"] == {"variant": "tt-asic", "serial": "E661"} and "warnings" not in report
    # no bitstreams need be installed for it: the package's designs are the FPGA board's
    bare = TT.check(_host(TT), TT_FOUND, {"images": tmp_path / "none"}, runner=Runner([_rpi_hwid(TT_CHIP_BOARD)]))
    assert bare["result"] == "pass" and [t["test"] for t in bare["tests"]] == ["sdk", "wiring"]


def test_a_ribbon_that_is_not_where_it_should_be_fails_the_board_and_is_named(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid(TT_CHIP_BOARD), _wiring_said(1, WRONG_RIBBON)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "fail" and report["reason"] == f"wiring fail: {WRONG_RIBBON}"
    assert report["tests"][-1]["reason"] == WRONG_RIBBON
    assert len(_sdk_starts(run)) == 1 and _restarted_last(run)


@pytest.mark.parametrize("answer, result, reason", [
    # exit 2: it could not make its reading at all
    (_wiring_said(2, "the wiring could not be tested: no raw REPL banner"), "error",
     "the wiring could not be tested: no raw REPL banner"),
    # a script that printed no WIRING: line
    ((WIRING, (1, "Traceback (most recent call last):\nKeyError: 'x'\n")), "fail", "the test exited 1"),
    # killed at the check's limit: it could not finish, nor put back what it changed
    ((WIRING, core.Problem("fail", "python3.11 did not finish within 300 s: ")), "error",
     "the wiring test did not finish within 300 s"),
])  # fmt: skip
def test_a_wiring_test_that_could_not_finish_is_said_as_that(tmp_path, monkeypatch, answer, result, reason):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid(TT_CHIP_BOARD), answer])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == result and report["tests"][-1] == {**report["tests"][-1], "result": result}
    assert report["tests"][-1]["reason"] == reason and report["reason"] == f"wiring {result}: {reason}"
    assert len(_sdk_starts(run)) == 1 and _restarted_last(run)


def _tt_host_script(name):
    spec = importlib.util.spec_from_file_location(name, host_tests.path(f"{name}.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_wiring_test_stops_itself_well_before_the_check_would_kill_it():
    """It stops at WIRING_TIME_LIMIT and puts everything back, with up to 75 s for its SDK fallback: all inside the
    check's own limit, which kills it outright."""
    assert tt_fpga.WIRING_TIME_LIMIT + tt_fpga.WIRING_TEARDOWN <= tt_fpga.WIRING_TIMEOUT
    wiring = _tt_host_script("tt_pmod_wiring")
    assert tt_fpga.WIRING_TEARDOWN == wiring.TEARDOWN_SECONDS + wiring.FALLBACK_SECONDS
    assert wiring.FALLBACK_SECONDS >= tt_fpga.SDK_START_TIMEOUT  # tt_sdk_start.py's own limit fits in it
    run = Runner([_wiring_said(0, "ok")])
    seen = []
    TT.run_script_test("wiring", _host(TT), lambda argv, timeout: seen.append((argv, timeout)) or run(argv, timeout))
    ((argv, timeout),) = seen
    assert timeout == tt_fpga.WIRING_TIMEOUT and argv[-2:] == ["--time-limit", str(tt_fpga.WIRING_TIME_LIMIT)]


def test_a_chip_board_with_another_fault_says_both_and_an_fpga_board_has_no_wiring_test_of_this_kind(
    tmp_path, monkeypatch
):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid({**TT_CHIP_BOARD, "sdk": "1.2.2"}), _wiring_said(1, WRONG_RIBBON)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "fail"
    # a board whose SDK is not one for its chip cannot select the chip's factory test: wiring is not run
    assert report["reason"] == "sdk fail: a tt06 chip needs SDK 2.0.x on an RP2040, and the board runs SDK 1.2.2 " \
                               "on an RP2040; wiring not run: it needs sdk to pass first"  # fmt: skip
    assert report["not_run"] == {"wiring": "it needs sdk to pass first"} and not any(WIRING in " ".join(c)
                                                                                      for c in run.calls)  # fmt: skip
    # the FPGA board's wiring test is pin-id, which loads its design: the chip board's script is not run there
    fpga_run = Runner([_rpi_hwid(TT_BOARD)])
    fpga = _check(TT, tmp_path / "fpga", TT_FOUND, fpga_run)
    assert fpga["result"] == "pass" and "not_run" not in fpga and not any(WIRING in " ".join(c) for c in fpga_run.calls)
    assert [t["test"] for t in fpga["tests"]] == ["sdk", "dip-switches", "pin-id", "uart"]


def test_the_report_of_a_chip_board_whose_ribbon_is_wrong_reads_plainly(tmp_path, monkeypatch):
    _installed(monkeypatch)
    board = _check(TT, tmp_path, TT_FOUND, Runner([_rpi_hwid(TT_CHIP_BOARD), _wiring_said(1, WRONG_RIBBON)]))
    report = {"result": "fail", "mode": "tt", "boards": [board]}
    shown = runner.summary(report)
    assert "  tt tt-asic: fail" in shown and "    sdk        pass" in shown
    assert f"    wiring     fail: {WRONG_RIBBON}" in shown
    closing = conclusion.lines(report)
    assert "  tt tt-asic: fail (1 test passed, 1 failed)" in closing
    assert "is not where it should be" in " ".join(closing) and "#the-wiring-test" in " ".join(closing)
    sent = runner.details(report)
    assert sent["board0"] == "tt tt-asic fail" and sent["board0_tests"] == "sdk=pass wiring=fail"
    assert "board0_not_run" not in sent and sent["board0_reason"] == f"wiring fail: {WRONG_RIBBON}"


@pytest.mark.parametrize("said, variant, why", [
    # a chip the SDK release on the board does not know: it could not select a project on it
    ({"sdk": "1.2.2"}, "tt-asic",
     "a tt06 chip needs SDK 2.0.x on an RP2040, and the board runs SDK 1.2.2 on an RP2040"),
    ({"mcu": "RP2350", "sdk": "3.1.0"}, "tt-asic",
     "a tt06 chip needs SDK 2.0.x on an RP2040, and the board runs SDK 3.1.0 on an RP2350"),
    ({"shuttle": "tt03p5", "sdk": "2.0.4"}, "tt-asic",
     "a tt03p5 chip needs SDK 1.2.x on an RP2040, and the board runs SDK 2.0.4 on an RP2040"),
    ({"shuttle": "tt09"}, "tt-asic",
     "no SDK release is recorded as supporting a tt09 chip: add its row to SDK_SUPPORTED"),
    ({"mcu": None}, "tt-asic", "the board did not say its microcontroller"),
    ({"sdk": "dev"}, "tt-asic", "the board's SDK release reads 'dev', which is not a release number"),
    # what ttboard.VERSION is on a board with no release file
    ({"sdk": "0.0.0"}, "tt-asic",
     "a tt06 chip needs SDK 2.0.x on an RP2040, and the board runs SDK 0.0.0 on an RP2040"),
    ({"chip": "fpga", "shuttle": None, "mcu": "RP2350", "sdk": "3.0.8", "demoboard": "TTDBv3 [3.2]"}, "tt-fpga",
     "the FPGA breakout needs SDK 3.1.x on an RP2350, and the board runs SDK 3.0.8 on an RP2350"),
])  # fmt: skip
def test_a_board_whose_sdk_is_not_one_for_its_chip_fails_the_sdk_test_with_what_it_said(
    tmp_path, monkeypatch, said, variant, why
):
    _installed(monkeypatch)
    report = _check(TT, tmp_path, TT_FOUND, Runner([_rpi_hwid({**TT_CHIP_BOARD, **said})]))
    assert report["variant"] == variant and report["result"] == "fail"
    assert report["tests"][0]["test"] == "sdk" and report["tests"][0]["reason"] == why
    assert f"sdk fail: {why}" in report["reason"]
    assert any(line.startswith("SDK release: ") for line in report["tests"][0]["output"])


@pytest.mark.parametrize("shuttle, sdk", [("tt03p5", "1.2.2"), ("tt04", "2.0.4"), ("tt05", "2.0.0"),
                                          ("tt07", "v2.0.3"), ("tt08", "2.0.4")])  # fmt: skip
def test_every_chip_the_fleet_has_passes_the_sdk_test_on_the_release_line_for_it(shuttle, sdk):
    facts = {"chip": "asic", "shuttle": shuttle, "mcu": "RP2040", "sdk": sdk}
    result, reason, lines = tt_fpga.sdk_check("tt-asic", facts)
    assert (result, reason) == ("pass", None) and f"supports a {shuttle} chip" in lines[-1]


def test_single_tests_asked_of_a_chip_board_are_refused_and_nothing_is_loaded(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid(TT_CHIP_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run, tests=["uart"])
    assert report["result"] == "error" and report["variant"] == "tt-asic" and _nothing_loaded(report, run)
    assert report["reason"] == "the board is a tt-asic: uart is for a tt-fpga, so nothing was loaded"
    assert report["tests"] == [] and "not_run" not in report
    # an empty list names no test: nothing is refused, and the whole check runs, its wiring test too
    none = _check(TT, tmp_path / "none", TT_FOUND, Runner([_rpi_hwid(TT_CHIP_BOARD)]), tests=[])
    assert [t["test"] for t in none["tests"]] == ["sdk", "wiring"] and none["result"] == "pass"


def test_an_fpga_board_whose_sdk_test_fails_still_has_its_designs_loaded_and_tested(tmp_path, monkeypatch):
    _installed(monkeypatch)
    report = _check(TT, tmp_path, TT_FOUND, Runner([_rpi_hwid({**TT_BOARD, "sdk": "3.0.8"})]))
    assert [(t["test"], t["result"]) for t in report["tests"]] == [("sdk", "fail"), ("dip-switches", "pass"),
                                                                    ("pin-id", "pass"),
                                                                    ("uart", "pass")]  # fmt: skip
    assert report["result"] == "fail" and report["reason"].startswith("sdk fail: the FPGA breakout needs SDK 3.1.x")


def test_rpi_hwid_gives_shuttles_in_lower_case_and_unknown_as_none_which_is_what_the_table_is_keyed_by():
    """rpi-hwid's tinytapeout_verdict() lower-cases the ROM's shuttle and gives None for "unknown" (read in
    mithro/rpi-hwid src/rpi_hwid/tinytapeout.py at 7d871be), so SDK_SUPPORTED holds lower-case names only."""
    shuttles = [s for row in tt_fpga.SDK_SUPPORTED for s in row[1] if s]
    assert shuttles and all(s == s.lower() and s != "unknown" for s in shuttles)


def test_single_tests_asked_of_an_fpga_board_run_alone(tmp_path, monkeypatch):
    _installed(monkeypatch)
    report = _check(TT, tmp_path, TT_FOUND, Runner([_rpi_hwid(TT_BOARD)]), tests=["uart"])
    assert report["result"] == "pass" and [t["test"] for t in report["tests"]] == ["uart"]


def test_a_chip_board_whose_shuttle_could_not_be_read_has_no_variant(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid({**TT_CHIP_BOARD, "shuttle": None})])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "error" and report["variant"] is None and _nothing_loaded(report, run)
    assert report["reason"] == f"{tt_fpga.NOT_SAID}: it has a Tiny Tapeout chip whose shuttle could not be read"


def test_an_rp2_in_its_boot_loader_fails_as_not_running_the_firmware_and_its_port_is_left_alone(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner()
    report = _check(TT, tmp_path, {**TT_FOUND, "usb_id": "2e8a:0003"}, run)
    assert report["result"] == "fail" and report["variant"] is None and _nothing_loaded(report, run)
    assert report["reason"] == f"{tt_fpga.NOT_TT_FIRMWARE}: it is in its USB boot loader (2e8a:0003)"
    assert not any(MAIN_PY in " ".join(c) or "rpi-hwid" in " ".join(c) for c in run.calls)


def test_a_variant_asked_for_that_the_board_does_not_say_it_is_loads_nothing(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid(TT_CHIP_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run, variant="tt-fpga")
    assert report["result"] == "error" and _nothing_loaded(report, run)
    assert "--variant tt-fpga was asked for, but the board says it is a tt-asic" in report["reason"]
    agreed = Runner([_rpi_hwid(TT_BOARD)])
    assert _check(TT, tmp_path / "again", TT_FOUND, agreed, variant="tt-fpga")["result"] == "pass"


def test_only_an_rp2_that_can_be_a_demo_board_is_a_tiny_tapeout_board(tmp_path):
    """MicroPython's USB serial (0005, 000f: the two ids the fpgas-tt udev rule matches) or the boot loader
    (0003): not a debug probe (000c) or anything else of Raspberry Pi's, which until #124 was called a tt-fpga."""
    usb = _usb(tmp_path, **{"1-1": ("2e8a", "000c", "PROBE"), "1-2": ("2e8a", "000f", "A"),
                            "1-3": ("2e8a", "0003", None), "1-4": ("2e8a", "0005", "B"),
                            "1-5": ("2e8a", "00c0", "HUB")})  # fmt: skip
    found = TT.spot(_host(TT), usb, [])
    assert [(f["usb"], f["usb_id"], f["variant"]) for f in found] == [
        ("1-2", "2e8a:000f", None), ("1-3", "2e8a:0003", None), ("1-4", "2e8a:0005", None)]  # fmt: skip


# -- what the check leaves running (#139) ------------------------------------------------------------------

DISPLAY = "tt-display-tt-fpga/tt_fpga_platform.bin"


def _loads(run):
    """The designs that went to the board, in order: by the programmer, or by the UART test's bridge."""
    return [c[3].rsplit("/", 2)[-2] for c in run.calls
            if "tt_fpga_program.py" in " ".join(c) or "tt_test_wrapper.py" in " ".join(c)]  # fmt: skip


def test_the_check_of_an_fpga_board_ends_by_leaving_the_display_design_running(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "pass" and "warnings" not in report
    assert report["left_running"] == {"design": "display", "bitstream": DISPLAY}
    # it is the last thing sent to the board: after every test, and nothing follows it but the bridge's start
    assert _loads(run) == ["tt-display-tt-fpga", "pmod-pin-id-tt-fpga", "uart-test-tt-fpga", "tt-display-tt-fpga"]
    last = run.calls[-2]
    assert last[1].endswith("tt_fpga_program.py") and last[2] == "/dev/ttyACM0" and last[3].endswith(DISPLAY)
    assert last[4:] == ["--gpio-release"] and _restarted_last(run)
    # it is no test: not in the tests, and nothing is run to read it
    assert [t["test"] for t in report["tests"]] == ["sdk", "dip-switches", "pin-id", "uart"]
    assert "display" not in TT.tests
    shown = runner.summary({"result": "pass", "mode": "tt", "boards": [report]})
    assert f"    left running: the display design ({DISPLAY})" in shown and "WARNING" not in shown
    sent = runner.details({"result": "pass", "mode": "tt", "boards": [report]})
    assert sent["board0_left_running"] == "display" and "board0_warnings" not in sent


def test_a_display_design_that_cannot_be_loaded_is_a_warning_and_the_board_still_passes(tmp_path, monkeypatch):
    """The board was tested before it; the design is for the camera. But it is said, in the report and the event."""
    _installed(monkeypatch)
    run = Runner([(DISPLAY, [(0, "ok"), (1, "mpremote: no device found\nPROGRAM_FAILED")]), _rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "pass" and "reason" not in report and "left_running" not in report
    assert report["warnings"] == [
        "the display design, which the check leaves running, could not be loaded (loading it failed (exit 1): "
        "mpremote: no device found PROGRAM_FAILED): the board is left as its last test left it"]  # fmt: skip
    assert [t["result"] for t in report["tests"]] == ["pass", "pass", "pass", "pass"] and _restarted_last(run)
    whole = {"result": "pass", "mode": "tt", "boards": [report]}
    assert "    WARNING: the display design, which the check leaves running, could not" in runner.summary(whole)
    assert runner.details(whole)["board0_warnings"] == report["warnings"][0]
    # a damaged or absent file is the same warning, and nothing is sent to the board for it; the DIP switch read,
    # which needs that design under it (#166), is an error then: the switches were not read
    images = _install(tmp_path / "damaged", TT, corrupt=DISPLAY)
    run = Runner([_rpi_hwid(TT_BOARD)])
    report = TT.check(_host(TT), TT_FOUND, {"images": images}, runner=run)
    assert report["result"] == "error" and "does not match its manifest" in report["warnings"][0]
    dip = report["tests"][1]
    assert dip["test"] == "dip-switches" and dip["result"] == "error" and "does not match its manifest" in dip["reason"]
    assert _loads(run) == ["pmod-pin-id-tt-fpga", "uart-test-tt-fpga"]


def test_the_display_design_is_left_after_single_tests_and_after_a_failed_test_too(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run, tests=["pin-id"])
    assert _loads(run) == ["pmod-pin-id-tt-fpga", "tt-display-tt-fpga"]
    assert report["left_running"]["design"] == "display"
    run = Runner([("tt_test_wrapper.py", (1, "could not enter raw repl")), _rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path / "failed", TT_FOUND, run)
    assert report["result"] == "fail" and report["left_running"]["design"] == "display"
    assert _loads(run)[-1] == "tt-display-tt-fpga"


def test_a_load_that_times_out_is_a_warning_and_a_failing_boards_closing_lines_keep_it_apart(tmp_path, monkeypatch):
    _installed(monkeypatch)
    # the display design is loaded twice: for the DIP switch read first (it loads), and last (it times out)
    run = Runner([(DISPLAY, [(0, "ok"), core.Problem("error", "tt_fpga_program.py did not finish within 300 s")]),
                  ("tt_test_wrapper.py", (1, "could not enter raw repl")), _rpi_hwid(TT_BOARD)])  # fmt: skip
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "fail" and "did not finish within 300 s" in report["warnings"][0]
    assert "did not finish" not in report["reason"]  # the warning is not a reason the board failed
    closing = conclusion.lines({"result": "fail", "mode": "tt", "boards": [report]})
    assert sum(line.startswith("    warning (not why it did not pass): the display design") for line in closing) == 1


def test_nothing_is_left_running_on_a_board_that_did_not_say_it_is_an_fpga_board(tmp_path, monkeypatch):
    """The display design is an FPGA bitstream: it goes only to a board that said it carries the FPGA."""
    _installed(monkeypatch)
    for said in (TT_CHIP_BOARD, {**TT_CHIP_BOARD, "shuttle": None}):
        run = Runner([_rpi_hwid(said)])
        report = _check(TT, tmp_path / str(said["shuttle"]), TT_FOUND, run)
        assert _loads(run) == [] and "left_running" not in report and "warnings" not in report
    assert set(TT.left_running) == {"tt-fpga"} and not any(b.left_running for b in (ARTY, NETV2, FOMU))


def test_the_bitstreams_package_holds_the_display_design_and_the_debug_listing_shows_it(tmp_path, capsys):
    assert ("display", "tt-fpga", DISPLAY) in TT.artifacts()
    assert len(TT.artifacts()) == len(TT.tests) + 1 and len(ARTY.artifacts()) == len(ARTY.tests) * len(ARTY.variants)
    images = _install(tmp_path, TT)
    args = cli.argparse.Namespace(command="list", images=images, variant=None, port=None)
    assert debug.run(TT, args) == 0
    assert f"display    tt-fpga  left running {DISPLAY}" in capsys.readouterr().out


def test_two_demo_boards_on_one_pi_are_both_an_error_and_neither_is_touched(tmp_path, monkeypatch):
    """#124: the check has one port for a demo board, so with two it does not know which one it would talk to."""
    _installed(monkeypatch)
    usb = _usb(tmp_path, **{"1-2": ("2e8a", "0005", "A"), "1-4": ("2e8a", "0005", "B"),
                            "1-1": ("2e8a", "000c", "PROBE")})  # fmt: skip
    found = TT.spot(_host(TT), usb, [])
    assert [(f["usb"], f["beside"]) for f in found] == [("1-2", ["1-4"]), ("1-4", ["1-2"])]
    for one in found:
        run = Runner([_rpi_hwid(TT_BOARD)])
        report = _check(TT, tmp_path / one["usb"], one, run)
        assert report["result"] == "error" and report["variant"] is None and _nothing_loaded(report, run)
        assert report["reason"] == tt_fpga.ONE_PORT.format(n=2, port="/dev/ttyACM0")
        assert report["reason"].startswith("2 Raspberry Pi RP2 boards that can be Tiny Tapeout demo boards")
        assert not any(MAIN_PY in " ".join(c) or SDK_START in " ".join(c) or "rpi-hwid" in " ".join(c)
                       for c in run.calls)  # fmt: skip
        assert report["identity"]["serial"] == one["serial"] and report["found"]["beside"]
    # one board alone has no such key, and is checked as before
    (tmp_path / "one").mkdir()
    (alone,) = TT.spot(_host(TT), _usb(tmp_path / "one", **{"1-2": ("2e8a", "0005", "A")}), [])
    assert "beside" not in alone


def test_no_other_board_settles_its_variant_late():
    """The hook is the Tiny Tapeout board's alone: every other board's check runs as it did."""
    assert TT.variant_from_board and not any(b.variant_from_board for b in (ARTY, NETV2, FOMU))
    assert not any(b.fact_tests or b.pending or b.script_tests for b in (ARTY, NETV2, FOMU))
    # a variant no bitstream is for is checked by its fact and script tests, which load nothing; none is pending
    assert TT.fact_tests_for("tt-asic") == ["sdk"] and "tt-asic" not in TT.variants
    assert TT.script_tests_for("tt-asic") == ["wiring"] and TT.script_tests_for("tt-fpga") == []
    assert TT.pending == {} and "wiring" not in TT.tests


def test_a_chip_board_whose_demo_board_was_not_detected_is_still_a_tt_asic(tmp_path, monkeypatch):
    """rpi-hwid gives null for a demo board the SDK did not detect: on an FPGA board that is a failed read, on a
    chip board it is not, and the chip and shuttle the board did say are kept."""
    _installed(monkeypatch)
    run = Runner([_rpi_hwid({**TT_CHIP_BOARD, "demoboard": None, "mcu": None})])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["variant"] == "tt-asic" and "tinytapeout_error" not in report["identity"]
    assert report["identity"]["shuttle"] == "tt06" and report["identity"]["demoboard"] is None
    assert tt_fpga.tinytapeout_fields("E661", Runner([_rpi_hwid({**TT_CHIP_BOARD, "chip": None})])) == {
        "tinytapeout_error": "rpi-hwid tinytapeout --json --no-stop-service: rpi-hwid could not read chip"}  # fmt: skip


def test_an_fpga_board_with_no_bitstreams_is_an_error_identified_once_and_nothing_is_loaded(tmp_path, monkeypatch):
    _installed(monkeypatch)
    events = []
    run = Runner([_rpi_hwid(TT_BOARD)])
    report = TT.check(_host(TT), TT_FOUND, {"images": tmp_path / "none", "event": lambda s, d: events.append(s)},
                      runner=run)  # fmt: skip
    assert report["result"] == "error" and report["variant"] == "tt-fpga" and _nothing_loaded(report, run)
    assert events == ["fpga-board-identified"] and report["identity"]["chip"] == "fpga"
    assert _restarted_last(run)


def test_a_test_the_tt_board_does_not_have_is_an_error_before_the_board_is_touched(tmp_path, monkeypatch):
    _installed(monkeypatch)
    run = Runner([_rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run, tests=["nonesuch"])
    assert report["result"] == "error" and "has no test nonesuch" in report["reason"] and run.calls == []
    assert report["variant"] is None and "variant" not in report["identity"]


def test_by_hand_the_debug_tool_does_not_guess_a_tt_boards_variant():
    import argparse

    from fpgas_online_verify import debug

    with pytest.raises(core.Problem, match="pass --variant \\(tt-fpga\\)"):
        debug._variant(TT, _host(TT), argparse.Namespace(variant=None))
    assert debug._variant(TT, _host(TT), argparse.Namespace(variant="tt-fpga")) == "tt-fpga"
    assert debug._variant(FOMU, _host(FOMU), argparse.Namespace(variant=None)) == "evt"


# -- the DIP switches (#166) -----------------------------------------------------------------------------------


def test_the_dip_switches_are_read_first_under_the_display_design_and_one_on_fails_the_board(tmp_path, monkeypatch):
    _installed(monkeypatch)
    said = "DIP_SWITCHES: switch 4 is on: set all DIP switches off"
    run = Runner([("tt_dip_switches.py", (1, f"{said}\n")), _rpi_hwid(TT_BOARD)])
    report = _check(TT, tmp_path, TT_FOUND, run)
    assert report["result"] == "fail"
    dip = report["tests"][1]
    assert dip == {**dip, "test": "dip-switches", "result": "fail", "bitstream": DISPLAY,
                   "reason": "switch 4 is on: set all DIP switches off"}  # fmt: skip
    # the display design went to the board with --gpio-release, then the read, on the board's port
    load = next(c for c in run.calls if "tt_fpga_program.py" in " ".join(c))
    read = next(c for c in run.calls if "tt_dip_switches.py" in " ".join(c))
    assert load[3].endswith(DISPLAY) and load[4:] == ["--gpio-release"] and read[2:] == ["/dev/ttyACM0"]
    assert (
        run.calls.index(load)
        < run.calls.index(read)
        < run.calls.index(next(c for c in run.calls if "pmod-pin-id" in " ".join(c)))
    )
    # nothing is stopped for its port: the RP2350's USB serial has no login console
    assert not any("serial-getty" in " ".join(c) for c in run.calls)
    assert "dip-switches fail: switch 4 is on: set all DIP switches off" in runner.summary(
        {"result": "fail", "mode": "tt", "boards": [report]}
    )


def test_dip_switches_that_could_not_be_read_are_an_error_with_the_scripts_reason(tmp_path, monkeypatch):
    _installed(monkeypatch)
    said = "DIP_SWITCHES: the DIP switches could not be read from the board (exit 1): no device"
    run = Runner([("tt_dip_switches.py", (2, f"{said}\n")), _rpi_hwid(TT_BOARD)])
    dip = _check(TT, tmp_path, TT_FOUND, run)["tests"][1]
    assert (dip["result"], dip["reason"]) == ("error", said.removeprefix("DIP_SWITCHES: "))
    # a script that dies without its last word is the plain fail it always was
    run = Runner([("tt_dip_switches.py", (1, "Traceback (most recent call last):\n")), _rpi_hwid(TT_BOARD)])
    dip = _check(TT, tmp_path / "again", TT_FOUND, run)["tests"][1]
    assert (dip["result"], dip["reason"]) == ("fail", "the test exited 1")


def test_a_pin_id_failure_keeps_the_routing_it_read_as_its_reason(tmp_path):
    """The registry and the board page keep only the reason: "the test exited 1" lost which connector each HAT
    connector reads (every Welland Arty, 2026-10-04; test-designs issue #58)."""
    said = "PIN-ID: 0/18 pins match: HAT JA reads Arty JC, HAT JB reads Arty JD, HAT JC reads Arty JB"
    run = Runner([("identify_pmod_pins.py", (1, f"| GPIO8 | ... |\n{said}\nRESULT: FAIL\n"))],
                 flash=b"\x5a" * ARTY.flash_region["a7-35"])  # fmt: skip
    report = _check(ARTY, tmp_path, ARTY_FOUND, run)
    pin_id = next(t for t in report["tests"] if t["test"] == "pin-id")
    assert (pin_id["result"], pin_id["reason"]) == ("fail", said.removeprefix("PIN-ID: "))
    assert report["reason"] == f"pin-id fail: {said.removeprefix('PIN-ID: ')}"
    assert TT.tests["pin-id"]["says"] == ARTY.tests["pin-id"]["says"] == "PIN-ID:"
