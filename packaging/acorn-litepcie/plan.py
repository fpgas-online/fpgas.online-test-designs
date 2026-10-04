#!/usr/bin/env python3
"""Plan a run of the LitePCIe packages' workflow: which debs it wants, and which -modules-<kver> it builds.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§4.2, §4.3).

The packages are published as assets of this repository's releases (packaging/release.py), where
fpgas-online/apt collects them. A published file is never replaced, so a deb whose asset name any release
already carries is not built again: a run on main builds the -modules-<kver> packages no release has yet.

It works out which kernels exist (kernels.toml and the Raspberry Pi archive's `Packages` indexes), which debs
each suite wants at this run's versions, which of them a release already carries, and which -modules-<kver>
packages this run builds. It prints the plan and writes the workflow's job matrix. It reads the archive and
the list of release assets, and changes nothing.

  * A kernel is a `linux-headers-<kver>` package of a wanted flavour that has its `linux-image-<kver>` too
    (the modules package depends on it). The unversioned meta packages (`linux-headers-rpi-v8`) are not
    kernels.
  * The floor is compared with the package's Version, not its name: the 6.1 kernels are all named
    `6.1.0-rpiN`, whatever 6.1.x they are.
  * A deb is published when a release carries an asset of its name as GitHub stores it (release.py's
    `stored_name`: the `~` of a version is stored as a dot).
  * A `sample` run (a pull request) builds the newest kernel of each suite and flavour, and the fleet kernel,
    whatever is published. An `unpublished` run (a push to main, the daily run, a run started by hand)
    builds every kernel no release has a package for: all of them after a driver change, only a new kernel
    on a quiet day, none when nothing is new. A `full` run (started by hand with the `full` input) builds
    every kernel.
  * -common, -dkms and -utils are built and tested by every run: they are cheap, and the modules packages'
    install tests need them. release.py uploads none of them a second time.

The indexes only choose what to build. The headers themselves are installed by apt, which checks the archive's
signature.

    python3 packaging/acorn-litepcie/plan.py --event pull_request \\
        --versions '{"bookworm": "0.0.post42~deb12~pr7", "trixie": "0.0.post42~deb13~pr7"}'
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


def _script(path):
    """Another script of this repository, under a module name nothing else in a test run can collide with."""
    spec = importlib.util.spec_from_file_location(f"acorn_litepcie_{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


build_debs = _script(HERE / "build_debs.py")  # names and kernels.toml
release = _script(HERE.parent / "release.py")  # what is published, and under which names

RPI_ARCHIVE = "https://archive.raspberrypi.com/debian"
RETRIES = 3
RETRY_DELAY_S = 10


class PlanError(Exception):
    pass


@dataclasses.dataclass(frozen=True)
class Job:
    """One kernel that gets a -modules-<kver> package."""

    suite: str
    arch: str
    flavour: str
    kver: str
    release: tuple  # the kernel's upstream release, from the package Version: (6, 12, 109)
    fleet: bool = False

    @property
    def package(self):
        return build_debs.modules_package(self.kver)


# -- which kernels ---------------------------------------------------------------------------------------------


def stanzas(text):
    """The stanzas of a `Packages` index, each as {field: value} of its single-line fields."""
    out = []
    for block in text.split("\n\n"):
        fields = dict(re.findall(r"^([A-Za-z0-9-]+): (.*)$", block, flags=re.M))
        if "Package" in fields and "Version" in fields:
            out.append(fields)
    return out


def upstream_release(version):
    """`1:6.1.73-1+rpt1` -> (6, 1, 73): the upstream release of a kernel package Version, as numbers."""
    m = re.fullmatch(r"(?:\d+:)?(\d+(?:\.\d+)+)(?:\D.*)?", version)
    if not m:
        raise PlanError(f"{version!r} is not a kernel package version")
    return tuple(int(x) for x in m.group(1).split("."))


def kernels(packages_text, flavour, min_kernel):
    """[(release, kver)] of `flavour` at or above the floor, oldest first."""
    packages = {}
    for fields in stanzas(packages_text):
        packages.setdefault(fields["Package"], []).append(fields["Version"])
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


# -- which debs, and which of them this run builds ---------------------------------------------------------------


def wanted(suite, version, suite_jobs):
    """Every deb of the suite at `version`: -common, -dkms, -utils per architecture, a -modules per kernel.

    `asset` is the name a release stores the file under, which is the name `published` is asked about."""
    debs = [
        {"package": build_debs.COMMON, "arch": "all"},
        {"package": build_debs.DKMS, "arch": "all"},
        *({"package": build_debs.UTILS, "arch": arch} for arch in build_debs.ARCHES),
        *({"package": job.package, "arch": job.arch, "kver": job.kver} for job in suite_jobs),
    ]
    for deb in debs:
        name = build_debs.deb_name(deb["package"], version, deb["arch"])
        deb.update(suite=suite, version=version, file=name, asset=release.stored_name(name))
    return debs


def mode(event, full=False):
    """`sample`: a pull request publishes nothing, so the sample of kernels is enough to exercise the build.
    `unpublished`: every kernel no release has a package for. `full`: every kernel, asked for by hand."""
    if full:
        return "full"
    return "sample" if event == "pull_request" else "unpublished"


def plan_suite(debs, published, run_mode, sampled=()):
    """Mark each wanted deb: `published` (a release already carries it) and `build` (this run builds it).

    `published` is the set of asset names on every release. A -modules-<kver> deb is built when the mode asks
    for its kernel (`sampled` holds a sample run's kernels); everything else always is."""
    out = []
    for deb in debs:
        have = deb["asset"] in published
        if "kver" not in deb or run_mode == "full":
            build = True
        elif run_mode == "sample":
            build = deb["kver"] in sampled
        else:
            build = not have
        out.append({**deb, "published": have, "build": build})
    return out


def main_version(version):
    """A pull request's preview version without its `~pr<P>`: what the merged build will be."""
    return re.sub(r"~pr\d+$", "", version)


def make_plan(config, all_jobs, versions, published, run_mode):
    """The whole plan. `published` is the set of asset names on every release of the repository."""
    if run_mode not in ("sample", "unpublished", "full"):
        raise PlanError(f"{run_mode!r} is not a mode")
    chosen = sample(all_jobs) if run_mode == "sample" else ()
    suites = {}
    for suite in config["suites"]:
        suite_jobs = [job for job in all_jobs if job.suite == suite]
        sampled = {job.kver for job in chosen if job.suite == suite}
        suites[suite] = plan_suite(wanted(suite, versions[suite], suite_jobs), published, run_mode, sampled)
    return {"mode": run_mode, "versions": versions, "suites": suites}


def matrix(plan, all_jobs):
    """The GitHub Actions matrix: the -modules-<kver> packages this run builds."""
    by = {(job.suite, job.kver): job for job in all_jobs}
    include = []
    for suite, debs in plan["suites"].items():
        for deb in debs:
            if "kver" in deb and deb["build"]:
                job = by[suite, deb["kver"]]
                include.append({"suite": suite, "arch": job.arch, "flavour": job.flavour, "kver": job.kver,
                                "package": job.package, "version": deb["version"], "deb": deb["file"],
                                "fleet": job.fleet})  # fmt: skip
    return {"include": include}


# What a run does with a deb, by (build, published).
WHAT = {(True, False): "build", (True, True): "rebuild", (False, True): "have", (False, False): "skip"}


def report(plan, all_jobs):
    lines = [f"{len(all_jobs)} kernels:"]
    groups = {}
    for job in all_jobs:
        groups.setdefault((job.suite, job.arch, job.flavour), []).append(job)
    for (suite, arch, flavour), group in groups.items():
        lines.append(f"  {suite} {arch} {flavour}: {len(group)} kernels, {group[0].kver} ... {group[-1].kver}")
    lines.append(f"\nmode {plan['mode']}")
    for suite, debs in plan["suites"].items():
        counts = dict.fromkeys(WHAT.values(), 0)
        lines.append(f"\n{suite} at {plan['versions'][suite]}: {len(debs)} debs")
        for deb in debs:
            what = WHAT[deb["build"], deb["published"]]
            counts[what] += 1
            lines.append(f"  {what:7} {deb['file']}")
        lines.append(
            f"  {suite}: {counts['build']} built and new to the releases, {counts['rebuild']} built for the "
            f"tests but already published, {counts['have']} already published and not built, "
            f"{counts['skip']} left out (a sample run)"
        )
    return "\n".join(lines)


# -- reading the archive and the releases -----------------------------------------------------------------------------


def fetch(url):
    for attempt in range(1, RETRIES + 1):
        try:
            request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=120) as r:
                return r.read()
        except (urllib.error.URLError, OSError) as e:
            if attempt == RETRIES:
                raise PlanError(f"{url}: {e}") from e
            print(f"{url}: {e}; retrying", file=sys.stderr)
            time.sleep(RETRY_DELAY_S)


def read_indexes(config, index_dir=None):
    indexes = {}
    for suite, arches in config["suites"].items():
        for arch in arches:
            if index_dir:
                indexes[suite, arch] = (pathlib.Path(index_dir) / f"Packages-{suite}-{arch}").read_text()
            else:
                url = f"{RPI_ARCHIVE}/dists/{suite}/main/binary-{arch}/Packages.gz"
                indexes[suite, arch] = gzip.decompress(fetch(url)).decode()
    return indexes


def read_published(path=None):
    """The asset names on every release of this repository; from the file `path`, one name a line, if given."""
    if path:
        return set(pathlib.Path(path).read_text().split())
    return release.published()


# -- the command line ---------------------------------------------------------------------------------------------


def plan(args):
    config = build_debs.read_kernels(args.kernels)
    versions = json.loads(args.versions)
    if set(versions) != set(config["suites"]):
        raise PlanError(f"--versions names {sorted(versions)}, kernels.toml the suites {sorted(config['suites'])}")
    for version in versions.values():
        build_debs.driver_of(version)
    all_jobs = jobs(config, read_indexes(config, args.index_dir))
    published = read_published(args.published)
    run_mode = mode(args.event, args.full)
    made = make_plan(config, all_jobs, versions, published, run_mode)
    print(report(made, all_jobs))
    merged = {suite: main_version(version) for suite, version in versions.items()}
    if merged != versions or run_mode != "unpublished":
        # The dry run of the publishing run of this driver version.
        would = make_plan(config, all_jobs, merged, published, "unpublished")
        print("\n-- dry run: on the default branch, the publishing run of this driver version would --")
        print(report(would, all_jobs))
    include = matrix(made, all_jobs)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"matrix={json.dumps(include)}\n")
            f.write(f"count={len(include['include'])}\n")
            f.write(f"mode={run_mode}\n")
            f.write(f"suites={json.dumps(list(config['suites']))}\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--versions", required=True, help='{"<suite>": "<version>"} as JSON, from the deb-version action')
    p.add_argument("--event", required=True, help="the workflow's event name (pull_request, push, ...)")
    p.add_argument("--full", action="store_true", help="build every kernel's modules, whatever the event")
    p.add_argument("--kernels", type=pathlib.Path, default=build_debs.KERNELS)
    p.add_argument("--index-dir", type=pathlib.Path, help="read Packages-<suite>-<arch> here, not the archive")
    p.add_argument("--published", type=pathlib.Path, help="read the published asset names here, not from GitHub")
    try:
        plan(p.parse_args(argv))
    except (PlanError, build_debs.BuildError, release.ReleaseError, json.JSONDecodeError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
