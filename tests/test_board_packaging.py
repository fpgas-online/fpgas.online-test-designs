"""Tests for the board deb builder (packaging/boards/build_debs.py).

Per board: -bitstreams (this commit's CI bitstreams, with a manifest), -tools (the verify, registered with
fpgas-verify) and -debug (the rest of the tests); plus fpgas-online-verify (the boot-time dispatcher) and
fpgas-online-verify-all (every board). What must hold: every bitstream a board's tests name is in its package
and matches the manifest, a missing one fails the build, each board's packages pin each other's version, and
nothing pulls in fpgas-online-setup-pi.
"""

import hashlib
import importlib.util
import json
import pathlib

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("board_build_debs", _REPO / "packaging" / "boards" / "build_debs.py")
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)
bv = bd.bv

V = "0.0.post600"


@pytest.fixture
def bundle(tmp_path):
    """An all-bitstreams bundle with every board's bitstreams, plus unrelated artifacts."""
    d = tmp_path / "bundle"
    for board in bv.BOARDS:
        for _, _, path in bd.selected(board):
            (d / path).parent.mkdir(parents=True, exist_ok=True)
            (d / path).write_bytes(path.encode())
    (d / "acorn-debs").mkdir()
    (d / "acorn-debs" / "x.deb").write_bytes(b"deb")
    return d


def test_the_bitstreams_package_carries_every_test_and_variant_with_a_manifest(bundle, tmp_path):
    images = bd.stage_bitstreams("netv2", bundle, tmp_path / "root", V, "abc123")
    manifest = json.loads((images / "manifest.json").read_text())
    assert manifest["board"] == "netv2" and manifest["version"] == V and manifest["commit"] == "abc123"
    paths = {f["path"] for f in manifest["files"]}
    assert len(paths) == len(bv.BOARDS["netv2"]["tests"]) * 2  # a7-35 and a7-100
    for f in manifest["files"]:
        data = (images / f["path"]).read_bytes()
        assert f["sha256"] == hashlib.sha256(data).hexdigest() and f["size"] == len(data)
    assert {p.stat().st_mode & 0o777 for p in images.rglob("*") if p.is_file()} == {0o644}
    assert images.stat().st_mode & 0o777 == 0o755
    assert images.relative_to(tmp_path / "root").as_posix() == "usr/share/fpgas-online/netv2/bitstreams"


def test_a_missing_bitstream_fails_the_build(bundle, tmp_path):
    (bundle / "ddr-test-arty" / "digilent_arty.bit").unlink()
    with pytest.raises(bd.BuildError, match="ddr-test-arty"):
        bd.stage_bitstreams("arty", bundle, tmp_path / "root", V, "abc")


def test_each_script_is_in_exactly_one_package_and_the_verify_has_what_it_runs():
    for board in bv.BOARDS:
        tools, debug = bd.scripts_for(board)
        assert not set(tools) & set(debug)
        for name, t in bv.BOARDS[board]["tests"].items():
            assert t["script"] in (tools if t.get("verify") else tools + debug), (board, name)
    assert "tt_fpga_program.py" in bd.scripts_for("tt")[0]  # the PMOD tests load through it too


def test_the_tools_package_pins_its_bitstreams_and_registers_with_fpgas_verify(tmp_path):
    config = bd.tools_nfpm("arty", V, tmp_path)
    assert config["name"] == "fpgas-online-arty-tools" and config["version_schema"] == "none"
    assert f"fpgas-online-arty-bitstreams (= {V})" in config["depends"]
    assert "python3-serial" in config["depends"]
    assert bd.OPENFPGALOADER in config["depends"]
    assert config["recommends"] == ["fpgas-online-verify"]
    assert "fpgas-online-setup-pi" not in config["depends"] + config["recommends"]
    dst = {c["dst"]: c for c in config["contents"]}
    assert dst["/usr/bin/fpgas-arty-verify"] == {"src": "/usr/lib/fpgas-online/arty/board_verify.py",
                                                  "dst": "/usr/bin/fpgas-arty-verify", "type": "symlink"}  # fmt: skip
    assert dst["/usr/lib/fpgas-online/arty/board_verify.py"]["file_info"]["mode"] == 0o755
    reg = json.loads(pathlib.Path(dst["/usr/share/fpgas-online/verify.d/arty.json"]["src"]).read_text())
    assert reg["command"] == ["/usr/bin/fpgas-arty-verify"] and reg["detect"] == {"usb": [["0403", "6010"]]}
    for c in config["contents"]:
        if c.get("type") != "symlink":
            assert pathlib.Path(c["src"]).is_file(), c["src"]


def test_the_netv2_registers_as_a_jtag_board_and_needs_openocd(tmp_path):
    config = bd.tools_nfpm("netv2", V, tmp_path)
    assert "openocd" in config["depends"]
    reg = json.loads((tmp_path / "netv2.json").read_text())
    assert reg["detect"] == {"jtag": True}


def test_the_tt_tools_are_named_tt_fpga_and_recommend_mpremote(tmp_path):
    config = bd.tools_nfpm("tt", V, tmp_path)
    assert config["name"] == "fpgas-online-tt-fpga-tools"  # fpgas-online-tt is the TT site's own package
    assert "micropython-mpremote" in config["recommends"]  # only bookworm-backports has it: not a Depends
    assert "/usr/bin/fpgas-tt-fpga-verify" in {c["dst"] for c in config["contents"]}


def test_the_debug_package_needs_the_same_tools_version():
    config = bd.debug_nfpm("arty", V)
    assert config["depends"] == [f"fpgas-online-arty-tools (= {V})", "python3-libgpiod"]
    assert "iputils-arping | arping" in config["recommends"]  # the Ethernet test
    dst = {c["dst"] for c in config["contents"]}
    assert {"/usr/bin/fpgas-arty-debug", "/usr/lib/fpgas-online/arty/board_debug.py",
            "/usr/lib/fpgas-online/arty/test_ethernet.py"} <= dst  # fmt: skip
    assert "/usr/lib/fpgas-online/arty/test_uart.py" not in dst  # the tools package has it
    assert "iproute2" not in bd.debug_nfpm("fomu", V)["recommends"]  # no Ethernet test


def test_the_dispatcher_enables_its_unit_on_install():
    config = bd.verify_nfpm(V)
    dst = {c["dst"]: c for c in config["contents"]}
    assert dst["/usr/bin/fpgas-verify"]["type"] == "symlink"
    assert "/usr/lib/systemd/system/fpgas-verify.service" in dst
    assert dst["/usr/share/fpgas-online/verify.d"] == {"dst": "/usr/share/fpgas-online/verify.d", "type": "dir",
                                                        "file_info": {"mode": 0o755}}  # fmt: skip
    postinst = pathlib.Path(config["scripts"]["postinstall"]).read_text()
    code = "\n".join(line for line in postinst.splitlines() if not line.lstrip().startswith("#"))
    assert 'deb-systemd-helper enable "$UNIT"' in code
    assert "systemctl start" not in code and "systemctl restart" not in code  # would reprogram the FPGA
    assert "init-system-helpers" in config["depends"]


def test_verify_all_depends_on_every_board():
    config = bd.verify_all_nfpm(V)
    assert config["depends"] == [
        f"fpgas-online-verify (= {V})",
        "fpgas-online-acorn-tools",
        f"fpgas-online-arty-tools (= {V})",
        f"fpgas-online-fomu-tools (= {V})",
        f"fpgas-online-netv2-tools (= {V})",
        f"fpgas-online-tt-fpga-tools (= {V})",
    ]
    assert "fpgas-online-netv2-debug" in config["recommends"]


def test_the_unit_runs_fpgas_verify_with_the_admins_options():
    unit = (bd.HERE / "fpgas-verify.service").read_text()
    assert "ExecStart=/usr/bin/fpgas-verify $FPGAS_VERIFY_ARGS" in unit
    assert "EnvironmentFile=-/etc/default/fpgas-verify" in unit
    assert "WantedBy=multi-user.target" in unit
