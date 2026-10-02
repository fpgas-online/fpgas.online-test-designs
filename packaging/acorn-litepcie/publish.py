#!/usr/bin/env python3
"""Publish the LitePCIe driver debs to this repository's rolling series release, which fpgas-online/apt pulls.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§3.6, §4.3).

  * The series is the driver version's own `vX.Y`, not HEAD's nearest tag: the version comes from the last
    commit that changed the driver's inputs, which can predate a newer tag.
  * Only files the release does not have yet are uploaded. A published version is never replaced: a rebuild's
    bytes differ (build times), and an apt repository that already pulled it must not see the same name and
    version change under it.
  * Another run of the same driver version may upload a file first; that is not a failure.
  * An asset is named as GitHub stores it. GitHub turns every character of an uploaded file's name other than
    letters, digits and `. _ + -` into a dot, so `..._0.0.post42~deb12_arm64.deb` is the asset
    `..._0.0.post42.deb12_arm64.deb`. The upload gives the file that name itself, and fails unless the
    release lists it afterwards.
  * The release is shared with the other packages' workflows and holds at most 1000 assets: nothing is
    uploaded if that would take it past 900.
  * After the upload, the LitePCIe assets older than the previous driver version are deleted, and so are the
    modules for kernels below the floor. No other package's asset is ever touched.

    GH_TOKEN=... python3 packaging/acorn-litepcie/publish.py --version 0.0.post42 dist/*.deb
    python3 packaging/acorn-litepcie/publish.py --version 0.0.post42 --dry-run dist/*.deb
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import tomllib

HERE = pathlib.Path(__file__).resolve().parent
NAME = "fpgas-online-acorn-litepcie"
LIMIT = 900
# <package>_<driver version>[<suite suffix>]_<architecture>.deb, the suffix as built (~deb12) or as stored (.deb12)
ASSET = re.compile(rf"({re.escape(NAME)}-[^_]+)_(\d+\.\d+(?:\.post\d+)?)(?:[.~]deb\d+)?_[a-z0-9]+\.deb")


class GhError(Exception):
    pass


class PublishError(Exception):
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


def version_key(version):
    """`0.0.post42` -> (0, 0, 42), `0.1` -> (0, 1, 0): driver versions in the order they were made."""
    m = re.fullmatch(r"(\d+)\.(\d+)(?:\.post(\d+))?", version)
    if not m:
        raise ValueError(f"{version!r} is not an X.Y or X.Y.postN version")
    return tuple(int(x or 0) for x in m.groups())


def release_name(filename):
    """The name GitHub stores an uploaded file under."""
    return re.sub(r"[^A-Za-z0-9._+-]", ".", filename)


def parse_asset(name):
    """(package, driver version) of a LitePCIe deb's name, built or stored; None for anything else."""
    m = ASSET.fullmatch(name)
    return (m.group(1), m.group(2)) if m else None


def to_upload(debs, published):
    return [d for d in debs if release_name(pathlib.Path(d).name) not in published]


def check_room(assets, uploads, limit=LIMIT):
    if uploads and assets + uploads > limit:
        raise PublishError(
            f"the release has {assets} assets and this run would add {uploads}, past the limit of {limit} "
            "this workflow keeps to (a release holds 1000): prune the release before publishing more"
        )


def _below_floor(package, min_kernel):
    """A modules package for a kernel below the floor. By the kernel's name, which reads low for the 6.1
    kernels (all named 6.1.0-rpiN): right for any floor above 6.1, and the floor only ever rises."""
    prefix = f"{NAME}-modules-"
    if not (min_kernel and package.startswith(prefix)):
        return False
    m = re.match(r"\d+(?:\.\d+)*", package[len(prefix) :])
    return bool(m) and _numbers(m.group()) < _numbers(min_kernel)


def _numbers(text):
    return tuple(int(x) for x in text.split("."))


def plan_prune(assets, current, min_kernel=None):
    """The LitePCIe assets to delete: every driver version older than the one before `current`, and the
    modules for kernels below the floor. Versions newer than `current` (another run's) are left alone."""
    ours = {name: parsed for name in assets if (parsed := parse_asset(name))}
    older = {version_key(v) for _package, v in ours.values() if version_key(v) < version_key(current)}
    keep_from = max(older) if older else version_key(current)
    return sorted(
        name
        for name, (package, version) in ours.items()
        if version_key(version) < keep_from or _below_floor(package, min_kernel)
    )


def release_assets(tag, gh=gh):
    """The release's asset names, or None when there is no such release."""
    try:
        return set(gh("release", "view", tag, "--json", "assets", "--jq", ".assets[].name").split())
    except GhError as e:
        if "not found" not in str(e):
            raise
        return None


def _upload(tag, deb, name, gh):
    """Upload `deb` as the asset `name`: under that file name, so GitHub has nothing to rename."""
    path = pathlib.Path(deb)
    with tempfile.TemporaryDirectory(dir=path.parent, prefix=".upload-") as tmp:
        if path.name != name:
            path = pathlib.Path(shutil.copyfile(deb, pathlib.Path(tmp) / name))
        try:
            gh("release", "upload", tag, str(path))
            print(f"uploaded {name} to {tag}")
        except GhError:
            if name not in (release_assets(tag, gh) or ()):
                raise
            print(f"uploaded meanwhile by another run: {name}")


def publish(debs, version, gh=gh, dry_run=False, min_kernel=None):
    tag = series(version)
    names = {}
    for deb in debs:
        name = release_name(pathlib.Path(deb).name)
        parsed = parse_asset(name)
        if not parsed:
            raise PublishError(f"{name} is not a {NAME} deb")
        if parsed[1] != version:
            raise PublishError(f"{name} is version {parsed[1]}, not the {version} being published")
        names[name] = deb
    published = release_assets(tag, gh)
    if published is None:
        if dry_run:
            print(f"would create the release {tag}")
        else:
            gh("release", "create", tag, "--prerelease", "--title", f"Debian packages (rolling, series {tag})",
               "--notes", f"Rolling .deb builds from this repository for series {tag}, one per green commit on "
               "main. Consumed by https://github.com/fpgas-online/apt.")  # fmt: skip
        published = set()
    uploads = sorted(set(names) - published)
    check_room(len(published), len(uploads))
    for name in sorted(set(names) & published):
        print(f"already published: {name}")
    for name in uploads:
        if dry_run:
            print(f"would upload {name}")
        else:
            _upload(tag, names[name], name, gh)
    after = published | set(uploads) if dry_run else release_assets(tag, gh) or set()
    lost = sorted(set(names) - after)
    if lost:
        raise PublishError(f"the release {tag} does not list {', '.join(lost)} after the upload")
    doomed = plan_prune(after, version, min_kernel)
    for name in doomed:
        if dry_run:
            print(f"would prune {name}")
        else:
            gh("release", "delete-asset", tag, name, "--yes")
            print(f"pruned {name} from {tag}")
    if dry_run:
        print(
            f"{tag}: {len(published)} assets now, {len(uploads)} to upload, {len(doomed)} to prune, "
            f"{len(after) - len(doomed)} afterwards (the limit is {LIMIT})"
        )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", required=True, help="the driver version the debs were built at")
    parser.add_argument("--dry-run", action="store_true", help="read the release and say what would be done")
    parser.add_argument("--kernels", type=pathlib.Path, default=HERE / "kernels.toml", help="for min_kernel")
    parser.add_argument("debs", nargs="+", type=pathlib.Path)
    args = parser.parse_args(argv)
    min_kernel = tomllib.loads(args.kernels.read_text())["min_kernel"]
    try:
        publish(args.debs, args.version, dry_run=args.dry_run, min_kernel=min_kernel)
    except (GhError, PublishError) as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
