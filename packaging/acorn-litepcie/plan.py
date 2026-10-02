#!/usr/bin/env python3
"""Plan a run of the LitePCIe packages' workflow, and assemble what it publishes.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§4.2, §4.3).

The packages are published as this repository's own apt archive, one flat suite each, by
mithro/apt-repo-action's publish-apt.yml. A deploy replaces the whole site, and a package the deploy does not
hold is dropped from it. So every publishing run hands over the complete set of every suite: -common, -dkms,
-utils for each architecture, and a -modules-<kver> for every kernel. A published (package, version) must
never change its bytes, so what the live site already has at the wanted version is taken from the site, and
only the rest is built.

    plan      Which kernels exist (kernels.toml and the Raspberry Pi archive's `Packages` indexes), which debs
              each suite wants at this run's versions, which of them the live site already has, and which
              -modules-<kver> packages this run builds. Writes plan.json and the workflow's job matrix. It
              reads the archive and the site, and changes nothing.

              * A kernel is a `linux-headers-<kver>` package of a wanted flavour that has its
                `linux-image-<kver>` too (the modules package depends on it). The unversioned meta packages
                (`linux-headers-rpi-v8`) are not kernels.
              * The floor is compared with the package's Version, not its name: the 6.1 kernels are all named
                `6.1.0-rpiN`, whatever 6.1.x they are.
              * A `sample` run (a pull request, or any run while there is no site to publish to) builds the
                newest kernel of each suite and flavour, and the fleet kernel. A `full` run builds every
                kernel the site lacks: all of them after a driver change, only a new kernel on a quiet day.

    assemble  One suite's directory for publish-apt, from plan.json: each deb the site has is downloaded
              and checked against the size and SHA256 its `Packages` gives; each other one is taken from
              this run's builds. A full run fails unless the set is complete.

The indexes only choose what to build. The headers themselves are installed by apt, which checks the archive's
signature.

    python3 packaging/acorn-litepcie/plan.py plan --event pull_request --out dist/plan.json \\
        --versions '{"bookworm": "0.0.post42~deb12~pr7", "trixie": "0.0.post42~deb13~pr7"}'
    python3 packaging/acorn-litepcie/plan.py assemble --plan dist/plan.json --suite bookworm \\
        --built dist/built --out dist/debs
"""

import argparse
import dataclasses
import gzip
import hashlib
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
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


build_debs = _sibling("build_debs")  # names and kernels.toml

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


# -- which debs, and where each comes from -----------------------------------------------------------------------


def wanted(suite, version, suite_jobs):
    """Every deb the suite's archive holds at `version`: the complete set a publish must hand over."""
    debs = [
        {"package": build_debs.COMMON, "arch": "all"},
        {"package": build_debs.DKMS, "arch": "all"},
        *({"package": build_debs.UTILS, "arch": arch} for arch in build_debs.ARCHES),
        *({"package": job.package, "arch": job.arch, "kver": job.kver} for job in suite_jobs),
    ]
    for deb in debs:
        deb.update(suite=suite, version=version, file=build_debs.deb_name(deb["package"], version, deb["arch"]))
    return debs


def site_index(packages_text):
    """A live suite's `Packages` as {(package, version, architecture): its stanza}."""
    return {(f["Package"], f["Version"], f.get("Architecture")): f for f in stanzas(packages_text)}


def plan_suite(debs, packages_text, selected=()):
    """Mark each wanted deb: `reuse` (the site has exactly it: where, how big, its SHA256) or `build`.

    `packages_text` is the live suite's `Packages`, or None when there is no site or no such suite yet: then
    everything is built. A deb to build carries `selected`: whether this run builds it. A -modules-<kver> one
    is built when `selected` holds its kernel; everything else always is."""
    index = site_index(packages_text) if packages_text else {}
    out = []
    for deb in debs:
        entry = dict(deb)
        stanza = index.get((deb["package"], deb["version"], deb["arch"]))
        if stanza:
            for field in ("Filename", "Size", "SHA256"):
                if not stanza.get(field):
                    raise PlanError(f"the site's Packages has no {field} for {deb['file']}")
            entry.update(action="reuse", filename=stanza["Filename"].removeprefix("./"), size=int(stanza["Size"]),
                         sha256=stanza["SHA256"])  # fmt: skip
        else:
            entry.update(action="build", selected="kver" not in deb or deb["kver"] in selected)
        out.append(entry)
    return out


def mode(event, site, full=False):
    """`full`: build every missing deb, so the set is complete and can be published. `sample`: build the
    sample of kernels only. A pull request never publishes, and without a site there is nothing to publish
    to or reuse from, so neither is worth 42 kernel builds; `full` (a run started by hand) asks for them."""
    if full:
        return "full"
    return "sample" if event == "pull_request" or not site else "full"


def main_version(version):
    """A pull request's preview version without its `~pr<P>`: what the merged build will be."""
    return re.sub(r"~pr\d+$", "", version)


def make_plan(config, all_jobs, versions, site, site_packages, run_mode):
    """The whole plan. `site_packages` is {suite: Packages text or None}."""
    chosen = sample(all_jobs) if run_mode == "sample" else all_jobs
    suites = {}
    for suite in config["suites"]:
        suite_jobs = [job for job in all_jobs if job.suite == suite]
        selected = {job.kver for job in chosen if job.suite == suite}
        suites[suite] = plan_suite(wanted(suite, versions[suite], suite_jobs), site_packages.get(suite), selected)
    return {"mode": run_mode, "site": site, "versions": versions, "suites": suites}


def matrix(plan, all_jobs):
    """The GitHub Actions matrix: the -modules-<kver> packages this run builds."""
    by = {(job.suite, job.kver): job for job in all_jobs}
    include = []
    for suite, debs in plan["suites"].items():
        for deb in debs:
            if "kver" in deb and deb["action"] == "build" and deb["selected"]:
                job = by[suite, deb["kver"]]
                include.append({"suite": suite, "arch": job.arch, "flavour": job.flavour, "kver": job.kver,
                                "package": job.package, "version": deb["version"], "deb": deb["file"],
                                "fleet": job.fleet})  # fmt: skip
    return {"include": include}


def report(plan, all_jobs):
    lines = [f"{len(all_jobs)} kernels:"]
    groups = {}
    for job in all_jobs:
        groups.setdefault((job.suite, job.arch, job.flavour), []).append(job)
    for (suite, arch, flavour), group in groups.items():
        lines.append(f"  {suite} {arch} {flavour}: {len(group)} kernels, {group[0].kver} ... {group[-1].kver}")
    site = plan["site"] or "no site yet: nothing to reuse"
    lines.append(f"\nmode {plan['mode']}; site: {site}")
    for suite, debs in plan["suites"].items():
        counts = {"reuse": 0, "build": 0, "skip": 0}
        lines.append(f"\n{suite} at {plan['versions'][suite]}: {len(debs)} debs")
        for deb in debs:
            what = "reuse" if deb["action"] == "reuse" else "build" if deb["selected"] else "skip"
            counts[what] += 1
            lines.append(f"  {what:5} {deb['file']}")
        lines.append(
            f"  {suite}: {counts['reuse']} from the site, {counts['build']} built by this run, "
            f"{counts['skip']} left out (a sample run)"
        )
    return "\n".join(lines)


# -- reading the archive and the site -----------------------------------------------------------------------------


def fetch(url, missing_ok=False):
    """The bytes at `url`; None for a 404 when `missing_ok`."""
    for attempt in range(1, RETRIES + 1):
        try:
            request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
            with urllib.request.urlopen(request, timeout=120) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404 and missing_ok:
                return None
            error = e
        except (urllib.error.URLError, OSError) as e:
            error = e
        if attempt == RETRIES:
            raise PlanError(f"{url}: {error}")
        print(f"{url}: {error}; retrying", file=sys.stderr)
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


def pages_site(repository):
    """The repository's GitHub Pages URL as GitHub reports it, or None when Pages is not enabled."""
    run = subprocess.run(["gh", "api", f"repos/{repository}/pages", "--jq", ".html_url"],
                         capture_output=True, text=True)  # fmt: skip
    if run.returncode == 0 and run.stdout.strip():
        return run.stdout.strip().rstrip("/")
    if "404" in run.stderr or "Not Found" in run.stderr:
        return None
    raise PlanError(f"gh api repos/{repository}/pages: {run.stderr.strip()}")


def read_site(site, suites, fetch=fetch):
    """{suite: its live `Packages` text, or None when the site does not have the suite}."""
    out = {}
    for suite in suites:
        data = fetch(f"{site}/{suite}/Packages", missing_ok=True) if site else None
        out[suite] = data.decode() if data is not None else None
    return out


# -- assembling a suite ------------------------------------------------------------------------------------------


def assemble(plan, suite, built, out, fetch=fetch):
    """Fill `out` with the suite's debs: reused ones from the site, verified; the others from `built`.

    Returns (names taken from the site, names taken from this run's builds, names left out)."""
    built, out = pathlib.Path(built), pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    have = {p.name: p for p in sorted(built.rglob("*.deb"))}
    reused, taken, left = [], [], []
    for deb in plan["suites"][suite]:
        name = deb["file"]
        if deb["action"] == "reuse":
            data = fetch(f"{plan['site']}/{suite}/{deb['filename']}")
            if len(data) != deb["size"] or hashlib.sha256(data).hexdigest() != deb["sha256"]:
                raise PlanError(f"{suite}/{deb['filename']} on the site does not match the site's own Packages")
            (out / name).write_bytes(data)
            reused.append(name)
        elif name in have:
            shutil.copyfile(have[name], out / name)
            taken.append(name)
        elif plan["mode"] == "sample" and not deb["selected"]:
            left.append(name)
        else:
            raise PlanError(f"{name} is neither on the site nor among this run's builds in {built}")
    return reused, taken, left


# -- the command line ---------------------------------------------------------------------------------------------


def cmd_plan(args):
    config = build_debs.read_kernels(args.kernels)
    versions = json.loads(args.versions)
    if set(versions) != set(config["suites"]):
        raise PlanError(f"--versions names {sorted(versions)}, kernels.toml the suites {sorted(config['suites'])}")
    for version in versions.values():
        build_debs.driver_of(version)
    all_jobs = jobs(config, read_indexes(config, args.index_dir))
    site = None if args.no_site else args.site or pages_site(os.environ["GITHUB_REPOSITORY"])
    site_packages = read_site(site, config["suites"])
    run_mode = mode(args.event, site, args.full)
    plan = make_plan(config, all_jobs, versions, site, site_packages, run_mode)
    print(report(plan, all_jobs))
    merged = {suite: main_version(version) for suite, version in versions.items()}
    if merged != versions or run_mode != "full":
        # The dry run of the publishing run of this driver version.
        would = make_plan(config, all_jobs, merged, site, site_packages, "full")
        print("\n-- dry run: on the default branch, the publishing run of this driver version would --")
        print(report(would, all_jobs))
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(plan, indent=1) + "\n")
    include = matrix(plan, all_jobs)
    if os.environ.get("GITHUB_OUTPUT"):
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"matrix={json.dumps(include)}\n")
            f.write(f"count={len(include['include'])}\n")
            f.write(f"mode={run_mode}\n")
            f.write(f"site={site or ''}\n")
            f.write(f"suites={json.dumps(list(config['suites']))}\n")
            f.write(f"suites-list={' '.join(config['suites'])}\n")


def cmd_assemble(args):
    plan = json.loads(args.plan.read_text())
    reused, taken, left = assemble(plan, args.suite, args.built, args.out)
    for what, names in (("from the site", reused), ("built by this run", taken), ("left out (a sample run)", left)):
        print(f"{args.suite}: {len(names)} {what}")
        for name in names:
            print(f"  {name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--versions", required=True, help='{"<suite>": "<version>"} as JSON, from the deb-version action')
    p.add_argument("--event", required=True, help="the workflow's event name (pull_request, push, ...)")
    p.add_argument("--full", action="store_true", help="build every missing deb, whatever the event")
    p.add_argument("--kernels", type=pathlib.Path, default=build_debs.KERNELS)
    p.add_argument("--index-dir", type=pathlib.Path, help="read Packages-<suite>-<arch> here, not the archive")
    p.add_argument("--site", help="the live site (default: this repository's GitHub Pages URL, from the API)")
    p.add_argument("--no-site", action="store_true", help="plan as if nothing were published")
    p.add_argument("--out", type=pathlib.Path, help="write plan.json here")
    p = sub.add_parser("assemble")
    p.add_argument("--plan", type=pathlib.Path, required=True)
    p.add_argument("--suite", required=True)
    p.add_argument("--built", type=pathlib.Path, required=True, help="this run's built debs, in any subdirectory")
    p.add_argument("--out", type=pathlib.Path, required=True)
    args = parser.parse_args(argv)
    try:
        {"plan": cmd_plan, "assemble": cmd_assemble}[args.command](args)
    except (PlanError, build_debs.BuildError, json.JSONDecodeError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
