"""Tests for the boot-time Acorn check (designs/acorn-pcie/host/acorn_verify.py).

The check has three tiers, run on every boot and never writing anything to the board:

  1. the PCI IDs in sysfs say which image family is running;
  2. the SoC's identifier string, read over BAR0, says which build of the fpgas.online design is running;
  3. the flash's golden and operational slots are read back and compared with the images the release says
     belong there.

The flash side uses the same fake S25FL256S and SoC register bus as tests/test_spi_flash.py, so a read here
goes through the real spi_flash.Flash code path, STARTUPE2's swallowed clocks included.
"""

import ast
import hashlib
import importlib.util
import json
import pathlib

import pytest

from tests.test_spi_flash import FakeBus, FakeS25FL, image, sf

_HOST = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "host"
_spec = importlib.util.spec_from_file_location("acorn_verify", _HOST / "acorn_verify.py")
av = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(av)

# What csr.json records (lower case) and what the SoC's identifier memory holds (as written in the gateware).
OP_IDENT = "fpgas-online acorn pcie soc cle-215+ 2026-09-21 14:23:32"
GOLDEN_IDENT = "fpgas-online acorn pcie soc cle-215+ golden 2026-09-21 14:31:19"
OP_IDENT_ON_CHIP = "fpgas-online Acorn PCIe SoC cle-215+ 2026-09-21 14:23:32"
GOLDEN_IDENT_ON_CHIP = "fpgas-online Acorn PCIe SoC cle-215+ golden 2026-09-21 14:31:19"

CSR = {
    "csr_bases": {"identifier_mem": 0xF0000800, "flash": 0xF0003800, "flash_cs_n": 0xF0004000},
    "constants": {},
}


# -- fixtures ------------------------------------------------------------------------------------------


def _golden_image():
    return image(wbstar=sf.OPERATIONAL_ADDR, iprog=True, fill=0x11)


def _operational_image():
    return image(fill=0x22)


@pytest.fixture
def images(tmp_path):
    """An installed images directory: the two flash images for cle-215+, both builds' csr.json, a manifest."""
    d = tmp_path / "images"
    d.mkdir()
    files = []

    def add(asset, data, variant, golden, name, ident, slot):
        (d / asset).write_bytes(data)
        files.append(
            {
                "asset": asset,
                "variant": variant,
                "golden": golden,
                "file": name,
                "config_identifier": ident,
                "slot": slot,
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )

    csr = json.dumps(CSR).encode()
    add("acorn-cle-215p-golden-sqrl_acorn_fallback.bin", _golden_image(), "cle-215+-golden", True,
        "sqrl_acorn_fallback.bin", GOLDEN_IDENT, "0x000000")  # fmt: skip
    add("acorn-cle-215p-sqrl_acorn_operational.bin", _operational_image(), "cle-215+", False,
        "sqrl_acorn_operational.bin", OP_IDENT, "0x400000")  # fmt: skip
    add("acorn-cle-215p-csr.json", csr, "cle-215+", False, "csr.json", OP_IDENT, None)
    add("acorn-cle-215p-golden-csr.json", csr, "cle-215+-golden", True, "csr.json", GOLDEN_IDENT, None)
    manifest = {
        "schema_version": 1,
        "tag": "vivado-bitstreams-acorn-pcie-20260921-gf3355dccf443",
        "source_commit": "f3355dccf443" + "0" * 28,
        "flash_layout": {
            "cle-215+": {
                "0x000000": "acorn-cle-215p-golden-sqrl_acorn_fallback.bin",
                "0x400000": "acorn-cle-215p-sqrl_acorn_operational.bin",
            }
        },
        "files": files,
    }
    (d / "manifest.json").write_text(json.dumps(manifest))
    return d


@pytest.fixture
def chip():
    c = FakeS25FL()
    golden, operational = _golden_image(), _operational_image()
    c.mem[: len(golden)] = golden
    c.mem[sf.OPERATIONAL_ADDR : sf.OPERATIONAL_ADDR + len(operational)] = operational
    return c


class SoCBus(FakeBus):
    """The fake SoC bus plus the identifier memory: one character in the low byte of each 32-bit word."""

    def __init__(self, flash, identifier):
        super().__init__(flash)
        self.identifier = identifier.encode() + b"\0"
        self.flash_touched = False

    def read(self, addr):
        base = av.IDENTIFIER_BASE
        if base <= addr < base + 4 * 256:
            i = (addr - base) // 4
            return self.identifier[i] if i < len(self.identifier) else 0
        self.flash_touched = True
        return super().read(addr)

    def write(self, addr, value):
        self.flash_touched = True
        super().write(addr, value)


def _sysfs(tmp_path, *devices):
    """A /sys/bus/pci/devices with the given (bdf, vendor, device, subsystem_vendor, subsystem_device) entries."""
    root = tmp_path / "sys"
    root.mkdir(exist_ok=True)
    for bdf, ven, dev, sven, sdev in devices:
        d = root / bdf
        d.mkdir()
        for name, value in (("vendor", ven), ("device", dev), ("subsystem_vendor", sven), ("subsystem_device", sdev)):
            (d / name).write_text(f"{value}\n")
    return root


RP1 = ("0002:01:00.0", "0x1de4", "0x0001", "0x0000", "0x0000")
OURS = ("0001:01:00.0", "0x10ee", "0x7021", "0x1e24", "0x021f")


def _verify(tmp_path, images, bus, *devices):
    return av.verify(av.scan_pci(_sysfs(tmp_path, *devices)), images, open_bar=lambda bdf: _Ctx(bus))


class _Ctx:
    def __init__(self, bus):
        self.bus = bus

    def __enter__(self):
        return self.bus

    def __exit__(self, *exc):
        return False


# -- tier 1: the PCI IDs ------------------------------------------------------------------------------


def test_the_subsystem_table_is_the_one_the_soc_is_built_with():
    """acorn_verify.py cannot import the gateware (no LiteX on a Pi), so check its copy against the source."""
    tree = ast.parse((_HOST.parent / "gateware" / "acorn_pcie_soc.py").read_text())
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
    ("device", "kind", "variant"),
    [
        (OURS, "fpgas-online", "cle-215+"),
        (("0001:01:00.0", "0x10ee", "0x7021", "0x1e24", "0x0101"), "fpgas-online", "cle-101"),
        (("0001:01:00.0", "0x1e24", "0x021f", "0x0000", "0x0000"), "sqrl-factory", "cle-215+"),
        (("0001:01:00.0", "0x1e24", "0x0101", "0x0000", "0x0000"), "sqrl-factory", "cle-101"),
        (("0001:01:00.0", "0x10ee", "0x7011", "0x0000", "0x0000"), "vendor-xdma", None),
        (("0001:01:00.0", "0x10ee", "0x7021", "0x10ee", "0x0007"), "litex-other", None),
    ],
)
def test_classify_names_what_is_running_from_config_space_alone(tmp_path, device, kind, variant):
    (dev,) = av.scan_pci(_sysfs(tmp_path, RP1, device))
    assert (dev["kind"], dev["variant"]) == (kind, variant)


def test_a_pi_with_no_fpga_on_pcie_reports_none_and_passes(tmp_path, images):
    report = _verify(tmp_path, images, None, RP1)
    assert report["result"] == "none"
    assert av.exit_code(report) == 0


FACTORY = ("0001:01:00.0", "0x1e24", "0x021f", "0x0000", "0x0000")
VENDOR_XDMA = ("0001:01:00.0", "0x10ee", "0x7011", "0x0000", "0x0000")


@pytest.mark.parametrize("device", [FACTORY, VENDOR_XDMA])
def test_a_board_on_factory_or_vendor_firmware_is_unconverted_and_its_bar_is_never_opened(tmp_path, images, device):
    def refuse(bdf):
        raise AssertionError("BAR0 of a design we did not build must not be touched")

    report = av.verify(av.scan_pci(_sysfs(tmp_path, device)), images, open_bar=refuse)
    assert report["result"] == "unconverted"
    assert av.exit_code(report) == 1


# -- tiers 2 and 3 ------------------------------------------------------------------------------------


def test_the_expected_build_with_both_slots_intact_passes(tmp_path, images, chip):
    bus = SoCBus(chip, OP_IDENT_ON_CHIP)
    report = _verify(tmp_path, images, bus, RP1, OURS)
    (board,) = report["boards"]
    assert report["result"] == "pass", board
    assert board["running"] == {"identifier": OP_IDENT_ON_CHIP, "build": "operational"}
    assert [s["result"] for s in board["flash"]["slots"]] == ["match", "match"]
    assert board["flash"]["part"] == "S25FL256S"
    assert board["flash"]["jedec"] == "0x010219"  # as openFPGALoader prints it: "JEDEC ID: 0x010219"
    assert av.exit_code(report) == 0


def test_the_identifier_is_compared_without_regard_to_case(tmp_path, images, chip):
    """csr.json lower-cases the constant; the identifier memory holds it as the gateware wrote it."""
    report = _verify(tmp_path, images, SoCBus(chip, OP_IDENT_ON_CHIP.upper()), OURS)
    assert report["result"] == "pass"


def test_running_the_golden_image_is_degraded_and_the_flash_is_still_checked(tmp_path, images, chip):
    report = _verify(tmp_path, images, SoCBus(chip, GOLDEN_IDENT_ON_CHIP), OURS)
    (board,) = report["boards"]
    assert report["result"] == "degraded"
    assert board["running"]["build"] == "golden"
    assert [s["result"] for s in board["flash"]["slots"]] == ["match", "match"]
    assert av.exit_code(report) == 1


def test_a_changed_operational_slot_fails_and_says_where(tmp_path, images, chip):
    chip.mem[sf.OPERATIONAL_ADDR + 0x1234] ^= 0x01
    report = _verify(tmp_path, images, SoCBus(chip, OP_IDENT_ON_CHIP), OURS)
    golden, operational = report["boards"][0]["flash"]["slots"]
    assert report["result"] == "fail"
    assert golden["result"] == "match"
    assert operational == {**operational, "result": "mismatch", "first_difference": "0x401234"}


def test_a_build_not_in_the_manifest_fails_without_the_flash_being_touched(tmp_path, images, chip):
    bus = SoCBus(chip, "fpgas-online Acorn PCIe SoC cle-215+ 2026-10-01 09:00:00")
    report = _verify(tmp_path, images, bus, OURS)
    assert report["result"] == "fail"
    assert "not in" in report["boards"][0]["reason"]
    assert not bus.flash_touched


def test_a_csr_map_that_disagrees_with_spi_flash_is_an_error_and_the_flash_is_not_touched(tmp_path, images, chip):
    csr = json.loads((images / "acorn-cle-215p-csr.json").read_text())
    csr["csr_bases"]["flash_cs_n"] = 0xF0004800
    data = json.dumps(csr).encode()
    (images / "acorn-cle-215p-csr.json").write_bytes(data)
    manifest = json.loads((images / "manifest.json").read_text())
    for f in manifest["files"]:
        if f["asset"] == "acorn-cle-215p-csr.json":
            f["sha256"], f["size"] = hashlib.sha256(data).hexdigest(), len(data)
    (images / "manifest.json").write_text(json.dumps(manifest))

    bus = SoCBus(chip, OP_IDENT_ON_CHIP)
    report = _verify(tmp_path, images, bus, OURS)
    assert report["result"] == "error"
    assert "flash_cs_n" in report["boards"][0]["reason"]
    assert not bus.flash_touched


def test_an_installed_image_that_does_not_match_its_manifest_hash_is_an_error(tmp_path, images, chip):
    (images / "acorn-cle-215p-sqrl_acorn_operational.bin").write_bytes(b"\0" * 10)
    report = _verify(tmp_path, images, SoCBus(chip, OP_IDENT_ON_CHIP), OURS)
    assert report["result"] == "error"
    assert "sha256" in report["boards"][0]["reason"]


def test_the_check_never_sends_a_writing_opcode(tmp_path, images, chip):
    _verify(tmp_path, images, SoCBus(chip, OP_IDENT_ON_CHIP), OURS)
    assert not set(chip.opcodes) & sf.WRITE_OPCODES


# -- reporting ----------------------------------------------------------------------------------------


def test_the_fleet_event_carries_a_flat_summary(tmp_path, images, chip):
    report = _verify(tmp_path, images, SoCBus(chip, OP_IDENT_ON_CHIP), OURS)
    argv = av.fleet_event_argv(report)
    assert argv[:2] == ["fleet-event", "fpga-verified"]
    details = dict(a.split("=", 1) for a in argv[3::2])
    assert argv[2::2] == ["--detail"] * len(details)
    assert details == {
        "result": "pass",
        "release": "vivado-bitstreams-acorn-pcie-20260921-gf3355dccf443",
        "board0": "0001:01:00.0 fpgas-online cle-215+ pass",
        "board0_identifier": OP_IDENT_ON_CHIP,
        "board0_flash": "0x000000=match 0x400000=match",
    }


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


def test_the_command_line_checks_against_the_images_it_is_given(tmp_path, monkeypatch, capsys):
    """--images reaches verify(): found on pi-sw2-p48, where main() once ignored it for the default path."""
    monkeypatch.setattr(av, "LOCK", tmp_path / "lock")
    real_scan, sysfs = av.scan_pci, _sysfs(tmp_path, OURS)
    monkeypatch.setattr(av, "scan_pci", lambda root=None: real_scan(sysfs))
    elsewhere = tmp_path / "somewhere-else"
    assert av.main(["--images", str(elsewhere), "--no-publish", "--report", "-"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert str(elsewhere / "manifest.json") in report["boards"][0]["reason"]


def test_a_failed_publish_names_where_the_report_went_and_keeps_the_result(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(av, "LOCK", tmp_path / "lock")
    monkeypatch.setattr(av, "scan_pci", lambda root=None: [])
    monkeypatch.setattr(av, "fleet_event_argv", lambda report: ["/nonexistent/fleet-event"])
    out = tmp_path / "report.json"
    assert av.main(["--report", str(out)]) == 0
    assert json.loads(out.read_text())["result"] == "none"
    assert f"the report is in {out}" in capsys.readouterr().err
