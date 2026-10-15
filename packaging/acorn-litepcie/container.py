#!/usr/bin/env python3
"""The LitePCIe builds and tests that run inside Debian containers.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§3.6, §3.9, §4.1, §4.4).

Each subcommand runs inside a container of the architecture and suite it is for, started by `run`, which
mounts this repository at /w and bootstraps python3 (stdlib only: bookworm's 3.11). Paths are relative to the
repository.

    utils                 compile the struct-layout asserts, then litepcie_util and litepcie_test, and record
                          what they were built for and the glibc floor they need (utils.json), for
                          build_debs.py to package
    install-test          install the -common and -utils debs and run litepcie_util
    module                build litepcie.ko and liteuart.ko against one kernel's headers from the Raspberry Pi
                          archive (default: the fleet kernel of kernels.toml), check their vermagic, and
                          record what they were built for (modules.json), for build_debs.py to package
    modules-install-test  in the fleet's shape, an armhf root with an arm64 kernel: install a
                          -modules-<kver> deb and -utils through apt from a flat repository of the given
                          debs, and check modinfo finds the modules for that kernel; then install the meta
                          package, which must take those modules and not DKMS
    meta-install-test     on a host with nothing installed: install the meta package through apt from a
                          flat repository of the given debs; it must choose DKMS, not a modules package
    dkms-test             install a kernel and its headers (the newest rpi-v8 on arm64, Debian's on amd64)
                          and the -common and -dkms debs, have DKMS build the modules, and check modinfo
                          finds them

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
QEMU = {"linux/arm64": "arm64", "linux/arm/v7": "arm", "linux/amd64": "amd64"}  # tonistiigi/binfmt's names
# It runs --privileged in the jobs whose debs are published, so by digest, never by tag: `latest` on 2026-10-04
# (docker buildx imagetools inspect tonistiigi/binfmt:latest).
BINFMT = "tonistiigi/binfmt@sha256:400a4873b838d1b89194d982c45e5fb3cda4593fbfd7e08a02e76b03b21166f0"
# The committed archive key (RPI_KEY below) is what every headers package is trusted by: its sha256.
RPI_KEY_SHA256 = "3a29901549ae65a910de13a32551e6eea7f45ba1fd70f0cb67e5c70d98488071"
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
# The DKMS test's kernel per architecture: (the image's and the headers' meta packages, flavour, from the
# Raspberry Pi archive?). The image is installed as on a host that boots it: DKMS runs depmod only for a
# kernel whose own modules are installed, and not every headers package depends on its image.
DKMS_KERNELS = {
    "arm64": (("linux-image-rpi-v8", "linux-headers-rpi-v8"), "rpi-v8", True),
    "amd64": (("linux-image-amd64", "linux-headers-amd64"), "amd64", False),
}


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


def driver_version(deb_version):
    """`0.0.post7~deb12~pr3` -> `0.0.post7`: the version DKMS knows the driver by."""
    return deb_version.split("~")[0]


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


def loadable(kver, modprobe_c, show_depends, modules_dep):
    """Why `modprobe litepcie` would not load the packaged module for `kver`, or None.

    From `modprobe -c`, `modprobe --show-depends -S <kver> litepcie` and the kernel's modules.dep."""
    if "blacklist litepcie" not in modprobe_c.splitlines():
        return "modprobe -c does not show `blacklist litepcie`"
    wanted = f"/modules/{kver}/updates/fpgas-online/litepcie.ko"
    if not any(line.startswith("insmod ") and line.split()[1].endswith(wanted) for line in show_depends.splitlines()):
        return f"modprobe --show-depends -S {kver} litepcie does not insmod the packaged module:\n{show_depends}"
    listed = {line.split(":")[0] for line in modules_dep.splitlines()}
    missing = [m for m in MODULES if f"updates/fpgas-online/{m}.ko" not in listed]
    if missing:
        return f"depmod has not listed {', '.join(missing)} in /lib/modules/{kver}/modules.dep"
    return None


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


def probe_argv(platform, suite, docker=("docker",)):
    """Run `true` in the image a build for `platform` uses: does this host execute that architecture?"""
    return [*docker, "run", "--rm", "--pull=always", "--platform", platform, f"debian:{suite}", "true"]


def binfmt_argv(platform, docker=("docker",)):
    """Register QEMU user emulation for `platform` with the kernel, as mithro/apt-repo-action's build-deb does."""
    return [*docker, "run", "--privileged", "--rm", BINFMT, "--install", QEMU[platform]]


# -- in the container ----------------------------------------------------------------------------------------


def sh(*argv, **kw):
    print("+", shlex.join(str(a) for a in argv), flush=True)
    return subprocess.run([str(a) for a in argv], check=True, **kw)


def out(*argv, **kw):
    """The command's stdout. One that fails is a ContainerError carrying what it printed: its stderr was
    captured, so nothing else would show it."""
    argv = [str(a) for a in argv]
    run = subprocess.run(argv, check=False, capture_output=True, text=True, **kw)
    if run.returncode != 0:
        said = (run.stderr + run.stdout).strip() or "it printed nothing"
        raise ContainerError(f"{shlex.join(argv)} exited {run.returncode}: {said}")
    return run.stdout


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
    expect_suite(args.suite)
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
    info = {"suite": args.suite, "arch": args.arch, "glibc": max(floors, key=_release)}
    (dest / "utils.json").write_text(json.dumps(info) + "\n")
    give_back(dest, driver)
    print(f"built {', '.join(TOOLS)} for {args.suite} {args.arch}, needing glibc {info['glibc']}")


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


def flat_repository(debs):
    """Offer `debs` to apt as a local flat repository, as the published archive offers them: apt chooses."""
    apt_install("apt-utils")
    repo = fresh(FLAT_REPO)
    for deb in debs:
        shutil.copy2(deb, repo)
    (repo / "Packages").write_text(out("apt-ftparchive", "packages", ".", cwd=repo))
    pathlib.Path("/etc/apt/sources.list.d/fpgas-online-acorn-litepcie.list").write_text(
        f"deb [trusted=yes] file:{FLAT_REPO} ./\n"
    )
    sh("apt-get", "update", "-qq")


def installed(name):
    """`<architecture> <version>` of an installed package, or None."""
    run = subprocess.run(
        ["dpkg-query", "-W", "-f", "${db:Status-Status} ${Architecture} ${Version}", name],
        stdout=subprocess.PIPE,
        text=True,
    )  # its stderr (why it is not there) goes to the log
    status, _, rest = run.stdout.partition(" ")
    return rest.strip() if run.returncode == 0 and status == "installed" else None


def cmd_install_test(args):
    expect_arch(args.arch)
    expect_suite(args.suite)
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
    # binutils by name: trixie's headers depend on gcc-14-for-host, which brings aarch64-linux-gnu-as but not
    # the plain `as` its gcc runs.
    apt_install("make", "kmod", "binutils", f"linux-headers-{kver}")
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
    flat_repository(args.debs)
    # Only the modules and the tools are named: apt has to find -common (Architecture: all, for an arm64
    # package on an armhf root) and the kernel image (arm64) from the modules package's Depends by itself.
    apt_install(f"{package}:{arch}", f"{NAME}-utils")
    want = {package: arch, f"linux-image-{kver}": arch, f"{NAME}-common": "all", f"{NAME}-utils": "armhf"}
    for name, architecture in want.items():
        got = installed(name)
        print(f"installed: {name} {got}")
        if not got or got.split()[0] != architecture:
            raise ContainerError(f"{name} is installed as {got}, not as {architecture}")
    for module in MODULES:
        path = out("modinfo", "-k", kver, "-F", "filename", module).strip()
        vermagic = out("modinfo", "-k", kver, "-F", "vermagic", module).strip()
        if not path.endswith(f"/modules/{kver}/updates/fpgas-online/{module}.ko") or not vermagic_ok(vermagic, kver):
            raise ContainerError(f"{module}: modinfo -k {kver} gives {path} with vermagic {vermagic!r}")
        print(f"{module}: {path} ({vermagic})")
    aliases = out("modinfo", "-k", kver, "-F", "alias", "liteuart").split()
    if "platform:liteuart" not in aliases:
        raise ContainerError(f"liteuart.ko has aliases {aliases}: litepcie's platform device would not load it")
    # What a host does is `modprobe litepcie`. The blacklist must be in force, and must stop only the
    # autoload by alias: asked for by name, the module still resolves to an insmod of the packaged file.
    problem = loadable(
        kver,
        out("modprobe", "-c"),
        out("modprobe", "--show-depends", "-S", kver, "litepcie"),
        pathlib.Path(f"/lib/modules/{kver}/modules.dep").read_text(),
    )
    if problem:
        raise ContainerError(problem)
    print(f"modprobe -S {kver} litepcie would load it, and `blacklist litepcie` only stops the autoload")
    check_tools(f"{package} and {NAME}-utils")
    # The meta package's driver dependency is `-dkms | -module`: the modules package already installed
    # provides -module, so apt must leave DKMS (and the compiler and headers it would bring) alone.
    apt_install(NAME)
    print(f"installed: {NAME} {installed(NAME)}")
    for name in (NAME, package):
        if not installed(name):
            raise ContainerError(f"{name} is not installed after installing {NAME}")
    for name in (f"{NAME}-dkms", "dkms"):
        if installed(name):
            raise ContainerError(f"installing {NAME} pulled in {name} although {package} is installed")
    sh("apt-get", "remove", "-y", "-qq", NAME, f"{package}:{arch}")
    gone = subprocess.run(["modinfo", "-k", kver, "litepcie"], capture_output=True, text=True)
    if gone.returncode == 0:
        raise ContainerError(f"modinfo -k {kver} still finds litepcie after removing {package}:\n{gone.stdout}")
    print(
        f"apt installed {package}:{arch} with its kernel on an armhf {args.suite} root; {NAME} kept to it "
        "without DKMS; and it was removed again"
    )


def cmd_meta_install_test(args):
    """An ordinary host with nothing of ours installed: the meta package's first alternative, DKMS, is taken,
    although the repository also offers the modules packages that provide the second."""
    expect_arch(args.arch)
    expect_suite(args.suite)
    flat_repository(args.debs)
    offered = out("apt-cache", "showpkg", f"{NAME}-module")
    print(f"apt-cache showpkg {NAME}-module:\n{offered}")
    apt_install(NAME)
    for name in (NAME, f"{NAME}-common", f"{NAME}-utils", f"{NAME}-dkms", "dkms"):
        got = installed(name)
        print(f"installed: {name} {got}")
        if not got:
            raise ContainerError(f"{name} is not installed after installing {NAME}")
    packages = out("dpkg-query", "-W", "-f", "${Package} ${db:Status-Status}\\n").splitlines()
    modules = [line for line in packages if line.startswith(f"{NAME}-modules-") and line.endswith(" installed")]
    if modules:
        raise ContainerError(f"installing {NAME} on a plain host took prebuilt modules, not DKMS: {modules}")
    check_tools(NAME)
    print(f"apt installed {NAME} on a plain {args.arch} {args.suite} host: it chose {NAME}-dkms")


def cmd_dkms_test(args):
    kernel, flavour, rpi = DKMS_KERNELS[args.arch]
    expect_arch(args.arch)
    expect_suite(args.suite)
    if rpi:
        add_rpi_archive(args.suite)
    apt_install("dkms", *kernel)
    installed = out("dpkg-query", "-W", "-f", "${Package}\\n", "linux-headers-*").split()
    kver = newest_kernel(installed, flavour)
    apt_install(*(f"./{d}" for d in args.debs))
    # DKMS knows the driver by its own version: the deb's, without the suite and preview suffixes.
    version = driver_version(out("dpkg-query", "-W", "-f", "${Version}", f"{NAME}-dkms").strip())
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


def ensure_runnable(platform, suite, docker):
    """Make sure this host can run `platform` containers, by QEMU if not by itself.

    AArch32 is optional on a 64-bit ARM CPU: most of GitHub's arm64 runners run armhf containers natively,
    and some answer `exec format error`. So it is tried, and only a host that cannot gets QEMU."""
    probe = probe_argv(platform, suite, docker)
    if subprocess.run(probe, check=False).returncode == 0:
        return
    print(f"this host does not run {platform} containers by itself: registering QEMU for them", flush=True)
    subprocess.run(binfmt_argv(platform, docker), check=True)
    subprocess.run(probe, check=True)


def cmd_run(args):
    inner = args.inner[1:] if args.inner[:1] == ["--"] else args.inner
    try:
        ensure_runnable(PLATFORMS[args.arch], args.suite, tuple(shlex.split(args.docker)))
    except subprocess.CalledProcessError as e:
        print(f"error: this host cannot run {args.arch} containers, even with QEMU: {e}", file=sys.stderr)
        return 1
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
    p.add_argument("--suite", choices=SUITES, required=True)
    p.add_argument("--driver", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("install-test")
    p.add_argument("--arch", choices=sorted(PLATFORMS), required=True)
    p.add_argument("--suite", choices=SUITES, required=True)
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
    p.add_argument("debs", nargs="+", help="-common, -dkms, -utils (armhf), -modules-<kver> and the meta package")
    p = sub.add_parser("meta-install-test")
    p.add_argument("--suite", choices=SUITES, required=True)
    p.add_argument("--arch", choices=sorted(PLATFORMS), required=True)
    p.add_argument("debs", nargs="+", help="the suite's debs and the meta package")
    p = sub.add_parser("dkms-test")
    p.add_argument("--arch", choices=sorted(DKMS_KERNELS), default="arm64")
    p.add_argument("--suite", choices=SUITES, required=True)
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
            "meta-install-test": cmd_meta_install_test,
            "dkms-test": cmd_dkms_test,
        }[args.command](args)
    except (ContainerError, subprocess.CalledProcessError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
