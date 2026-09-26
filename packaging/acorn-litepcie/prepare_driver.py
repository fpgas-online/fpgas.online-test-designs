#!/usr/bin/env python3
"""Generate the LitePCIe driver for the Acorn SoC at this commit, and apply the packaging patches.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§3.1, §3.3-§3.5).

Generation elaborates the cle-215+ SoC and has LitePCIe write its software tree (`kernel/`, `user/`) with
the SoC's `csr.h`, `soc.h` and `mem.h`. No Vivado runs (`--build` is not given), and `--no-compile-software`
keeps LiteX from building the BIOS, which needs a RISC-V toolchain the driver does not use.

Then three one-line patches, each refused once upstream carries its fix, so it is dropped as soon as
`uv.lock` moves to a litepcie that has it:

  * `.compat_ioctl = compat_ptr_ioctl`: armhf tools on an arm64 kernel otherwise get ENOTTY (§3.3);
  * `MODULE_ALIAS("platform:liteuart")`: the stray space upstream stops udev ever loading liteuart (§3.4);
  * `dma_set_mask_and_coherent()`: with only the streaming mask set, the coherent mask stays 32-bit and every
    dmam_alloc_coherent fails with -ENOMEM on a Pi 5, whose RAM sits at bus address 0x10_0000_0000 (§3.5).

    uv run --extra build python packaging/acorn-litepcie/prepare_driver.py --out dist/driver
    uv run --no-project python packaging/acorn-litepcie/prepare_driver.py --out dist/driver --from-dir <tree>
"""

import argparse
import dataclasses
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOC_SCRIPT = REPO / "designs" / "acorn-pcie" / "gateware" / "acorn_pcie_soc.py"
VARIANT = "cle-215+"
BUILD_DIR = REPO / "designs" / "acorn-pcie" / "build" / f"acorn-{VARIANT}"
PYTHON = ("uv", "run", "--extra", "build", "python")


class PatchError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Patch:
    path: str  # relative to the driver tree
    old: str
    new: str
    already: str  # present in the file only once upstream has the fix
    why: str


PATCHES = (
    Patch(
        "kernel/main.c",
        "\t.unlocked_ioctl = litepcie_ioctl,\n",
        "\t.unlocked_ioctl = litepcie_ioctl,\n\t.compat_ioctl = compat_ptr_ioctl,\n",
        "compat_ioctl",
        "32-bit tools on a 64-bit kernel get ENOTTY without a compat_ioctl",
    ),
    Patch(
        "kernel/liteuart.c",
        'MODULE_ALIAS("platform: liteuart");',
        'MODULE_ALIAS("platform:liteuart");',
        'MODULE_ALIAS("platform:liteuart")',
        "the stray space means udev never matches the platform:liteuart modalias",
    ),
    Patch(
        "kernel/main.c",
        "\tret = dma_set_mask(&dev->dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));\n",
        "\tret = dma_set_mask_and_coherent(&dev->dev, DMA_BIT_MASK(DMA_ADDR_WIDTH));\n",
        "dma_set_mask_and_coherent",
        "a 32-bit coherent mask fails every dmam_alloc_coherent on a Pi 5",
    ),
)


def apply_patches(driver_dir, patches=PATCHES):
    """Apply every patch or none: all are checked against the files before any file is written."""
    driver_dir = pathlib.Path(driver_dir)
    texts = {}
    for p in patches:
        path = driver_dir / p.path
        text = texts.get(p.path)
        if text is None:
            text = path.read_text()
        if p.already in text:
            raise PatchError(f"{p.path} already has {p.already!r}: upstream carries this fix, drop the patch")
        count = text.count(p.old)
        if count != 1:
            where = "not found" if count == 0 else f"found {count} times"
            raise PatchError(f"{p.path}: the text to patch ({p.old.strip()!r}) is {where}: litepcie has changed")
        texts[p.path] = text.replace(p.old, p.new)
    for rel, text in texts.items():
        (driver_dir / rel).write_text(text)


def copy_tree(generated, out_dir, license_file):
    """`kernel/` and `user/` of a generated driver tree, without LitePCIe's Python package files, and
    litepcie's LICENSE: BSD-2-Clause, whose binary redistributions must reproduce it."""
    generated, out_dir, license_file = pathlib.Path(generated), pathlib.Path(out_dir), pathlib.Path(license_file)
    if not license_file.is_file():
        raise PatchError(f"litepcie's LICENSE is not at {license_file}")
    if out_dir.exists():
        raise PatchError(f"{out_dir} already exists: refusing to mix a new driver tree into an old one")
    for sub in ("kernel", "user"):
        if not (generated / sub).is_dir():
            raise PatchError(f"{generated} has no {sub}/: not a generated LitePCIe driver tree")
        shutil.copytree(generated / sub, out_dir / sub, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(license_file, out_dir / "LICENSE")
    return out_dir


_FIND_LICENSE = """
import importlib.metadata as m
d = m.distribution("litepcie")
(f,) = [f for f in d.files if f.name == "LICENSE"]
print(d.locate_file(f))
"""


def litepcie_license(python=PYTHON):
    """Where the Python environment that generates the driver has litepcie's LICENSE."""
    out = subprocess.run([*python, "-c", _FIND_LICENSE], check=True, capture_output=True, text=True, cwd=REPO)
    return pathlib.Path(out.stdout.strip())


def generate(out_dir, python=PYTHON, build_dir=BUILD_DIR, license_file=None):
    """Elaborate the SoC, have LitePCIe write its driver tree, and copy that tree to `out_dir`."""
    driver = pathlib.Path(build_dir) / "driver"
    if driver.exists():
        shutil.rmtree(driver)  # a tree from an earlier run must not survive into this one
    argv = [*python, str(SOC_SCRIPT), "--variant", VARIANT, "--driver", "--no-compile-software"]
    subprocess.run(argv, check=True, cwd=REPO)
    return copy_tree(driver, out_dir, license_file or litepcie_license(python))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=pathlib.Path, required=True, help="where the patched tree goes")
    parser.add_argument("--from-dir", type=pathlib.Path, help="an already generated driver tree")
    parser.add_argument("--license", type=pathlib.Path, help="litepcie's LICENSE (default: from the uv environment)")
    args = parser.parse_args(argv)
    try:
        if args.from_dir:
            copy_tree(args.from_dir, args.out, args.license or litepcie_license())
        else:
            generate(args.out, license_file=args.license)
        apply_patches(args.out)
    except PatchError as e:
        sys.exit(f"error: {e}")
    for p in PATCHES:
        print(f"patched {p.path}: {p.new.strip()}  ({p.why})")


if __name__ == "__main__":
    main()
