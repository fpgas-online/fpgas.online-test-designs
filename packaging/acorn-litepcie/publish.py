#!/usr/bin/env python3
"""Publish the LitePCIe driver debs to this repository's rolling series release, which fpgas-online/apt pulls.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§3.6).

  * The series is the driver version's own `vX.Y`, not HEAD's nearest tag: the version comes from the last
    commit that changed the driver's inputs, which can predate a newer tag.
  * Only files the release does not have yet are uploaded. A published version is never replaced: a rebuild's
    bytes differ (build times), and an apt repository that already pulled it must not see the same name and
    version change under it.
  * Another run of the same driver version may upload a file first; that is not a failure.

    GH_TOKEN=... python3 packaging/acorn-litepcie/publish.py --version 0.0.post42 dist/*.deb
"""

import argparse
import pathlib
import re
import subprocess
import sys


class GhError(Exception):
    pass


def gh(*args):
    run = subprocess.run(["gh", *args], capture_output=True, text=True)
    if run.returncode:
        raise GhError(f"gh {' '.join(args[:2])}: {run.stderr.strip()}")
    return run.stdout


def series(version):
    m = re.match(r"(\d+)\.(\d+)(?:\.post\d+)?$", version)
    if not m:
        raise ValueError(f"{version!r} is not an X.Y or X.Y.postN version")
    return f"v{m.group(1)}.{m.group(2)}"


def to_upload(debs, published):
    return [d for d in debs if pathlib.Path(d).name not in published]


def _assets(tag, gh):
    return set(gh("release", "view", tag, "--json", "assets", "--jq", ".assets[].name").split())


def publish(debs, version, gh=gh):
    tag = series(version)
    try:
        published = _assets(tag, gh)
    except GhError as e:
        if "not found" not in str(e):
            raise
        gh("release", "create", tag, "--prerelease", "--title", f"Debian packages (rolling, series {tag})",
           "--notes", f"Rolling .deb builds from this repository for series {tag}, one per green commit on main. "
           "Consumed by https://github.com/fpgas-online/apt.")  # fmt: skip
        published = set()
    for deb in debs:
        if pathlib.Path(deb).name in published:
            print(f"already published: {pathlib.Path(deb).name}")
    for deb in to_upload(debs, published):
        name = pathlib.Path(deb).name
        try:
            gh("release", "upload", tag, str(deb))
            print(f"uploaded {name} to {tag}")
        except GhError:
            if name not in _assets(tag, gh):
                raise
            print(f"uploaded meanwhile by another run: {name}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", required=True, help="the driver version the debs were built at")
    parser.add_argument("debs", nargs="+", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        publish(args.debs, args.version)
    except GhError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
