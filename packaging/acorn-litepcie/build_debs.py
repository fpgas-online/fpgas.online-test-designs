#!/usr/bin/env python3
"""Build the Acorn LitePCIe driver debs: -common, -dkms and -utils.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§2, §3).

  * fpgas-online-acorn-litepcie-common (all): the modprobe.d blacklist that keeps udev from loading
    litepcie.ko at boot. Loading it is always an operator's decision.
  * fpgas-online-acorn-litepcie-dkms (all): the patched kernel sources and a dkms.conf, for single-architecture
    SD-booted hosts. The netbooted fleet (armhf root, arm64 kernel) cannot use DKMS; it gets prebuilt modules.
  * fpgas-online-acorn-litepcie-utils (armhf, arm64): litepcie_util and litepcie_test, compiled in
    debian:bookworm by container.py.

Takes the tree prepare_driver.py writes (patched, with litepcie's LICENSE).

The version is `X.Y.postN` from `git describe`, as the repository's other debs, but of the last commit on
main's first-parent line that changed one of the driver's inputs (VERSION_INPUTS), not of HEAD: a merge that
touches nothing the driver is built from gives it no new version.
"""

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import tomllib

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
KERNELS = HERE / "kernels.toml"
NAME = "fpgas-online-acorn-litepcie"
COMMON, DKMS, UTILS = f"{NAME}-common", f"{NAME}-dkms", f"{NAME}-utils"
MODULE = f"{NAME}-module"  # virtual: Provided by -dkms and (Part B) every -modules-<kver>
PREBUILT = f"{NAME}-prebuilt"  # virtual: Provided by every -modules-<kver>
TOOLS = ("litepcie_util", "litepcie_test")
ARCHES = ("armhf", "arm64")
MAINTAINER = "fpgas.online <fpgas@fpgas.online>"
HOMEPAGE = "https://github.com/fpgas-online/fpgas.online-test-designs"

# What the driver packages are built from (§3.8). packaging/acorn-pcie/ (the bitstreams pin) is deliberately
# not one: a pin move that changes a CSR the driver reads is caught by csr_check.py instead.
VERSION_INPUTS = (
    "packaging/acorn-litepcie/",
    "designs/acorn-pcie/gateware/acorn_pcie_soc.py",
    "designs/_shared/",
    "uv.lock",
    ".github/workflows/acorn-litepcie.yml",
)


class BuildError(Exception):
    pass


def _git(repo, *args):
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        raise BuildError(f"git {' '.join(args)}: {e.stderr.strip()}") from None


def driver_version(repo=REPO):
    """`X.Y` / `X.Y.postN` for the last first-parent commit that changed a VERSION_INPUTS path."""
    if _git(repo, "rev-parse", "--is-shallow-repository") == "true":
        raise BuildError(f"{repo} is a shallow clone: the version needs the full history (fetch-depth: 0)")
    commit = _git(repo, "log", "-1", "--first-parent", "--format=%H", "--", *VERSION_INPUTS)
    if not commit:
        raise BuildError(f"no commit changes any of {', '.join(VERSION_INPUTS)}")
    try:
        out = _git(repo, "describe", "--tags", "--long", "--match", "v[0-9]*.[0-9]*", commit)
    except BuildError as e:
        raise BuildError(f"git describe found no vX.Y tag (were the tags fetched?): {e}") from None
    m = re.fullmatch(r"v(\d+)\.(\d+)-(\d+)-g[0-9a-f]+", out)
    if not m:
        raise BuildError(f"unexpected git describe output {out!r}")
    major, minor, n = m.groups()
    return f"{major}.{minor}" if n == "0" else f"{major}.{minor}.post{n}"


def kernel_release_key(kver):
    """`6.12.109+rpt-rpi-v8` -> (6, 12, 109): the upstream release, compared as numbers."""
    m = re.match(r"(\d+(?:\.\d+)*)", kver)
    if not m:
        raise BuildError(f"{kver!r} does not start with a kernel release number")
    return tuple(int(x) for x in m.group(1).split("."))


def read_kernels(path=KERNELS):
    kernels = tomllib.loads(pathlib.Path(path).read_text())
    for key in ("fleet_kernel", "fleet_suite", "min_kernel"):
        if not isinstance(kernels.get(key), str):
            raise BuildError(f"{path}: {key} is missing")
    return kernels


# -- the packages ----------------------------------------------------------------------------------------


def dkms_conf(version):
    """kbuild directly, not the upstream Makefile: that one sets ARCH?=$(uname -m), which is aarch64 rather than
    the kernel's arm64, and builds for `uname -r` rather than the kernel DKMS is building for (§3.6)."""
    return (
        f'PACKAGE_NAME="{NAME}"\n'
        f'PACKAGE_VERSION="{version}"\n'
        'MAKE[0]="make -C ${kernel_source_dir} M=${dkms_tree}/${PACKAGE_NAME}/${PACKAGE_VERSION}/build modules"\n'
        'CLEAN="make -C ${kernel_source_dir} M=${dkms_tree}/${PACKAGE_NAME}/${PACKAGE_VERSION}/build clean"\n'
        'BUILT_MODULE_NAME[0]="litepcie"\n'
        'BUILT_MODULE_NAME[1]="liteuart"\n'
        'DEST_MODULE_LOCATION[0]="/updates/dkms"\n'
        'DEST_MODULE_LOCATION[1]="/updates/dkms"\n'
        'AUTOINSTALL="yes"\n'
    )


def _base(name, arch, version, license_, summary, body):
    return {
        "name": name,
        "arch": arch,
        "section": "kernel" if name == DKMS else "misc",
        "platform": "linux",
        "version": version,
        "version_schema": "none",  # nfpm would otherwise rewrite it as semver
        "maintainer": MAINTAINER,
        "homepage": HOMEPAGE,
        "license": license_,
        "description": f"{summary}\n{body}",
    }


def _render(template, out, version):
    text = (HERE / template).read_text().replace("@NAME@", NAME).replace("@VERSION@", version)
    out = pathlib.Path(out)
    out.write_text(text)
    out.chmod(0o755)
    return str(out)


def _license(tree):
    path = pathlib.Path(tree) / "LICENSE"
    if not path.is_file():
        raise BuildError(f"{tree} has no LICENSE: prepare the tree with prepare_driver.py")
    return path


def common_nfpm(version):
    return {
        **_base(
            COMMON,
            "all",
            version,
            "Apache-2.0",
            "fpgas.online Acorn LitePCIe driver: shared configuration",
            "Blacklists litepcie so that udev never loads it at boot for an Acorn running the fpgas.online SoC:\n"
            "loading it resets the SoC and takes BAR0 from fpgas-acorn-verify. `modprobe litepcie` still\n"
            "loads it on purpose.",
        ),
        "contents": [
            {
                "src": str(HERE / "fpgas-online-acorn-litepcie.conf"),
                "dst": "/etc/modprobe.d/fpgas-online-acorn-litepcie.conf",
                "type": "config",
                "file_info": {"mode": 0o644},
            }
        ],
    }


def dkms_nfpm(version, tree, stage):
    """Stage /usr/src/<name>-<version> (the kernel sources and dkms.conf) and the maintainer scripts."""
    stage = pathlib.Path(stage)
    src = stage / f"{NAME}-{version}"
    shutil.copytree(pathlib.Path(tree) / "kernel", src)
    (src / "dkms.conf").write_text(dkms_conf(version))
    src.chmod(0o755)
    for path in src.iterdir():
        if not path.is_file():
            raise BuildError(f"{path}: the kernel tree has a subdirectory, which DKMS would not build")
        path.chmod(0o644)
    notice = stage / "copyright"
    notice.write_text(
        _license(tree).read_text()
        + "\nliteuart.c and litex.h are GPL-2.0 (their SPDX headers): see /usr/share/common-licenses/GPL-2.\n"
    )
    return {
        **_base(
            DKMS,
            "all",
            version,
            "BSD-2-Clause AND GPL-2.0-only",
            "fpgas.online Acorn LitePCIe driver: DKMS source",
            "litepcie.ko and liteuart.ko for the fpgas.online Acorn PCIe SoC, generated from its gateware and\n"
            "built by DKMS for each kernel whose headers are installed. For single-architecture hosts whose\n"
            "root filesystem keeps what DKMS builds; install the headers for your kernel yourself.",
        ),
        "depends": ["dkms", COMMON],
        "provides": [MODULE],
        "conflicts": [PREBUILT],
        "contents": [
            {"src": str(src), "dst": f"/usr/src/{NAME}-{version}", "type": "tree"},
            {"src": str(notice), "dst": f"/usr/share/doc/{DKMS}/copyright", "file_info": {"mode": 0o644}},
        ],
        "scripts": {
            "postinstall": _render("dkms-postinst.in", stage / "postinst", version),
            "preremove": _render("dkms-prerm.in", stage / "prerm", version),
        },
    }


def utils_nfpm(version, arch, bin_dir, tree):
    """The tools container.py built: `bin_dir` holds them and utils.json (their architecture and glibc floor)."""
    bin_dir = pathlib.Path(bin_dir)
    info = json.loads((bin_dir / "utils.json").read_text())
    if info.get("arch") != arch:
        raise BuildError(f"{bin_dir} holds tools built for {info.get('arch')}, not {arch}")
    exe = {"file_info": {"mode": 0o755}}
    return {
        **_base(
            UTILS,
            arch,
            version,
            "BSD-2-Clause",
            "fpgas.online Acorn LitePCIe tools",
            "litepcie_util (info, scratch, DMA and flash commands) and litepcie_test (DMA streaming) for the\n"
            "fpgas.online Acorn PCIe SoC, through /dev/litepcie*. Needs litepcie.ko loaded.",
        ),
        "depends": [f"libc6 (>= {info['glibc']})"],
        "recommends": [MODULE],
        "contents": [
            *({"src": str(bin_dir / tool), "dst": f"/usr/bin/{tool}", **exe} for tool in TOOLS),
            {"src": str(_license(tree)), "dst": f"/usr/share/doc/{UTILS}/copyright", "file_info": {"mode": 0o644}},
        ],
    }


def run_nfpm(config, out_dir, nfpm="nfpm"):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir=out_dir, delete=False) as f:
        json.dump(config, f, indent=2)  # JSON is YAML
        cfg = pathlib.Path(f.name)
    try:
        subprocess.run([nfpm, "package", "--config", str(cfg), "--packager", "deb", "--target", str(out_dir)],
                       check=True)  # fmt: skip
    finally:
        cfg.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--print-version", action="store_true", help="print driver_version() and stop")
    parser.add_argument("--out", type=pathlib.Path, help="where the .deb files go")
    parser.add_argument("--driver", type=pathlib.Path, help="the tree prepare_driver.py wrote")
    parser.add_argument("--only", choices=("common", "dkms", "utils"), action="append")
    parser.add_argument("--arch", choices=ARCHES, help="-utils: the architecture the tools were built for")
    parser.add_argument("--bin-dir", type=pathlib.Path, help="-utils: where container.py put the tools")
    parser.add_argument("--version", help="override the version (default: driver_version())")
    parser.add_argument("--nfpm", default="nfpm", help="the nfpm binary")
    args = parser.parse_args(argv)
    if not args.print_version and not (args.out and args.driver and args.only):
        parser.error("--out, --driver and at least one --only are required")
    try:
        if args.print_version:
            print(driver_version())
            return
        version = args.version or driver_version()
        args.out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=args.out, prefix=".stage-") as stage:
            for which in args.only:
                if which == "common":
                    config = common_nfpm(version)
                elif which == "dkms":
                    config = dkms_nfpm(version, args.driver, stage)
                else:
                    if not (args.arch and args.bin_dir):
                        raise BuildError("-utils needs --arch and --bin-dir")
                    config = utils_nfpm(version, args.arch, args.bin_dir, args.driver)
                run_nfpm(config, args.out, args.nfpm)
    except BuildError as e:
        sys.exit(f"error: {e}")
    print(f"built {', '.join(args.only)} at version {version}")


if __name__ == "__main__":
    main()
