"""Tests for the LitePCIe driver packaging (packaging/acorn-litepcie/).

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md. What must hold:

  * the packages' version moves only when the driver's inputs change, and never goes backwards (§3.8);
  * the fleet kernel the CI module is built for is named in one place, above the kernel floor (§3.6, §4.3).
"""

import hashlib
import importlib.util
import json
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
    (d / "utils.json").write_text('{"suite": "bookworm", "arch": "armhf", "glibc": "2.34"}')
    return d


def test_the_utils_package_installs_both_tools_for_its_architecture(tree, bins):
    config = bd.utils_nfpm(VERSION, "bookworm", "armhf", bins, tree)
    assert config["name"] == "fpgas-online-acorn-litepcie-utils"
    assert config["arch"] == "armhf"
    dst = _dst(config)
    for tool in ("litepcie_util", "litepcie_test"):
        assert dst[f"/usr/bin/{tool}"]["file_info"]["mode"] == 0o755
    assert config["depends"] == ["libc6 (>= 2.34)"]


def test_the_utils_package_only_suggests_a_driver(tree, bins):
    """apt installs Recommends by default and picks the sole provider of a virtual package: a Recommends would
    pull -dkms, dkms and gcc into the netbooted fleet's armhf root, where DKMS cannot work (§2)."""
    config = bd.utils_nfpm(VERSION, "bookworm", "armhf", bins, tree)
    assert config["suggests"] == ["fpgas-online-acorn-litepcie-module"]
    assert "recommends" not in config


def test_generation_uses_exactly_what_uv_lock_pins():
    """uv.lock is a version input: a stale lock must fail, not re-resolve to litepcie/litex HEAD."""
    assert pd.PYTHON[:3] == ("uv", "run", "--locked")


def test_binaries_built_for_another_architecture_are_refused(tree, bins):
    with pytest.raises(bd.BuildError, match="armhf"):
        bd.utils_nfpm(VERSION, "bookworm", "arm64", bins, tree)


def test_the_litepcie_notice_ships_with_the_binaries_and_the_sources(tree, bins, tmp_path):
    for config in (
        bd.utils_nfpm(VERSION, "bookworm", "armhf", bins, tree),
        bd.dkms_nfpm(VERSION, tree, tmp_path / "s"),
    ):
        copyright_file = _dst(config)[f"/usr/share/doc/{config['name']}/copyright"]
        assert "LitePCIe is Copyright 2015-2024 / EnjoyDigital" in pathlib.Path(copyright_file["src"]).read_text()


def test_every_package_keeps_its_version_exactly_as_given(tree, bins, tmp_path):
    configs = [bd.common_nfpm(VERSION), bd.dkms_nfpm(VERSION, tree, tmp_path / "s"),
               bd.utils_nfpm(VERSION, "bookworm", "armhf", bins, tree)]  # fmt: skip
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


def test_the_dkms_test_asks_dkms_about_the_drivers_own_version():
    """`dkms status -v 0.0.post7~deb13` finds nothing: dkms.conf says 0.0.post7 (seen in CI on trixie)."""
    assert ct.driver_version("0.0.post7~deb13~pr79") == bd.driver_of("0.0.post7~deb13~pr79") == "0.0.post7"
    assert ct.driver_version("0.0.post7") == "0.0.post7"


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
    assert ct.PLATFORMS == {"arm64": "linux/arm64", "armhf": "linux/arm/v7", "amd64": "linux/amd64"}


def test_a_module_is_built_in_its_suites_own_image():
    """The same kernel name is built with GCC 12 in bookworm and GCC 14 in trixie (§4.2)."""
    assert ct.docker_argv("linux/arm64", ["module"])[-4] == "debian:bookworm"
    assert ct.docker_argv("linux/arm64", ["module"], suite="trixie")[-4] == "debian:trixie"


def test_the_dkms_test_finds_debians_own_amd64_kernel():
    names = ["linux-headers-amd64", "linux-headers-6.1.0-40-common", "linux-headers-6.1.0-40-amd64"]
    assert ct.newest_kernel(names, "amd64") == "6.1.0-40-amd64"
    assert ct.vermagic_ok("6.1.0-40-amd64 SMP preempt mod_unload modversions ", "6.1.0-40-amd64")
    assert ct.DKMS_KERNELS["amd64"] == (("linux-image-amd64", "linux-headers-amd64"), "amd64", False)


def test_the_dkms_test_installs_the_kernel_with_its_headers():
    """DKMS runs depmod only where the kernel's own modules are, and the Raspberry Pi 6.18 headers do not pull
    their image in: without it `modinfo -k` found nothing DKMS had installed (seen in CI on trixie)."""
    for image, headers in (kernel for kernel, _flavour, _rpi in ct.DKMS_KERNELS.values()):
        assert image.startswith("linux-image-") and headers == image.replace("-image-", "-headers-")


def test_the_container_and_the_packager_agree_on_names():
    assert (ct.NAME, ct.TOOLS, ct.MODULES) == (bd.NAME, bd.TOOLS, bd.MODULES)
    assert set(ct.SUITES) == set(bd.SUITES) >= set(bd.read_kernels()["suites"])


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


@pytest.mark.parametrize(("version", "series"), [("0.0.post42", "v0.0"), ("0.1", "v0.1"), ("1.12.post3", "v1.12")])
def test_the_series_release_is_the_versions_own(version, series):
    """Not HEAD's nearest tag: the version is the driver inputs' last commit's, which can predate a new tag."""
    assert pub.series(version) == series


def test_only_files_the_release_lacks_are_uploaded(tmp_path):
    """A published version never changes under an apt repository that already pulled it."""
    debs = [tmp_path / n for n in ("a_0.0.post1_all.deb", "b_0.0.post1_all.deb")]
    assert pub.to_upload(debs, {"a_0.0.post1_all.deb", "fpgas-online-acorn-tools_0.0.post9_all.deb"}) == [debs[1]]


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
            if name in self.race:  # another run got there first
                self.assets.add(name)
                raise pub.GhError(f"asset {name} already exists")
            self.assets.add(name)
            return ""
        raise AssertionError(args)


def test_publish_creates_the_series_release_when_missing_and_uploads(tmp_path):
    deb = tmp_path / "x_0.0.post1_all.deb"
    deb.write_bytes(b"x")
    gh = FakeGh([], exists=False)
    pub.publish([deb], "0.0.post1", gh=gh)
    assert gh.calls[1][:2] == ("release", "create") and gh.calls[1][2] == "v0.0"
    assert "x_0.0.post1_all.deb" in gh.assets


def test_an_upload_another_run_made_meanwhile_is_not_a_failure(tmp_path):
    deb = tmp_path / "x_0.0.post1_all.deb"
    deb.write_bytes(b"x")
    pub.publish([deb], "0.0.post1", gh=FakeGh([], race={"x_0.0.post1_all.deb"}))


def test_an_upload_that_really_failed_is_a_failure(tmp_path):
    deb = tmp_path / "x_0.0.post1_all.deb"
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
    deb = tmp_path / "x_0.0.post1_all.deb"
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
P = "fpgas-online-acorn-litepcie"
VERSIONS = {"bookworm": "0.0.post7~deb12", "trixie": "0.0.post7~deb13"}


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
    """An empty or truncated index must not read as 'nothing to build': the publish would drop every module."""
    with pytest.raises(plan.PlanError, match="trixie arm64 index has no rpi-2712"):
        plan.jobs(CONFIG, {**INDEXES, ("trixie", "arm64"): _index(("6.18.50+rpt-rpi-v8", "1:6.18.50-1+rpt1"))})


def test_a_sample_is_the_newest_kernel_of_each_suite_and_flavour_and_the_fleet_kernel():
    assert [(j.suite, j.kver) for j in plan.sample(plan.jobs(CONFIG, INDEXES))] == [
        ("bookworm", "6.12.96+rpt-rpi-v8"),  # the fleet kernel, though it is not the newest
        ("bookworm", "6.12.109+rpt-rpi-v8"),
        ("bookworm", "6.12.120+rpt-rpi-2712"),
        ("trixie", "6.18.50+rpt-rpi-v8"),
        ("trixie", "6.18.50+rpt-rpi-2712"),
    ]


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


@pytest.mark.parametrize(("table", "problem"), [('[suites.bookworm]\nriscv64 = ["rpi-v8"]\n', "riscv64"),
                                                ('[suites.buster]\narm64 = ["rpi-v8"]\n', "buster")])  # fmt: skip
def test_a_suite_or_an_architecture_no_build_exists_for_is_refused(tmp_path, table, problem):
    bad = tmp_path / "kernels.toml"
    bad.write_text('fleet_kernel = "6.12.96+rpt-rpi-v8"\nfleet_suite = "bookworm"\nmin_kernel = "6.12"\n' + table)
    with pytest.raises(bd.BuildError, match=problem):
        bd.read_kernels(bad)


# -- what a suite's archive holds, and where each deb comes from (§4.3) -------------------------------------------


def _wanted(suite="bookworm"):
    jobs = [j for j in plan.jobs(CONFIG, INDEXES) if j.suite == suite]
    return plan.wanted(suite, VERSIONS[suite], jobs)


def test_a_suite_wants_the_complete_set_at_its_own_version():
    """publish-apt drops a package the deploy does not hold: every publish hands over all of them."""
    files = [deb["file"] for deb in _wanted("trixie")]
    assert files == [
        f"{P}-common_0.0.post7~deb13_all.deb",
        f"{P}-dkms_0.0.post7~deb13_all.deb",
        f"{P}-utils_0.0.post7~deb13_armhf.deb",
        f"{P}-utils_0.0.post7~deb13_arm64.deb",
        f"{P}-utils_0.0.post7~deb13_amd64.deb",
        f"{P}-modules-6.12.25+rpt-rpi-v8_0.0.post7~deb13_arm64.deb",
        f"{P}-modules-6.18.50+rpt-rpi-v8_0.0.post7~deb13_arm64.deb",
        f"{P}-modules-6.18.50+rpt-rpi-2712_0.0.post7~deb13_arm64.deb",
    ]
    assert P not in {deb["package"] for deb in _wanted("trixie")}  # the meta package is not in this archive


def _site(*debs, version=None):
    """A live suite's Packages, as publish-apt's dpkg-scanpackages writes it."""
    return "\n".join(
        f"Package: {deb['package']}\nVersion: {version or deb['version']}\nArchitecture: {deb['arch']}\n"
        f"Depends: x\nFilename: ./{deb['file']}\nSize: {len(deb['file'])}\n"
        f"SHA256: {hashlib.sha256(deb['file'].encode()).hexdigest()}\nDescription: d\n more\n"
        for deb in debs
    )


def test_without_a_site_everything_is_built():
    planned = plan.plan_suite(_wanted(), None, selected={"6.12.96+rpt-rpi-v8"})
    assert {deb["action"] for deb in planned} == {"build"}
    assert [deb["kver"] for deb in planned if "kver" in deb and deb["selected"]] == ["6.12.96+rpt-rpi-v8"]
    assert all(deb["selected"] for deb in planned if "kver" not in deb)  # -common, -dkms, -utils: always built


def test_a_deb_the_site_has_at_this_version_is_reused_never_rebuilt():
    """A published (package, version) never changes its bytes."""
    debs = _wanted()
    planned = plan.plan_suite(debs, _site(*debs[:3]), selected={j["kver"] for j in debs if "kver" in j})
    assert [deb["action"] for deb in planned[:4]] == ["reuse", "reuse", "reuse", "build"]
    first = planned[0]
    assert first["filename"] == first["file"] and first["size"] == len(first["file"])
    assert first["sha256"] == hashlib.sha256(first["file"].encode()).hexdigest()


def test_another_version_or_architecture_on_the_site_is_not_this_deb():
    debs = _wanted()
    older = _site(*debs, version="0.0.post6~deb12")
    assert {deb["action"] for deb in plan.plan_suite(debs, older)} == {"build"}
    armhf = next(deb for deb in debs if deb["arch"] == "armhf")
    other = plan.plan_suite(debs, _site(armhf))
    assert [deb["arch"] for deb in other if deb["action"] == "reuse"] == ["armhf"]


def test_a_quiet_day_builds_no_module_and_a_new_kernel_only_its_own():
    jobs = plan.jobs(CONFIG, INDEXES)
    site = {suite: _site(*_wanted(suite)) for suite in VERSIONS}
    quiet = plan.make_plan(CONFIG, jobs, VERSIONS, "https://site", site, "full")
    assert plan.matrix(quiet, jobs) == {"include": []}
    site["bookworm"] = _site(*[d for d in _wanted() if d.get("kver") != "6.12.120+rpt-rpi-2712"])
    new = plan.make_plan(CONFIG, jobs, VERSIONS, "https://site", site, "full")
    assert plan.matrix(new, jobs) == {
        "include": [
            {
                "suite": "bookworm",
                "arch": "arm64",
                "flavour": "rpi-2712",
                "kver": "6.12.120+rpt-rpi-2712",
                "package": f"{P}-modules-6.12.120+rpt-rpi-2712",
                "version": "0.0.post7~deb12",
                "deb": f"{P}-modules-6.12.120+rpt-rpi-2712_0.0.post7~deb12_arm64.deb",
                "fleet": False,
            }
        ]
    }


def test_a_new_driver_version_builds_every_kernel():
    jobs = plan.jobs(CONFIG, INDEXES)
    site = {suite: _site(*_wanted(suite)) for suite in VERSIONS}
    newer = {"bookworm": "0.0.post8~deb12", "trixie": "0.0.post8~deb13"}
    made = plan.make_plan(CONFIG, jobs, newer, "https://site", site, "full")
    assert len(plan.matrix(made, jobs)["include"]) == len(jobs) == 8


def test_a_sample_run_builds_the_sample_whatever_the_site_has():
    jobs = plan.jobs(CONFIG, INDEXES)
    pr = {"bookworm": "0.0.post8~deb12~pr79", "trixie": "0.0.post8~deb13~pr79"}
    made = plan.make_plan(CONFIG, jobs, pr, None, {}, "sample")
    built = plan.matrix(made, jobs)["include"]
    assert [(j["suite"], j["kver"], j["fleet"]) for j in built] == [
        ("bookworm", "6.12.96+rpt-rpi-v8", True),
        ("bookworm", "6.12.109+rpt-rpi-v8", False),
        ("bookworm", "6.12.120+rpt-rpi-2712", False),
        ("trixie", "6.18.50+rpt-rpi-v8", False),
        ("trixie", "6.18.50+rpt-rpi-2712", False),
    ]
    assert {j["version"] for j in built} == set(pr.values())


@pytest.mark.parametrize(
    ("event", "site", "full", "expected"),
    [
        ("pull_request", "https://site", False, "sample"),  # never published
        ("push", None, False, "sample"),  # nothing to publish to, or to reuse from
        ("push", "https://site", False, "full"),
        ("schedule", "https://site", False, "full"),
        ("workflow_dispatch", None, True, "full"),  # asked for by hand
    ],
)
def test_a_run_builds_every_missing_kernel_only_when_it_can_publish_or_is_asked_to(event, site, full, expected):
    assert plan.mode(event, site, full) == expected


def test_a_preview_version_without_its_pull_request_is_the_merged_builds():
    assert plan.main_version("0.0.post8~deb12~pr79") == "0.0.post8~deb12"
    assert plan.main_version("0.0.post8~deb12") == "0.0.post8~deb12"


def test_a_site_index_without_a_checksum_is_refused():
    debs = _wanted()
    with pytest.raises(plan.PlanError, match="SHA256"):
        plan.plan_suite(debs, _site(*debs).replace("SHA256", "MD5sum"))


def _fetcher(files):
    def fetch(url, missing_ok=False):
        if url not in files:
            if missing_ok:
                return None
            raise plan.PlanError(f"{url}: HTTP 404")
        return files[url]

    return fetch


def _assembled(tmp_path, mode, on_site, built, corrupt=None):
    debs = _wanted()
    jobs = plan.jobs(CONFIG, INDEXES)
    site = {"bookworm": _site(*[d for d in debs if d["file"] in on_site]), "trixie": None}
    made = plan.make_plan(CONFIG, jobs, VERSIONS, "https://site", site, mode)
    files = {f"https://site/bookworm/{name}": name.encode() for name in on_site}
    if corrupt:
        files[f"https://site/bookworm/{corrupt}"] = b"other bytes"
    (tmp_path / "built" / "artifact").mkdir(parents=True)
    for name in built:
        (tmp_path / "built" / "artifact" / name).write_bytes(b"built " + name.encode())
    result = plan.assemble(made, "bookworm", tmp_path / "built", tmp_path / "out", fetch=_fetcher(files))
    return result, {p.name: p.read_bytes() for p in (tmp_path / "out").iterdir()}


def test_assembling_takes_the_sites_copy_over_this_runs_rebuild(tmp_path):
    """-common is rebuilt by every run; the bytes that were published are the ones published again."""
    names = [deb["file"] for deb in _wanted()]
    (reused, taken, left), out = _assembled(tmp_path, "full", on_site=names[:2], built=names)
    assert reused == names[:2] and taken == names[2:] and left == []
    assert out[names[0]] == names[0].encode()
    assert out[names[2]] == b"built " + names[2].encode()
    assert sorted(out) == sorted(names)


def test_a_full_run_refuses_an_incomplete_suite(tmp_path):
    """The deploy would drop the missing package from the archive."""
    names = [deb["file"] for deb in _wanted()]
    with pytest.raises(plan.PlanError, match=r"modules-6\.12\.120\+rpt-rpi-2712.*neither on the site nor among"):
        _assembled(tmp_path, "full", on_site=names[:2], built=names[:-1])


def test_a_sample_run_leaves_out_the_kernels_it_did_not_build(tmp_path):
    names = [deb["file"] for deb in _wanted()]
    not_sampled = [n for n in names if "6.12.19+rpt" in n]
    built = [n for n in names if n not in not_sampled]
    (reused, taken, left), out = _assembled(tmp_path, "sample", on_site=[], built=built)
    assert (reused, taken, left) == ([], built, not_sampled)
    assert sorted(out) == sorted(built)


def test_a_sample_run_still_fails_when_something_it_should_have_built_is_missing(tmp_path):
    names = [deb["file"] for deb in _wanted()]
    with pytest.raises(plan.PlanError, match="utils"):
        _assembled(tmp_path, "sample", on_site=[], built=[n for n in names if "utils" not in n])


def test_a_site_file_that_is_not_what_its_index_says_is_refused(tmp_path):
    names = [deb["file"] for deb in _wanted()]
    with pytest.raises(plan.PlanError, match="does not match the site's own Packages"):
        _assembled(tmp_path, "full", on_site=names, built=[], corrupt=names[1])


def test_a_site_without_a_suite_yet_reads_as_nothing_published():
    files = {"https://site/bookworm/Packages": b"Package: x\nVersion: 1\n"}
    assert plan.read_site("https://site", ["bookworm", "trixie"], fetch=_fetcher(files)) == {
        "bookworm": "Package: x\nVersion: 1\n",
        "trixie": None,
    }
    assert plan.read_site(None, ["bookworm"], fetch=_fetcher({})) == {"bookworm": None}


def test_the_plan_command_writes_the_plan_and_the_matrix_for_the_workflow(tmp_path, monkeypatch, capsys):
    for (suite, arch), text in INDEXES.items():
        (tmp_path / f"Packages-{suite}-{arch}").write_text(text)
    kernels = tmp_path / "kernels.toml"
    kernels.write_text(
        'fleet_kernel = "6.12.96+rpt-rpi-v8"\nfleet_suite = "bookworm"\nmin_kernel = "6.12"\n'
        '[suites.bookworm]\narm64 = ["rpi-v8", "rpi-2712"]\n[suites.trixie]\narm64 = ["rpi-v8", "rpi-2712"]\n'
    )
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    versions = {"bookworm": "0.0.post7~deb12~pr79", "trixie": "0.0.post7~deb13~pr79"}
    where = ["--kernels", str(kernels), "--index-dir", str(tmp_path), "--out", str(tmp_path / "plan.json")]
    plan.main(["plan", "--versions", json.dumps(versions), "--event", "pull_request", "--no-site", *where])
    out = dict(line.split("=", 1) for line in output.read_text().splitlines())
    assert out["count"] == "5" and out["mode"] == "sample" and out["site"] == ""
    assert json.loads(out["suites"]) == ["bookworm", "trixie"] and out["suites-list"] == "bookworm trixie"
    assert len(json.loads(out["matrix"])["include"]) == 5
    written = json.loads((tmp_path / "plan.json").read_text())
    assert written["mode"] == "sample" and written["versions"] == versions
    text = capsys.readouterr().out
    assert f"skip  {P}-modules-6.12.19+rpt-rpi-v8_0.0.post7~deb12~pr79_arm64.deb" in text
    assert "dry run: on the default branch, the publishing run of this driver version would" in text
    assert f"build {P}-modules-6.12.19+rpt-rpi-v8_0.0.post7~deb12_arm64.deb" in text
    assert "bookworm: 0 from the site, 10 built by this run, 0 left out" in text


def test_the_plan_wants_a_version_for_exactly_the_suites_of_kernels_toml(tmp_path):
    with pytest.raises(SystemExit, match="trixie"):
        plan.main(["plan", "--versions", '{"bookworm": "0.0.post7~deb12"}', "--event", "push", "--no-site"])


# -- the prebuilt modules package and the meta package (§2, §3.8) ------------------------------------------------

KVER = "6.12.109+rpt-rpi-v8"
DEB12 = "0.0.post7~deb12"


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
    return bd.modules_nfpm(DEB12, suite, kver, arch, built, tree, tmp_path / "stage")


def test_the_modules_package_is_named_for_its_kernel_and_built_for_the_kernels_architecture(tree, built, tmp_path):
    config = _modules(tree, built, tmp_path)
    assert config["name"] == "fpgas-online-acorn-litepcie-modules-6.12.109+rpt-rpi-v8"
    assert config["arch"] == "arm64"
    assert config["section"] == "kernel"
    assert (config["version"], config["version_schema"]) == (DEB12, "none")


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


def test_the_deb_file_name_is_the_debian_one():
    assert (
        bd.deb_name("fpgas-online-acorn-litepcie-modules-6.12.109+rpt-rpi-v8", DEB12, "arm64")
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


def test_an_arm64_modules_package_counts_on_an_armhf_root(tree, built, tmp_path):
    """The fleet's root is armhf and its modules package arm64. apt lets an Architecture: all package (-common)
    satisfy an arm64 package's dependency, and an arm64 package's Provides (-module) satisfy an armhf-root
    package's (the meta package's), only when the one depended on is Multi-Arch: foreign."""
    assert bd.common_nfpm(DEB12)["deb"]["fields"] == {"Multi-Arch": "foreign"}
    assert _modules(tree, built, tmp_path)["deb"]["fields"] == {"Multi-Arch": "foreign"}


def test_the_utils_are_built_for_the_pi_architectures_and_x86():
    assert set(bd.ARCHES) == {"armhf", "arm64", "amd64"}


@pytest.mark.parametrize(
    ("version", "driver"),
    [
        ("0.0.post7~deb12", "0.0.post7"),
        ("0.0.post7~deb13~pr79", "0.0.post7"),
        ("0.1~deb12", "0.1"),
        ("1.2.post3", "1.2.post3"),
    ],
)
def test_the_drivers_own_version_is_the_debs_without_the_suite_and_preview_suffixes(version, driver):
    assert bd.driver_of(version) == driver


@pytest.mark.parametrize("version", ["20261002~deb12", "~deb12", "0.0.post7+bookworm", "v0.0.post7"])
def test_a_version_that_is_not_a_git_describe_one_is_refused(version):
    with pytest.raises(bd.BuildError, match=r"X\.Y"):
        bd.driver_of(version)


def test_dkms_knows_the_driver_by_its_own_version_in_every_suite(tree, tmp_path):
    """The suite is in the deb's version only: the sources, dkms.conf and the DKMS module version are the same."""
    for n, version in enumerate(("0.0.post7~deb12", "0.0.post7~deb13~pr79")):
        config = bd.dkms_nfpm(version, tree, tmp_path / str(n))
        assert config["version"] == version
        src = pathlib.Path(_dst(config)["/usr/src/fpgas-online-acorn-litepcie-0.0.post7"]["src"])
        assert (src / "dkms.conf").read_text() == DKMS_CONF
        postinst = pathlib.Path(config["scripts"]["postinstall"]).read_text()
        assert "/usr/lib/dkms/common.postinst fpgas-online-acorn-litepcie 0.0.post7 " in postinst


def test_the_meta_package_takes_dkms_unless_prebuilt_modules_are_already_installed(tmp_path):
    """apt installs the first alternative it can: -dkms on an ordinary host. A host that already has a
    -modules-<kver> package satisfies the second, and gets no DKMS, compiler or headers."""
    config = bd.meta_nfpm("0.0.post7", tmp_path / "stage")
    assert config["name"] == "fpgas-online-acorn-litepcie"
    assert config["arch"] == "all"
    assert config["version"] == "0.0.post7"
    assert config["depends"] == [
        "fpgas-online-acorn-litepcie-common",
        "fpgas-online-acorn-litepcie-utils",
        "fpgas-online-acorn-litepcie-dkms | fpgas-online-acorn-litepcie-module",
    ]
    (notice,) = config["contents"]
    assert notice["dst"] == "/usr/share/doc/fpgas-online-acorn-litepcie/copyright"
    text = pathlib.Path(notice["src"]).read_text()
    assert text.startswith("fpgas-online-acorn-litepcie\n") and "Apache-2.0" in text


def test_tools_built_in_another_suite_are_refused(tree, bins):
    """Each suite's tools are compiled in that suite's image, against its glibc."""
    with pytest.raises(bd.BuildError, match="bookworm armhf, not trixie armhf"):
        bd.utils_nfpm("0.0.post7~deb13", "trixie", "armhf", bins, tree)


def test_the_command_line_builds_common_and_dkms_once_per_suite(tree, tmp_path, monkeypatch):
    built = []
    monkeypatch.setattr(bd, "run_nfpm", lambda config, out, nfpm: built.append((config["name"], config["version"])))
    versions = {"bookworm": "0.0.post7~deb12", "trixie": "0.0.post7~deb13"}
    bd.main(["--out", str(tmp_path / "out"), "--driver", str(tree), "--only", "common", "--only", "dkms",
             "--versions", json.dumps(versions)])  # fmt: skip
    assert built == [
        ("fpgas-online-acorn-litepcie-common", "0.0.post7~deb12"),
        ("fpgas-online-acorn-litepcie-dkms", "0.0.post7~deb12"),
        ("fpgas-online-acorn-litepcie-common", "0.0.post7~deb13"),
        ("fpgas-online-acorn-litepcie-dkms", "0.0.post7~deb13"),
    ]


def test_the_command_line_wants_the_version_it_is_given_not_one_of_its_own(tmp_path):
    with pytest.raises(SystemExit):
        bd.main(["--out", str(tmp_path), "--only", "common"])
    with pytest.raises(SystemExit, match=r"X\.Y"):
        bd.main(["--out", str(tmp_path), "--only", "common", "--version", "2026.10.02"])


def test_the_driver_commit_can_be_checked_out_for_the_shared_version_action(repo, tmp_path):
    """deb-version versions a checkout: it gets one of the last commit that changed a driver input, not HEAD."""
    _commit(repo, "uv.lock", "1\n", "lock")
    want = _git(repo, "rev-parse", "HEAD")
    _commit(repo, "README.md", "1\n", "docs")
    assert bd.driver_commit(repo) == want
    assert bd.version_tree(tmp_path / "tree", repo) == want
    assert _git(tmp_path / "tree", "rev-parse", "HEAD") == want
    assert _git(tmp_path / "tree", "describe", "--tags", "--long", "--match", "v[0-9]*").startswith("v0.0-1-g")
