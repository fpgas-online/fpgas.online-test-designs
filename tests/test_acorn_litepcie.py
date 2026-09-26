"""Tests for the LitePCIe driver packaging (packaging/acorn-litepcie/).

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md. What must hold:

  * the packages' version moves only when the driver's inputs change, and never goes backwards (§3.8);
  * the fleet kernel the CI module is built for is named in one place, above the kernel floor (§3.6, §4.3).
"""

import importlib.util
import pathlib
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
