"""Tests for fpgas-verify (designs/_host/fpgas_verify.py): which board's verify runs at boot.

The netboot root has every board's tools installed, so what matters is that each Pi runs exactly its own
board's check, and that the JTAG scan, which drives GPIO header pins, never runs where another board was found.
"""

import importlib.util
import json
import pathlib
import subprocess

_PATH = pathlib.Path(__file__).resolve().parents[1] / "designs" / "_host" / "fpgas_verify.py"
_spec = importlib.util.spec_from_file_location("fpgas_verify", _PATH)
fv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fv)

ACORN_REG = pathlib.Path(__file__).resolve().parents[1] / "packaging" / "acorn-pcie" / "acorn.verify.json"


def _registry(tmp_path):
    reg = tmp_path / "verify.d"
    reg.mkdir()
    entries = {
        "arty": {"detect": {"usb": [["0403", "6010"]]}},
        "fomu": {"detect": {"usb": [["1209", "5bf0"]]}},
        "tt-fpga": {"board": "tt", "detect": {"usb": [["2e8a", None]]}},
        "netv2": {"detect": {"jtag": True}},
    }
    for name, e in entries.items():
        e.setdefault("board", name)
        e.update(command=[f"/usr/bin/fpgas-{name}-verify"], report=str(tmp_path / f"{name}-verify.json"))
        (reg / f"{name}.json").write_text(json.dumps(e))
    acorn = {**json.loads(ACORN_REG.read_text()), "report": str(tmp_path / "acorn-verify.json")}
    (reg / "acorn.json").write_text(json.dumps(acorn))
    (reg / "broken.json").write_text("{not json")
    return reg


class Boards:
    """Stands in for subprocess.run: each board's verify writes its report with the result given."""

    def __init__(self, tmp_path, results):
        self.tmp_path, self.results, self.ran = tmp_path, results, []

    def __call__(self, argv, check, timeout):
        name = pathlib.Path(argv[0]).name.removeprefix("fpgas-").removesuffix("-verify")
        self.ran.append(argv)
        result = self.results.get(name, "none")
        pathlib.Path(argv[argv.index("--report") + 1]).write_text(json.dumps({"result": result}))
        return subprocess.CompletedProcess(argv, 0 if result in ("pass", "none") else 1)


def test_the_registry_skips_a_broken_entry(tmp_path, capsys):
    reg = fv.load_registry(_registry(tmp_path))
    assert [e["board"] for e in reg] == ["acorn", "arty", "fomu", "netv2", "tt"]
    assert "broken.json" in capsys.readouterr().err


def test_an_arty_host_runs_only_the_arty_check_and_never_scans_jtag(tmp_path):
    reg = fv.load_registry(_registry(tmp_path))
    boards = Boards(tmp_path, {"arty": "pass"})
    report = fv.verify(reg, usb={(0x0403, 0x6010), (0x1D6B, 0x0002)}, pci=set(), run=boards)
    assert [b["board"] for b in report["boards"]] == ["arty"]
    assert report["result"] == "pass" and report["chosen_by"] == "USB/PCI IDs"
    assert all("netv2" not in a[0] for a in boards.ran)


def test_an_acorn_is_spotted_on_pci(tmp_path):
    reg = fv.load_registry(_registry(tmp_path))
    boards = Boards(tmp_path, {"acorn": "degraded"})
    report = fv.verify(reg, usb=set(), pci={0x1E24, 0x14E4}, run=boards)
    assert [b["board"] for b in report["boards"]] == ["acorn"]
    assert report["result"] == "degraded" and fv.exit_code(report) == 1


def test_the_tt_board_matches_any_rp2350_product(tmp_path):
    reg = fv.load_registry(_registry(tmp_path))
    report = fv.verify(reg, usb={(0x2E8A, 0x0009)}, pci=set(), run=Boards(tmp_path, {"tt-fpga": "pass"}))
    assert [b["board"] for b in report["boards"]] == ["tt"]


def test_with_nothing_on_usb_or_pci_the_jtag_boards_are_tried(tmp_path):
    reg = fv.load_registry(_registry(tmp_path))
    boards = Boards(tmp_path, {"netv2": "fail"})
    report = fv.verify(reg, usb=set(), pci=set(), run=boards)
    assert [b["board"] for b in report["boards"]] == ["netv2"] and report["chosen_by"] == "JTAG scan"
    assert report["result"] == "fail"


def test_the_jtag_scan_can_be_ruled_out(tmp_path):
    reg = fv.load_registry(_registry(tmp_path))
    boards = Boards(tmp_path, {})
    report = fv.verify(reg, usb=set(), pci=set(), jtag_scan=False, run=boards)
    assert report["boards"] == [] and report["result"] == "none" and boards.ran == []


def test_a_board_can_be_named_instead_of_detected(tmp_path):
    reg = fv.load_registry(_registry(tmp_path))
    boards = Boards(tmp_path, {"fomu": "pass"})
    report = fv.verify(reg, usb={(0x0403, 0x6010)}, pci=set(), only=["fomu"], no_publish=True, run=boards)
    assert [b["board"] for b in report["boards"]] == ["fomu"]
    assert boards.ran[0][-1] == "--no-publish"


def test_a_verify_that_cannot_run_is_an_error(tmp_path):
    reg = fv.load_registry(_registry(tmp_path))

    def missing(argv, check, timeout):
        raise FileNotFoundError(argv[0])

    report = fv.verify(reg, usb={(0x0403, 0x6010)}, pci=set(), run=missing)
    assert report["result"] == "error" and fv.exit_code(report) == 1


def test_main_on_a_host_with_no_board_reports_none(tmp_path, monkeypatch):
    monkeypatch.setattr(fv, "usb_ids", lambda root=None: set())
    monkeypatch.setattr(fv, "pci_vendors", lambda root=None: set())
    monkeypatch.setattr(fv.subprocess, "run", Boards(tmp_path, {}))
    out = tmp_path / "verify.json"
    rc = fv.main(["--registry", str(_registry(tmp_path)), "--report", str(out), "--no-publish"])
    report = json.loads(out.read_text())
    assert rc == 0 and report["result"] == "none"
    assert [b["board"] for b in report["boards"]] == ["netv2"]  # the JTAG scan found nothing either


def test_sysfs_ids_are_read_as_numbers(tmp_path):
    usb, pci = tmp_path / "usb", tmp_path / "pci"
    (usb / "1-1").mkdir(parents=True)
    (usb / "1-1" / "idVendor").write_text("0403\n")
    (usb / "1-1" / "idProduct").write_text("6010\n")
    (pci / "0001:01:00.0").mkdir(parents=True)
    (pci / "0001:01:00.0" / "vendor").write_text("0x10ee\n")
    assert fv.usb_ids(usb) == {(0x0403, 0x6010)}
    assert fv.pci_vendors(pci) == {0x10EE}
    assert fv.usb_ids(tmp_path / "absent") == set()
