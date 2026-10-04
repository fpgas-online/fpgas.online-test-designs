#!/usr/bin/env python3
"""Upload a build's debs to that build's own GitHub release, `build-<version>`.

Every push to main gets a release of its own, tagged `build-<X.Y.postN>` at the commit that was built
(mithro/apt-repo-action docs/packaging.md, "GitHub Releases"). fpgas-online/apt reads every release of this
repository and pulls each `<package>_<version>_<arch>.deb` it does not have yet.

  * The tag is never `v*`: `vX.Y` is a series tag, made by hand, and the version is `git describe` against
    it. The tag ruleset must admit `refs/tags/build-*`.
  * Several workflows upload to one build's release (collect-bitstreams.yml, acorn-litepcie.yml). Whichever
    finishes first creates it; the other finding it already there is not a failure.
  * A published file is never replaced, and never published twice: a deb whose name any release of this
    repository already carries is left out. A rebuild's bytes differ (build times), and an apt repository
    that already pulled a (package, version) must not find other bytes under the same name. So a package
    that did not change with this push (its version comes from something else: a pinned release, the last
    commit that changed the driver) stays on the release that first carried it.
  * Two runs of different commits are not serialised, so each checks again just before each upload, and
    after it: if an older release also has the file (the other run uploaded it meanwhile), the copy just
    uploaded is deleted. Both runs apply the same rule, so the copy on the oldest release is the one kept.
  * An asset is named as GitHub will store it: every character but letters, digits and `. _ + -` becomes a
    dot (`~` in a version does), so the names compared here are the names GitHub lists.

    GH_TOKEN=... python3 packaging/release.py dist/*.deb
"""

import argparse
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[1]
NOTES = (
    "The Debian packages build {version} of this repository published, built from {commit}. A package this "
    "build did not change is on the release that first carried its version. "
    "https://github.com/fpgas-online/apt collects them into https://fpgas.online/apt."
)


class ReleaseError(Exception):
    pass


def gh(*args):
    run = subprocess.run(["gh", *args], capture_output=True, text=True)
    if run.returncode:
        raise ReleaseError(f"gh {' '.join(args[:3])}: {run.stderr.strip()}")
    return run.stdout


def repo_version(repo=REPO):
    """`X.Y` at a vX.Y tag, `X.Y.postN` N commits later: the version the debs of this commit carry."""
    run = subprocess.run(
        ["git", "-C", str(repo), "describe", "--tags", "--long", "--match", "v[0-9]*.[0-9]*"],
        capture_output=True,
        text=True,
    )
    if run.returncode:
        raise ReleaseError(f"git describe found no vX.Y tag (a shallow clone?): {run.stderr.strip()}")
    m = re.fullmatch(r"v(\d+)\.(\d+)-(\d+)-g[0-9a-f]+", run.stdout.strip())
    if not m:
        raise ReleaseError(f"unexpected git describe output {run.stdout.strip()!r}")
    major, minor, n = m.groups()
    return f"{major}.{minor}" if n == "0" else f"{major}.{minor}.post{n}"


def head_commit(repo=REPO):
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def stored_name(name):
    """The name GitHub gives an uploaded asset."""
    return re.sub(r"[^A-Za-z0-9._+-]", ".", name)


def named(debs):
    """{stored name: path}. Two files that would be stored under one name are an error, not a choice."""
    out = {}
    for deb in map(pathlib.Path, debs):
        name = stored_name(deb.name)
        if name in out:
            raise ReleaseError(f"{out[name]} and {deb} would both be stored as {name}")
        out[name] = deb
    return out


def published(gh=gh):
    """The name of every asset on every release of this repository."""
    return set(gh("api", "repos/{owner}/{repo}/releases", "--paginate", "--jq", ".[].assets[].name").split())


def carriers(name, gh=gh):
    """The tags of the releases carrying `name`, oldest first. `name` is a stored name: no quotes in it."""
    out = gh("api", "repos/{owner}/{repo}/releases", "--paginate", "--jq",
             f'.[] | select(any(.assets[]; .name == "{name}")) | "\\(.created_at) \\(.tag_name)"')  # fmt: skip
    return [tag for _, tag in sorted(tuple(line.split()) for line in out.splitlines() if line.strip())]


def _exists(tag, gh):
    try:
        gh("release", "view", tag, "--json", "tagName")
    except ReleaseError as e:
        if "not found" not in str(e):
            raise
        return False
    return True


def ensure_release(tag, version, commit, gh=gh):
    if _exists(tag, gh):
        return
    try:
        gh("release", "create", tag, "--prerelease", "--target", commit, "--title", f"Build {version}",
           "--notes", NOTES.format(version=version, commit=commit))  # fmt: skip
        print(f"created {tag} at {commit}")
    except ReleaseError:
        if not _exists(tag, gh):  # not another workflow of this build creating it first
            raise
        print(f"{tag} was created meanwhile by another workflow")


def publish(debs, version, commit, gh=gh):
    """Upload what no release has yet to `build-<version>`. Returns the names this build's release keeps."""
    tag = f"build-{version}"
    files = named(debs)
    have = published(gh)
    new = {name: path for name, path in files.items() if name not in have}
    for name in sorted(files.keys() - new.keys()):
        print(f"already published: {name}")
    if not new:
        print(f"nothing new for {tag}")
        return []
    ensure_release(tag, version, commit, gh)
    kept = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, path in sorted(new.items()):
            if name in published(gh):  # another run, of this commit or another, got there first
                print(f"published meanwhile by another run: {name}")
                continue
            upload = pathlib.Path(tmp) / name  # under the stored name, so GitHub renames nothing
            shutil.copyfile(path, upload)
            try:
                gh("release", "upload", tag, str(upload))
                print(f"uploaded {name} to {tag}")
            except ReleaseError:
                if name not in published(gh):
                    raise
                print(f"uploaded meanwhile by another run: {name}")
                continue
            oldest = carriers(name, gh)[0]
            if oldest != tag:  # another run put it on an older release in the meantime: keep that one
                gh("release", "delete-asset", tag, name, "--yes")
                print(f"{name} is also on {oldest}: deleted the copy on {tag}")
                continue
            kept.append(name)
    return kept


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("debs", nargs="+", type=pathlib.Path)
    args = parser.parse_args(argv)
    try:
        publish(args.debs, repo_version(), head_commit())
    except ReleaseError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
