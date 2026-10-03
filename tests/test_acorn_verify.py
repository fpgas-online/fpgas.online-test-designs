"""Tests for the Acorn check (fpgas_online_verify.boards.acorn: check.py, suite.py).

The check never writes the flash and never reconfigures the FPGA. It runs every test it can and lists every
fault: one result, pass or fail (docs/verify-goals.md). Its tests, in order:

  pcie-link, pcie-bar0, jtag, flash, p2-uart, scratch, p2-gpio

The SoC is tests/acorn_fakes.py's FakeSoC (its flash side is tests/test_spi_flash.py's fake S25FL256S, so
a read goes through the real spi_flash.Flash code path, STARTUPE2's swallowed clocks included), the Pi is
FakePi, and the release is installed in a temporary directory.
"""

import ast
import json
import pathlib

import pytest
from fpgas_online_verify import core, identity
from fpgas_online_verify.boards.acorn import BOARD as ACORN
from fpgas_online_verify.boards.acorn import check as av
from fpgas_online_verify.boards.acorn import suite

from tests import acorn_fakes as fk
from tests import test_spi_flash as tsf
from tests.test_spi_flash import sf


@pytest.fixture(autouse=True)
def small_slots(monkeypatch):
    """The check reads each 4 MiB slot whole; through the fake chip that is minutes. 80 KiB still holds the
    70000-byte test images and more, so what lies past an image is still read and hashed."""
    monkeypatch.setattr(sf, "SLOT_SIZE", 0x14000)


@pytest.fixture
def images(tmp_path):
    return fk.release(tmp_path / "images")


class Rig:
    """One Acorn on one Pi: the SoC, the Pi's pins and tools, the P2 UART, and the sysfs the check reads."""

    def __init__(self, tmp_path, images, model=fk.PI5, ids=fk.OURS, driver=None, uart=None, width="1", **soc):
        self.soc = fk.FakeSoC(**soc)
        self.pi = fk.FakePi(self.soc)
        self.uart = uart or fk.SoCLink(self.soc)
        self.bar = fk.Bar(self.soc)
        self.root = fk.pci(tmp_path / "sys" / "devices", ids=ids, driver=driver, width=width)
        self.images, self.model, self.events = images, model, []

    def found(self):
        (dev,) = av.scan_pci(self.root)
        return dev

    def options(self, **extra):
        return {"images": self.images, "model": self.model, "open_bar": self.bar, "run": self.pi,
                "gpiochip": lambda compatible: None, "uart_opener": self.uart.open, "settle": self.uart.settle,
                "sysfs_pci": self.root, "event": lambda stage, d: self.events.append((stage, d)),
                "sleep": self.soc.sleep, "clock": self.soc.clock, **extra}  # fmt: skip

    def check(self, **extra):
        return suite.check_board(self.found(), self.options(**extra))


def _results(report):
    return {t["test"]: t["result"] for t in report["tests"]}


# -- PCI IDs ---------------------------------------------------------------------------------------------


def test_the_subsystem_table_is_the_one_the_soc_is_built_with():
    """The check cannot import the gateware (no LiteX on a Pi), so check its copy against the source."""
    soc = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "gateware" / "acorn_pcie_soc.py"
    tree = ast.parse(soc.read_text())
    consts = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in ("PCIE_SUBSYSTEM_VENDOR_ID", "PCIE_SUBSYSTEM_ID")
    }  # fmt: skip
    vendor = consts["PCIE_SUBSYSTEM_VENDOR_ID"]
    expected = {(vendor, sid): variant for variant, sid in consts["PCIE_SUBSYSTEM_ID"].items()}
    assert expected == av.OUR_SUBSYSTEMS


@pytest.mark.parametrize(
    ("ids", "cls", "bars", "kind", "variant"),
    [
        (fk.OURS, "0x058000", (0x100000,), "fpgas-online", "cle-215+"),
        (("0x10ee", "0x7021", "0x1e24", "0x0101"), "0x058000", (0x100000,), "fpgas-online", "cle-101"),
        (fk.FACTORY, "0x058000", (0x100000,), "sqrl-factory", "cle-215+"),
        (("0x1e24", "0x0101", "0x0000", "0x0000"), "0x058000", (0x100000,), "sqrl-factory", "cle-101"),
        (fk.VENDOR_XDMA, "0x070001", (0x100000,), "vendor-xdma", None),
        # an older build of ours, without the subsystem IDs: one BAR, LitePCIe's class
        (("0x10ee", "0x7021", "0x10ee", "0x0007"), "0x058000", (0x100000,), "litex-other", None),
        # pi-sw2-p37 (2026-10-01): the same IDs, but the XDMA IP's class and its DMA BAR as well
        (("0x10ee", "0x7021", "0x10ee", "0x0007"), "0x070001", (0x100000, 0, 0x10000), "xilinx-xdma", None),
        # pi-sw1-p38: PCILeech's ID
        (("0x10ee", "0x0666", "0x10ee", "0x0007"), "0x020000", (0x1000,), "pcileech", None),
    ],
)
def test_classify_names_what_is_running_from_config_space_alone(tmp_path, ids, cls, bars, kind, variant):
    root = fk.pci(tmp_path / "devices", ids=ids, cls=cls, bars=bars)
    fk.pci(root, bdf="0002:01:00.0", ids=fk.RP1)
    (dev,) = av.scan_pci(root)
    assert (dev["kind"], dev["variant"]) == (kind, variant)


def test_a_pi_with_no_pci_bus_at_all_has_no_devices(tmp_path):
    """A Pi 3 or an Orange Pi has no PCIe, so no /sys/bus/pci/devices: found on pi-sw1-p10, where the
    service crashed with FileNotFoundError instead of reporting "none"."""
    assert av.scan_pci(tmp_path / "no-such-dir") == []


def test_the_command_on_a_pi_with_no_pci_bus_reports_missing_without_crashing(tmp_path, monkeypatch):
    """#43: a Pi with no /sys/bus/pci (a Pi 3, an Orange Pi). The check must not crash there. A host set up for
    an Acorn that has none is `missing`, which is fatal (fpgas-verify's rule for a configured board)."""
    from fpgas_online_verify import cli, runner

    monkeypatch.setattr(runner, "pci_devices", lambda: core.pci_devices(tmp_path / "no-such-dir"))
    monkeypatch.setattr(runner, "usb_devices", lambda: [])
    out = tmp_path / "report.json"
    rc = cli.board_main(["--no-publish", "--report", str(out), "--state", str(tmp_path / "state.json")],
                        prog="fpgas-acorn-verify")  # fmt: skip
    report = json.loads(out.read_text())
    assert rc == 1 and report["result"] == "missing" and report["mode"] == "acorn"


# -- boards that do not run our design -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("ids", "what"), [(fk.FACTORY, "SQRL's factory image"), (fk.VENDOR_XDMA, "the vendor XDMA sample image")]
)
def test_a_board_on_factory_or_vendor_firmware_fails_as_unconverted_and_its_bar_is_never_opened(
    tmp_path, images, ids, what
):
    rig = Rig(tmp_path, images, ids=ids)
    report = suite.check_board(rig.found(), rig.options(open_bar=fk.refuse))
    assert report["result"] == "fail"
    assert report["reason"].startswith(f"unconverted: runs {what}, not the fpgas.online design")
    assert not rig.uart.opened_at  # no UARTBone traffic to a design we did not build


@pytest.mark.parametrize(
    ("kind", "identifier", "model"),
    [
        ("fpgas-online", fk.OP_IDENT_ON_CHIP, "cle-215+"),
        ("fpgas-online", "fpgas-online Acorn PCIe SoC cle-101 2026-09-21 14:23:32", "cle-101"),
        ("fpgas-online", fk.GOLDEN_IDENT_ON_CHIP, "cle-215+"),
        ("fpgas-online", "fpgas-online Acorn PCIe SoC 2026-09-21 14:23:32", None),  # names no variant
        ("fpgas-online", "LiteX SoC on Acorn CLE-215+ 2026-09-21", None),  # not our SoC's identifier
        ("fpgas-online", None, None),  # BAR0 not read
        ("sqrl-factory", fk.OP_IDENT_ON_CHIP, None),  # not our design, whatever it says
        ("litex-other", fk.OP_IDENT_ON_CHIP, None),
    ],
)
def test_the_soc_model_is_what_our_socs_identifier_names(kind, identifier, model):
    assert av.soc_model(kind, identifier) == model


def test_the_identity_is_handed_to_the_runner_once_it_is_built(tmp_path, images):
    kept = []
    report = Rig(tmp_path, images).check(**{identity.KEEP: kept.append})
    assert kept == [report["identity"]]


def test_the_soc_model_comes_from_the_identifier_and_not_the_pci_ids(tmp_path, images):
    ident = Rig(tmp_path, images).check()["identity"]
    assert ident["soc_model"] == "cle-215+" and ident["identifier"] == fk.OP_IDENT_ON_CHIP
    rig = Rig(tmp_path / "factory", images, ids=fk.FACTORY)  # the variant is known, from SQRL's IDs
    ident = suite.check_board(rig.found(), rig.options(open_bar=fk.refuse))["identity"]
    assert ident["variant"] == "cle-215+" and "soc_model" not in ident and "identifier" not in ident


def test_a_board_on_sqrl_factory_image_still_has_its_link_and_jtag_checked(tmp_path, images):
    """Its variant is known from the factory IDs, so its P1 JTAG and PCIe link are tested; nothing on BAR0."""
    rig = Rig(tmp_path, images, ids=fk.FACTORY)
    report = suite.check_board(rig.found(), rig.options(open_bar=fk.refuse))
    assert _results(report) == {"pcie-link": "pass", "jtag": "pass"}
    assert set(report["not_run"]) == {"pcie-bar0", "flash", "ddr", "p2-uart", "p2-serial", "scratch", "p2-gpio"}
    assert "unconverted" in report["not_run"]["flash"]


@pytest.mark.parametrize(
    ("ids", "cls", "bars", "title"),
    [
        (("0x10ee", "0x0666", "0x10ee", "0x0007"), "0x020000", (0x1000,), "PCIe Screamer (PCILeech image)"),
        (("0x10ee", "0x7021", "0x10ee", "0x0007"), "0x070001", (0x100000, 0, 0x10000),
         "Xilinx XDMA design (likely PicoEVB)"),
    ],
)  # fmt: skip
def test_xilinx_boards_that_are_not_acorns_are_named_and_fail_with_no_bar_traffic(tmp_path, images, ids, cls, bars,
                                                                                   title):  # fmt: skip
    root = fk.pci(tmp_path / "devices", ids=ids, cls=cls, bars=bars)
    (dev,) = av.scan_pci(root)
    assert dev["title"] == title
    events = []
    report = suite.check_board(dev, {"images": images, "open_bar": fk.refuse, "run": fk.FakePi(), "model": fk.PI5,
                                     "event": lambda s, d: events.append(s)})  # fmt: skip
    assert report["result"] == "fail"
    assert report["reason"] == f"{title}: fpgas.online has no test design for this board yet"
    assert report["tests"] == [] and "unconverted" not in report["reason"]
    assert events == ["fpga-board-identified"]


def test_a_design_we_did_not_build_fails_as_such(tmp_path, images):
    root = fk.pci(tmp_path / "devices", ids=("0x10ee", "0x7021", "0x10ee", "0x0007"))
    (dev,) = av.scan_pci(root)
    report = suite.check_board(dev, {"images": images, "open_bar": fk.refuse, "model": fk.PI5})
    assert report["result"] == "fail" and report["reason"] == "10ee:7021 subsystem 10ee:0007 is not a design we built"


# -- a board that runs the release -------------------------------------------------------------------


def test_a_board_running_the_release_with_every_link_working_passes_every_test(tmp_path, images):
    rig = Rig(tmp_path, images)
    report = rig.check()
    assert report["result"] == "pass", report.get("reason")
    assert _results(report) == dict.fromkeys(suite.TESTS, "pass")
    assert report["running"] == {"identifier": fk.OP_IDENT_ON_CHIP, "build": "operational"}
    assert report["setup"] == "Raspberry Pi 5"
    assert report["identity"] == {
        "board": "acorn", "kind": "acorn", "variant": "cle-215+", "bdf": "0001:01:00.0", "soc_model": "cle-215+",
        "identifier": fk.OP_IDENT_ON_CHIP, "build": "operational", "dna": "0x0054b48664b04854",
        "idcode": "0x13636093", "idcode_version": 1, "idcode_part_number": "0x3636", "idcode_manufacturer_id": "0x049",
        "idcode_manufacturer": "Xilinx", "idcode_device": "XC7A200T",
        "flash": "S25FL256S", "flash_jedec": "0x010219", "flash_extended_id": "0x4d0180",
        "flash_size_bytes": 33554432, "flash_status": "0x00", "flash_config": "0x02", "flash_quad": True,
        "flash_uid": "a0a1a2a3a4a5a6a7a8a9aaabacadaeaf", "flash_uid_bits": 128, "flash_uid_state": "read",
        "flash_uid_opcode": "0x4b", "flash_sfdp": "none", "flash_source": "pcie",
    }  # fmt: skip
    assert report["state"]["dna"] == "0x0054b48664b04854"
    assert set(report["state"]["flash"]["slots"]) == {"0x000000", "0x400000"}
    assert "not_run" not in report


def test_the_state_is_the_slot_ids_dna_and_flash_contents(tmp_path, images):
    report = Rig(tmp_path, images).check()
    flash = report["state"].pop("flash")
    assert report["state"] == {"bdf": "0001:01:00.0", "ids": "10ee:7021", "subsystem": "1e24:021f",
                               "variant": "cle-215+", "dna": "0x0054b48664b04854"}  # fmt: skip
    assert flash["part"] == "S25FL256S" and flash["jedec"] == "0x010219" and len(flash["unique_id"]) == 32
    assert set(flash["slots"]) == {"0x000000", "0x400000"} and all(len(h) == 64 for h in flash["slots"].values())
    assert report["bitstreams"] == fk.TAG


def test_what_each_test_read_is_in_the_report(tmp_path, images):
    report = Rig(tmp_path, images).check()
    t = {x["test"]: x for x in report["tests"]}
    assert (t["pcie-link"]["speed_gt_s"], t["pcie-link"]["width"]) == (5.0, 1)
    assert t["pcie-bar0"]["xadc"] == {"temperature_c": 39.1, "vccint_v": 1.022, "vccaux_v": 1.789, "vccbram_v": 1.022}
    assert t["pcie-bar0"]["dna"] == t["jtag"]["dna"] == t["p2-uart"]["dna"] == "0x54b48664b04854"
    assert t["p2-uart"]["baud"] == [1200, 921600]
    assert t["scratch"]["over"] == ["BAR0", "P2 UART"]
    assert t["p2-gpio"]["wired"] == {"J5": "GPIO3", "H5": "GPIO4"}


def test_the_identifier_is_compared_without_regard_to_case(tmp_path, images):
    """csr.json lower-cases the constant; the identifier memory holds it as the gateware wrote it."""
    assert fk.OP_IDENT_ON_CHIP != fk.OP_IDENT and fk.OP_IDENT_ON_CHIP.casefold() == fk.OP_IDENT
    report = Rig(tmp_path, images, identifier=fk.OP_IDENT_ON_CHIP).check()
    assert report["running"]["build"] == "operational"


def test_the_events_say_each_test_as_it_goes_and_who_the_board_is(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.check()
    stages = [s for s, _ in rig.events]
    assert stages[:6] == ["fpga-test-started", "fpga-test-finished"] * 3
    assert stages[6] == "fpga-board-identified"  # once PCIe and JTAG have said who it is
    assert stages.count("fpga-test-finished") == len(suite.TESTS)
    finished = [d for s, d in rig.events if s == "fpga-test-finished"]
    assert finished[0] == {"test": "pcie-link", "result": "pass", "reason": ""}
    assert all(isinstance(v, str) for _, d in rig.events for v in d.values() if v is not None)


def test_the_identified_event_is_the_identity_as_flat_strings(tmp_path, images):
    rig = Rig(tmp_path, images)
    report = rig.check(board_key="acorn@0001:01:00.0")
    (sent,) = [d for s, d in rig.events if s == "fpga-board-identified"]
    assert sent == identity.details(report["identity"])
    assert sent["schema"] == "fpga-identity/1" and sent["board"] == "acorn@0001:01:00.0"
    assert sent["flash_quad"] == "true" and sent["flash_size_bytes"] == "33554432"
    assert "pci_ids" not in sent and "subsystem" not in sent  # in the report's found and state, not the event


def test_a_flash_that_did_not_identify_itself_is_a_flash_error(tmp_path, images, monkeypatch):
    def broken(flash):
        raise av.spi_flash.FlashError("the SPI master never went idle")

    monkeypatch.setattr(av, "flash_identity", broken)
    report = Rig(tmp_path, images).check()
    assert report["identity"]["flash_error"] == "the flash did not identify itself: the SPI master never went idle"
    assert report["identity"]["flash_source"] == "pcie" and "flash_jedec" not in report["identity"]


def test_a_jtag_probe_that_could_not_run_is_an_idcode_and_dna_error(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.pi.tool = False
    report = rig.check(tests=["jtag"])  # nothing that needs BAR0: no DNA from there either
    ident = report["identity"]
    assert "openFPGALoader is not installed" in ident["idcode_error"]
    assert ident["dna_error"] == "not read over P1 JTAG: P1 JTAG could not be probed: openFPGALoader is not installed"
    assert "idcode" not in ident and "dna" not in ident and "flash_source" not in ident


def test_with_bar0_down_and_the_wrong_idcode_the_dna_error_says_why_the_dna_was_not_read(tmp_path, images):
    """The JTAG test's reason is about the IDCODE; the DNA's is that --read-dna was never run."""
    rig = Rig(tmp_path, images)
    rig.pi.idcode = 0x13631093  # an XC7A100T on a cle-215+
    report = rig.check(tests=["jtag"])
    ident = report["identity"]
    assert "expected one XC7A200T" in report["tests"][0]["reason"] and ident["idcode"] == "0x13631093"
    assert ident["dna_error"] == (
        "not read over P1 JTAG: --read-dna runs only once --detect has found the one FPGA expected"
    )
    assert "XC7A200T" not in ident["dna_error"]


def test_with_bar0_down_a_failed_dna_read_says_so(tmp_path, images, monkeypatch):
    rig = Rig(tmp_path, images)
    real = rig.pi.__call__

    def no_dna(argv, timeout):
        return (1, "JTAG error\n") if "--read-dna" in argv else real(argv, timeout)

    monkeypatch.setattr(rig, "pi", no_dna)
    ident = rig.check(tests=["jtag"])["identity"]
    assert ident["idcode"] == "0x13636093" and "idcode_error" not in ident
    assert ident["dna_error"] == "openFPGALoader --read-dna read no device DNA over P1 JTAG (exit status 1)"


@pytest.mark.parametrize("stuck", [0, (1 << 57) - 1])
def test_a_stuck_bar0_dna_is_no_dna_and_a_good_jtag_one_is_used(tmp_path, images, stuck):
    report = Rig(tmp_path, images, dna=stuck).check()
    assert "the DNA port is not being read" in {t["test"]: t for t in report["tests"]}["pcie-bar0"]["reason"]
    assert report["identity"]["dna"] == "0x0054b48664b04854" and "dna_error" not in report["identity"]


@pytest.mark.parametrize("stuck", [0, (1 << 57) - 1])
def test_a_stuck_bar0_dna_is_not_compared_with_a_good_jtag_one(tmp_path, images, stuck):
    """A stuck BAR0 DNA is pcie-bar0's fault, not a wrong TDI: jtag passes on its own good DNA."""
    report = Rig(tmp_path, images, dna=stuck).check()
    tests = {t["test"]: t for t in report["tests"]}
    assert tests["pcie-bar0"]["result"] == "fail"
    assert tests["pcie-bar0"]["reason"] == f"device DNA over BAR0 reads {stuck:#x}: the DNA port is not being read"
    assert tests["jtag"]["result"] == "pass" and tests["jtag"]["dna"] == "0x54b48664b04854"
    assert "is not the one over BAR0" not in report["reason"]


def test_a_good_jtag_dna_that_differs_from_a_good_bar0_one_still_fails(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.pi.jtag_dna = 0x1234
    jtag = {t["test"]: t for t in rig.check()["tests"]}["jtag"]
    assert jtag["result"] == "fail"
    assert jtag["reason"] == ("device DNA over JTAG 0x1234 is not the one over BAR0 0x54b48664b04854: "
                              "TDI (or the DNA readout) is wrong")  # fmt: skip


def test_a_stuck_bar0_dna_is_not_compared_with_a_good_p2_uart_one(tmp_path, images, monkeypatch):
    """A stuck BAR0 DNA (here, BAR0's DNA read alone stuck) is not blamed on the P2 UART."""
    real = av.read_dna
    monkeypatch.setattr(av, "read_dna", lambda read, csrs: 0 if read.__name__ == "read" else real(read, csrs))
    tests = {t["test"]: t for t in Rig(tmp_path, images).check()["tests"]}
    assert tests["pcie-bar0"]["reason"] == "device DNA over BAR0 reads 0x0: the DNA port is not being read"
    assert tests["p2-uart"]["result"] == "pass" and tests["jtag"]["result"] == "pass"


def test_a_stuck_bar0_dna_with_no_jtag_read_is_a_dna_error(tmp_path, images):
    ident = Rig(tmp_path, images, dna=0).check(tests=["pcie-bar0"])["identity"]
    assert "dna" not in ident
    assert ident["dna_error"] == "device DNA over BAR0 reads 0x0: the DNA port is not being read"


def test_a_stuck_dna_over_both_bar0_and_jtag_is_a_dna_error_saying_both(tmp_path, images):
    rig = Rig(tmp_path, images, dna=0)
    rig.pi.jtag_dna = 0
    ident = rig.check()["identity"]
    assert "dna" not in ident
    assert ident["dna_error"] == ("device DNA over BAR0 reads 0x0: the DNA port is not being read; "
                                  "device DNA over P1 JTAG reads 0x0: the DNA port is not being read")  # fmt: skip


STUCK_DNAS = [0, (1 << 57) - 1]  # openFPGALoader masks the DNA to 57 bits, so all ones is 0x1ffffffffffffff


@pytest.mark.parametrize("bar0_dna", [fk.DNA, *STUCK_DNAS], ids=["bar0-good", "bar0-zeros", "bar0-ones"])
@pytest.mark.parametrize("jtag_dna", STUCK_DNAS, ids=["jtag-zeros", "jtag-ones"])
def test_a_stuck_jtag_dna_fails_the_jtag_test_whatever_bar0_read(tmp_path, images, bar0_dna, jtag_dna):
    """A stuck JTAG DNA is the jtag test's own fault, with a good BAR0 DNA or a stuck one, and is not the
    board's DNA."""
    rig = Rig(tmp_path, images, dna=bar0_dna)
    rig.pi.jtag_dna = jtag_dna
    report = rig.check()
    tests = {t["test"]: t for t in report["tests"]}
    stuck = f"device DNA over P1 JTAG reads {jtag_dna:#x}: the DNA port is not being read"
    assert tests["jtag"]["result"] == "fail"
    assert "dna" not in tests["jtag"] and tests["jtag"]["dna_error"] == stuck
    assert stuck in report["reason"]
    ident = report["identity"]
    if bar0_dna == fk.DNA:  # BAR0's DNA is good, so the JTAG one is compared with it as well (a TDI fault)
        assert tests["jtag"]["reason"] == (f"{stuck}; device DNA over JTAG {jtag_dna:#x} is not the one over BAR0 "
                                           f"{fk.DNA:#x}: TDI (or the DNA readout) is wrong")  # fmt: skip
        assert ident["dna"] == "0x0054b48664b04854" and "dna_error" not in ident
        assert tests["pcie-bar0"]["result"] == "pass"
    else:  # BAR0's is stuck too, so not compared
        assert tests["jtag"]["reason"] == stuck
        bar0_stuck = f"device DNA over BAR0 reads {bar0_dna:#x}: the DNA port is not being read"
        assert tests["pcie-bar0"]["reason"] == bar0_stuck
        assert "dna" not in ident and ident["dna_error"] == f"{bar0_stuck}; {stuck}"


def test_an_s25fs256s_is_named_by_its_extended_id(tmp_path, images, monkeypatch):
    monkeypatch.setattr(tsf, "RDID", bytes.fromhex("0102194d0181"))
    ident = Rig(tmp_path, images).check()["identity"]
    assert (ident["flash"], ident["flash_jedec"], ident["flash_extended_id"]) == ("S25FS256S", "0x010219", "0x4d0181")


def test_the_flash_sfdp_revision_is_in_the_identity(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.soc.flash.sfdp = tsf.SFDP_1_6
    report = rig.check()
    assert report["identity"]["flash_sfdp"] == "1.6" and "flash_sfdp_error" not in report["identity"]
    assert report["flash"]["sfdp_header"] == tsf.SFDP_1_6[:8].hex()
    assert _results(report)["pcie-bar0"] == "pass"


def test_an_s25fl256s_answers_without_sfdp_so_its_flash_sfdp_is_none(tmp_path, images):
    report = Rig(tmp_path, images).check()
    assert report["identity"]["flash_sfdp"] == "none"
    assert identity.details(report["identity"])["flash_sfdp"] == "none"


def test_an_sfdp_read_that_failed_is_a_flash_sfdp_error_and_fails_pcie_bar0(tmp_path, images, monkeypatch):
    def broken(flash):
        raise sf.FlashError("the SPI master never went idle")

    monkeypatch.setattr(sf.Flash, "sfdp_header", broken)
    report = Rig(tmp_path, images).check()
    ident = report["identity"]
    assert ident["flash_sfdp_error"] == "Read SFDP (0x5a) failed: the SPI master never went idle"
    assert "flash_sfdp" not in ident and ident["flash_jedec"] == "0x010219"  # the IDs still stand
    bar0 = next(t for t in report["tests"] if t["test"] == "pcie-bar0")
    assert bar0["result"] == "fail"
    assert bar0["reason"] == ("the flash's SFDP could not be read: Read SFDP (0x5a) failed: the SPI master never "
                              "went idle")  # fmt: skip


FIXTURE = pathlib.Path(__file__).parent / "data" / "identity-v1-acorn-p48.json"
P48_FLASH_UID = "edcbeececb2b2a88b04f914d2e46af90"  # pi-sw2-p48's S25FL256S, read over BAR0 and by openFPGALoader


def p48_document(tmp_path, images):
    """The golden fixture: the Acorn fakes' identity (pi-sw2-p48's DNA, IDCODE and RDID), with p48's flash
    unique ID, as fpgas-verify --identify prints it."""
    board = {**Rig(tmp_path / "p48", images).check()["identity"], "flash_uid": P48_FLASH_UID}
    doc = identity.document([board], tool="fpgas-online-verify 0.0.post808", read_at="2026-10-02T00:00:00+00:00")
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


def test_the_golden_fixture_is_what_the_check_reads_from_p48(tmp_path, images):
    """tests/data/identity-v1-acorn-p48.json; rpi-hwid keeps a byte-identical copy and tests its parser on it."""
    assert FIXTURE.read_text() == p48_document(tmp_path, images)


# -- faults: each fails the board, and the check goes on -------------------------------------------------


def test_running_the_golden_image_fails_and_the_flash_is_still_checked(tmp_path, images):
    rig = Rig(tmp_path, images, identifier=fk.GOLDEN_IDENT_ON_CHIP, golden=True)
    report = rig.check()
    assert report["result"] == "fail"
    assert report["running"]["build"] == "golden"
    results = _results(report)
    assert results["pcie-bar0"] == "fail" and results["flash"] == "pass" and results["jtag"] == "pass"
    assert "running the golden image: the operational slot did not boot" in report["reason"]
    # the golden image has no DRAM, P2 switch or spare GPIO: not run, and the board fails for running golden
    assert report["not_run"] == {"ddr": "the golden image has no DRAM",
                                 "p2-serial": "the golden image has no P2 serial switch",
                                 "p2-gpio": "the golden image has no P2 spare GPIO"}  # fmt: skip


def test_a_changed_operational_slot_fails_and_says_where(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.soc.flash.mem[sf.OPERATIONAL_ADDR + 0x1234] ^= 0x01
    report = rig.check()
    golden, operational = report["flash"]["slots"]
    assert report["result"] == "fail"
    assert golden["result"] == "match"
    assert operational == {**operational, "result": "mismatch", "first_difference": "0x401234"}
    assert report["reason"] == f"flash fail: flash does not hold release {fk.TAG}: 0x400000 differs at 0x401234"
    assert [r for r in _results(report).values() if r != "pass"] == ["fail"]  # everything else still ran


def test_several_faults_are_all_listed_and_every_test_still_runs(tmp_path, images):
    """A dead P2 UART, a link at the wrong width and a TDI that does not carry: three faults, one report."""
    rig = Rig(tmp_path, images, uart=fk.Cut(), width="2")
    rig.pi.jtag_dna = 0x1  # what a JTAG chain whose TDI never arrives might read
    report = rig.check()
    assert report["result"] == "fail"
    results = _results(report)
    assert [t for t, r in results.items() if r != "pass"] == ["pcie-link", "jtag", "p2-uart", "p2-serial", "scratch"]
    assert "link is x2, expected x1" in report["reason"]
    assert "device DNA over JTAG 0x1 is not the one over BAR0 0x54b48664b04854" in report["reason"]
    assert "no UARTBone reply on /dev/ttyAMA0 (P2 K2/J2)" in report["reason"]
    assert results["flash"] == results["p2-gpio"] == "pass"


def test_a_dna_that_reads_all_ones_fails(tmp_path, images):
    report = Rig(tmp_path, images, dna=(1 << 57) - 1).check()
    assert "the DNA port is not being read" in report["reason"]


def test_xadc_readings_out_of_range_fail(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.soc.xadc["xadc_vccint"] = 0x600  # 1.125 V
    report = rig.check()
    assert "XADC vccint_v over BAR0 is 1.125, outside 0.95 to 1.05" in report["reason"]
    assert "XADC vccint_v over P2 UART is 1.125" in report["reason"]


def test_a_scratch_register_that_does_not_hold_a_bit_fails_over_both_bridges(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.soc.scratch_stuck = 0x00000100
    report = rig.check()
    assert _results(report)["scratch"] == "fail"
    assert "scratch over BAR0" in report["reason"] and "scratch over P2 UART" in report["reason"]


def test_a_cut_j5_wire_fails_both_directions(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.pi.cut = ("J5",)
    report = rig.check()
    assert _results(report)["p2-gpio"] == "fail"
    assert "J5 -> GPIO3: the FPGA drove 0, the Pi read 1" in report["reason"]
    assert "GPIO3 -> J5: the Pi drove 0, the FPGA read 1" in report["reason"]
    assert "H5" not in report["reason"]


def test_j5_and_h5_go_back_to_inputs_on_both_sides(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.check()
    assert rig.soc.oe == 0 and rig.soc.out == 0
    assert rig.pi.pins[3][:2] == ["no", "pu"] and rig.pi.pins[4][:2] == ["no", "pu"]  # as they were found


def test_the_jtag_pins_go_back_as_they_were_found(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.check()
    assert all(rig.pi.pins[g][0] == "ip" for g in (8, 9, 10, 11))


def test_a_build_not_in_the_manifest_fails_without_the_flash_being_touched(tmp_path, images):
    rig = Rig(tmp_path, images, identifier="fpgas-online Acorn PCIe SoC cle-215+ 2026-10-01 09:00:00")
    report = rig.check()
    assert report["result"] == "fail"
    assert "not in release" in report["reason"]
    assert not rig.soc.flash_touched
    assert {"flash", "p2-gpio"} <= set(report["not_run"])
    assert _results(report)["p2-uart"] == "fail"  # the same unknown build answers on P2: nothing is sent to it


def test_a_csr_map_that_disagrees_with_spi_flash_is_an_error_and_the_flash_is_not_touched(tmp_path, images):
    csr = fk.csr_json()
    csr["csr_bases"]["flash_cs_n"] = 0xF0004800
    fk.rewrite(images, "acorn-cle-215p-csr.json", json.dumps(csr).encode())
    rig = Rig(tmp_path, images)
    report = rig.check()
    assert report["result"] == "error"
    assert "flash_cs_n" in report["reason"]
    assert not rig.soc.flash_touched


def test_an_installed_image_that_does_not_match_its_manifest_hash_is_an_error(tmp_path, images):
    (images / "acorn-cle-215p-sqrl_acorn_operational.bin").write_bytes(b"\0" * 10)
    report = Rig(tmp_path, images).check()
    assert report["result"] == "error"
    assert "sha256" in report["reason"]


def test_the_check_never_sends_a_writing_opcode(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.check()
    assert not set(rig.soc.flash.opcodes) & sf.WRITE_OPCODES


# -- setups ----------------------------------------------------------------------------------------------


def test_on_a_compute_blade_jtag_uses_its_pins_and_j5_h5_are_not_tested(tmp_path, images):
    rig = Rig(tmp_path, images, model=fk.CM4)
    rig.pi.pins.update({2: ["a0", "pu", None], 3: ["a0", "pu", None], 4: ["ip", "pu", None]})
    report = rig.check()
    assert report["setup"] == "Compute Blade"
    assert report["result"] == "pass", report.get("reason")
    loads = rig.pi.ran("openFPGALoader")
    blade_p1 = ["openFPGALoader", "--cable", "libgpiod", "--pins", "2:3:4:14"]
    assert loads[0] == [*blade_p1, "--detect", "--verbose-level", "2"]
    assert report["not_run"] == {"p2-gpio": "J5 and H5 are not wired on the Compute Blade setup"}
    # GPIO14 is TMS and the UART's TX: it goes back to its UART function, or the P2 UART would be dead
    assert rig.pi.pins[14][:2] == ["a4", "pn"]


def test_a_host_that_is_no_acorn_setup_is_an_error_but_the_pcie_side_is_still_checked(tmp_path, images):
    report = Rig(tmp_path, images, model="Raspberry Pi 4 Model B Rev 1.4").check()
    assert report["result"] == "error"
    assert "is not an Acorn setup in wiring.toml" in report["reason"]
    assert _results(report) == {"pcie-bar0": "pass", "flash": "pass", "ddr": "pass", "scratch": "pass"}
    assert set(report["not_run"]) >= {"pcie-link", "jtag", "p2-uart", "p2-gpio"}


# -- a driver that holds BAR0 -------------------------------------------------------------------------------


def test_a_bound_driver_is_unbound_for_the_check_and_bound_again(tmp_path, images):
    rig = Rig(tmp_path, images, driver="litepcie")
    drivers = tmp_path / "sys" / "drivers" / "litepcie"
    report = rig.check()
    assert report["result"] == "pass", report.get("reason")
    assert (drivers / "unbind").read_text() == "0001:01:00.0"
    assert (drivers / "bind").read_text() == "0001:01:00.0"
    assert report["driver"] == {"driver": "litepcie", "unbound": True, "rebound": True}


def test_a_driver_that_cannot_be_bound_again_is_an_error(tmp_path, images):
    rig = Rig(tmp_path, images, driver="litepcie")
    (tmp_path / "sys" / "drivers" / "litepcie" / "bind").chmod(0o444)
    report = rig.check()
    if report["driver"].get("rebound"):  # running as root: the mode does not stop the write
        pytest.skip("root can write a read-only file")
    assert report["result"] == "error"
    assert "the litepcie driver could not be bound again" in report["reason"]


# -- choosing tests --------------------------------------------------------------------------------------


def test_only_the_tests_asked_for_run(tmp_path, images):
    rig = Rig(tmp_path, images)
    report = rig.check(tests=["pcie-link", "flash"])
    assert _results(report) == {"pcie-link": "pass", "flash": "pass"}
    assert not rig.pi.ran("openFPGALoader") and not rig.uart.opened_at


def test_a_test_the_acorn_does_not_have_is_an_error(tmp_path, images):
    rig = Rig(tmp_path, images)
    with pytest.raises(core.Problem, match="the Acorn has no test uart"):
        rig.check(tests=["uart"])


def test_the_board_module_lists_the_tests():
    assert ACORN.tests == suite.TESTS


# -- BAR0 ---------------------------------------------------------------------------------------------


def test_memory_decoding_is_enabled_for_the_read_and_put_back_afterwards(tmp_path):
    dev = tmp_path / "0001:01:00.0"
    dev.mkdir()
    config = bytearray(64)
    config[4:6] = (0x0000).to_bytes(2, "little")
    (dev / "config").write_bytes(config)
    (dev / "resource0").write_bytes(bytes(0x10000))

    with av.open_bar0("0001:01:00.0", sysfs=tmp_path) as bus:
        assert int.from_bytes((dev / "config").read_bytes()[4:6], "little") & 0x2
        assert bus.read(av.CSR_BASE) == 0
    assert int.from_bytes((dev / "config").read_bytes()[4:6], "little") == 0x0000


def test_memory_decoding_that_was_already_on_is_left_on(tmp_path):
    dev = tmp_path / "0001:01:00.0"
    dev.mkdir()
    config = bytearray(64)
    config[4:6] = (0x0006).to_bytes(2, "little")
    (dev / "config").write_bytes(config)
    (dev / "resource0").write_bytes(bytes(0x10000))
    with av.open_bar0("0001:01:00.0", sysfs=tmp_path):
        pass
    assert int.from_bytes((dev / "config").read_bytes()[4:6], "little") == 0x0006


def test_the_check_and_spi_flash_share_one_lock(tmp_path):
    import fcntl

    assert pathlib.Path(sf.LOCK) == av.LOCK
    lock = tmp_path / "run" / "lock" / "fpgas-acorn.lock"
    held = sf.hold_lock(str(lock))
    try:
        with open(lock, "w") as other, pytest.raises(BlockingIOError):
            fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    finally:
        held.close()


# -- review fixes ----------------------------------------------------------------------------------------


def test_something_unexpected_in_one_test_is_an_error_and_the_rest_still_run(tmp_path, images):
    rig = Rig(tmp_path, images)
    real = rig.soc.read

    def read(addr):
        if addr == fk.REGS["xadc_vccaux"]:
            raise ValueError("a bus that misbehaves")
        return real(addr)

    rig.soc.read = read
    report = rig.check()
    results = _results(report)
    assert results["pcie-bar0"] == "error"
    assert "pcie-bar0 error: ValueError: a bus that misbehaves" in report["reason"]
    assert [t for t in suite.TESTS if t not in results] == []  # every test after it ran
    assert results["flash"] == results["jtag"] == results["p2-gpio"] == "pass"


def test_a_csr_beyond_the_mapped_bar0_is_refused_before_anything_is_read(tmp_path, images):
    csr = fk.csr_json()
    csr["csr_registers"]["p2_gpio_oe"]["addr"] = 0xF0010000
    fk.rewrite(images, "acorn-cle-215p-csr.json", json.dumps(csr).encode())
    rig = Rig(tmp_path, images)
    report = rig.check()
    assert report["result"] == "error"
    assert "puts p2_gpio_oe at 0xf0010000, outside the 0x10000 bytes of BAR0" in report["reason"]
    assert not rig.soc.flash_touched


def test_the_driver_is_left_bound_when_no_test_asked_for_needs_bar0(tmp_path, images):
    rig = Rig(tmp_path, images, driver="litepcie")
    report = rig.check(tests=["pcie-link", "jtag"])
    assert _results(report) == {"pcie-link": "pass", "jtag": "pass"}
    assert (tmp_path / "sys" / "drivers" / "litepcie" / "unbind").read_text() == ""
    assert "driver" not in report and rig.bar.opened == 0


def test_no_event_goes_out_while_the_driver_is_unbound(tmp_path, images):
    rig = Rig(tmp_path, images, driver="litepcie")
    unbind = tmp_path / "sys" / "drivers" / "litepcie" / "unbind"
    bind = tmp_path / "sys" / "drivers" / "litepcie" / "bind"
    sent_while_unbound = []

    def event(stage, details):
        if unbind.read_text() and not bind.read_text():
            sent_while_unbound.append(stage)
        rig.events.append((stage, details))

    report = rig.check(event=event)
    assert report["result"] == "pass", report.get("reason")
    assert sent_while_unbound == []
    assert [s for s, _ in rig.events].count("fpga-test-finished") == len(suite.TESTS)  # all sent, after the rebind


def test_a_driver_that_cannot_be_unbound_is_an_error_and_bar0_is_not_touched(tmp_path, images):
    rig = Rig(tmp_path, images, driver="litepcie")
    (tmp_path / "sys" / "drivers" / "litepcie" / "unbind").unlink()
    (tmp_path / "sys" / "drivers" / "litepcie" / "unbind").mkdir()  # writing it fails, root or not
    report = rig.check()
    assert report["result"] == "error"
    assert "the litepcie driver holds the board and could not be unbound" in report["reason"]
    assert rig.bar.opened == 0
    assert {"pcie-bar0", "flash", "p2-gpio"} <= set(report["not_run"])
    assert _results(report)["jtag"] == "pass"  # what does not need BAR0 still runs


def test_missing_expected_figures_are_said_once(tmp_path, images, monkeypatch):
    from fpgas_online_verify.boards.acorn import setup

    real = setup.load

    def load(name, dirs=setup.DATA_DIRS):
        if name == setup.EXPECTED:
            raise core.Problem("error", "expected.toml is not installed")
        return real(name, dirs)

    monkeypatch.setattr(setup, "load", load)
    report = Rig(tmp_path, images).check()
    assert report["reason"].count("expected.toml is not installed") == 1
    assert report["setup"] == "Raspberry Pi 5"


def test_a_malformed_csr_json_is_an_error_and_what_needs_no_csr_map_still_runs(tmp_path, images):
    csr = fk.csr_json()
    del csr["csr_registers"]["dna_id"]["addr"]
    fk.rewrite(images, "acorn-cle-215p-csr.json", json.dumps(csr).encode())
    rig = Rig(tmp_path, images)
    report = rig.check()
    assert report["result"] == "error"
    assert "the release's csr.json could not be read: KeyError" in report["reason"]
    assert "the check crashed" not in report["reason"]
    assert _results(report)["pcie-link"] == _results(report)["jtag"] == "pass"
    assert not rig.soc.flash_touched


# -- the DRAM BIST and J2/K2 -----------------------------------------------------------------------------


def test_ddr_reports_its_errors_and_bandwidth_as_named_measurements(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.soc.console = bytearray(b"Initializing SDRAM @0x40000000...\nMemtest at 0x40000000 (2.0MiB)...\nMemtest OK\n")
    t = {x["test"]: x for x in rig.check()["tests"]}["ddr"]
    assert t["result"] == "pass"
    assert (t["bytes"], t["passes"], t["errors"]) == (fk.DRAM_BYTES, 2, 0)
    assert t["write_MBps"] > 1100 and t["read_MBps"] > 1100
    assert t["bios_memtest"] == "Memtest OK" and t["output"][-1] == "Memtest OK"
    assert rig.soc.console == bytearray()  # the console was read out first


def test_a_bandwidth_below_the_variants_minimum_fails_ddr_and_the_rest_still_run(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.soc.dram.mbps = 700
    report = rig.check()
    assert _results(report)["ddr"] == "fail"
    assert "DRAM write 7" in report["reason"] and "below the 1100 MB/s expected of cle-215+" in report["reason"]
    assert [t for t, r in _results(report).items() if r != "pass"] == ["ddr"]


def test_a_dead_dram_address_bit_fails_ddr(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.soc.dram = fk.DramModel(fk.DRAM_BYTES, dead_bit=(fk.DRAM_BYTES // fk.DramModel.WORD).bit_length() - 2)
    report = rig.check()
    assert _results(report)["ddr"] == "fail" and "words wrong" in report["reason"]


def test_j2_and_k2_both_ways_then_the_uartbone_again_and_the_pins_back(tmp_path, images):
    rig = Rig(tmp_path, images)
    report = rig.check()
    t = {x["test"]: x for x in report["tests"]}["p2-serial"]
    assert t["result"] == "pass", t
    assert t["wired"] == {"J2": "GPIO14", "K2": "GPIO15"}
    assert "switch timeout: mode 1, 0.5 s later 0" in t["output"]
    assert t["output"][-1] == f"UARTBone after the switch: {fk.OP_IDENT_ON_CHIP!r}"
    assert rig.pi.pins[14][:2] == ["a4", "pn"] and rig.pi.pins[15][:2] == ["a4", "pu"]  # as they were found
    assert rig.soc.serial == {"mode": 0, "oe": 0, "out": 0, "timeout": 5000}


def test_a_cut_k2_fails_both_ways(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.pi.cut = ("K2",)
    report = rig.check()
    assert _results(report)["p2-serial"] == "fail"
    assert "K2 -> GPIO15: the FPGA drove 1, the Pi read 0" in report["reason"]
    assert "GPIO15 -> K2: the Pi drove 0, the FPGA read 1" in report["reason"]


def test_a_switch_that_never_times_out_fails(tmp_path, images):
    rig = Rig(tmp_path, images)
    rig.soc.switch_stuck = True
    report = rig.check()
    assert "p2_serial did not go back to serial by itself" in report["reason"]


def test_on_a_blade_j2_and_k2_are_tested_and_j5_h5_are_not_wired(tmp_path, images):
    rig = Rig(tmp_path, images, model=fk.CM4)
    rig.pi.pins.update({2: ["a0", "pu", None], 3: ["a0", "pu", None], 4: ["ip", "pu", None]})
    report = rig.check()
    assert _results(report)["p2-serial"] == "pass"
    assert report["not_run"] == {"p2-gpio": "J5 and H5 are not wired on the Compute Blade setup"}
    assert rig.pi.pins[14][:2] == ["a4", "pn"]


@pytest.mark.parametrize("asked", [["ddr"], ["p2-gpio"], ["p2-serial"], ["ddr", "p2-serial", "p2-gpio"]])
def test_a_test_run_on_a_golden_board_fails_even_when_pcie_bar0_was_not_asked_for(tmp_path, images, asked):
    rig = Rig(tmp_path, images, identifier=fk.GOLDEN_IDENT_ON_CHIP, golden=True)
    report = rig.check(tests=asked)
    assert report["result"] == "fail"
    assert "running the golden image: the operational slot did not boot" in report["reason"]
    assert report["reason"].count("running the golden image") == 1
    assert f"none of the tests asked for ran ({', '.join(asked)})" in report["reason"]


def test_golden_is_said_once_when_pcie_bar0_runs(tmp_path, images):
    report = Rig(tmp_path, images, identifier=fk.GOLDEN_IDENT_ON_CHIP, golden=True).check()
    assert report["reason"].count("running the golden image") == 1


def test_a_run_in_which_nothing_asked_for_ran_fails(tmp_path, images):
    """J5/H5 are not wired on a Blade: asked for only that, nothing is tested, which is not a pass."""
    rig = Rig(tmp_path, images, model=fk.CM4)
    report = rig.check(tests=["p2-gpio"])
    assert report["tests"] == [] and report["result"] == "fail"
    assert report["reason"] == "none of the tests asked for ran (p2-gpio)"
