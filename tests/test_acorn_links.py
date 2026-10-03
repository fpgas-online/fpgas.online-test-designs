"""The Acorn's P1 JTAG, P2 UART and P2 GPIO tests (boards/acorn/links.py), one at a time.

Real output from pi-sw2-p48: `openFPGALoader --cable libgpiod --pins 10:9:11:8 --detect --verbose-level 2`
printed the raw scan "- 0 -> 0x13636093" and, from its part table, "idcode 0x3636093" (2026-10-02);
`--read-dna` printed {"dna": "0x0054b48664b04854"}, which is what the `dna_id` CSR gave over BAR0 and over the
P2 UARTBone (2026-10-01). tests/test_acorn_verify.py runs them inside the whole check.
"""

import ast
import os
import pathlib

import pytest
from fpgas_online_verify.boards.acorn import check, links, setup, uartbone_link
from fpgas_online_verify.core import Problem

from tests import acorn_fakes as fk

PI5 = setup.detect(fk.PI5)
BLADE = setup.detect(fk.CM5)


def _no_chip(compatible):
    pass


# -- P1 JTAG -------------------------------------------------------------------------------------------


def test_a_chain_with_the_variants_fpga_and_bar0s_dna_passes():
    pi = fk.FakePi()
    t = links.jtag(PI5, "cle-215+", pi, bar0_dna=fk.DNA, gpiochip=_no_chip)
    assert t["result"] == "pass", t
    assert (t["idcode"], t["dna"]) == ("0x13636093", "0x54b48664b04854") and "dna_error" not in t
    fields = {"idcode_version": 1, "idcode_part_number": "0x3636", "idcode_manufacturer_id": "0x049",
              "idcode_manufacturer": "Xilinx", "idcode_device": "XC7A200T"}  # fmt: skip
    assert {k: t[k] for k in fields} == fields
    # the raw scan, not openFPGALoader's part table, which prints the IDCODE masked
    assert t["output"] == ["- 0 -> 0x13636093", "- 1 -> 0xffffffff", '{"dna": "0x0054b48664b04854"}']
    loads = pi.ran("openFPGALoader")
    assert loads == [["openFPGALoader", "--cable", "libgpiod", "--pins", "10:9:11:8", "--detect",
                      "--verbose-level", "2"],
                     ["openFPGALoader", "--cable", "libgpiod", "--pins", "10:9:11:8", "--read-dna"]]  # fmt: skip


def test_another_silicon_version_of_the_right_part_passes_and_is_reported():
    t = links.jtag(PI5, "cle-215+", fk.FakePi(idcode=0x03636093), bar0_dna=fk.DNA, gpiochip=_no_chip)
    assert t["result"] == "pass", t
    assert (t["idcode"], t["idcode_version"], t["idcode_device"]) == ("0x03636093", 0, "XC7A200T")


def test_an_idcode_with_bit_0_clear_fails():
    t = links.jtag(PI5, "cle-215+", fk.FakePi(idcode=0x13636092), bar0_dna=fk.DNA, gpiochip=_no_chip)
    assert t["result"] == "fail" and "bit 0 clear" in t["reason"], t


def test_a_dna_over_jtag_that_is_not_bar0s_fails_because_tdi_is_not_proven():
    """--detect reads the IDCODE with TDI unused; only the DNA read needs an instruction shifted in."""
    t = links.jtag(PI5, "cle-215+", fk.FakePi(jtag_dna=0x0), bar0_dna=fk.DNA, gpiochip=_no_chip)
    assert t["result"] == "fail" and "TDI" in t["reason"]


def test_an_empty_chain_fails():
    t = links.jtag(PI5, "cle-215+", fk.FakePi(chain=False), gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"] == (
        "no device on the P1 JTAG chain; openFPGALoader --detect exited 1 on the P1 JTAG chain"
    )
    assert t["dna_error"].startswith("not read over P1 JTAG: --read-dna runs only once")


def test_a_pin_state_that_cannot_be_read_is_a_dna_error_as_well():
    class NoPinctrl(fk.FakePi):
        def __call__(self, argv, timeout):
            if argv[0] == "pinctrl":
                raise Problem("error", "pinctrl is not installed")
            return super().__call__(argv, timeout)

    t = links.jtag(PI5, "cle-215+", NoPinctrl(), gpiochip=_no_chip)
    assert t["result"] == "error" and t["dna_error"].startswith("not read over P1 JTAG: P1 JTAG not probed")


class NoRawScan(fk.FakePi):
    """openFPGALoader --detect that prints `text` in place of its raw scan and part table, and exits `rc`."""

    def __init__(self, text, rc=0, **kw):
        super().__init__(**kw)
        self.text, self.rc = text, rc

    def __call__(self, argv, timeout):
        rc, out = super().__call__(argv, timeout)
        return (self.rc, self.text) if "--detect" in argv else (rc, out)


def test_output_without_the_raw_scan_says_so_not_that_the_chain_is_empty():
    part_table = "found 1 devices\n" + fk.DETECT.format(masked=0x3636093)
    t = links.jtag(PI5, "cle-215+", NoRawScan(part_table), gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"] == (
        "P1 JTAG: openFPGALoader printed no raw IDCODE scan (needs --verbose-level 2 output)"
    )


def test_a_detect_that_fails_before_scanning_says_the_tool_failed_and_why():
    text = "unable to open gpiochip: /dev/gpiochip15: No such file or directory\n"
    t = links.jtag(PI5, "cle-215+", NoRawScan(text, rc=1), gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"] == (
        "P1 JTAG: openFPGALoader --detect failed (exit 1) before scanning the JTAG chain: "
        "unable to open gpiochip: /dev/gpiochip15: No such file or directory"
    )


def test_a_stuck_tdo_is_an_empty_chain():
    stuck = "Raw IDCODE:\n- 0 -> 0x00000000\nJTAG init failed with: TDO is stuck at 0\n"
    t = links.jtag(PI5, "cle-215+", NoRawScan(stuck), gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"] == "no device on the P1 JTAG chain"


class DetectExits(fk.FakePi):
    """openFPGALoader --detect prints the scan, then exits with `rc`."""

    def __init__(self, rc, **kw):
        super().__init__(**kw)
        self.rc = rc

    def __call__(self, argv, timeout):
        rc, out = super().__call__(argv, timeout)
        return (self.rc, out) if "--detect" in argv else (rc, out)


def test_a_detect_that_exits_non_zero_fails_even_with_the_right_idcode():
    pi = DetectExits(2)
    t = links.jtag(PI5, "cle-215+", pi, bar0_dna=fk.DNA, gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"] == "openFPGALoader --detect exited 2 on the P1 JTAG chain"
    assert t["idcode_device"] == "XC7A200T" and "dna" not in t  # decoded, but the DNA is not read after it
    assert len(pi.ran("openFPGALoader")) == 1
    assert t["dna_error"] == "not read over P1 JTAG: openFPGALoader --detect exited 2, so --read-dna was not run"


def test_the_wrong_part_and_a_non_zero_exit_are_both_reported():
    t = links.jtag(PI5, "cle-101", DetectExits(1), gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"].startswith("P1 JTAG chain has 0x13636093 (XC7A200T)")
    assert t["reason"].endswith("; openFPGALoader --detect exited 1 on the P1 JTAG chain")
    assert t["dna_error"].startswith("not read over P1 JTAG: --read-dna runs only once")  # not the one expected


def test_the_wrong_part_fails_and_says_which():
    t = links.jtag(PI5, "cle-101", fk.FakePi(), gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"] == (
        "P1 JTAG chain has 0x13636093 (XC7A200T), expected one XC7A100T (IDCODE 0x03631093, any version) for cle-101"
    )
    assert t["idcode"] == "0x13636093" and "dna" not in t  # the DNA is not read from the wrong part


def test_the_pins_go_back_as_they_were_found_even_after_a_hang():
    class Hangs(fk.FakePi):
        def __call__(self, argv, timeout):
            if argv[0] == "openFPGALoader":
                super().__call__(argv, timeout)  # it drives the pins, then never returns
                raise Problem("fail", "openFPGALoader did not finish within 60 s")
            return super().__call__(argv, timeout)

    pi = Hangs()
    t = links.jtag(PI5, "cle-215+", pi, gpiochip=_no_chip)
    assert t["result"] == "fail" and "did not finish" in t["reason"]
    assert all(pi.pins[g][:2] == ["ip", "pd"] for g in (8, 9, 10, 11))


def test_on_a_blade_gpio14_goes_back_to_the_uart_not_to_an_input():
    pi = fk.FakePi(idcode=0x13631093)
    pi.pins.update({2: ["a0", "pu", None], 3: ["a0", "pu", None], 4: ["ip", "pu", None]})
    t = links.jtag(BLADE, "cle-101", pi, gpiochip=_no_chip)
    assert t["result"] == "pass"
    assert pi.ran("openFPGALoader")[0][4] == "2:3:4:14"
    assert pi.pins[14][:2] == ["a4", "pn"] and pi.pins[2][:2] == ["a0", "pu"] and pi.pins[4][:2] == ["ip", "pu"]


def test_a_missing_openfpgaloader_is_an_error_not_a_board_fault():
    t = links.jtag(PI5, "cle-215+", fk.FakePi(tool=False), gpiochip=_no_chip)
    assert t["result"] == "error"


def _gpio_sysfs(tmp_path, chips):
    """/sys/bus/gpio/devices and /dev with {gpiochipN: compatible}."""
    sysfs, dev = tmp_path / "sys", tmp_path / "dev"
    dev.mkdir()
    for chip, compat in chips.items():
        (sysfs / chip / "of_node").mkdir(parents=True)
        (sysfs / chip / "of_node" / "compatible").write_bytes(compat.encode() + b"\0")
        (dev / chip).write_text("")
    return str(sysfs), str(dev)


PI5_CHIPS = {"gpiochip11": "brcm,brcmstb-gpio", "gpiochip12": "brcm,brcmstb-gpio", "gpiochip15": "raspberrypi,rp1-gpio"}


def test_a_fresh_pi5_gets_gpiochip0_linked_to_the_rp1_chip(tmp_path):
    sysfs, dev = _gpio_sysfs(tmp_path, PI5_CHIPS)
    links.header_gpiochip(PI5.gpiochip, f"{dev}/gpiochip0", sysfs, dev)
    assert os.path.realpath(f"{dev}/gpiochip0") == os.path.realpath(f"{dev}/gpiochip15")
    links.header_gpiochip(PI5.gpiochip, f"{dev}/gpiochip0", sysfs, dev)  # the next check: already right


def test_a_cm4s_own_gpiochip0_is_its_header(tmp_path):
    sysfs, dev = _gpio_sysfs(tmp_path, {"gpiochip0": "brcm,bcm2711-gpio", "gpiochip1": "raspberrypi,firmware-gpio"})
    cm4 = setup.detect(fk.CM4)
    links.header_gpiochip(cm4.gpiochip, f"{dev}/gpiochip0", sysfs, dev)
    assert not os.path.islink(f"{dev}/gpiochip0")


def test_a_gpiochip0_that_is_not_the_header_is_refused(tmp_path):
    sysfs, dev = _gpio_sysfs(tmp_path, PI5_CHIPS)
    pathlib.Path(dev, "gpiochip0").write_text("")  # some other chip
    with pytest.raises(Problem, match="is not the header's GPIO chip"):
        links.header_gpiochip(PI5.gpiochip, f"{dev}/gpiochip0", sysfs, dev)


def test_no_header_chip_is_an_error_and_openfpgaloader_is_not_run(tmp_path):
    pi = fk.FakePi()
    t = links.jtag(PI5, "cle-215+", pi, gpiochip=lambda c: links.header_gpiochip(c, sysfs=str(tmp_path / "none")))
    assert t["result"] == "error" and "no GPIO chip compatible with raspberrypi,rp1-gpio" in t["reason"]
    assert not pi.ran("openFPGALoader")


# -- P2 UART -------------------------------------------------------------------------------------------


def _builds():
    return {fk.OP_IDENT: check.Csrs(fk.csr_json())}


def test_a_p2_uart_at_both_rates_that_matches_bar0_passes():
    soc = fk.FakeSoC()
    far = fk.SoCLink(soc)
    t = links.p2_uart(PI5, _builds(), setup.load(setup.EXPECTED),
                      {"identifier": fk.OP_IDENT_ON_CHIP, "dna": fk.DNA}, far.open, far.settle)  # fmt: skip
    assert t["result"] == "pass", t
    assert t["baud"] == [1200, 921600] and t["dna"] == "0x54b48664b04854"
    assert far.baud == uartbone_link.RESET_BAUD  # left at the reset rate for the next user


def test_a_silent_p2_uart_fails():
    far = fk.Cut()
    t = links.p2_uart(PI5, _builds(), {}, {}, far.open, far.settle)
    assert t["result"] == "fail" and t["reason"] == "no UARTBone reply on /dev/ttyAMA0 (P2 K2/J2)"


def test_a_p2_uart_answering_for_another_build_fails_and_is_sent_nothing_more():
    soc = fk.FakeSoC(identifier="fpgas-online Acorn PCIe SoC cle-215+ 2026-01-01 00:00:00")
    far = fk.SoCLink(soc)
    t = links.p2_uart(PI5, _builds(), {}, {"identifier": fk.OP_IDENT_ON_CHIP}, far.open, far.settle)
    assert t["result"] == "fail" and "is not the BAR0 identifier" in t["reason"]
    assert "is not a build of the installed release" in t["reason"]
    assert uartbone_link.FAST_BAUD not in far.opened_at  # never moved to the fast rate


def test_a_link_that_only_works_at_1200_fails():
    far = fk.SoCLink(fk.FakeSoC())
    far.ignore_tuning_write = True
    t = links.p2_uart(PI5, _builds(), {}, {}, far.open, far.settle)
    assert t["result"] == "fail" and "at the fast rate" in t["reason"]
    assert far.baud == uartbone_link.RESET_BAUD  # the failed probe, then the reset, leave it at 1200


def test_a_dna_over_p2_that_is_not_bar0s_fails():
    far = fk.SoCLink(fk.FakeSoC(dna=0x123))
    t = links.p2_uart(PI5, _builds(), {}, {"dna": fk.DNA}, far.open, far.settle)
    assert "device DNA over P2 UART 0x123 is not the one over BAR0" in t["reason"]


def test_no_pyserial_is_an_error_not_a_crash(monkeypatch):
    def no_serial(device):
        raise ImportError("No module named 'serial'")

    monkeypatch.setattr(uartbone_link, "_serial_opener", no_serial)
    t = links.p2_uart(PI5, _builds(), {}, {})
    assert t["result"] == "error" and "serial" in t["reason"]


# -- P2 GPIO -------------------------------------------------------------------------------------------


def test_j5_and_h5_pass_in_both_directions_and_go_back_to_inputs():
    soc = fk.FakeSoC()
    pi = fk.FakePi(soc)
    t = links.p2_gpio(PI5, soc, check.Csrs(fk.csr_json()), pi)
    assert t["result"] == "pass", t
    assert len(t["output"]) == 8  # four patterns each way
    assert soc.oe == 0 and pi.pins[3][:2] == ["no", "pu"]


def test_the_pi_never_drives_a_ball_the_fpga_drives():
    soc = fk.FakeSoC()

    class Watch(fk.FakePi):
        def __call__(self, argv, timeout):
            if argv[:2] == ["pinctrl", "set"] and "op" in argv:
                assert soc.oe == 0, "the Pi drove a ball while the FPGA drove it"
            return super().__call__(argv, timeout)

    assert links.p2_gpio(PI5, soc, check.Csrs(fk.csr_json()), Watch(soc))["result"] == "pass"


def test_a_ball_shorted_high_fails():
    soc = fk.FakeSoC()
    pi = fk.FakePi(soc, cut=("H5",))
    t = links.p2_gpio(PI5, soc, check.Csrs(fk.csr_json()), pi)
    assert t["result"] == "fail" and "H5 -> GPIO4" in t["reason"] and "J5" not in t["reason"]


def test_a_build_without_p2_gpio_cannot_pass():
    soc = fk.FakeSoC(golden=True)
    t = links.p2_gpio(PI5, soc, check.Csrs(fk.csr_json(golden=True)), fk.FakePi(soc))
    assert t["result"] == "fail" and "no p2_gpio_oe CSR" in t["reason"]


def test_pinctrl_output_is_read_as_pinctrl_prints_it():
    pi = fk.FakePi()
    assert links.pin_states(pi, [14, 8, 3]) == {14: ("a4", "pn", "hi"), 8: ("ip", "pd", "lo"), 3: ("no", "pu", "--")}


def test_the_p2_gpio_bits_are_the_ones_the_soc_is_built_with():
    """designs/_shared/acorn_p2.py imports LiteX, which the verify tests do without: read SPARE_GPIO from its
    source, as test_acorn_verify.py reads the subsystem IDs."""
    p2 = pathlib.Path(__file__).resolve().parents[1] / "designs" / "_shared" / "acorn_p2.py"
    (spare,) = [ast.literal_eval(node.value) for node in ast.parse(p2.read_text()).body
                if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "SPARE_GPIO"]  # fmt: skip
    assert {ball: bit for bit, ball in enumerate(spare)} == links.P2_GPIO_BITS


def test_with_no_pin_state_to_put_back_openfpgaloader_is_not_run():
    """openFPGALoader leaves the pins driven: on a Blade GPIO14 is TMS and the UART's TX. Unless their state can
    be read, and so put back, nothing is probed."""

    class NoPinctrl(fk.FakePi):
        def __call__(self, argv, timeout):
            if argv[0] == "pinctrl":
                raise Problem("error", "pinctrl is not installed")
            return super().__call__(argv, timeout)

    pi = NoPinctrl()
    t = links.jtag(BLADE, "cle-101", pi, gpiochip=_no_chip)
    assert t["result"] == "error" and "P1 JTAG not probed" in t["reason"] and "pinctrl is not installed" in t["reason"]
    assert not pi.ran("openFPGALoader")


def test_a_pinctrl_get_that_fails_stops_the_probe_too():
    class Fails(fk.FakePi):
        def __call__(self, argv, timeout):
            if argv[:2] == ["pinctrl", "get"]:
                return 1, "pinctrl: permission denied\n"
            return super().__call__(argv, timeout)

    pi = Fails()
    assert links.jtag(PI5, "cle-215+", pi, gpiochip=_no_chip)["result"] == "error"
    assert not pi.ran("openFPGALoader")


def test_scratch_over_p2_leaves_the_link_at_the_reset_rate():
    far = fk.SoCLink(fk.FakeSoC())
    assert links.uart_scratch(PI5, _builds(), far.open, far.settle) == []
    assert uartbone_link.FAST_BAUD in far.opened_at and far.baud == uartbone_link.RESET_BAUD


# -- the Pi 5's RP1 PIO ----------------------------------------------------------------------------------

# pi-sw2-p47's kernel journal (bootloader 2024/11/05 3c4fc886, 2026-10-02): rp1_pio loaded, no /dev/pio0.
P47_KERNEL = (
    "sdhci-brcmstb 1000fff000.mmc: Got CD GPIO\n"
    "rp1-pio 1f00178000.pio: failed to contact RP1 firmware\n"
    "rp1-pio 1f00178000.pio: probe with driver rp1-pio failed with error -2\n"
)


def _modules(tmp_path, names=links.RP1_PIO_MODULES):
    for name in names:
        (tmp_path / "module" / name).mkdir(parents=True)
    return str(tmp_path / "module")


def _journal(text, rc=0):
    calls = []

    def run(argv, timeout):
        calls.append(argv)
        return rc, text

    return run, calls


def test_rp1_pio_passes_with_both_modules_and_a_device_that_opens(tmp_path):
    run, calls = _journal(P47_KERNEL)
    entry = links.rp1_pio(run, sysfs_module=_modules(tmp_path), dev="/dev/null")  # a character device anyone opens
    assert entry["result"] == "pass" and entry["test"] == "rp1-pio"
    assert calls == []  # the journal is only read to explain a failure


def test_a_missing_pio0_fails_with_the_kernels_reason(tmp_path):
    run, _ = _journal(P47_KERNEL)
    entry = links.rp1_pio(run, sysfs_module=_modules(tmp_path), dev=str(tmp_path / "pio0"))
    assert entry["result"] == "fail"
    assert f"{tmp_path / 'pio0'}: No such file or directory" in entry["reason"]
    assert "kernel: rp1-pio 1f00178000.pio: probe with driver rp1-pio failed with error -2" in entry["reason"]
    assert entry["output"] == [line for line in P47_KERNEL.splitlines() if "rp1-pio" in line]


def test_an_unloaded_module_is_named(tmp_path):
    run, _ = _journal("")
    entry = links.rp1_pio(run, sysfs_module=_modules(tmp_path, ("rp1_fw",)), dev="/dev/null")
    assert entry["result"] == "fail" and entry["reason"] == "kernel module rp1_pio is not loaded"


def test_a_pio0_that_is_not_a_character_device_fails(tmp_path):
    (tmp_path / "pio0").write_text("")
    run, _ = _journal("", rc=1)  # and a journal that cannot be read adds nothing
    entry = links.rp1_pio(run, sysfs_module=_modules(tmp_path), dev=str(tmp_path / "pio0"))
    assert entry["result"] == "fail" and entry["reason"] == f"{tmp_path / 'pio0'} is not a character device"


@pytest.mark.parametrize(
    ("compatible", "why"),
    [
        (b"raspberrypi,5-model-b\0brcm,bcm2712\0", None),
        (b"raspberrypi,5-compute-module\0brcm,bcm2712\0", None),
        (b"raspberrypi,4-model-b\0brcm,bcm2711\0", "not a BCM2712 (Pi 5 / CM5): no RP1 PIO"),
    ],
)
def test_rp1_pio_runs_only_on_a_bcm2712(tmp_path, compatible, why):
    (tmp_path / "compatible").write_bytes(compatible)
    assert links.not_rp1_host(str(tmp_path / "compatible")) == why


def test_a_host_without_a_device_tree_skips_rp1_pio(tmp_path):
    assert links.not_rp1_host(str(tmp_path / "none")).startswith("cannot read ")
