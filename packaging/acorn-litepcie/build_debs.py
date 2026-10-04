#!/usr/bin/env python3
"""Build the Acorn LitePCIe driver debs: -common, -dkms, -utils, -modules-<kver> and the meta package.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§2, §3, §4).

  * fpgas-online-acorn-litepcie-common (all): the modprobe.d blacklist that keeps udev from loading
    litepcie.ko at boot. Loading it is always an operator's decision.
  * fpgas-online-acorn-litepcie-dkms (all): the patched kernel sources and a dkms.conf, for single-architecture
    hosts. The netbooted fleet (armhf root, arm64 kernel) cannot use DKMS; it gets prebuilt modules.
  * fpgas-online-acorn-litepcie-utils (armhf, arm64, amd64): litepcie_util and litepcie_test, compiled in each
    suite's Debian image by container.py.
  * fpgas-online-acorn-litepcie-modules-<kver> (the kernel's architecture): litepcie.ko and liteuart.ko
    built by container.py against one Raspberry Pi kernel's headers, for the hosts DKMS cannot serve.
  * fpgas-online-acorn-litepcie (all): depends on the others, a driver by DKMS unless prebuilt modules are
    already installed.

Takes the tree prepare_driver.py writes (patched, with litepcie's LICENSE).

Every package is built once per suite, at that suite's version: `X.Y.postN~deb<R>`, and `~pr<P>` after it
on a pull request (mithro/apt-repo-action, docs/packaging.md). CI gets it from the shared deb-version action
and passes it in. That action versions a checkout, so CI gives it one of the driver commit (--version-tree):
the last commit on main's first-parent line that changed one of the driver's inputs (VERSION_INPUTS), not
HEAD. A merge that touches nothing the driver is built from gives it no new version.
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
META, COMMON, DKMS, UTILS = NAME, f"{NAME}-common", f"{NAME}-dkms", f"{NAME}-utils"
MODULE = f"{NAME}-module"  # virtual: Provided by -dkms and every -modules-<kver>
PREBUILT = f"{NAME}-prebuilt"  # virtual: Provided by every -modules-<kver>
TOOLS = ("litepcie_util", "litepcie_test")
MODULES = ("litepcie", "liteuart")
ARCHES = ("armhf", "arm64", "amd64")  # -utils
KERNEL_ARCHES = ("arm64", "armhf")  # -modules-<kver>: the Raspberry Pi archive's
SUITES = ("bookworm", "trixie")  # the suites the Raspberry Pi archive has kernels for
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


def driver_commit(repo=REPO):
    """The last first-parent commit that changed a VERSION_INPUTS path: the commit the packages are versioned by."""
    if _git(repo, "rev-parse", "--is-shallow-repository") == "true":
        raise BuildError(f"{repo} is a shallow clone: the version needs the full history (fetch-depth: 0)")
    commit = _git(repo, "log", "-1", "--first-parent", "--format=%H", "--", *VERSION_INPUTS)
    if not commit:
        raise BuildError(f"no commit changes any of {', '.join(VERSION_INPUTS)}")
    return commit


def version_tree(path, repo=REPO):
    """Check the driver commit out at `path` (a detached worktree), for the shared deb-version action to version."""
    commit = driver_commit(repo)
    _git(repo, "worktree", "add", "--detach", str(path), commit)
    return commit


def driver_version(repo=REPO):
    """`X.Y` / `X.Y.postN` of the driver commit: what the shared deb-version action puts before `~deb<R>`."""
    commit = driver_commit(repo)
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
    suites = kernels.get("suites")
    if not isinstance(suites, dict) or not suites:
        raise BuildError(f"{path}: no [suites.<suite>] table says which kernel flavours to build")
    for suite, arches in suites.items():
        if suite not in SUITES:
            raise BuildError(f"{path}: {suite} is not one of the suites the builds run in ({', '.join(SUITES)})")
        for arch, flavours in arches.items():
            if arch not in KERNEL_ARCHES:
                raise BuildError(f"{path}: {suite} lists flavours for {arch}, which no build exists for")
            if not (isinstance(flavours, list) and flavours and all(isinstance(f, str) for f in flavours)):
                raise BuildError(f"{path}: {suite} {arch} is not a list of flavours")
    return kernels


def modules_package(kver):
    return f"{NAME}-modules-{kver}"


def driver_of(version):
    """`0.0.post7~deb12~pr3` -> `0.0.post7`: the driver's own version, without the suite and preview suffixes."""
    driver = version.split("~")[0]
    if not re.fullmatch(r"\d+\.\d+(\.post\d+)?", driver):
        raise BuildError(f"{version!r} does not start with an X.Y or X.Y.postN version")
    return driver


def deb_name(package, version, arch):
    """The file name nfpm gives a deb."""
    return f"{package}_{version}_{arch}.deb"


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
        "section": "kernel" if name == DKMS or name.startswith(f"{NAME}-modules-") else "misc",
        "platform": "linux",
        "version": version,
        "version_schema": "none",  # nfpm would otherwise rewrite it as semver
        "maintainer": MAINTAINER,
        "homepage": HOMEPAGE,
        "license": license_,
        "description": f"{summary}\n{body}",
    }


def _render(template, out, **fields):
    """Fill a maintainer script template's @FIELD@s."""
    text = (HERE / template).read_text()
    for field, value in fields.items():
        text = text.replace(f"@{field.upper()}@", value)
    out = pathlib.Path(out)
    out.write_text(text)
    out.chmod(0o755)
    return str(out)


def _license(tree):
    path = pathlib.Path(tree) / "LICENSE"
    if not path.is_file():
        raise BuildError(f"{tree} has no LICENSE: prepare the tree with prepare_driver.py")
    return path


def _driver_notice(tree, stage):
    """litepcie's BSD-2-Clause notice, and a pointer to the GPL for the files that are under it."""
    notice = pathlib.Path(stage) / "copyright"
    notice.write_text(
        _license(tree).read_text()
        + "\nliteuart.c and litex.h are GPL-2.0 (their SPDX headers): see /usr/share/common-licenses/GPL-2.\n"
    )
    return notice


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
        # A modules package of a foreign architecture (arm64 on the fleet's armhf root) depends on this one.
        "deb": {"fields": {"Multi-Arch": "foreign"}},
        "contents": [
            {
                "src": str(HERE / "fpgas-online-acorn-litepcie.conf"),
                "dst": "/etc/modprobe.d/fpgas-online-acorn-litepcie.conf",
                "type": "config",
                "file_info": {"mode": 0o644},
            },
            {
                "src": str(HERE / "copyright.common"),
                "dst": f"/usr/share/doc/{COMMON}/copyright",
                "file_info": {"mode": 0o644},
            },
        ],
    }


def dkms_nfpm(version, tree, stage):
    """Stage /usr/src/<name>-<driver version> (the kernel sources and dkms.conf) and the maintainer scripts.

    DKMS knows the module by the driver's own version, which is the same in every suite: only the deb's
    version carries the suite."""
    stage = pathlib.Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    version, deb_version = driver_of(version), version
    src = stage / f"{NAME}-{version}"
    shutil.copytree(pathlib.Path(tree) / "kernel", src)
    (src / "dkms.conf").write_text(dkms_conf(version))
    src.chmod(0o755)
    for path in src.iterdir():
        if not path.is_file():
            raise BuildError(f"{path}: the kernel tree has a subdirectory, which DKMS would not build")
        path.chmod(0o644)
    notice = _driver_notice(tree, stage)
    return {
        **_base(
            DKMS,
            "all",
            deb_version,
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
            "postinstall": _render("dkms-postinst.in", stage / "postinst", name=NAME, version=version),
            "preremove": _render("dkms-prerm.in", stage / "prerm", name=NAME, version=version),
        },
    }


def modules_root(suite):
    """Where the suite's kernels keep their modules: Raspberry Pi's trixie kernels ship /usr/lib/modules
    (merged /usr), bookworm's /lib/modules. A package must use the same path as the kernel's own, or dpkg
    sees two directories where there is one (DEP17)."""
    return "/usr/lib/modules" if suite == "trixie" else "/lib/modules"


def modules_nfpm(version, suite, kver, arch, module_dir, tree, stage):
    """The modules container.py built: `module_dir` holds them and modules.json (what they were built for)."""
    module_dir, stage = pathlib.Path(module_dir), pathlib.Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    info = json.loads((module_dir / "modules.json").read_text())
    want = {"kver": kver, "suite": suite, "arch": arch}
    got = {key: info.get(key) for key in want}
    if got != want:
        raise BuildError(
            f"{module_dir} holds modules built for {got['kver']} ({got['suite']}, {got['arch']}), "
            f"not {kver} ({suite}, {arch})"
        )
    package = modules_package(kver)
    return {
        **_base(
            package,
            arch,
            version,
            "BSD-2-Clause AND GPL-2.0-only",
            f"fpgas.online Acorn LitePCIe driver: modules for Linux {kver}",
            "litepcie.ko and liteuart.ko for the fpgas.online Acorn PCIe SoC, built for this one kernel. For\n"
            "hosts DKMS cannot serve: a root filesystem of another architecture than its kernel, or one that\n"
            "does not keep what DKMS builds.",
        ),
        "depends": [COMMON, f"linux-image-{kver}"],
        "provides": [MODULE, PREBUILT],
        # On the fleet this package is arm64 and the root armhf. Foreign, its Provides satisfy the meta
        # package's (an armhf-root package's) dependency on a driver; without it they would only count for
        # arm64 packages.
        "deb": {"fields": {"Multi-Arch": "foreign"}},
        "contents": [
            *(
                {
                    "src": str(module_dir / f"{module}.ko"),
                    "dst": f"{modules_root(suite)}/{kver}/updates/fpgas-online/{module}.ko",
                    "file_info": {"mode": 0o644},
                }
                for module in MODULES
            ),
            {
                "src": str(_driver_notice(tree, stage)),
                "dst": f"/usr/share/doc/{package}/copyright",
                "file_info": {"mode": 0o644},
            },
        ],
        "scripts": {
            "postinstall": _render("modules-postinst.in", stage / "postinst", package=package, kver=kver),
            "postremove": _render("modules-postrm.in", stage / "postrm", package=package, kver=kver),
        },
    }


def utils_nfpm(version, suite, arch, bin_dir, tree):
    """The tools container.py built: `bin_dir` holds them and utils.json (what for, and their glibc floor)."""
    bin_dir = pathlib.Path(bin_dir)
    info = json.loads((bin_dir / "utils.json").read_text())
    if (info.get("suite"), info.get("arch")) != (suite, arch):
        raise BuildError(f"{bin_dir} holds tools built for {info.get('suite')} {info.get('arch')}, not {suite} {arch}")
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
        # Not Recommends: apt would install the sole provider, -dkms, into the fleet's armhf root (see §2).
        "suggests": [MODULE],
        "contents": [
            *({"src": str(bin_dir / tool), "dst": f"/usr/bin/{tool}", **exe} for tool in TOOLS),
            {"src": str(_license(tree)), "dst": f"/usr/share/doc/{UTILS}/copyright", "file_info": {"mode": 0o644}},
        ],
    }


def meta_nfpm(version, stage):
    """The package a host asks for. `-dkms` is the first alternative on purpose: apt picks it on an ordinary
    host, while a host that already has a -modules-<kver> package (which provides -module) keeps that and
    gets no DKMS, compiler or headers."""
    stage = pathlib.Path(stage)
    stage.mkdir(parents=True, exist_ok=True)
    notice = stage / "copyright"
    notice.write_text((HERE / "copyright.common").read_text().replace(COMMON, META, 1))
    return {
        **_base(
            META,
            "all",
            version,
            "Apache-2.0",
            "fpgas.online Acorn LitePCIe driver and tools",
            "Installs the LitePCIe driver for the fpgas.online Acorn PCIe SoC and its tools: the modules\n"
            "prebuilt for this host's kernel when their package is already installed, built by DKMS otherwise.",
        ),
        "depends": [COMMON, UTILS, f"{DKMS} | {MODULE}"],
        "contents": [{"src": str(notice), "dst": f"/usr/share/doc/{META}/copyright", "file_info": {"mode": 0o644}}],
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
    parser.add_argument("--version-tree", type=pathlib.Path, help="check the driver commit out there and stop")
    parser.add_argument("--out", type=pathlib.Path, help="where the .deb files go")
    parser.add_argument("--driver", type=pathlib.Path, help="the tree prepare_driver.py wrote")
    parser.add_argument("--only", choices=("common", "dkms", "utils", "modules", "meta"), action="append")
    parser.add_argument("--version", help="the deb's version, from the shared deb-version action")
    parser.add_argument("--versions", help='-common, -dkms: {"<suite>": "<version>"} as JSON, one deb each')
    parser.add_argument("--suite", help="-utils, -modules: the suite they were built in")
    parser.add_argument("--arch", choices=ARCHES, help="-utils, -modules: the architecture they were built for")
    parser.add_argument("--bin-dir", type=pathlib.Path, help="-utils: where container.py put the tools")
    parser.add_argument("--kver", help="-modules: the kernel the modules were built for")
    parser.add_argument("--module-dir", type=pathlib.Path, help="-modules: where container.py put the modules")
    parser.add_argument("--nfpm", default="nfpm", help="the nfpm binary")
    args = parser.parse_args(argv)
    try:
        if args.print_version:
            print(driver_version())
            return
        if args.version_tree:
            print(f"the driver commit {version_tree(args.version_tree)} is checked out at {args.version_tree}")
            return
        if not (args.out and args.only and (args.version or args.versions)):
            parser.error("--out, at least one --only, and --version or --versions are required")
        versions = list(json.loads(args.versions).values()) if args.versions else [args.version]
        if len(versions) > 1 and set(args.only) - {"common", "dkms"}:
            raise BuildError("--versions is for -common and -dkms, which are the same in every suite")
        if set(args.only) - {"common", "meta"} and not args.driver:
            raise BuildError("--driver is required for everything but -common and the meta package")
        args.out.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=args.out, prefix=".stage-") as tmp:
            for n, version in enumerate(versions):
                driver_of(version)  # refuse anything that is not X.Y[.postN][~...]
                for which in args.only:
                    stage = pathlib.Path(tmp) / f"{n}-{which}"
                    if which == "common":
                        config = common_nfpm(version)
                    elif which == "meta":
                        config = meta_nfpm(version, stage)
                    elif which == "dkms":
                        config = dkms_nfpm(version, args.driver, stage)
                    elif which == "modules":
                        if not (args.arch and args.suite and args.kver and args.module_dir):
                            raise BuildError("-modules needs --arch, --suite, --kver and --module-dir")
                        config = modules_nfpm(
                            version, args.suite, args.kver, args.arch, args.module_dir, args.driver, stage
                        )
                    else:
                        if not (args.arch and args.suite and args.bin_dir):
                            raise BuildError("-utils needs --arch, --suite and --bin-dir")
                        config = utils_nfpm(version, args.suite, args.arch, args.bin_dir, args.driver)
                    run_nfpm(config, args.out, args.nfpm)
    except (BuildError, json.JSONDecodeError) as e:
        sys.exit(f"error: {e}")
    print(f"built {', '.join(args.only)} at {', '.join(versions)}")


if __name__ == "__main__":
    main()
