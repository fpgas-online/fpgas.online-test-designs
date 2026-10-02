#!/usr/bin/env python3
"""Decide which prebuilt LitePCIe modules packages a run builds: the job matrix of acorn-litepcie.yml.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§4.2, §4.4).

kernels.toml names the Raspberry Pi kernel flavours per suite and the kernel floor. The Raspberry Pi archive's
`Packages` indexes name the kernels that exist. Together they give one job per (suite, kernel):

  * a kernel is a `linux-headers-<kver>` package of a wanted flavour that has its `linux-image-<kver>` too
    (the modules package depends on it). The unversioned meta packages (`linux-headers-rpi-v8`) are not kernels;
  * the floor is compared with the package's Version, not its name: the 6.1 kernels are all named
    `6.1.0-rpiN`, whatever 6.1.x they are;
  * `--mode sample` (pull requests) keeps the newest kernel of each suite and flavour, and the fleet kernel;
  * `--mode missing` (main, the daily run) keeps every kernel whose package at this driver version is not on
    the series release yet, so a quiet day builds nothing and a new kernel costs one build.

The indexes only choose what to build. The headers themselves are installed by apt, which checks the archive's
signature.

    python3 packaging/acorn-litepcie/plan.py --version 0.0.post42 --mode sample
"""

import argparse
import dataclasses
import gzip
import importlib.util
import json
import os
import pathlib
import re
import sys
import time
import urllib.error
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent


def _sibling(name):
    """Another script of this directory, under a module name nothing else in a test run can collide with."""
    spec = importlib.util.spec_from_file_location(f"acorn_litepcie_{name}", HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_debs = _sibling("build_debs")  # names, versions and kernels.toml
publish = _sibling("publish")  # the series release and its asset names

RPI_ARCHIVE = "https://archive.raspberrypi.com/debian"
RETRIES = 3
RETRY_DELAY_S = 10


class PlanError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Job:
    suite: str
    arch: str
    flavour: str
    kver: str
    release: tuple  # the kernel's upstream release, from the package Version: (6, 12, 109)
    fleet: bool = False

    @property
    def package(self):
        return build_debs.modules_package(self.kver)

    def deb(self, version):
        return build_debs.deb_name(self.package, build_debs.modules_version(version, self.suite), self.arch)

    def asset(self, version):
        """The deb's name on the series release: GitHub stores the `~` of its version as `.`."""
        return publish.release_name(self.deb(version))


def parse_packages(text):
    """A `Packages` index as {package name: [Version, ...]}."""
    packages = {}
    for stanza in text.split("\n\n"):
        fields = dict(re.findall(r"^(Package|Version): (.*)$", stanza, flags=re.M))
        if "Package" in fields and "Version" in fields:
            packages.setdefault(fields["Package"], []).append(fields["Version"])
    return packages


def upstream_release(version):
    """`1:6.1.73-1+rpt1` -> (6, 1, 73): the upstream release of a kernel package Version, as numbers."""
    m = re.fullmatch(r"(?:\d+:)?(\d+(?:\.\d+)+)(?:\D.*)?", version)
    if not m:
        raise PlanError(f"{version!r} is not a kernel package version")
    return tuple(int(x) for x in m.group(1).split("."))


def kernels(packages_text, flavour, min_kernel):
    """[(release, kver)] of `flavour` at or above the floor, oldest first."""
    packages = parse_packages(packages_text)
    floor = build_debs.kernel_release_key(min_kernel)
    found = []
    for name, versions in packages.items():
        m = re.fullmatch(rf"linux-headers-(\d\S*-{re.escape(flavour)})", name)
        if not m or f"linux-image-{m.group(1)}" not in packages:
            continue
        release = max(upstream_release(v) for v in versions)
        if release >= floor:
            found.append((release, m.group(1)))
    return sorted(found)


def jobs(config, indexes):
    """Every (suite, kernel) kernels.toml asks for. `indexes` is {(suite, arch): Packages text}."""
    fleet = (config["fleet_suite"], config["fleet_kernel"])
    if build_debs.kernel_release_key(fleet[1]) < build_debs.kernel_release_key(config["min_kernel"]):
        raise PlanError(f"fleet_kernel {fleet[1]} is below min_kernel {config['min_kernel']}")
    out = []
    for suite, arches in config["suites"].items():
        for arch, flavours in arches.items():
            for flavour in flavours:
                found = kernels(indexes[suite, arch], flavour, config["min_kernel"])
                if not found:
                    raise PlanError(f"the {suite} {arch} index has no {flavour} kernel at or above the floor")
                out.extend(Job(suite, arch, flavour, kver, release, (suite, kver) == fleet) for release, kver in found)
    if not any(job.fleet for job in out):
        raise PlanError(f"fleet_kernel {fleet[1]} ({fleet[0]}) is not one of the kernels kernels.toml builds")
    return out


def sample(all_jobs):
    """The newest kernel of each suite and flavour, and the fleet kernel."""
    newest = {}
    for job in all_jobs:
        key = (job.suite, job.arch, job.flavour)
        if key not in newest or (job.release, job.kver) > (newest[key].release, newest[key].kver):
            newest[key] = job
    return [job for job in all_jobs if job.fleet or newest[job.suite, job.arch, job.flavour] is job]


def missing(all_jobs, version, assets):
    """The jobs whose package at this driver version is not on the series release."""
    return [job for job in all_jobs if job.asset(version) not in assets]


def matrix(selected, version):
    """The GitHub Actions matrix. Never empty-handed: the workflow skips the job when `count` is 0."""
    return {
        "include": [
            {
                "suite": job.suite,
                "arch": job.arch,
                "flavour": job.flavour,
                "kver": job.kver,
                "package": job.package,
                "deb": job.deb(version),
                "asset": job.asset(version),
                "fleet": job.fleet,
            }
            for job in selected
        ]
    }


# -- reading the archive and the release ---------------------------------------------------------------------


def fetch_index(suite, arch):
    url = f"{RPI_ARCHIVE}/dists/{suite}/main/binary-{arch}/Packages.gz"
    for attempt in range(1, RETRIES + 1):
        try:
            with urllib.request.urlopen(url, timeout=120) as r:
                return gzip.decompress(r.read()).decode()
        except (urllib.error.URLError, OSError) as e:
            if attempt == RETRIES:
                raise PlanError(f"{url}: {e}") from None
            print(f"{url}: {e}; retrying", file=sys.stderr)
            time.sleep(RETRY_DELAY_S)


def read_indexes(config, index_dir=None):
    indexes = {}
    for suite, arches in config["suites"].items():
        for arch in arches:
            if index_dir:
                indexes[suite, arch] = (pathlib.Path(index_dir) / f"Packages-{suite}-{arch}").read_text()
            else:
                indexes[suite, arch] = fetch_index(suite, arch)
    return indexes


def report(all_jobs, selected, version, assets, mode):
    lines = [f"driver version {version}, series release {publish.series(version)}: {len(all_jobs)} kernels"]
    groups = {}
    for job in all_jobs:
        groups.setdefault((job.suite, job.arch, job.flavour), []).append(job)
    for (suite, arch, flavour), group in groups.items():
        lines.append(f"  {suite} {arch} {flavour}: {len(group)} kernels, {group[0].kver} ... {group[-1].kver}")
    lines.append("")
    for job in all_jobs:
        state = "published" if job.asset(version) in assets else "missing"
        building = "build" if job in selected else "-"
        fleet = " (fleet kernel)" if job.fleet else ""
        lines.append(f"  {state:9} {building:5} {job.asset(version)}{fleet}")
    todo = missing(all_jobs, version, assets)
    lines.append("")
    lines.append(f"main and the daily run would build {len(todo)} of {len(all_jobs)}")
    lines.append(f"this run ({mode}) builds {len(selected)}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", required=True, help="the driver version (build_debs.py --print-version)")
    parser.add_argument("--mode", choices=("sample", "missing"), required=True)
    parser.add_argument("--kernels", type=pathlib.Path, default=build_debs.KERNELS)
    parser.add_argument("--index-dir", type=pathlib.Path, help="read Packages-<suite>-<arch> here, not the archive")
    parser.add_argument("--assets-file", type=pathlib.Path, help="the release's asset names, one per line")
    args = parser.parse_args(argv)
    try:
        config = build_debs.read_kernels(args.kernels)
        all_jobs = jobs(config, read_indexes(config, args.index_dir))
        if args.assets_file:
            assets = set(args.assets_file.read_text().split())
        else:
            assets = publish.release_assets(publish.series(args.version)) or set()
    except (PlanError, build_debs.BuildError, publish.GhError) as e:
        sys.exit(f"error: {e}")
    selected = sample(all_jobs) if args.mode == "sample" else missing(all_jobs, args.version, assets)
    print(report(all_jobs, selected, args.version, assets, args.mode))
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"matrix={json.dumps(matrix(selected, args.version))}\n")
            f.write(f"count={len(selected)}\n")


if __name__ == "__main__":
    main()
