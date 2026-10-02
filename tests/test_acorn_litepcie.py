"""Tests for the LitePCIe driver packaging (packaging/acorn-litepcie/).

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md. What must hold:

  * the packages' version moves only when the driver's inputs change, and never goes backwards (§3.8);
  * the fleet kernel the CI module is built for is named in one place, above the kernel floor (§3.6, §4.3).
"""

import importlib.util
import json
import pathlib
import shutil
import subprocess

import pytest

_DIR = pathlib.Path(__file__).resolve().parents[1] / "packaging" / "acorn-litepcie"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _DIR / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bd = _load("build_debs")


# -- the version -----------------------------------------------------------------------------------------


def _git(repo, *args):
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin"}
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false"]
    return subprocess.run(
        ["git", "-C", str(repo), *ident, *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _commit(repo, path, text, message):
    f = repo / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text)
    _git(repo, "add", path)
    _git(repo, "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _commit(r, "packaging/acorn-litepcie/kernels.toml", "a\n", "root")
    _git(r, "tag", "v0.0")
    return r


def test_at_the_series_tag_the_version_is_the_series(repo):
    assert bd.driver_version(repo) == "0.0"


def test_each_commit_that_changes_an_input_moves_the_version(repo):
    _commit(repo, "uv.lock", "1\n", "lock")
    _commit(repo, "designs/_shared/x.py", "1\n", "shared")
    assert bd.driver_version(repo) == "0.0.post2"


def test_a_commit_that_changes_no_input_leaves_the_version_alone(repo):
    _commit(repo, "uv.lock", "1\n", "lock")
    _commit(repo, "README.md", "1\n", "docs")
    _commit(repo, "packaging/acorn-pcie/release.toml", "1\n", "a bitstreams pin move is not a driver input")
    assert bd.driver_version(repo) == "0.0.post1"


def test_a_merged_side_branch_takes_the_merge_commits_version_so_it_never_goes_backwards(repo):
    """The side branch changes an input before main moves on; without --first-parent the version would be the
    side commit's (post1), below versions main already published."""
    _git(repo, "checkout", "-q", "-b", "side")
    _commit(repo, "designs/acorn-pcie/gateware/acorn_pcie_soc.py", "1\n", "side change")
    _git(repo, "checkout", "-q", "main")
    _commit(repo, "uv.lock", "1\n", "main change")
    _commit(repo, "uv.lock", "2\n", "main change")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    assert bd.driver_version(repo) == "0.0.post4"


def test_the_version_refuses_a_repository_without_a_series_tag(tmp_path):
    """A shallow clone, or one fetched without tags, would otherwise give a wrong, low postN."""
    r = tmp_path / "untagged"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _commit(r, "uv.lock", "1\n", "root")
    with pytest.raises(bd.BuildError, match=r"vX\.Y tag"):
        bd.driver_version(r)


def test_the_version_refuses_a_shallow_clone(repo, tmp_path):
    """Say so plainly: otherwise the version depends on whether the cut happens to leave the tag reachable."""
    for i in range(3):
        _commit(repo, "uv.lock", f"{i}\n", f"lock {i}")
    shallow = tmp_path / "shallow"
    _git(tmp_path, "clone", "-q", "--depth", "1", f"file://{repo}", str(shallow))
    with pytest.raises(bd.BuildError, match="is a shallow clone"):
        bd.driver_version(shallow)


def test_the_version_inputs_are_the_ones_the_spec_names():
    assert set(bd.VERSION_INPUTS) == {
        "packaging/acorn-litepcie/",
        "designs/acorn-pcie/gateware/acorn_pcie_soc.py",
        "designs/_shared/",
        "uv.lock",
        ".github/workflows/acorn-litepcie.yml",
    }


# -- kernels.toml ----------------------------------------------------------------------------------------


def test_the_fleet_kernel_is_the_one_the_netbooted_fleet_runs():
    kernels = bd.read_kernels()
    assert kernels["fleet_kernel"] == "6.12.109+rpt-rpi-v8"
    assert kernels["fleet_suite"] == "bookworm"


def test_the_kernel_floor_never_drops_the_fleet_kernel():
    kernels = bd.read_kernels()
    assert bd.kernel_release_key(kernels["fleet_kernel"]) >= bd.kernel_release_key(kernels["min_kernel"])


@pytest.mark.parametrize(
    ("kver", "key"),
    [("6.12.109+rpt-rpi-v8", (6, 12, 109)), ("6.12", (6, 12)), ("6.18.50+rpt-rpi-2712", (6, 18, 50))],
)
def test_kernel_release_key_orders_by_number_not_by_text(kver, key):
    assert bd.kernel_release_key(kver) == key
    assert bd.kernel_release_key("6.12.9+rpt-rpi-v8") < bd.kernel_release_key("6.12.10+rpt-rpi-v8")


def test_a_kernels_toml_without_the_fleet_kernel_is_refused(tmp_path):
    bad = tmp_path / "kernels.toml"
    bad.write_text('min_kernel = "6.12"\n')
    with pytest.raises(bd.BuildError, match="fleet_kernel"):
        bd.read_kernels(bad)


# -- the driver patches (§3.3-§3.5) -----------------------------------------------------------------------

pd = _load("prepare_driver")

# The lines the patches anchor on, as litepcie aceef740dbfe has them.
MAIN_C = """static const struct file_operations litepcie_fops = {
\t.owner = THIS_MODULE,
\t.unlocked_ioctl = litepcie_ioctl,
\t.mmap = litepcie_mmap,
};

\tpci_set_master(dev);
#if LINUX_VERSION_CODE < KERNEL_VERSION(5, 18, 0)
\tret = pci_set_dma_mask(dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));
#else
\tret = dma_set_mask(&dev->dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));
#endif
"""
LITEUART_C = 'MODULE_DESCRIPTION("LiteUART serial driver");\nMODULE_ALIAS("platform: liteuart");\n'


@pytest.fixture
def driver(tmp_path):
    d = tmp_path / "driver"
    (d / "kernel").mkdir(parents=True)
    (d / "user").mkdir()
    (d / "kernel" / "main.c").write_text(MAIN_C)
    (d / "kernel" / "liteuart.c").write_text(LITEUART_C)
    return d


def test_the_three_patches_apply(driver):
    pd.apply_patches(driver)
    main_c = (driver / "kernel" / "main.c").read_text()
    assert "\t.unlocked_ioctl = litepcie_ioctl,\n\t.compat_ioctl = compat_ptr_ioctl,\n" in main_c
    assert "\tret = dma_set_mask_and_coherent(&dev->dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));\n" in main_c
    assert "dma_set_mask(&dev->dev" not in main_c
    assert "pci_set_dma_mask(dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));" in main_c  # the pre-5.18 branch is left alone
    assert 'MODULE_ALIAS("platform:liteuart");' in (driver / "kernel" / "liteuart.c").read_text()


def test_a_patch_already_carried_upstream_fails_so_it_gets_dropped(driver):
    pd.apply_patches(driver)
    with pytest.raises(pd.PatchError, match="already"):
        pd.apply_patches(driver)


@pytest.mark.parametrize("patch", pd.PATCHES, ids=lambda p: p.already)
def test_each_patch_notices_on_its_own_that_upstream_has_the_fix(driver, patch):
    f = driver / patch.path
    f.write_text(f.read_text().replace(patch.old, patch.new))
    with pytest.raises(pd.PatchError, match="already"):
        pd.apply_patches(driver, [patch])


def test_a_patch_whose_anchor_is_gone_fails(driver):
    (driver / "kernel" / "liteuart.c").write_text('MODULE_LICENSE("GPL");\n')
    with pytest.raises(pd.PatchError, match="not found"):
        pd.apply_patches(driver)


def test_a_patch_anchor_that_is_not_unique_is_refused(driver):
    (driver / "kernel" / "liteuart.c").write_text(LITEUART_C * 2)
    with pytest.raises(pd.PatchError, match="2 times"):
        pd.apply_patches(driver)
    assert (driver / "kernel" / "liteuart.c").read_text() == LITEUART_C * 2


def test_a_failed_patch_leaves_every_file_as_it_was(driver):
    (driver / "kernel" / "liteuart.c").write_text("nothing to patch\n")
    with pytest.raises(pd.PatchError):
        pd.apply_patches(driver)
    assert (driver / "kernel" / "main.c").read_text() == MAIN_C


# -- generation (§3.1) ---------------------------------------------------------------------------------------


FAKE_SOC = """
import pathlib, sys
pathlib.Path({argv!r}).write_text(" ".join(sys.argv[1:]))
out = pathlib.Path({build!r}) / "driver"
for sub in ("kernel", "user"):
    (out / sub).mkdir(parents=True, exist_ok=True)
(out / "kernel" / "main.c").write_text("main")
(out / "kernel" / "csr.h").write_text("csr")
(out / "user" / "litepcie_util.c").write_text("util")
(out / "__init__.py").write_text("")
"""


def test_generate_runs_the_soc_for_the_driver_only_and_copies_the_tree_out(tmp_path):
    build = tmp_path / "build" / "acorn-cle-215+"
    script = tmp_path / "fake_soc.py"
    argv_file = tmp_path / "argv"
    script.write_text(FAKE_SOC.format(build=str(build), argv=str(argv_file)))
    licence = tmp_path / "LICENSE"
    licence.write_text("Unless otherwise noted, LitePCIe is Copyright 2015-2024 / EnjoyDigital\n")
    out = pd.generate(tmp_path / "out", python=("python3", str(script)), build_dir=build, license_file=licence)
    assert argv_file.read_text().split() == [
        str(pd.SOC_SCRIPT),
        "--variant",
        "cle-215+",
        "--driver",
        "--no-compile-software",
    ]
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [
        "LICENSE",
        "kernel/csr.h",
        "kernel/main.c",
        "user/litepcie_util.c",
    ]


def test_the_litepcie_licence_travels_with_the_tree_because_the_binaries_must_reproduce_it(tmp_path):
    """BSD-2-Clause, clause 2: binary redistributions reproduce the notice. The -utils and -dkms debs ship it."""
    gen = tmp_path / "gen"
    for sub in ("kernel", "user"):
        (gen / sub).mkdir(parents=True)
    with pytest.raises(pd.PatchError, match="LICENSE"):
        pd.copy_tree(gen, tmp_path / "a", license_file=tmp_path / "missing")
    lic = tmp_path / "LICENSE"
    lic.write_text("BSD\n")
    assert (pd.copy_tree(gen, tmp_path / "b", license_file=lic) / "LICENSE").read_text() == "BSD\n"


def test_the_licence_is_found_in_the_environment_litepcie_was_installed_into(tmp_path):
    """generate() asks the same Python that ran the SoC where litepcie's LICENSE is."""
    fake = tmp_path / "LICENSE"
    fake.write_text("x")
    script = tmp_path / "py"
    script.write_text(f"#!/bin/sh\necho {fake}\n")
    script.chmod(0o755)
    assert pd.litepcie_license((str(script),)) == fake


# -- the CSR cross-check (§3.2) ----------------------------------------------------------------------------

cc = _load("csr_check")

CSR_H = """#ifndef CSR_BASE
#define CSR_BASE 0xf0000000L
#endif /* ! CSR_BASE */
/* PCIE_MSI Registers */
#define CSR_PCIE_MSI_BASE (CSR_BASE + 0x5800L)
#define CSR_PCIE_MSI_ENABLE_ADDR (CSR_BASE + 0x5800L)
#define CSR_PCIE_MSI_ENABLE_SIZE 1
#define CSR_PCIE_DMA0_BASE (CSR_BASE + 0x6000L)
#define CSR_CTRL_RESET_ADDR (CSR_BASE + 0x0L)
#define CSR_CTRL_RESET_SOC_RST_OFFSET 0
"""
SOC_H = """#define CONFIG_CPU_HAS_INTERRUPT
#define CONFIG_IDENTIFIER "fpgas-online Acorn PCIe SoC cle-215+ 2026-09-24 17:21:58"
#define DMA_CHANNELS 1
#define DMA_ADDR_WIDTH 64
#define PCIE_DMA0_WRITER_INTERRUPT 1
"""
DRIVER_C = """/* CSR_NOT_A_REFERENCE_IN_A_COMMENT */
#ifdef CSR_PCIE_MSI_PBA_ADDR
	irqs = pci_alloc_irq_vectors(dev, 1, 32, PCI_IRQ_MSIX);
#endif
	litepcie_writel(s, CSR_PCIE_MSI_ENABLE_ADDR, 0);  // CSR_ALSO_NOT_IN_A_LINE_COMMENT
	litepcie_writel(s, CSR_CTRL_RESET_ADDR, 1);
	base = CSR_PCIE_DMA0_BASE - CSR_BASE;
#ifdef CSR_PCIE_DMA1_BASE
	irq = PCIE_DMA1_READER_INTERRUPT;
#endif
	for (i = 0; i < DMA_CHANNELS; i++)
		n = DMA_BUFFER_COUNT;
	w = PCIE_DMA0_WRITER_INTERRUPT;
	dev_info(dev, "CSR_IN_A_STRING %d", DMA_ADDR_WIDTH);
"""
IMAGES = ("cle-215+", "cle-215+-golden", "cle-215", "cle-215-golden", "cle-101", "cle-101-golden")


def _csr_json():
    return {
        "memories": {"csr": {"base": 0xF0000000, "size": 0x10000, "type": "io"}},
        "csr_bases": {"pcie_msi": 0xF0005800, "pcie_dma0": 0xF0006000, "ctrl": 0xF0000000},
        "csr_registers": {
            "pcie_msi_enable": {"addr": 0xF0005800, "size": 1, "type": "rw"},
            "ctrl_reset": {"addr": 0xF0000000, "size": 1, "type": "rw"},
        },
        "constants": {"dma_channels": 1, "dma_addr_width": 64, "pcie_dma0_writer_interrupt": 1},
    }


@pytest.fixture
def generated(tmp_path):
    d = tmp_path / "driver"
    (d / "kernel").mkdir(parents=True)
    (d / "user").mkdir()
    (d / "kernel" / "csr.h").write_text(CSR_H)
    (d / "kernel" / "soc.h").write_text(SOC_H)
    (d / "kernel" / "mem.h").write_text("#define CSR_BASE 0xf0000000L\n#define CSR_SIZE 0x00010000\n")
    (d / "kernel" / "main.c").write_text(DRIVER_C)
    return d


@pytest.fixture
def csrs():
    return {name: _csr_json() for name in IMAGES}


def test_headers_and_six_agreeing_images_pass(generated, csrs):
    assert cc.check(generated, csrs) == []


def test_the_names_checked_include_the_ifdef_only_ones_and_skip_comments_and_strings(generated):
    names = cc.referenced_names(generated)
    assert {"CSR_PCIE_MSI_PBA_ADDR", "CSR_PCIE_DMA1_BASE", "PCIE_DMA1_READER_INTERRUPT"} <= names
    assert not {n for n in names if "NOT_A_REFERENCE" in n or "NOT_IN_A_LINE" in n or "IN_A_STRING" in n}


def test_header_expressions_are_evaluated():
    values = cc.evaluate(cc.parse_defines(CSR_H + SOC_H))
    assert values["CSR_PCIE_MSI_ENABLE_ADDR"] == 0xF0005800
    assert values["CSR_BASE"] == 0xF0000000
    assert values["CONFIG_CPU_HAS_INTERRUPT"] is None
    assert values["CONFIG_IDENTIFIER"].startswith("fpgas-online")


def test_an_image_that_moves_a_register_fails_and_names_the_image_and_both_values(generated, csrs):
    csrs["cle-101-golden"]["csr_registers"]["pcie_msi_enable"]["addr"] = 0xF0005804
    (problem,) = cc.check(generated, csrs)
    assert "CSR_PCIE_MSI_ENABLE_ADDR" in problem
    assert "cle-101-golden" in problem
    assert "0xf0005800" in problem and "0xf0005804" in problem


def test_a_register_absent_from_the_headers_but_present_in_one_image_fails(generated, csrs):
    """The driver is built without that DMA channel, so on that image it would silently leave it unset up."""
    csrs["cle-215"]["csr_bases"]["pcie_dma1"] = 0xF0006800
    (problem,) = cc.check(generated, csrs)
    assert "CSR_PCIE_DMA1_BASE" in problem and "cle-215" in problem


def test_a_register_in_the_headers_but_missing_from_one_image_fails(generated, csrs):
    del csrs["cle-215+-golden"]["csr_registers"]["pcie_msi_enable"]
    (problem,) = cc.check(generated, csrs)
    assert "CSR_PCIE_MSI_ENABLE_ADDR" in problem and "cle-215+-golden" in problem


def test_a_soc_constant_that_differs_fails(generated, csrs):
    csrs["cle-101"]["constants"]["dma_channels"] = 2
    (problem,) = cc.check(generated, csrs)
    assert "DMA_CHANNELS" in problem


def test_a_soc_constant_only_an_image_defines_fails(generated, csrs):
    csrs["cle-101"]["constants"]["pcie_dma1_reader_interrupt"] = 2
    (problem,) = cc.check(generated, csrs)
    assert "PCIE_DMA1_READER_INTERRUPT" in problem


def test_names_the_soc_does_not_define_are_outside_the_check(generated, csrs):
    """DMA_BUFFER_COUNT is litepcie's config.h, fixed by the litepcie pin."""
    rows = {row.name for row in cc.compare(generated, csrs)}
    assert "DMA_BUFFER_COUNT" not in rows
    assert "CSR_PCIE_DMA0_BASE" in rows and "DMA_CHANNELS" in rows


def test_an_unmappable_csr_name_is_an_error(generated, csrs):
    """A field macro has no csr.json counterpart: it must be noticed, not silently skipped."""
    main_c = generated / "kernel" / "main.c"
    main_c.write_text(main_c.read_text() + "\tbit = CSR_CTRL_RESET_SOC_RST_OFFSET;\n")
    (problem,) = cc.check(generated, csrs)
    assert "CSR_CTRL_RESET_SOC_RST_OFFSET" in problem and "cannot" in problem


def test_a_tree_that_references_no_csr_at_all_is_refused(generated, csrs):
    (generated / "kernel" / "main.c").write_text("int x;\n")
    assert any("no CSR" in p for p in cc.check(generated, csrs))


def test_the_check_wants_all_six_images(generated, csrs):
    del csrs["cle-101"]
    assert any("six" in p for p in cc.check(generated, csrs))


# -- fetching the six csr.json -----------------------------------------------------------------------------


def _staged_release(tmp_path, tamper=None):
    import hashlib
    import json

    d = tmp_path / "release"
    d.mkdir()
    files = []
    for variant in IMAGES:
        asset = f"acorn-{variant.replace('+', 'p')}-csr.json"
        data = json.dumps(_csr_json()).encode()
        if asset == tamper:
            (d / asset).write_bytes(data + b" ")
        else:
            (d / asset).write_bytes(data)
        files.append({"asset": asset, "variant": variant, "file": "csr.json", "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})  # fmt: skip
    tag = "vivado-bitstreams-acorn-pcie-20260923-ge48a750c8303"
    raw = json.dumps({"tag": tag, "files": files}).encode()
    (d / "manifest.json").write_bytes(raw)
    pin = tmp_path / "release.toml"
    pin.write_text(f'repo = "x/y"\ntag = "{tag}"\nmanifest_sha256 = "{hashlib.sha256(raw).hexdigest()}"\n')
    return d, pin


def test_the_six_csr_json_come_from_the_pinned_release(tmp_path):
    d, pin = _staged_release(tmp_path)
    got = cc.fetch_release_csrs(pin, from_dir=d)
    assert sorted(got) == sorted(IMAGES)
    assert got["cle-101-golden"]["csr_bases"]["pcie_dma0"] == 0xF0006000


def test_a_manifest_that_is_not_the_pinned_one_is_refused(tmp_path):
    d, pin = _staged_release(tmp_path)
    pin.write_text(pin.read_text().replace('manifest_sha256 = "', 'manifest_sha256 = "0'))
    with pytest.raises(cc.CheckError, match="manifest_sha256"):
        cc.fetch_release_csrs(pin, from_dir=d)


def test_a_csr_json_that_does_not_match_its_manifest_entry_is_refused(tmp_path):
    d, pin = _staged_release(tmp_path, tamper="acorn-cle-215-csr.json")
    with pytest.raises(cc.CheckError, match=r"acorn-cle-215-csr\.json"):
        cc.fetch_release_csrs(pin, from_dir=d)


def test_the_check_reads_the_pin_the_bitstreams_package_is_built_from():
    assert cc.RELEASE_PIN == cc.REPO / "packaging" / "acorn-pcie" / "release.toml"
    cc.bits.bitstreams_version(cc.bits.read_pin(cc.RELEASE_PIN)["tag"])


# -- the packages (§2, §3.6) ----------------------------------------------------------------------------------

VERSION = "0.0.post7"
DKMS_CONF = """PACKAGE_NAME="fpgas-online-acorn-litepcie"
PACKAGE_VERSION="0.0.post7"
MAKE[0]="make -C ${kernel_source_dir} M=${dkms_tree}/${PACKAGE_NAME}/${PACKAGE_VERSION}/build modules"
CLEAN="make -C ${kernel_source_dir} M=${dkms_tree}/${PACKAGE_NAME}/${PACKAGE_VERSION}/build clean"
BUILT_MODULE_NAME[0]="litepcie"
BUILT_MODULE_NAME[1]="liteuart"
DEST_MODULE_LOCATION[0]="/updates/dkms"
DEST_MODULE_LOCATION[1]="/updates/dkms"
AUTOINSTALL="yes"
"""


@pytest.fixture
def tree(tmp_path):
    """A prepared driver tree, as prepare_driver.py leaves it."""
    d = tmp_path / "driver"
    for rel, text in {
        "LICENSE": "Unless otherwise noted, LitePCIe is Copyright 2015-2024 / EnjoyDigital\n",
        "kernel/Makefile": "obj-m = litepcie.o liteuart.o\nlitepcie-objs = main.o\n",
        "kernel/main.c": "main\n",
        "kernel/liteuart.c": "uart\n",
        "kernel/csr.h": "csr\n",
        "user/litepcie_util.c": "util\n",
    }.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text)
    return d


def _dst(config):
    return {c["dst"]: c for c in config["contents"]}


def test_dkms_conf_is_the_specs_calling_kbuild_directly():
    """Not the upstream Makefile: its ARCH?=$(uname -m) is aarch64 on arm64 and it builds for uname -r."""
    assert bd.dkms_conf(VERSION) == DKMS_CONF


def test_the_dkms_package_carries_the_kernel_sources_and_dkms_conf(tree, tmp_path):
    config = bd.dkms_nfpm(VERSION, tree, tmp_path / "stage")
    assert config["name"] == "fpgas-online-acorn-litepcie-dkms"
    assert config["arch"] == "all"
    assert config["section"] == "kernel"
    src = pathlib.Path(_dst(config)["/usr/src/fpgas-online-acorn-litepcie-0.0.post7"]["src"])
    assert sorted(p.name for p in src.iterdir()) == ["Makefile", "csr.h", "dkms.conf", "liteuart.c", "main.c"]
    assert (src / "dkms.conf").read_text() == DKMS_CONF
    assert {p.stat().st_mode & 0o777 for p in src.iterdir()} == {0o644}


def test_the_dkms_package_relationships_are_the_specs(tree, tmp_path):
    config = bd.dkms_nfpm(VERSION, tree, tmp_path / "stage")
    assert config["depends"] == ["dkms", "fpgas-online-acorn-litepcie-common"]
    assert config["provides"] == ["fpgas-online-acorn-litepcie-module"]
    assert config["conflicts"] == ["fpgas-online-acorn-litepcie-prebuilt"]
    assert "linux-headers" not in json_text(config)  # the RPi headers are per kernel: the operator's choice


def test_the_dkms_maintainer_scripts_register_and_remove_this_version(tree, tmp_path):
    config = bd.dkms_nfpm(VERSION, tree, tmp_path / "stage")
    postinst = pathlib.Path(config["scripts"]["postinstall"]).read_text()
    prerm = pathlib.Path(config["scripts"]["preremove"]).read_text()
    assert "/usr/lib/dkms/common.postinst fpgas-online-acorn-litepcie 0.0.post7" in postinst
    assert "dkms remove -m fpgas-online-acorn-litepcie -v 0.0.post7 --all" in prerm
    for script in (postinst, prerm):
        assert script.startswith("#!/bin/sh\nset -e\n")
        assert "@" not in script  # every template field was filled


def test_the_common_package_is_the_blacklist_only():
    config = bd.common_nfpm(VERSION)
    assert config["name"] == "fpgas-online-acorn-litepcie-common"
    assert config["arch"] == "all"
    entry, notice = config["contents"]
    assert notice["dst"] == "/usr/share/doc/fpgas-online-acorn-litepcie-common/copyright"
    assert "Apache-2.0" in pathlib.Path(notice["src"]).read_text()
    assert entry["dst"] == "/etc/modprobe.d/fpgas-online-acorn-litepcie.conf"
    assert entry["type"] == "config"
    lines = [line for line in pathlib.Path(entry["src"]).read_text().splitlines() if not line.startswith("#")]
    assert [line for line in lines if line.strip()] == ["blacklist litepcie"]


@pytest.fixture
def bins(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    for name in ("litepcie_util", "litepcie_test"):
        (d / name).write_bytes(b"\x7fELF")
    (d / "utils.json").write_text('{"arch": "armhf", "glibc": "2.34"}')
    return d


def test_the_utils_package_installs_both_tools_for_its_architecture(tree, bins):
    config = bd.utils_nfpm(VERSION, "armhf", bins, tree)
    assert config["name"] == "fpgas-online-acorn-litepcie-utils"
    assert config["arch"] == "armhf"
    dst = _dst(config)
    for tool in ("litepcie_util", "litepcie_test"):
        assert dst[f"/usr/bin/{tool}"]["file_info"]["mode"] == 0o755
    assert config["depends"] == ["libc6 (>= 2.34)"]


def test_the_utils_package_only_suggests_a_driver(tree, bins):
    """apt installs Recommends by default and picks the sole provider of a virtual package: a Recommends would
    pull -dkms, dkms and gcc into the netbooted fleet's armhf root, where DKMS cannot work (§2)."""
    config = bd.utils_nfpm(VERSION, "armhf", bins, tree)
    assert config["suggests"] == ["fpgas-online-acorn-litepcie-module"]
    assert "recommends" not in config


def test_generation_uses_exactly_what_uv_lock_pins():
    """uv.lock is a version input: a stale lock must fail, not re-resolve to litepcie/litex HEAD."""
    assert pd.PYTHON[:3] == ("uv", "run", "--locked")


def test_binaries_built_for_another_architecture_are_refused(tree, bins):
    with pytest.raises(bd.BuildError, match="armhf"):
        bd.utils_nfpm(VERSION, "arm64", bins, tree)


def test_the_litepcie_notice_ships_with_the_binaries_and_the_sources(tree, bins, tmp_path):
    for config in (bd.utils_nfpm(VERSION, "armhf", bins, tree), bd.dkms_nfpm(VERSION, tree, tmp_path / "s")):
        copyright_file = _dst(config)[f"/usr/share/doc/{config['name']}/copyright"]
        assert "LitePCIe is Copyright 2015-2024 / EnjoyDigital" in pathlib.Path(copyright_file["src"]).read_text()


def test_every_package_keeps_its_version_exactly_as_given(tree, bins, tmp_path):
    configs = [bd.common_nfpm(VERSION), bd.dkms_nfpm(VERSION, tree, tmp_path / "s"),
               bd.utils_nfpm(VERSION, "armhf", bins, tree)]  # fmt: skip
    assert {c["version"] for c in configs} == {VERSION}
    assert {c["version_schema"] for c in configs} == {"none"}


def json_text(config):
    import json

    return json.dumps(config)


# -- container.py: the in-container builds (§3.6, §3.9) ---------------------------------------------------------

ct = _load("container")

OBJDUMP_T = """
litepcie_util:     file format elf32-littlearm

DYNAMIC SYMBOL TABLE:
00000000      DF *UND*  00000000 (GLIBC_2.4)  __stack_chk_fail
00000000      DF *UND*  00000000 (GLIBC_2.34) __libc_start_main
00000000      DF *UND*  00000000 (GLIBC_2.9)  pipe2
00000000  w   D  *UND*  00000000  Base        __gmon_start__
"""


def test_the_glibc_floor_is_the_highest_symbol_version_compared_as_numbers():
    assert ct.max_glibc(OBJDUMP_T) == "2.34"  # not "2.9", which sorts higher as text


def test_no_glibc_symbols_is_an_error_not_a_floor_of_nothing():
    with pytest.raises(ct.ContainerError, match="GLIBC"):
        ct.max_glibc("DYNAMIC SYMBOL TABLE:\n")


@pytest.mark.parametrize(
    ("vermagic", "ok"),
    [
        ("6.12.109+rpt-rpi-v8 SMP preempt mod_unload modversions aarch64", True),  # as seen on pi-sw2-p48
        ("6.12.109+rpt-rpi-v8-rt SMP preempt_rt mod_unload modversions aarch64", False),
        ("6.12.10+rpt-rpi-v8 SMP preempt mod_unload modversions aarch64", False),
        ("", False),
    ],
)
def test_vermagic_must_name_exactly_the_kernel(vermagic, ok):
    assert ct.vermagic_ok(vermagic, "6.12.109+rpt-rpi-v8") is ok


def test_the_newest_installed_headers_name_the_kernel_to_build_for():
    names = [
        "linux-headers-rpi-v8",  # the meta package: not a kernel
        "linux-headers-6.12.9+rpt-rpi-v8",
        "linux-headers-6.12.47+rpt-rpi-v8",
        "linux-headers-6.12.47+rpt-common-rpi",
    ]
    assert ct.newest_kernel(names, "rpi-v8") == "6.12.47+rpt-rpi-v8"


def test_no_installed_headers_is_an_error():
    with pytest.raises(ct.ContainerError, match="rpi-v8"):
        ct.newest_kernel(["linux-headers-rpi-v8"], "rpi-v8")


def test_the_docker_command_mounts_the_repository_and_bootstraps_python(tmp_path):
    argv = ct.docker_argv("linux/arm/v7", ["utils", "--arch", "armhf"], docker=("sudo", "-n", "docker"))
    assert argv[:3] == ["sudo", "-n", "docker"]
    assert argv[argv.index("--platform") + 1] == "linux/arm/v7"
    assert "--pull=always" in argv  # otherwise a local debian:bookworm of the other architecture is reused
    assert f"{ct.REPO}:/w" in argv
    assert argv[-1].endswith("python3 packaging/acorn-litepcie/container.py utils --arch armhf")


def test_every_architecture_has_its_docker_platform():
    assert ct.PLATFORMS == {"arm64": "linux/arm64", "armhf": "linux/arm/v7"}


def test_the_command_line_prints_the_version_for_the_workflow(monkeypatch, capsys):
    """CI computes the version once and hands it to every job, so all the debs of a run agree."""
    monkeypatch.setattr(bd, "driver_version", lambda repo=None: "0.0.post42")
    bd.main(["--print-version"])
    assert capsys.readouterr().out == "0.0.post42\n"


def test_the_command_line_wants_a_package_to_build(tmp_path):
    with pytest.raises(SystemExit):
        bd.main(["--out", str(tmp_path), "--driver", str(tmp_path)])


def test_a_string_define_python_cannot_read_is_kept_as_text_not_a_crash():
    """evaluate() sees every define in the generated headers, not only the ones the driver uses."""
    values = cc.evaluate(cc.parse_defines('#define CONFIG_ODD "C:\\\\N{x"\n#define CONFIG_BAD "\\N"\n'))
    assert values["CONFIG_BAD"] == '"\\N"'


# -- publishing (§3.6) -----------------------------------------------------------------------------------------

pub = _load("publish")
P = "fpgas-online-acorn-litepcie"
X = f"{P}-common_0.0.post1_all.deb"


@pytest.mark.parametrize(("version", "series"), [("0.0.post42", "v0.0"), ("0.1", "v0.1"), ("1.12.post3", "v1.12")])
def test_the_series_release_is_the_versions_own(version, series):
    """Not HEAD's nearest tag: the version is the driver inputs' last commit's, which can predate a new tag."""
    assert pub.series(version) == series


def test_only_files_the_release_lacks_are_uploaded(tmp_path):
    """A published version never changes under an apt repository that already pulled it."""
    debs = [tmp_path / n for n in (f"{P}-common_0.0.post1_all.deb", f"{P}-dkms_0.0.post1_all.deb")]
    published = {f"{P}-common_0.0.post1_all.deb", "fpgas-online-acorn-tools_0.0.post9_all.deb"}
    assert pub.to_upload(debs, published) == [debs[1]]


class FakeGh:
    def __init__(self, assets, exists=True, race=()):
        self.assets, self.exists, self.race, self.calls = set(assets), exists, set(race), []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("release", "view"):
            if not self.exists:
                raise pub.GhError("release not found")
            return "\n".join(sorted(self.assets))
        if args[:2] == ("release", "create"):
            self.exists = True
            return ""
        if args[:2] == ("release", "upload"):
            name = pathlib.Path(args[3]).name
            assert pathlib.Path(args[3]).is_file()
            name = self.stored(name)
            if name in self.race:  # another run got there first
                self.assets.add(name)
                raise pub.GhError(f"asset {name} already exists")
            self.assets.add(name)
            return ""
        if args[:2] == ("release", "delete-asset"):
            assert args[4:] == ("--yes",)
            self.assets.remove(args[3])
            return ""
        raise AssertionError(args)

    @staticmethod
    def stored(name):
        """What GitHub does to an uploaded file's name."""
        return name.replace("~", ".")

    def did(self, verb):
        return [c[3] if verb == "delete-asset" else pathlib.Path(c[3]).name for c in self.calls if c[1] == verb]


def test_publish_creates_the_series_release_when_missing_and_uploads(tmp_path):
    deb = tmp_path / X
    deb.write_bytes(b"x")
    gh = FakeGh([], exists=False)
    pub.publish([deb], "0.0.post1", gh=gh)
    assert gh.calls[1][:2] == ("release", "create") and gh.calls[1][2] == "v0.0"
    assert X in gh.assets


def test_an_upload_another_run_made_meanwhile_is_not_a_failure(tmp_path):
    deb = tmp_path / X
    deb.write_bytes(b"x")
    pub.publish([deb], "0.0.post1", gh=FakeGh([], race={X}))


def test_an_upload_that_really_failed_is_a_failure(tmp_path):
    deb = tmp_path / X
    deb.write_bytes(b"x")

    class Broken(FakeGh):
        def __call__(self, *args):
            if args[:2] == ("release", "upload"):
                raise pub.GhError("HTTP 500")
            return super().__call__(*args)

    with pytest.raises(pub.GhError, match="500"):
        pub.publish([deb], "0.0.post1", gh=Broken([]))


def test_a_release_view_that_fails_for_another_reason_is_reported_as_itself(tmp_path):
    """Only a missing release is created; an auth or network failure must not turn into a bogus create."""
    deb = tmp_path / X
    deb.write_bytes(b"x")

    class Offline(FakeGh):
        def __call__(self, *args):
            if args[:2] == ("release", "view"):
                raise pub.GhError("gh release: HTTP 401: Bad credentials")
            return super().__call__(*args)

    gh = Offline([])
    with pytest.raises(pub.GhError, match="401"):
        pub.publish([deb], "0.0.post1", gh=gh)
    assert not [c for c in gh.calls if c[:2] == ("release", "create")]


# -- the release's asset names, the asset budget and retention (§4.3) --------------------------------------------

M = f"{P}-modules-6.12.109+rpt-rpi-v8"


def test_github_stores_a_tilde_as_a_dot_and_keeps_the_plus():
    """GitHub "renames asset filenames that have special characters": seen on this organisation's releases."""
    assert pub.release_name(f"{M}_0.0.post7~deb12_arm64.deb") == f"{M}_0.0.post7.deb12_arm64.deb"
    assert pub.release_name(f"{P}-utils_0.0.post7_armhf.deb") == f"{P}-utils_0.0.post7_armhf.deb"


@pytest.mark.parametrize(
    ("name", "parsed"),
    [
        (f"{P}-common_0.0.post7_all.deb", (f"{P}-common", "0.0.post7")),
        (f"{M}_0.0.post7.deb12_arm64.deb", (M, "0.0.post7")),
        (f"{M}_0.0.post7~deb13_arm64.deb", (M, "0.0.post7")),
        (f"{P}-utils_0.1_amd64.deb", (f"{P}-utils", "0.1")),
        ("fpgas-online-acorn-tools_0.0.post7_all.deb", None),
        (f"{P}-common_20260921+gf3355dccf443_all.deb", None),
        (f"{P}-common_0.0.post7_all.deb.sha256", None),
    ],
)
def test_an_asset_name_gives_the_package_and_the_driver_version(name, parsed):
    assert pub.parse_asset(name) == parsed


def _set(version, kvers=("6.12.109+rpt-rpi-v8",), suite="deb12"):
    """The assets of one driver version."""
    names = {f"{P}-common_{version}_all.deb", f"{P}-dkms_{version}_all.deb"}
    names |= {f"{P}-utils_{version}_{arch}.deb" for arch in ("armhf", "arm64", "amd64")}
    return names | {f"{P}-modules-{kver}_{version}.{suite}_arm64.deb" for kver in kvers}


OTHERS = {
    "fpgas-online-acorn-tools_0.0.post3_all.deb",
    "fpgas-online-acorn-bitstreams_20260921+gf3355dccf443_all.deb",
    "fpgas-online-acorn_0.0.post3_all.deb",
}


def test_pruning_keeps_the_current_driver_version_and_the_one_before_it():
    assets = _set("0.0.post3") | _set("0.0.post5") | _set("0.0.post9") | _set("0.0.post10") | OTHERS
    assert set(pub.plan_prune(assets, "0.0.post10", "6.12")) == _set("0.0.post3") | _set("0.0.post5")


def test_pruning_never_touches_another_packages_assets():
    assets = _set("0.0.post9") | _set("0.0.post10") | _set("0.0.post11") | OTHERS
    assert not set(pub.plan_prune(assets, "0.0.post11", "6.12")) & OTHERS


def test_the_one_before_is_the_newest_older_version_on_the_release_not_the_previous_number():
    """Driver versions skip numbers: most merges change no driver input."""
    assets = _set("0.0.post621") | _set("0.0.post776") | _set("0.0.post800")
    assert set(pub.plan_prune(assets, "0.0.post800", "6.12")) == _set("0.0.post621")


def test_versions_are_ordered_as_numbers_and_across_series():
    assets = _set("0.0.post99") | _set("0.0.post100") | _set("0.1")
    assert set(pub.plan_prune(assets, "0.1", "6.12")) == _set("0.0.post99")
    assert pub.plan_prune(_set("0.0.post9") | _set("0.0.post10"), "0.0.post10", "6.12") == []


def test_a_run_of_an_older_commit_never_prunes_what_a_newer_one_published():
    assets = _set("0.0.post8") | _set("0.0.post9") | _set("0.0.post10") | _set("0.0.post11")
    assert set(pub.plan_prune(assets, "0.0.post10", "6.12")) == _set("0.0.post8")


def test_with_only_the_current_version_nothing_is_pruned():
    assert pub.plan_prune(_set("0.0.post10") | OTHERS, "0.0.post10", "6.12") == []


def test_modules_for_a_kernel_below_the_floor_are_pruned_whatever_their_version():
    kept = _set("0.0.post10", kvers=("6.12.109+rpt-rpi-v8", "6.18.50+rpt-rpi-2712"))
    below = {f"{P}-modules-6.6.74+rpt-rpi-v8_0.0.post10.deb12_arm64.deb",
             f"{P}-modules-6.1.0-rpi8-rpi-v8_0.0.post10.deb12_arm64.deb"}  # fmt: skip
    assert set(pub.plan_prune(kept | below, "0.0.post10", "6.12")) == below
    raised = {f"{P}-modules-6.12.109+rpt-rpi-v8_0.0.post10.deb12_arm64.deb"}
    assert set(pub.plan_prune(kept, "0.0.post10", "6.13")) == raised


def test_an_upload_that_would_take_the_release_past_900_assets_is_refused():
    """A release holds 1000 assets and the series release is shared with the other packages' workflows."""
    pub.check_room(858, 42)
    with pytest.raises(pub.PublishError, match=r"859 assets.*42.*900"):
        pub.check_room(859, 42)
    pub.check_room(950, 0)  # nothing to upload: nothing to refuse


def _debs(tmp_path, names):
    paths = []
    for name in sorted(names):
        (tmp_path / name).write_bytes(b"deb")
        paths.append(tmp_path / name)
    return paths


def test_a_modules_deb_is_uploaded_under_the_name_github_stores(tmp_path):
    """Uploaded as `...~deb12_arm64.deb`, GitHub would rename it; the upload names it so nothing is implicit."""
    deb = tmp_path / f"{M}_0.0.post10~deb12_arm64.deb"
    deb.write_bytes(b"deb")
    gh = FakeGh(OTHERS)
    pub.publish([deb], "0.0.post10", gh=gh, min_kernel="6.12")
    assert gh.did("upload") == [f"{M}_0.0.post10.deb12_arm64.deb"]
    assert f"{M}_0.0.post10.deb12_arm64.deb" in gh.assets


def test_publish_uploads_what_is_missing_then_prunes(tmp_path):
    new = {n.replace(".deb12", "~deb12") for n in _set("0.0.post10")}
    gh = FakeGh(_set("0.0.post3") | _set("0.0.post9") | OTHERS | {f"{P}-common_0.0.post10_all.deb"})
    pub.publish(_debs(tmp_path, new), "0.0.post10", gh=gh, min_kernel="6.12")
    assert gh.assets == _set("0.0.post9") | _set("0.0.post10") | OTHERS
    assert set(gh.did("upload")) == _set("0.0.post10") - {f"{P}-common_0.0.post10_all.deb"}
    assert set(gh.did("delete-asset")) == _set("0.0.post3")
    verbs = [c[1] for c in gh.calls]
    assert verbs.index("delete-asset") > max(i for i, v in enumerate(verbs) if v == "upload")


def test_a_dry_run_changes_nothing_and_says_what_it_would_do(tmp_path, capsys):
    new = {n.replace(".deb12", "~deb12") for n in _set("0.0.post10")}
    before = _set("0.0.post3") | _set("0.0.post9") | OTHERS
    gh = FakeGh(before)
    pub.publish(_debs(tmp_path, new), "0.0.post10", gh=gh, min_kernel="6.12", dry_run=True)
    assert gh.assets == before
    assert {c[1] for c in gh.calls} == {"view"}
    out = capsys.readouterr().out
    assert f"would upload {M}_0.0.post10.deb12_arm64.deb" in out
    assert f"would prune {P}-dkms_0.0.post3_all.deb" in out
    assert f"would prune {P}-dkms_0.0.post9_all.deb" not in out
    assert "v0.0: 15 assets now, 6 to upload, 6 to prune, 15 afterwards (the limit is 900)" in out


def test_a_dry_run_does_not_create_a_missing_release(tmp_path, capsys):
    gh = FakeGh([], exists=False)
    pub.publish(_debs(tmp_path, {X}), "0.0.post1", gh=gh, dry_run=True)
    assert {c[1] for c in gh.calls} == {"view"}
    assert "would create the release v0.0" in capsys.readouterr().out


def test_the_budget_is_checked_before_anything_is_uploaded(tmp_path):
    gh = FakeGh({f"other_{i}_all.deb" for i in range(900)})
    with pytest.raises(pub.PublishError, match="900"):
        pub.publish(_debs(tmp_path, {X}), "0.0.post1", gh=gh)
    assert not gh.did("upload")


def test_a_deb_of_another_driver_version_is_refused(tmp_path):
    """A stale artifact must not be published as part of this version's set."""
    gh = FakeGh(OTHERS)
    with pytest.raises(pub.PublishError, match=r"0\.0\.post1"):
        pub.publish(_debs(tmp_path, {X}), "0.0.post2", gh=gh)
    with pytest.raises(pub.PublishError, match="not a"):
        pub.publish(_debs(tmp_path, {"fpgas-online-acorn-tools_0.0.post2_all.deb"}), "0.0.post2", gh=gh)
    assert not gh.did("upload")


def test_an_upload_the_release_does_not_list_afterwards_is_a_failure(tmp_path):
    """If GitHub stored the file under another name, the next run would build and upload it again, for ever."""

    class Renaming(FakeGh):
        @staticmethod
        def stored(name):
            return name.replace(".deb12", "-deb12")

    deb = tmp_path / f"{M}_0.0.post10~deb12_arm64.deb"
    deb.write_bytes(b"deb")
    gh = Renaming(OTHERS)
    with pytest.raises(pub.PublishError, match="does not list"):
        pub.publish([deb], "0.0.post10", gh=gh, min_kernel="6.12")
    assert not gh.did("delete-asset")


def test_a_transient_download_failure_is_retried(tmp_path, monkeypatch):
    """GitHub's release downloads return an occasional HTTP 500 (seen on this PR's CI)."""
    import urllib.error

    d, pin = _staged_release(tmp_path)
    real = cc.bits.local_fetcher(d)
    failures = {"acorn-cle-215-csr.json": 2}

    def flaky(asset):
        if failures.get(asset):
            failures[asset] -= 1
            raise urllib.error.HTTPError(asset, 500, "Internal Server Error", None, None)
        return real(asset)

    monkeypatch.setattr(cc, "RETRY_DELAY_S", 0)
    got = cc.fetch_release_csrs(pin, fetch=flaky)
    assert len(got) == 6


def test_a_download_that_keeps_failing_is_a_clear_error_not_a_traceback(tmp_path, monkeypatch):
    import urllib.error

    _d, pin = _staged_release(tmp_path)

    def down(asset):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(cc, "RETRY_DELAY_S", 0)
    with pytest.raises(cc.CheckError, match=r"manifest\.json.*no route to host"):
        cc.fetch_release_csrs(pin, fetch=down)


# -- which kernels get a modules package (§4.2) ---------------------------------------------------------------

plan = _load("plan")


def _index(*kernels, images=True):
    """A Packages index: a linux-headers stanza (and its linux-image) per (kver, Version)."""
    stanzas = []
    for kver, version in kernels:
        kinds = ("headers", "image") if images else ("headers",)
        for kind in kinds:
            stanzas.append(f"Package: linux-{kind}-{kver}\nSource: linux\nVersion: {version}\nArchitecture: arm64\n")
    return "\n".join(stanzas)


BOOKWORM = _index(
    ("rpi-v8", "1:6.12.109-1+rpt1"),  # the meta package: not a kernel
    ("6.1.0-rpi8-rpi-v8", "1:6.1.73-1+rpt1"),
    ("6.6.74+rpt-rpi-v8", "1:6.6.74-1+rpt1"),
    ("6.12.19+rpt-rpi-v8", "1:6.12.19-1+rpt1~bpo12+1"),
    ("6.12.109+rpt-rpi-v8", "1:6.12.109-1+rpt1"),
    ("6.12.96+rpt-rpi-v8", "1:6.12.96-1+rpt1"),
    ("6.12.109+rpt-rpi-v8-rt", "1:6.12.109-1+rpt1"),
    ("6.12.109+rpt-common-rpi", "1:6.12.109-1+rpt1"),
    ("6.12.109+rpt-rpi-2712", "1:6.12.109-1+rpt1"),
    ("6.12.120+rpt-rpi-2712", "1:6.12.120-1+rpt1"),
)
TRIXIE = _index(
    ("6.12.25+rpt-rpi-v8", "1:6.12.25-1+rpt1+trixie"),
    ("6.18.50+rpt-rpi-v8", "1:6.18.50-1+rpt1"),
    ("6.18.50+rpt-rpi-2712", "1:6.18.50-1+rpt1"),
)
CONFIG = {
    "fleet_kernel": "6.12.96+rpt-rpi-v8",
    "fleet_suite": "bookworm",
    "min_kernel": "6.12",
    "suites": {"bookworm": {"arm64": ["rpi-v8", "rpi-2712"]}, "trixie": {"arm64": ["rpi-v8", "rpi-2712"]}},
}
INDEXES = {("bookworm", "arm64"): BOOKWORM, ("trixie", "arm64"): TRIXIE}


def _kvers(found):
    return [kver for _release, kver in found]


def test_the_kernels_of_a_flavour_are_its_versioned_headers_at_or_above_the_floor_oldest_first():
    """Not the meta package, not the -rt flavour, not the shared -common-rpi headers, and 6.12.19 before 6.12.96."""
    assert _kvers(plan.kernels(BOOKWORM, "rpi-v8", "6.12")) == [
        "6.12.19+rpt-rpi-v8",
        "6.12.96+rpt-rpi-v8",
        "6.12.109+rpt-rpi-v8",
    ]


def test_the_floor_is_compared_with_the_package_version_not_its_name():
    """Every 6.1 kernel is named 6.1.0-rpiN: by name 6.1.0-rpi8 would be below a 6.1.50 floor; it is 6.1.73."""
    assert "6.1.0-rpi8-rpi-v8" in _kvers(plan.kernels(BOOKWORM, "rpi-v8", "6.1.50"))
    assert "6.1.0-rpi8-rpi-v8" not in _kvers(plan.kernels(BOOKWORM, "rpi-v8", "6.1.74"))


def test_a_kernel_without_its_image_package_is_not_built():
    """The modules package depends on linux-image-<kver>: without one it could never be installed."""
    assert plan.kernels(_index(("6.12.96+rpt-rpi-v8", "1:6.12.96-1+rpt1"), images=False), "rpi-v8", "6.12") == []


@pytest.mark.parametrize(
    ("version", "release"),
    [
        ("1:6.1.73-1+rpt1", (6, 1, 73)),
        ("1:6.12.34-1+rpt1~bookworm", (6, 12, 34)),
        ("1:6.12.25-1+rpt1+trixie", (6, 12, 25)),
        ("6.18.50-1", (6, 18, 50)),
    ],
)
def test_the_upstream_release_of_a_kernel_package_version(version, release):
    assert plan.upstream_release(version) == release


def test_a_version_that_names_no_release_is_an_error():
    with pytest.raises(plan.PlanError, match="rpt1"):
        plan.upstream_release("rpt1")


def test_there_is_one_job_per_suite_and_kernel_of_each_flavour():
    jobs = plan.jobs(CONFIG, INDEXES)
    assert [(j.suite, j.flavour, j.kver) for j in jobs] == [
        ("bookworm", "rpi-v8", "6.12.19+rpt-rpi-v8"),
        ("bookworm", "rpi-v8", "6.12.96+rpt-rpi-v8"),
        ("bookworm", "rpi-v8", "6.12.109+rpt-rpi-v8"),
        ("bookworm", "rpi-2712", "6.12.109+rpt-rpi-2712"),
        ("bookworm", "rpi-2712", "6.12.120+rpt-rpi-2712"),
        ("trixie", "rpi-v8", "6.12.25+rpt-rpi-v8"),
        ("trixie", "rpi-v8", "6.18.50+rpt-rpi-v8"),
        ("trixie", "rpi-2712", "6.18.50+rpt-rpi-2712"),
    ]
    assert {j.arch for j in jobs} == {"arm64"}
    assert [j.kver for j in jobs if j.fleet] == ["6.12.96+rpt-rpi-v8"]


def test_the_same_kernel_name_in_two_suites_is_two_jobs_and_only_the_fleet_suites_is_the_fleet_kernel():
    """6.12.34+rpt-rpi-v8 is built with GCC 12 in bookworm and GCC 14 in trixie: never shared between suites."""
    both = _index(("6.12.34+rpt-rpi-v8", "1:6.12.34-1+rpt1"), ("6.12.34+rpt-rpi-2712", "1:6.12.34-1+rpt1"))
    config = {**CONFIG, "fleet_kernel": "6.12.34+rpt-rpi-v8"}
    jobs = plan.jobs(config, {("bookworm", "arm64"): both, ("trixie", "arm64"): both})
    assert [(j.suite, j.fleet) for j in jobs if j.kver == "6.12.34+rpt-rpi-v8"] == [
        ("bookworm", True),
        ("trixie", False),
    ]


def test_a_fleet_kernel_below_the_floor_fails_the_plan():
    with pytest.raises(plan.PlanError, match="below min_kernel"):
        plan.jobs({**CONFIG, "min_kernel": "6.13"}, INDEXES)


def test_a_fleet_kernel_that_is_not_built_fails_the_plan():
    """A typo, a kernel the archive dropped, or a flavour kernels.toml does not list."""
    with pytest.raises(plan.PlanError, match=r"6\.12\.97\+rpt-rpi-v8 \(bookworm\) is not one of the kernels"):
        plan.jobs({**CONFIG, "fleet_kernel": "6.12.97+rpt-rpi-v8"}, INDEXES)


def test_a_flavour_the_archive_has_no_kernel_for_fails_the_plan():
    """An empty or truncated index must not read as 'nothing to build'."""
    with pytest.raises(plan.PlanError, match="trixie arm64 index has no rpi-2712"):
        plan.jobs(CONFIG, {**INDEXES, ("trixie", "arm64"): _index(("6.18.50+rpt-rpi-v8", "1:6.18.50-1+rpt1"))})


def test_a_pull_request_builds_the_newest_kernel_of_each_suite_and_flavour_and_the_fleet_kernel():
    assert [(j.suite, j.kver) for j in plan.sample(plan.jobs(CONFIG, INDEXES))] == [
        ("bookworm", "6.12.96+rpt-rpi-v8"),  # the fleet kernel, though it is not the newest
        ("bookworm", "6.12.109+rpt-rpi-v8"),
        ("bookworm", "6.12.120+rpt-rpi-2712"),
        ("trixie", "6.18.50+rpt-rpi-v8"),
        ("trixie", "6.18.50+rpt-rpi-2712"),
    ]


def test_the_deb_is_named_for_the_kernel_the_driver_version_and_the_suite():
    (job,) = [j for j in plan.jobs(CONFIG, INDEXES) if j.fleet]
    assert job.package == "fpgas-online-acorn-litepcie-modules-6.12.96+rpt-rpi-v8"
    assert job.deb("0.0.post7") == "fpgas-online-acorn-litepcie-modules-6.12.96+rpt-rpi-v8_0.0.post7~deb12_arm64.deb"


def test_the_asset_is_the_deb_as_github_stores_it():
    """GitHub turns the `~` of an uploaded file's name into `.`; the release is compared by the stored name."""
    (job,) = [j for j in plan.jobs(CONFIG, INDEXES) if j.fleet]
    assert job.asset("0.0.post7") == "fpgas-online-acorn-litepcie-modules-6.12.96+rpt-rpi-v8_0.0.post7.deb12_arm64.deb"


def test_main_builds_only_the_packages_the_release_does_not_have_at_this_driver_version():
    jobs = plan.jobs(CONFIG, INDEXES)
    published = {j.asset("0.0.post7") for j in jobs if j.suite == "bookworm"}
    published |= {j.asset("0.0.post6") for j in jobs}  # an older driver version does not count
    assert {j.suite for j in plan.missing(jobs, "0.0.post7", published)} == {"trixie"}
    assert plan.missing(jobs, "0.0.post7", {j.asset("0.0.post7") for j in jobs}) == []
    assert plan.missing(jobs, "0.0.post8", published) == jobs


def test_the_matrix_is_what_the_workflow_reads():
    jobs = [j for j in plan.jobs(CONFIG, INDEXES) if j.fleet]
    assert plan.matrix(jobs, "0.0.post7") == {
        "include": [
            {
                "suite": "bookworm",
                "arch": "arm64",
                "flavour": "rpi-v8",
                "kver": "6.12.96+rpt-rpi-v8",
                "package": "fpgas-online-acorn-litepcie-modules-6.12.96+rpt-rpi-v8",
                "deb": "fpgas-online-acorn-litepcie-modules-6.12.96+rpt-rpi-v8_0.0.post7~deb12_arm64.deb",
                "asset": "fpgas-online-acorn-litepcie-modules-6.12.96+rpt-rpi-v8_0.0.post7.deb12_arm64.deb",
                "fleet": True,
            }
        ]
    }


def test_the_plan_command_writes_the_matrix_for_the_workflow(tmp_path, monkeypatch, capsys):
    for (suite, arch), text in INDEXES.items():
        (tmp_path / f"Packages-{suite}-{arch}").write_text(text)
    kernels = tmp_path / "kernels.toml"
    kernels.write_text(
        'fleet_kernel = "6.12.96+rpt-rpi-v8"\nfleet_suite = "bookworm"\nmin_kernel = "6.12"\n'
        '[suites.bookworm]\narm64 = ["rpi-v8", "rpi-2712"]\n[suites.trixie]\narm64 = ["rpi-v8", "rpi-2712"]\n'
    )
    assets = tmp_path / "assets"
    assets.write_text("fpgas-online-acorn-litepcie-modules-6.12.96+rpt-rpi-v8_0.0.post7.deb12_arm64.deb\n")
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    common = ["--version", "0.0.post7", "--kernels", str(kernels), "--index-dir", str(tmp_path)]
    plan.main([*common, "--assets-file", str(assets), "--mode", "missing"])
    out = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert out["count"] == "7"
    assert len(json.loads(out["matrix"])["include"]) == 7
    text = capsys.readouterr().out
    assert "published -     fpgas-online-acorn-litepcie-modules-6.12.96+rpt-rpi-v8_0.0.post7.deb12_arm64.deb" in text
    assert "main and the daily run would build 7 of 8" in text


def test_kernels_toml_builds_the_kernels_a_pi_5_boots():
    """Both suites, the two 64-bit flavours: no 32-bit kernel boots on a Pi 5, and no host runs -rt."""
    assert bd.read_kernels()["suites"] == {
        "bookworm": {"arm64": ["rpi-v8", "rpi-2712"]},
        "trixie": {"arm64": ["rpi-v8", "rpi-2712"]},
    }


def test_a_kernels_toml_without_suites_is_refused(tmp_path):
    bad = tmp_path / "kernels.toml"
    bad.write_text('fleet_kernel = "6.12.96+rpt-rpi-v8"\nfleet_suite = "bookworm"\nmin_kernel = "6.12"\n')
    with pytest.raises(bd.BuildError, match="suites"):
        bd.read_kernels(bad)


def test_a_flavour_for_an_architecture_no_build_exists_for_is_refused(tmp_path):
    bad = tmp_path / "kernels.toml"
    bad.write_text(
        'fleet_kernel = "6.12.96+rpt-rpi-v8"\nfleet_suite = "bookworm"\nmin_kernel = "6.12"\n'
        '[suites.bookworm]\nriscv64 = ["rpi-v8"]\n'
    )
    with pytest.raises(bd.BuildError, match="riscv64"):
        bd.read_kernels(bad)


# -- the prebuilt modules package (§2, §3.8) ---------------------------------------------------------------------

KVER = "6.12.109+rpt-rpi-v8"


@pytest.fixture
def built(tmp_path):
    """What container.py's `module` leaves: the two modules and modules.json saying what they were built for."""
    d = tmp_path / "modules"
    d.mkdir()
    for name in ("litepcie.ko", "liteuart.ko"):
        (d / name).write_bytes(b"\x7fELF")
    (d / "modules.json").write_text(json.dumps({"kver": KVER, "suite": "bookworm", "arch": "arm64"}))
    return d


def _modules(tree, built, tmp_path, suite="bookworm", kver=KVER, arch="arm64"):
    return bd.modules_nfpm(VERSION, suite, kver, arch, built, tree, tmp_path / "stage")


def test_the_modules_package_is_named_for_its_kernel_and_built_for_the_kernels_architecture(tree, built, tmp_path):
    config = _modules(tree, built, tmp_path)
    assert config["name"] == "fpgas-online-acorn-litepcie-modules-6.12.109+rpt-rpi-v8"
    assert config["arch"] == "arm64"
    assert config["section"] == "kernel"


def test_the_modules_go_where_depmod_prefers_them_over_the_kernels_own(tree, built, tmp_path):
    dst = _dst(_modules(tree, built, tmp_path))
    for name in ("litepcie.ko", "liteuart.ko"):
        entry = dst[f"/lib/modules/{KVER}/updates/fpgas-online/{name}"]
        assert entry["src"] == str(built / name)
        assert entry["file_info"]["mode"] == 0o644


def test_the_modules_package_relationships_are_the_specs(tree, built, tmp_path):
    config = _modules(tree, built, tmp_path)
    assert config["depends"] == ["fpgas-online-acorn-litepcie-common", f"linux-image-{KVER}"]
    assert config["provides"] == ["fpgas-online-acorn-litepcie-module", "fpgas-online-acorn-litepcie-prebuilt"]
    assert "conflicts" not in config  # -dkms conflicts with -prebuilt; modules for two kernels install together


def test_the_modules_maintainer_scripts_run_depmod_for_the_packages_kernel(tree, built, tmp_path):
    config = _modules(tree, built, tmp_path)
    postinst = pathlib.Path(config["scripts"]["postinstall"]).read_text()
    postrm = pathlib.Path(config["scripts"]["postremove"]).read_text()
    for script in (postinst, postrm):
        assert script.startswith("#!/bin/sh\nset -e\n")
        assert f"depmod -a {KVER}\n" in script
        assert "@" not in script  # every template field was filled


def test_the_modules_version_carries_the_suites_debian_release(tree, built, tmp_path):
    assert _modules(tree, built, tmp_path)["version"] == "0.0.post7~deb12"
    (built / "modules.json").write_text(json.dumps({"kver": KVER, "suite": "trixie", "arch": "arm64"}))
    config = _modules(tree, built, tmp_path / "t", suite="trixie")
    assert config["version"] == "0.0.post7~deb13"
    assert config["version_schema"] == "none"


def test_the_suite_suffix_is_never_a_date_or_a_codename():
    assert bd.modules_version("0.0.post7", "bookworm") == "0.0.post7~deb12"
    assert bd.modules_version("0.0", "trixie") == "0.0~deb13"
    with pytest.raises(bd.BuildError, match="buster"):
        bd.modules_version("0.0.post7", "buster")


@pytest.mark.skipif(not shutil.which("dpkg"), reason="needs dpkg --compare-versions")
def test_the_older_suites_build_sorts_lower_so_a_release_upgrade_replaces_it():
    """bookworm < trixie < forky < an unsuffixed version, by dpkg's own comparison."""
    order = [bd.modules_version("0.0.post5", suite) for suite in ("bookworm", "trixie", "forky")]
    assert order == ["0.0.post5~deb12", "0.0.post5~deb13", "0.0.post5~deb14"]
    order += ["0.0.post5", "0.0.post6~deb12"]
    for lower, higher in zip(order, order[1:]):
        subprocess.run(["dpkg", "--compare-versions", lower, "lt", higher], check=True)


def test_the_deb_file_name_is_the_debian_one():
    assert (
        bd.deb_name("fpgas-online-acorn-litepcie-modules-6.12.109+rpt-rpi-v8", "0.0.post7~deb12", "arm64")
        == "fpgas-online-acorn-litepcie-modules-6.12.109+rpt-rpi-v8_0.0.post7~deb12_arm64.deb"
    )


def test_modules_built_for_another_kernel_suite_or_architecture_are_refused(tree, built, tmp_path):
    """The same kernel name is a different build in each suite (§4.2): never package one as the other."""
    with pytest.raises(bd.BuildError, match="trixie"):
        _modules(tree, built, tmp_path / "a", suite="trixie")
    with pytest.raises(bd.BuildError, match=r"6\.12\.96"):
        _modules(tree, built, tmp_path / "b", kver="6.12.96+rpt-rpi-v8")
    with pytest.raises(bd.BuildError, match="armhf"):
        _modules(tree, built, tmp_path / "c", arch="armhf")


def test_the_modules_package_ships_the_litepcie_notice(tree, built, tmp_path):
    config = _modules(tree, built, tmp_path)
    notice = pathlib.Path(_dst(config)[f"/usr/share/doc/{config['name']}/copyright"]["src"]).read_text()
    assert "LitePCIe is Copyright 2015-2024 / EnjoyDigital" in notice
    assert "GPL-2" in notice  # liteuart.ko


def test_common_satisfies_a_modules_package_of_a_foreign_architecture():
    """The fleet's root is armhf and its modules package arm64: apt lets an arm64 package's dependency be met
    by an Architecture: all package only when that one is Multi-Arch: foreign."""
    assert bd.common_nfpm(VERSION)["deb"]["fields"] == {"Multi-Arch": "foreign"}


def test_the_utils_are_built_for_the_pi_architectures_and_x86():
    assert set(bd.ARCHES) == {"armhf", "arm64", "amd64"}
