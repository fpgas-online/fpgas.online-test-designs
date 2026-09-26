#!/usr/bin/env python3
"""Build the Acorn LitePCIe driver debs: -common, -dkms and -utils.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§2, §3).

The version is `X.Y.postN` from `git describe`, as the repository's other debs, but of the last commit on
main's first-parent line that changed one of the driver's inputs (VERSION_INPUTS), not of HEAD: a merge that
touches nothing the driver is built from gives it no new version.
"""

import pathlib
import re
import subprocess

import tomllib

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
KERNELS = HERE / "kernels.toml"

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
    commit = _git(repo, "log", "-1", "--first-parent", "--format=%H", "--", *VERSION_INPUTS)
    if not commit:
        raise BuildError(f"no commit changes any of {', '.join(VERSION_INPUTS)}")
    try:
        out = _git(repo, "describe", "--tags", "--long", "--match", "v[0-9]*.[0-9]*", commit)
    except BuildError as e:
        raise BuildError(f"git describe found no vX.Y tag (a shallow clone, or no tags fetched?): {e}") from None
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
