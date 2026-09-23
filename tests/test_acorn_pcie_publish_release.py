"""Unit tests for designs/acorn-pcie/tools/publish_release.py.

The build tree is synthetic: each image is a minimal 7-series configuration
header (sync word, then the type-1 register writes spi_flash.image_info reads),
so the slot each file is for comes from the same parser the flash writer uses.
"""

import hashlib
import importlib.util
import json
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PATH = _ROOT / "designs" / "acorn-pcie" / "tools" / "publish_release.py"
_spec = importlib.util.spec_from_file_location("publish_release", _PATH)
pr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pr)

IDCODE_200T = 0x13636093
IDCODE_100T = 0x13631093
SYNC = bytes.fromhex("aa995566")


def _type1(reg, value):
    return ((1 << 29) | (2 << 27) | (reg << 13) | 1).to_bytes(4, "big") + value.to_bytes(4, "big")


def _image(idcode, flavour):
    """A .bin whose header says what an image of that flavour says."""
    body = b"\xff" * 16 + b"\x00\x00\x00\xbb\x11\x22\x00\x44" + SYNC
    body += _type1(0x0C, idcode)  # IDCODE
    if flavour == "operational":
        body += _type1(0x11, 0x40000000 | 0x1000)  # TIMER: watchdog enabled
    elif flavour == "fallback":
        body += _type1(0x10, 0x400000)  # WBSTAR
        body += _type1(0x04, 0xF)  # CMD IPROG
    body += ((1 << 29) | (2 << 27) | (0x02 << 13) | 0).to_bytes(4, "big")  # FDRI: frames start
    return body + bytes(64)


def _bit(bin_data, version="2025.2", date="2026/09/21", time="14:23:32", part="7a200tfbg484"):
    """A .bit: Xilinx's TLV header in front of the same configuration data."""

    def field(key, text):
        raw = text.encode() + b"\x00"
        return key + len(raw).to_bytes(2, "big") + raw

    head = bytes.fromhex("0009") + bytes.fromhex("0ff00ff00ff00ff000") + bytes.fromhex("0001")
    head += field(b"a", f"sqrl_acorn;UserID=0XFFFFFFFF;COMPRESS=TRUE;Version={version};SW_CRC=0")
    head += field(b"b", part) + field(b"c", date) + field(b"d", time)
    return head + b"e" + len(bin_data).to_bytes(4, "big") + bin_data


def _variant(root, name, idcode, ident, part="7a200tfbg484", with_bits=True):
    v = root / name
    gw = v / "gateware"
    gw.mkdir(parents=True)
    for suffix, flavour in (("", "plain"), ("_fallback", "fallback"), ("_operational", "operational")):
        data = _image(idcode, flavour)
        (gw / f"sqrl_acorn{suffix}.bin").write_bytes(data)
        if with_bits:
            (gw / f"sqrl_acorn{suffix}.bit").write_bytes(_bit(data, part=part))
    (gw / "sqrl_acorn_route.dcp").write_bytes(b"not published")
    (v / "csr.json").write_text(
        json.dumps(
            {
                "csr_bases": {"identifier_mem": 0xF0000800, "flash": 0xF0003800, "flash_cs_n": 0xF0004000},
                "constants": {"config_identifier": ident},
                "memories": {"csr": {"base": 0xF0000000, "size": 0x10000}},
            }
        )
    )
    (v / "csr.csv").write_text("csr_base,flash,0xf0003800,,\n")
    return v


@pytest.fixture
def build(tmp_path):
    root = tmp_path / "build"
    _variant(root, "acorn-cle-215+", IDCODE_200T, "fpgas-online acorn pcie soc cle-215+ 2026-09-21 14:23:32")
    _variant(
        root, "acorn-cle-215+-golden", IDCODE_200T, "fpgas-online acorn pcie soc cle-215+ golden 2026-09-21 14:31:19"
    )
    _variant(
        root,
        "acorn-cle-101",
        IDCODE_100T,
        "fpgas-online acorn pcie soc cle-101 2026-09-21 14:37:08",
        part="7a100tfgg484",
    )
    _variant(
        root,
        "acorn-cle-101-golden",
        IDCODE_100T,
        "fpgas-online acorn pcie soc cle-101 golden 2026-09-21 14:43:28",
        part="7a100tfgg484",
    )
    return root


def _collect(build, **kw):
    kw.setdefault("source_commit", "f3355dc" + "0" * 33)
    kw.setdefault("source_describe", "v0.0-514-gf3355dc")
    return pr.collect(build, **kw)


def _by_asset(manifest):
    return {f["asset"]: f for f in manifest["files"]}


def test_asset_names_are_unique_and_carry_the_variant(build):
    manifest, _ = _collect(build)
    names = [f["asset"] for f in manifest["files"]]
    assert len(names) == len(set(names))
    assert "acorn-cle-215p-golden-sqrl_acorn_fallback.bin" in names
    assert "acorn-cle-215p-sqrl_acorn_operational.bin" in names
    assert "acorn-cle-101-csr.json" in names
    assert "acorn-cle-101-golden-csr.csv" in names
    # Only images and CSR maps: nothing else out of the build tree.
    assert not any(n.endswith(".dcp") for n in names)
    # 4 variants x (3 .bin + 3 .bit + csr.json + csr.csv)
    assert len(names) == 4 * 8


def test_slot_comes_from_the_image_header(build):
    files = _by_asset(_collect(build)[0])
    assert files["acorn-cle-215p-golden-sqrl_acorn_fallback.bin"]["slot"] == "0x000000"
    assert files["acorn-cle-215p-sqrl_acorn_operational.bin"]["slot"] == "0x400000"
    assert files["acorn-cle-215p-sqrl_acorn.bin"]["slot"] is None
    assert files["acorn-cle-215p-sqrl_acorn_operational.bit"]["slot"] is None  # .bit is for JTAG only
    assert files["acorn-cle-215p-csr.json"]["slot"] is None


def test_every_file_has_the_provenance_fields(build):
    manifest, staged = _collect(build)
    for f in manifest["files"]:
        data = (staged[f["asset"]]).read_bytes()
        assert f["size"] == len(data)
        assert f["sha256"] == hashlib.sha256(data).hexdigest()
        assert f["source_commit"].startswith("f3355dc")
        assert f["toolchain"] == {"name": "vivado", "version": "2025.2"}
        assert f["config_identifier"].startswith("fpgas-online acorn pcie soc ")
        assert f["golden"] == ("golden" in f["variant"])


def test_image_idcode_is_recorded(build):
    files = _by_asset(_collect(build)[0])
    assert files["acorn-cle-215p-sqrl_acorn_operational.bin"]["idcode"] == "0x13636093"
    assert files["acorn-cle-101-sqrl_acorn_operational.bin"]["idcode"] == "0x13631093"


def test_flash_layout_names_the_pair_for_each_board(build):
    layout = _collect(build)[0]["flash_layout"]
    assert layout["cle-215+"] == {
        "0x000000": "acorn-cle-215p-golden-sqrl_acorn_fallback.bin",
        "0x400000": "acorn-cle-215p-sqrl_acorn_operational.bin",
    }
    assert layout["cle-101"]["0x000000"] == "acorn-cle-101-golden-sqrl_acorn_fallback.bin"


def test_golden_directory_must_carry_a_golden_identifier(build):
    csr = build / "acorn-cle-215+-golden" / "csr.json"
    data = json.loads(csr.read_text())
    data["constants"]["config_identifier"] = "fpgas-online acorn pcie soc cle-215+ 2026-09-21 14:31:19"
    csr.write_text(json.dumps(data))
    with pytest.raises(pr.ReleaseError, match="golden"):
        _collect(build)


def test_operational_image_without_watchdog_is_refused(build):
    (build / "acorn-cle-215+" / "gateware" / "sqrl_acorn_operational.bin").write_bytes(_image(IDCODE_200T, "plain"))
    with pytest.raises(pr.ReleaseError, match="operational"):
        _collect(build)


def test_image_for_the_wrong_part_is_refused(build):
    (build / "acorn-cle-101" / "gateware" / "sqrl_acorn_operational.bin").write_bytes(
        _image(IDCODE_200T, "operational")
    )
    with pytest.raises(pr.ReleaseError, match="IDCODE"):
        _collect(build)


def test_missing_file_is_refused(build):
    (build / "acorn-cle-101" / "csr.csv").unlink()
    with pytest.raises(pr.ReleaseError, match=r"csr\.csv"):
        _collect(build)


def test_variants_can_be_selected(build):
    manifest, _ = _collect(build, variants=["cle-215+", "cle-215+-golden"])
    assert {f["variant"] for f in manifest["files"]} == {"cle-215+", "cle-215+-golden"}
    assert set(manifest["flash_layout"]) == {"cle-215+"}


def test_sha256sums_matches_the_staged_files(build, tmp_path):
    manifest, staged = _collect(build)
    out = tmp_path / "stage"
    pr.stage(manifest, staged, out)
    lines = (out / "SHA256SUMS").read_text().splitlines()
    assert len(lines) == len(manifest["files"]) + 1  # plus manifest.json itself
    for line in lines:
        digest, name = line.split("  ", 1)
        assert hashlib.sha256((out / name).read_bytes()).hexdigest() == digest
    assert json.loads((out / "manifest.json").read_text())["files"] == manifest["files"]


def test_tag_uses_the_allowed_prefix():
    # Ruleset 13744509 only lets refs/tags/vivado-bitstreams-* through besides vX.Y.
    assert pr.release_tag("v0.0-514-gf3355dc") == "vivado-bitstreams-v0.0-514-gf3355dc"
