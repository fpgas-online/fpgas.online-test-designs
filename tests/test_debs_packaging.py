"""Tests for the deb builder (packaging/debs/build_debs.py): what each package holds and pulls in.

* Installing one board's package brings that board's tooling and nothing else's.
* The mode packages (fpgas-online-<board>, -multi-board) conflict, so two boards are never set up by
  accident, and they, not the core, turn the boot check on.
* Every board's packages pin each other's version; a missing test bitstream fails the build.
"""

import importlib.util
import json
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("debs_build_debs", _REPO / "packaging" / "debs" / "build_debs.py")
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)

V = "0.0.post600"
ACORN_BITS = "20260923+ge48a750c8303"
B = bd.BOARDS


def _dst(config):
    return {c["dst"]: c for c in config["contents"]}


def test_the_core_has_every_module_but_the_boards_and_every_host_script(tmp_path):
    config = bd.verify_nfpm(V, tmp_path)
    dst = _dst(config)
    assert f"{bd.DIST}/runner.py" in dst and f"{bd.DIST}/cli.py" in dst
    assert not any("/boards/" in d for d in dst)
    assert {f"{bd.DIST}/scripts/{n}" for n in bd.host_tests.SCRIPTS} <= set(dst)
    assert config["depends"] == ["python3 (>= 3.9)"]
    assert "/usr/lib/systemd/system/fpgas-verify.service" in dst
    assert "scripts" not in config  # installing the core alone does not turn the boot check on
    wrapper = pathlib.Path(dst["/usr/bin/fpgas-verify"]["src"]).read_text()
    assert "sys.dont_write_bytecode = True" in wrapper and "verify_main()" in wrapper
    for c in config["contents"]:
        if "src" in c:
            assert pathlib.Path(c["src"]).is_file(), c["src"]


def test_each_board_tools_package_has_its_module_and_only_its_own_tooling(tmp_path):
    arty = bd.tools_nfpm(B["arty"], V, V, tmp_path)
    assert arty["name"] == "fpgas-online-arty-tools"
    assert arty["depends"] == [f"fpgas-online-verify (= {V})", f"fpgas-online-arty-bitstreams (= {V})",
                               "python3-serial", bd.OPENFPGALOADER]  # fmt: skip
    assert set(_dst(arty)) == {f"{bd.DIST}/boards/arty.py", "/usr/bin/fpgas-arty-verify"}
    acorn = bd.tools_nfpm(B["acorn"], V, ACORN_BITS, tmp_path)
    # GPIO and PCIe only: no USB tooling, no serial, not even openFPGALoader (that is the debug package's)
    assert acorn["depends"] == [f"fpgas-online-verify (= {V})", f"fpgas-online-acorn-bitstreams (= {ACORN_BITS})"]
    assert {f"{bd.DIST}/boards/acorn/{m}.py" for m in ("__init__", "check", "spi_flash", "uartbone_link")} <= set(
        _dst(acorn)
    )
    assert "/usr/bin/fpgas-acorn-flash" in _dst(acorn)
    netv2 = bd.tools_nfpm(B["netv2"], V, V, tmp_path)
    assert "openocd" in netv2["depends"]
    tt = bd.tools_nfpm(B["tt"], V, V, tmp_path)
    assert tt["name"] == "fpgas-online-tt-fpga-tools" and tt["recommends"] == ["micropython-mpremote"]
    assert bd.OPENFPGALOADER not in tt["depends"]
    for config in (arty, acorn, netv2, tt):
        assert "fpgas-online-setup-pi" not in config["depends"] + config.get("recommends", [])


def test_debug_packages_carry_what_the_extra_tests_need(tmp_path):
    arty = bd.debug_nfpm(B["arty"], V, tmp_path)
    assert arty["depends"] == [f"fpgas-online-arty-tools (= {V})", "python3-libgpiod"]
    assert "iputils-arping | arping" in arty["recommends"]
    assert "iproute2" not in bd.debug_nfpm(B["fomu"], V, tmp_path)["recommends"]  # no Ethernet test
    acorn = bd.debug_nfpm(B["acorn"], V, tmp_path)
    assert bd.OPENFPGALOADER in acorn["depends"]  # converting from SQRL's factory image
    assert set(_dst(acorn)) == {"/usr/bin/fpgas-acorn-debug"}


def test_a_board_mode_package_sets_the_board_turns_the_check_on_and_conflicts_with_the_others(tmp_path):
    config = bd.board_mode_nfpm(B["tt"], V, tmp_path)
    assert config["name"] == "fpgas-online-tt-fpga"
    assert config["depends"] == [f"fpgas-online-tt-fpga-tools (= {V})"]
    assert config["provides"] == config["conflicts"] == [bd.MODE]
    ini = pathlib.Path(_dst(config)[f"{bd.MODE_DIR}/fpgas-online-tt-fpga.ini"]["src"]).read_text()
    assert "[verify]\nfpga-board = tt\n" in ini
    postinst = pathlib.Path(config["scripts"]["postinstall"]).read_text()
    code = "\n".join(line for line in postinst.splitlines() if not line.lstrip().startswith("#"))
    assert 'deb-systemd-helper enable "$UNIT"' in code
    assert "systemctl start" not in code and "systemctl restart" not in code  # it would reprogram the FPGA


def test_multi_board_is_auto_and_all_boards_is_every_board(tmp_path):
    multi = bd.multi_board_nfpm(V, tmp_path)
    assert multi["provides"] == multi["conflicts"] == [bd.MODE]
    assert (
        "fpga-board = auto"
        in pathlib.Path(_dst(multi)[f"{bd.MODE_DIR}/fpgas-online-multi-board.ini"]["src"]).read_text()
    )
    everything = bd.all_boards_nfpm(V)
    assert everything["depends"] == [f"fpgas-online-multi-board (= {V})"] + [
        f"fpgas-online-{s}-tools (= {V})" for s in ("acorn", "arty", "fomu", "netv2", "tt-fpga")
    ]
    assert "fpgas-online-netv2-debug" in everything["recommends"]


def test_test_bitstreams_are_staged_with_a_manifest(tmp_path):
    bundle = tmp_path / "bundle"
    board = B["netv2"]
    for test in board.tests:
        for variant in board.variants:
            p = bundle / board.artifact(test, variant)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(p.name.encode() + variant.encode())
    images = bd.stage_test_bitstreams(board, bundle, tmp_path / "root", V, "abc")
    manifest = json.loads((images / "manifest.json").read_text())
    assert manifest["version"] == V and len(manifest["files"]) == len(board.tests) * 2
    assert images.relative_to(tmp_path / "root").as_posix() == "usr/share/fpgas-online/netv2/bitstreams"
    assert {p.stat().st_mode & 0o777 for p in images.rglob("*") if p.is_file()} == {0o644}
    (bundle / "ddr-test-netv2-a7-35t" / "kosagi_netv2.bit").unlink()
    with pytest.raises(bd.BuildError, match="ddr-test-netv2-a7-35t"):
        bd.stage_test_bitstreams(board, bundle, tmp_path / "again", V, "abc")


def test_every_package_keeps_its_version_as_given(tmp_path):
    configs = [bd.verify_nfpm(V, tmp_path), bd.multi_board_nfpm(V, tmp_path), bd.all_boards_nfpm(V)]
    for board in B.values():
        configs += [bd.tools_nfpm(board, V, V, tmp_path), bd.debug_nfpm(board, V, tmp_path),
                    bd.board_mode_nfpm(board, V, tmp_path)]  # fmt: skip
    assert {c["version_schema"] for c in configs} == {"none"} and {c["arch"] for c in configs} == {"all"}
