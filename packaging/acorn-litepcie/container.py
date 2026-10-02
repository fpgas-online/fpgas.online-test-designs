#!/usr/bin/env python3
"""The LitePCIe builds and tests that run inside Debian containers.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§3.6, §3.9, §4.1, §4.4).

Each subcommand runs inside a container of the architecture and suite it is for, started by `run`, which
mounts this repository at /w and bootstraps python3 (stdlib only: bookworm's 3.11). Paths are relative to the
repository.

    utils                 compile the struct-layout asserts, then litepcie_util and litepcie_test, and record
                          the glibc floor they need (utils.json), for build_debs.py to package
    install-test          install the -common and -utils debs and run litepcie_util
    module                build litepcie.ko and liteuart.ko against one kernel's headers from the Raspberry Pi
                          archive (default: the fleet kernel of kernels.toml), check their vermagic, and
                          record what they were built for (modules.json), for build_debs.py to package
    modules-install-test  in the fleet's shape, an armhf root with an arm64 kernel: install a
                          -modules-<kver> deb and -utils through apt from a flat repository of the given
                          debs, and check modinfo finds the modules for that kernel
    dkms-test             install kernel headers (the newest rpi-v8 on arm64, Debian's on amd64) and the
                          -common and -dkms debs, have DKMS build the modules, and check modinfo finds them

    python3 packaging/acorn-litepcie/container.py run --arch armhf -- \
        utils --arch armhf --driver dist/driver --out dist/utils-armhf
    python3 packaging/acorn-litepcie/container.py run --arch arm64 --suite trixie --docker "sudo -n docker" -- \
        module --suite trixie --kver 6.18.50+rpt-rpi-v8 --driver dist/driver --out dist/modules
"""

import argparse
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys

import tomllib

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
IN_CONTAINER = "packaging/acorn-litepcie/container.py"
PLATFORMS = {"arm64": "linux/arm64", "armhf": "linux/arm/v7", "amd64": "linux/amd64"}
SUITES = ("bookworm", "trixie")  # the Debian images
RPI_ARCHIVE = "https://archive.raspberrypi.com/debian"
# The archive's signing key, CF8A1AF502A2AA2D763BAE7E82B129927FA3303E, as raspberrypi-archive-keyring
# 2025.1+rpt1 ships it. The copy at <archive>/raspberrypi.gpg.key still carries a SHA-1 self-signature, which
# trixie's apt (sqv) refuses.
RPI_KEY = HERE / "raspberrypi-archive-keyring.gpg"
RPI_KEYRING = "/usr/share/keyrings/raspberrypi-archive-keyring.gpg"
NAME = "fpgas-online-acorn-litepcie"
TOOLS = ("litepcie_util", "litepcie_test")
MODULES = ("litepcie", "liteuart")
BLACKLIST = "/etc/modprobe.d/fpgas-online-acorn-litepcie.conf"
FLAT_REPO = "/srv/fpgas-online-acorn-litepcie"
# The DKMS test's kernel per architecture: (headers meta package, flavour, from the Raspberry Pi archive?).
DKMS_KERNELS = {"arm64": ("linux-headers-rpi-v8", "rpi-v8", True), "amd64": ("linux-headers-amd64", "amd64", False)}


class ContainerError(Exception):
    pass


# -- pure helpers (unit-tested on the host) ----------------------------------------------------------------


def _release(text):
    return tuple(int(x) for x in text.split("."))


def max_glibc(objdump_t):
    """The highest GLIBC_x.y symbol version in `objdump -T` output: the libc6 the binary needs."""
    versions = set(re.findall(r"\bGLIBC_(\d+(?:\.\d+)+)\b", objdump_t))
    if not versions:
        raise ContainerError("no GLIBC_ symbol versions: not a dynamically linked glibc binary")
    return max(versions, key=_release)


def vermagic_ok(vermagic, kver):
    return vermagic.startswith(f"{kver} ")


def newest_kernel(header_packages, flavour):
    """The newest `linux-headers-<kver>` for `flavour` among installed package names, as its <kver>."""
    kvers = []
    for name in header_packages:
        m = re.fullmatch(rf"linux-headers-((\d+(?:\.\d+)+)\S*-{re.escape(flavour)})", name)
        if m:
            kvers.append((_release(m.group(2)), m.group(1)))
    if not kvers:
        raise ContainerError(f"no linux-headers-<kver>-{flavour} package is installed")
    return max(kvers)[1]


def docker_argv(platform, args, docker=("docker",), suite="bookworm"):
    """Run this script's `args` in debian:<suite> for `platform`, with the repository at /w."""
    boot = (
        "apt-get update -qq && apt-get install -y -qq --no-install-recommends python3 >/dev/null; "
        f"exec python3 {IN_CONTAINER} {shlex.join(args)}"
    )
    return [
        *docker, "run", "--rm", "--pull=always", "--platform", platform, "--network", "host",
        "-e", "DEBIAN_FRONTEND=noninteractive", "-v", f"{REPO}:/w", "-w", "/w", f"debian:{suite}",
        "sh", "-ec", boot,
    ]  # fmt: skip


# -- in the container ----------------------------------------------------------------------------------------


def sh(*argv, **kw):
    print("+", shlex.join(str(a) for a in argv), flush=True)
    return subprocess.run([str(a) for a in argv], check=True, **kw)


def out(*argv, **kw):
    return subprocess.run([str(a) for a in argv], check=True, capture_output=True, text=True, **kw).stdout


def apt_install(*packages):
    sh("apt-get", "install", "-y", "-qq", "--no-install-recommends", *packages)


def expect_arch(arch):
    """The container really is `arch`: docker reuses a local image of another platform without a word."""
    got = out("dpkg", "--print-architecture").strip()
    if got != arch:
        raise ContainerError(f"this container is {got}, not {arch}")


def expect_suite(suite):
    """The container really is `suite`: a module is only right for the suite whose compiler built it."""
    got = dict(
        line.split("=", 1) for line in pathlib.Path("/etc/os-release").read_text().splitlines() if "=" in line
    ).get("VERSION_CODENAME")
    if got != suite:
        raise ContainerError(f"this container is {got}, not {suite}")


def add_rpi_archive(suite):
    apt_install("ca-certificates")
    shutil.copyfile(RPI_KEY, RPI_KEYRING)
    pathlib.Path("/etc/apt/sources.list.d/raspberrypi.list").write_text(
        f"deb [signed-by={RPI_KEYRING}] {RPI_ARCHIVE} {suite} main\n"
    )
    sh("apt-get", "update", "-qq")


def give_back(path, like):
    """Files written as root in the container go back to whoever owns the checkout."""
    st = pathlib.Path(like).stat()
    for p in [path, *pathlib.Path(path).rglob("*")]:
        os.chown(p, st.st_uid, st.st_gid)


def fresh(path):
    path = pathlib.Path(path)
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    return path


def cmd_utils(args):
    expect_arch(args.arch)
    apt_install("gcc", "make", "libc6-dev", "binutils")
    driver = pathlib.Path(args.driver)
    sh("gcc", "-fsyntax-only", "-Wall", "-Werror", f"-I{driver / 'kernel'}", HERE / "struct_layout.c")
    dest = fresh(args.out)
    work = dest / ".build"
    shutil.copytree(driver, work)
    sh("make", "-C", work / "user", "CC=gcc", *TOOLS)
    floors = []
    for tool in TOOLS:
        shutil.copy2(work / "user" / tool, dest / tool)
        sh("strip", dest / tool)
        floors.append(max_glibc(out("objdump", "-T", dest / tool)))
    shutil.rmtree(work)
    info = {"arch": args.arch, "glibc": max(floors, key=_release)}
    (dest / "utils.json").write_text(json.dumps(info) + "\n")
    give_back(dest, driver)
    print(f"built {', '.join(TOOLS)} for {args.arch}, needing glibc {info['glibc']}")


def check_tools(what):
    """litepcie_util and litepcie_test are installed and run, and the blacklist is in place."""
    for tool in TOOLS:
        if not shutil.which(tool):
            raise ContainerError(f"{tool} is not on PATH after installing {what}")
    run = subprocess.run(["litepcie_util"], capture_output=True, text=True)
    if "usage: litepcie_util" not in run.stdout + run.stderr:
        raise ContainerError(f"litepcie_util did not print its usage:\n{run.stdout}{run.stderr}")
    if "blacklist litepcie" not in pathlib.Path(BLACKLIST).read_text().splitlines():
        raise ContainerError(f"{BLACKLIST} does not blacklist litepcie")


def cmd_install_test(args):
    expect_arch(args.arch)
    debs = [f"./{d}" for d in args.debs]
    apt_install(*debs)
    check_tools(", ".join(args.debs))
    print(f"installed {', '.join(args.debs)}: litepcie_util runs and litepcie is blacklisted")


def cmd_module(args):
    kernels = tomllib.loads((HERE / "kernels.toml").read_text())
    kver = args.kver or kernels["fleet_kernel"]
    suite = args.suite or kernels["fleet_suite"]
    expect_arch(args.arch)
    expect_suite(suite)
    add_rpi_archive(suite)
    apt_install("make", "kmod", f"linux-headers-{kver}")
    dest = fresh(args.out)
    work = dest / ".build"
    shutil.copytree(pathlib.Path(args.driver) / "kernel", work)
    sh("make", "-C", f"/usr/src/linux-headers-{kver}", f"M={work.resolve()}", "modules")
    info = {"kver": kver, "suite": suite, "arch": args.arch, "vermagic": {}}
    for module in MODULES:
        vermagic = out("modinfo", "-F", "vermagic", work / f"{module}.ko").strip()
        if not vermagic_ok(vermagic, kver):
            raise ContainerError(f"{module}.ko has vermagic {vermagic!r}, not one for {kver}")
        print(f"{module}.ko vermagic: {vermagic}")
        info["vermagic"][module] = vermagic
        shutil.copy2(work / f"{module}.ko", dest / f"{module}.ko")
    shutil.rmtree(work)
    (dest / "kernel.txt").write_text(kver + "\n")
    (dest / "modules.json").write_text(json.dumps(info) + "\n")
    # litepcie's BSD-2-Clause notice travels with the binaries; liteuart.c is GPL-2.0 (its SPDX header).
    shutil.copyfile(pathlib.Path(args.driver) / "LICENSE", dest / "LICENSE")
    give_back(dest, args.driver)
    print(f"built {', '.join(MODULES)} for {kver} ({suite}, {args.arch})")


def cmd_modules_install_test(args):
    """The netbooted fleet's shape (§4.4): an armhf root whose kernel, and so whose modules package, is arm64."""
    kver, arch = args.kver, args.arch
    package = f"{NAME}-modules-{kver}"
    expect_arch("armhf")
    expect_suite(args.suite)
    if arch != "armhf":
        sh("dpkg", "--add-architecture", arch)
    add_rpi_archive(args.suite)
    apt_install("apt-utils")
    repo = fresh(FLAT_REPO)
    for deb in args.debs:
        shutil.copy2(deb, repo)
    (repo / "Packages").write_text(out("apt-ftparchive", "packages", ".", cwd=repo))
    pathlib.Path("/etc/apt/sources.list.d/fpgas-online-acorn-litepcie.list").write_text(
        f"deb [trusted=yes] file:{FLAT_REPO} ./\n"
    )
    sh("apt-get", "update", "-qq")
    # Only the modules and the tools are named: apt has to find -common (Architecture: all, for an arm64
    # package on an armhf root) and the kernel image (arm64) from the modules package's Depends by itself.
    apt_install(f"{package}:{arch}", f"{NAME}-utils")
    installed = {}
    for name in (package, f"linux-image-{kver}", f"{NAME}-common", f"{NAME}-utils"):
        installed[name] = out("dpkg-query", "-W", "-f", "${Architecture} ${Version}", name).strip()
        print(f"installed: {name} {installed[name]}")
    want = {package: arch, f"linux-image-{kver}": arch, f"{NAME}-common": "all", f"{NAME}-utils": "armhf"}
    for name, architecture in want.items():
        if installed[name].split()[0] != architecture:
            raise ContainerError(f"{name} is installed as {installed[name]}, not as {architecture}")
    for module in MODULES:
        path = out("modinfo", "-k", kver, "-F", "filename", module).strip()
        vermagic = out("modinfo", "-k", kver, "-F", "vermagic", module).strip()
        if not path.endswith(f"/modules/{kver}/updates/fpgas-online/{module}.ko") or not vermagic_ok(vermagic, kver):
            raise ContainerError(f"{module}: modinfo -k {kver} gives {path} with vermagic {vermagic!r}")
        print(f"{module}: {path} ({vermagic})")
    aliases = out("modinfo", "-k", kver, "-F", "alias", "liteuart").split()
    if "platform:liteuart" not in aliases:
        raise ContainerError(f"liteuart.ko has aliases {aliases}: litepcie's platform device would not load it")
    check_tools(f"{package} and {NAME}-utils")
    sh("apt-get", "remove", "-y", "-qq", f"{package}:{arch}")
    gone = subprocess.run(["modinfo", "-k", kver, "litepcie"], capture_output=True, text=True)
    if gone.returncode == 0:
        raise ContainerError(f"modinfo -k {kver} still finds litepcie after removing {package}:\n{gone.stdout}")
    print(f"apt installed {package}:{arch} with its kernel on an armhf {args.suite} root, and removed it")


def cmd_dkms_test(args):
    meta, flavour, rpi = DKMS_KERNELS[args.arch]
    expect_arch(args.arch)
    if rpi:
        add_rpi_archive("bookworm")
    apt_install("dkms", meta)
    installed = out("dpkg-query", "-W", "-f", "${Package}\\n", "linux-headers-*").split()
    kver = newest_kernel(installed, flavour)
    apt_install(*(f"./{d}" for d in args.debs))
    version = out("dpkg-query", "-W", "-f", "${Version}", f"{NAME}-dkms").strip()
    # The package's postinst (common.postinst) must have built and installed the modules by itself: no
    # `dkms install` here, or a postinst that silently builds nothing would still pass.
    status = out("dkms", "status", "-m", NAME, "-v", version, "-k", kver)
    print(f"dkms status after install: {status.strip()}")
    if "installed" not in status:
        raise ContainerError(f"installing {NAME}-dkms did not build and install it for {kver}: {status!r}")
    for module in MODULES:
        path = out("modinfo", "-k", kver, "-F", "filename", module).strip()
        vermagic = out("modinfo", "-k", kver, "-F", "vermagic", module).strip()
        if "/updates/dkms/" not in path or not vermagic_ok(vermagic, kver):
            raise ContainerError(f"{module}: modinfo -k {kver} gives {path} with vermagic {vermagic!r}")
        print(f"{module}: {path} ({vermagic})")
    if "blacklist litepcie" not in out("modprobe", "-c").splitlines():
        raise ContainerError("modprobe -c does not show `blacklist litepcie`")
    sh("apt-get", "purge", "-y", "-qq", f"{NAME}-dkms")
    if pathlib.Path(f"/var/lib/dkms/{NAME}").exists():
        raise ContainerError(f"purging {NAME}-dkms left /var/lib/dkms/{NAME} behind")
    print(f"DKMS built, installed and removed {NAME} {version} for {kver}")


# -- on the host ---------------------------------------------------------------------------------------------


def cmd_run(args):
    inner = args.inner[1:] if args.inner[:1] == ["--"] else args.inner
    argv = docker_argv(PLATFORMS[args.arch], inner, docker=tuple(shlex.split(args.docker)), suite=args.suite)
    print("+", shlex.join(argv), flush=True)
    return subprocess.run(argv, check=False).returncode


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="on the host: run a subcommand in debian:<suite> for --arch")
    run.add_argument("--arch", choices=sorted(PLATFORMS), required=True)
    run.add_argument("--suite", choices=SUITES, default="bookworm")
    run.add_argument("--docker", default="docker", help='the docker command, e.g. "sudo -n docker"')
    run.add_argument("inner", nargs=argparse.REMAINDER)
    p = sub.add_parser("utils")
    p.add_argument("--arch", choices=sorted(PLATFORMS), required=True)
    p.add_argument("--driver", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("install-test")
    p.add_argument("--arch", choices=sorted(PLATFORMS), required=True)
    p.add_argument("debs", nargs="+")
    p = sub.add_parser("module")
    p.add_argument("--driver", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--kver", help="default: fleet_kernel from kernels.toml")
    p.add_argument("--suite", choices=SUITES, help="default: fleet_suite from kernels.toml")
    p.add_argument("--arch", choices=("arm64", "armhf"), default="arm64", help="the kernel's architecture")
    p = sub.add_parser("modules-install-test")
    p.add_argument("--suite", choices=SUITES, required=True)
    p.add_argument("--kver", required=True)
    p.add_argument("--arch", choices=("arm64", "armhf"), default="arm64", help="the kernel's architecture")
    p.add_argument("debs", nargs="+", help="the -common, -utils (armhf) and -modules-<kver> debs")
    p = sub.add_parser("dkms-test")
    p.add_argument("--arch", choices=sorted(DKMS_KERNELS), default="arm64")
    p.add_argument("debs", nargs="+", help="the -common and -dkms debs")
    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    try:
        {
            "utils": cmd_utils,
            "install-test": cmd_install_test,
            "module": cmd_module,
            "modules-install-test": cmd_modules_install_test,
            "dkms-test": cmd_dkms_test,
        }[args.command](args)
    except (ContainerError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
