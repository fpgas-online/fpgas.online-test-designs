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
    out = pd.generate(tmp_path / "out", python=("python3", str(script)), build_dir=build)
    assert argv_file.read_text().split() == [
        str(pd.SOC_SCRIPT),
        "--variant",
        "cle-215+",
        "--driver",
        "--no-compile-software",
    ]
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [
        "kernel/csr.h",
        "kernel/main.c",
        "user/litepcie_util.c",
    ]
