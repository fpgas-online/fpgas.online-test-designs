"""Tests for the Acorn deb builder (packaging/acorn-pcie/build_debs.py).

Two packages come out of it:

  * fpgas-online-acorn-bitstreams: the images a Pi uses, from the release pinned in release.toml. Versioned by
    that release, so it only changes (and only adds to the apt pool) when a reviewed PR moves the pin.
  * fpgas-online-acorn-tools: acorn_verify.py, spi_flash.py and the boot unit, versioned by git describe, and
    depending on exactly the pinned bitstreams version.

What must hold: every file that reaches a package matches the manifest, the manifest matches the pin, and
nothing else from the release is shipped.
"""

import hashlib
import importlib.util
import json
import pathlib

import pytest

_PATH = pathlib.Path(__file__).resolve().parents[1] / "packaging" / "acorn-pcie" / "build_debs.py"
_spec = importlib.util.spec_from_file_location("build_debs", _PATH)
bd = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bd)

TAG = "vivado-bitstreams-acorn-pcie-20260921-gf3355dccf443"


def _entry(asset, variant, golden, file, slot=None, data=None):
    data = data if data is not None else asset.encode()
    return (
        asset,
        data,
        {
            "asset": asset,
            "variant": variant,
            "golden": golden,
            "file": file,
            "slot": slot,
            "size": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "config_identifier": f"ident {variant}",
        },
    )


@pytest.fixture
def staged(tmp_path):
    """A staged release, as publish_release.py writes it, for two variants."""
    d = tmp_path / "release"
    d.mkdir()
    entries = []
    for base, p in (("cle-215+", "acorn-cle-215p"), ("cle-101", "acorn-cle-101")):
        for golden in (False, True):
            v = f"{base}-golden" if golden else base
            pre = f"{p}-golden" if golden else p
            for f, slot in (("sqrl_acorn.bin", None), ("sqrl_acorn_fallback.bin", "0x000000"),
                            ("sqrl_acorn_operational.bin", "0x400000")):  # fmt: skip
                entries.append(_entry(f"{pre}-{f}", v, golden, f, slot))
                entries.append(_entry(f"{pre}-{f[:-4]}.bit", v, golden, f[:-4] + ".bit"))
            entries.append(_entry(f"{pre}-csr.json", v, golden, "csr.json"))
            entries.append(_entry(f"{pre}-csr.csv", v, golden, "csr.csv"))
    for asset, data, _ in entries:
        (d / asset).write_bytes(data)
    manifest = {
        "schema_version": 1,
        "tag": TAG,
        "source_commit": "f3355dccf443" + "0" * 28,
        "source_commit_date": "20260921",
        "flash_layout": {
            "cle-101": {
                "0x000000": "acorn-cle-101-golden-sqrl_acorn_fallback.bin",
                "0x400000": "acorn-cle-101-sqrl_acorn_operational.bin",
            },
            "cle-215+": {
                "0x000000": "acorn-cle-215p-golden-sqrl_acorn_fallback.bin",
                "0x400000": "acorn-cle-215p-sqrl_acorn_operational.bin",
            },
        },
        "files": [e for _, _, e in entries],
    }
    text = json.dumps(manifest, indent=2) + "\n"
    (d / "manifest.json").write_text(text)
    return d, hashlib.sha256(text.encode()).hexdigest()


def test_the_bitstreams_version_comes_from_the_release_and_sorts_by_date():
    assert bd.bitstreams_version(TAG) == "20260921+gf3355dccf443"
    older = bd.bitstreams_version("vivado-bitstreams-acorn-pcie-20251231-gffffffffffff")
    assert older < bd.bitstreams_version(TAG)  # same-length date prefix: string order is date order


@pytest.mark.parametrize("bad", ["vivado-bitstreams-v0.0-496-gf162f60", "acorn-pcie-20260921-gf3355dccf443", ""])
def test_a_tag_that_is_not_an_acorn_pcie_release_is_refused(bad):
    with pytest.raises(bd.BuildError):
        bd.bitstreams_version(bad)


def test_only_what_a_pi_uses_is_shipped(staged):
    d, pin = staged
    manifest = bd.load_manifest(d / "manifest.json", pin)
    chosen = bd.select_assets(manifest)
    assert chosen == sorted(
        [
            # the two images each board's flash should hold
            "acorn-cle-101-golden-sqrl_acorn_fallback.bin",
            "acorn-cle-101-sqrl_acorn_operational.bin",
            "acorn-cle-215p-golden-sqrl_acorn_fallback.bin",
            "acorn-cle-215p-sqrl_acorn_operational.bin",
            # the register maps of the builds that can be running
            "acorn-cle-101-csr.json",
            "acorn-cle-101-csr.csv",
            "acorn-cle-101-golden-csr.json",
            "acorn-cle-101-golden-csr.csv",
            "acorn-cle-215p-csr.json",
            "acorn-cle-215p-csr.csv",
            "acorn-cle-215p-golden-csr.json",
            "acorn-cle-215p-golden-csr.csv",
            # what loads the operational design into SRAM over JTAG, to convert a board on factory firmware
            "acorn-cle-101-sqrl_acorn.bit",
            "acorn-cle-215p-sqrl_acorn.bit",
        ]
    )


def test_a_manifest_that_is_not_the_pinned_one_is_refused(staged):
    d, _pin = staged
    with pytest.raises(bd.BuildError, match=r"release\.toml"):
        bd.load_manifest(d / "manifest.json", "0" * 64)


def test_an_asset_that_does_not_match_the_manifest_is_refused(staged, tmp_path):
    d, pin = staged
    (d / "acorn-cle-215p-sqrl_acorn_operational.bin").write_bytes(b"tampered")
    manifest = bd.load_manifest(d / "manifest.json", pin)
    with pytest.raises(bd.BuildError, match="sha256"):
        bd.stage_bitstreams(manifest, bd.local_fetcher(d), tmp_path / "root")


def test_the_staged_tree_is_the_installed_layout(staged, tmp_path):
    d, pin = staged
    manifest = bd.load_manifest(d / "manifest.json", pin)
    root = tmp_path / "root"
    bd.stage_bitstreams(manifest, bd.local_fetcher(d), root)
    images = root / "usr/share/fpgas-online/acorn-pcie/images"
    assert json.loads((images / "manifest.json").read_text()) == manifest
    assert sorted(p.name for p in images.iterdir()) == sorted([*bd.select_assets(manifest), "manifest.json"])


def test_the_tools_package_depends_on_exactly_the_pinned_bitstreams():
    config = bd.tools_nfpm(version="0.0.post600", bitstreams="20260921+gf3355dccf443", repo=_PATH.parents[2])
    assert "fpgas-online-acorn-bitstreams (= 20260921+gf3355dccf443)" in config["depends"]
    dst = {c["dst"]: c for c in config["contents"]}
    assert dst["/usr/bin/fpgas-acorn-verify"]["type"] == "symlink"
    assert dst["/usr/lib/fpgas-online/acorn-pcie/acorn_verify.py"]["file_info"]["mode"] == 0o755
    assert "/usr/lib/systemd/system/fpgas-acorn-verify.service" in dst
    for c in config["contents"]:
        if c.get("type") != "symlink":
            assert pathlib.Path(c["src"]).is_file(), c["src"]


def test_the_tools_package_pulls_in_openfpgaloader_but_not_the_fleet_setup():
    config = bd.tools_nfpm(version="0.0.post600", bitstreams="20260921+gf3355dccf443", repo=_PATH.parents[2])
    # The fpgas.online builds first, so apt picks one when the fpga-tools repo is configured; both Provide
    # openfpgaloader, and Debian's own openfpgaloader resolves it on a host with only Debian + apt.fpgas.online.
    assert "openfpgaloader-fpgasonline | openfpgaloader-fpgasonline-git | openfpgaloader" in config["depends"]
    # apt installs Recommends by default: fpgas-online-setup-pi reconfigures the host as a fleet node, so only
    # fpgas-online-verify (the boot-time check) is recommended.
    assert config["recommends"] == ["fpgas-online-verify"]
    assert config["suggests"] == ["fpgas-online-setup-pi"]


def test_the_tools_package_registers_the_acorn_with_fpgas_verify():
    """fpgas-verify spots the Acorn by its PCI vendor (Xilinx for our SoC, SQRL for the factory image)."""
    config = bd.tools_nfpm(version="0.0.post600", bitstreams="20260921+gf3355dccf443", repo=_PATH.parents[2])
    dst = {c["dst"]: c for c in config["contents"]}
    entry = json.loads(pathlib.Path(dst["/usr/share/fpgas-online/verify.d/acorn.json"]["src"]).read_text())
    assert entry["command"] == ["/usr/bin/fpgas-acorn-verify"]
    assert entry["report"] == "/run/fpgas-online/acorn-verify.json"
    assert entry["detect"] == {"pci_vendor": ["10ee", "1e24"]}


def test_the_pin_file_names_a_release_this_builder_accepts():
    pin = bd.read_pin(_PATH.parent / "release.toml")
    bd.bitstreams_version(pin["tag"])
    assert len(pin["manifest_sha256"]) == 64


def test_nfpm_is_told_to_keep_the_version_exactly_as_given():
    """Left to itself nfpm turns 20260921+gf3355dccf443 into 20260921.0.0+gf3355dccf443 (seen building it)."""
    tools = bd.tools_nfpm(version="0.0.post600", bitstreams="20260921+gf3355dccf443", repo=_PATH.parents[2])
    bits = bd.bitstreams_nfpm("20260921+gf3355dccf443", "/nonexistent", TAG)
    assert tools["version_schema"] == bits["version_schema"] == "none"


def test_packaged_files_get_system_modes_whatever_the_builders_umask(staged, tmp_path):
    d, pin = staged
    manifest = bd.load_manifest(d / "manifest.json", pin)
    root = tmp_path / "root"
    images = bd.stage_bitstreams(manifest, bd.local_fetcher(d), root)
    assert {p.stat().st_mode & 0o777 for p in images.iterdir()} == {0o644}
    assert images.stat().st_mode & 0o777 == 0o755
    config = bd.tools_nfpm(version="0.0.post600", bitstreams="20260921+gf3355dccf443", repo=_PATH.parents[2])
    for c in config["contents"]:
        if c.get("type") != "symlink":
            assert c["file_info"]["mode"] in (0o644, 0o755), c["dst"]
