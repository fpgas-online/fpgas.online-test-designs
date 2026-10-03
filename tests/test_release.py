"""Tests for packaging/release.py: each build's debs go to that build's own `build-<version>` release.

What must hold:

  * the release is the build's own, tagged `build-<version>` at the built commit, never a `v*` series tag;
  * a file any release already carries is never uploaded again, to this release or another;
  * two workflows of one build can both publish: the one that finds the release already made does not fail;
  * a real failure (auth, network, a tag the ruleset refuses) is reported, not taken for one of the above.
"""

import importlib.util
import pathlib
import subprocess

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, REPO / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rel = _load("packaging/release.py", "packaging_release")
COMMIT = "0123456789abcdef0123456789abcdef01234567"


class FakeGh:
    """GitHub's releases: {tag: asset names}, oldest first. `race`: assets another run uploads to the same
    release just before ours. `elsewhere`: {asset: tag}, assets another run puts on that (older) release while
    ours is being uploaded."""

    def __init__(self, releases=None, race=(), create_race=False, elsewhere=None):
        self.releases = {tag: set(assets) for tag, assets in (releases or {}).items()}
        self.race, self.create_race, self.calls = set(race), create_race, []
        self.elsewhere = dict(elsewhere or {})

    def __call__(self, *args):
        self.calls.append(args)
        if args[0] == "api" and "select(" in args[-1]:  # carriers(): the releases with one asset, created_at order
            name = args[-1].split('.name == "')[1].split('"')[0]
            return "\n".join(f"2026-10-03T00:00:{i:02d}Z {tag}" for i, (tag, a) in enumerate(self.releases.items())
                             if name in a)  # fmt: skip
        if args[0] == "api":
            return "\n".join(sorted(name for assets in self.releases.values() for name in assets))
        if args[:2] == ("release", "view"):
            if args[2] not in self.releases:
                raise rel.ReleaseError("gh release view: release not found")
            return ""
        if args[:2] == ("release", "create"):
            if self.create_race:  # the other workflow of this build made it between our view and our create
                self.releases[args[2]] = set()
                raise rel.ReleaseError("gh release create: HTTP 422: Validation Failed (already_exists)")
            self.releases[args[2]] = set()
            return ""
        if args[:2] == ("release", "delete-asset"):
            self.releases[args[2]].remove(args[3])
            return ""
        if args[:2] == ("release", "upload"):
            name = pathlib.Path(args[3]).name
            if name in self.elsewhere:
                self.releases[self.elsewhere.pop(name)].add(name)
            if name in self.race:
                self.releases[args[2]].add(name)
                raise rel.ReleaseError(f"gh release upload: asset {name} already exists")
            self.releases[args[2]].add(name)
            return ""
        raise AssertionError(args)

    def created(self):
        return [c for c in self.calls if c[:2] == ("release", "create")]


def _deb(tmp_path, name):
    path = tmp_path / name
    path.write_bytes(b"x")
    return path


def test_a_build_gets_its_own_release_at_the_built_commit(tmp_path):
    gh = FakeGh({"v0.0": {"old_0.0.post1_all.deb"}})
    deb = _deb(tmp_path, "x_0.0.post7_all.deb")
    assert rel.publish([deb], "0.0.post7", COMMIT, gh=gh) == ["x_0.0.post7_all.deb"]
    (create,) = gh.created()
    assert create[2] == "build-0.0.post7"
    assert create[create.index("--target") + 1] == COMMIT
    assert "--prerelease" in create
    assert gh.releases["build-0.0.post7"] == {"x_0.0.post7_all.deb"}
    assert gh.releases["v0.0"] == {"old_0.0.post1_all.deb"}


def test_a_file_any_release_already_carries_is_not_published_again(tmp_path):
    """The Acorn's bitstreams deb, or a driver package of a push that did not touch the driver: its name and
    version did not move, and a rebuild's bytes differ."""
    gh = FakeGh({"v0.0": {"pinned_20261001+gabc_all.deb"}, "build-0.0.post6": {"driver_0.0.post5_all.deb"}})
    debs = [
        _deb(tmp_path, n) for n in ("pinned_20261001+gabc_all.deb", "driver_0.0.post5_all.deb", "x_0.0.post7_all.deb")
    ]
    assert rel.publish(debs, "0.0.post7", COMMIT, gh=gh) == ["x_0.0.post7_all.deb"]
    assert gh.releases["build-0.0.post7"] == {"x_0.0.post7_all.deb"}


def test_a_build_with_nothing_new_makes_no_release(tmp_path):
    """The daily run of a commit whose packages are all published already."""
    gh = FakeGh({"build-0.0.post7": {"x_0.0.post7_all.deb"}})
    assert rel.publish([_deb(tmp_path, "x_0.0.post7_all.deb")], "0.0.post7", COMMIT, gh=gh) == []
    assert not gh.created()


def test_the_second_workflow_of_a_build_adds_to_the_release_the_first_made(tmp_path):
    gh = FakeGh({"build-0.0.post7": {"x_0.0.post7_all.deb"}})
    rel.publish([_deb(tmp_path, "y_0.0.post7_arm64.deb")], "0.0.post7", COMMIT, gh=gh)
    assert not gh.created()
    assert gh.releases["build-0.0.post7"] == {"x_0.0.post7_all.deb", "y_0.0.post7_arm64.deb"}


def test_losing_the_race_to_create_the_release_is_not_a_failure(tmp_path):
    gh = FakeGh(create_race=True)
    rel.publish([_deb(tmp_path, "y_0.0.post7_arm64.deb")], "0.0.post7", COMMIT, gh=gh)
    assert gh.releases["build-0.0.post7"] == {"y_0.0.post7_arm64.deb"}


def test_a_create_the_tag_ruleset_refuses_is_a_failure(tmp_path):
    """Until the tag ruleset admits `build-*`, creating the release fails and must say so."""

    class Refused(FakeGh):
        def __call__(self, *args):
            if args[:2] == ("release", "create"):
                self.calls.append(args)
                raise rel.ReleaseError("gh release create: HTTP 422: Repository rule violations found")
            return super().__call__(*args)

    with pytest.raises(rel.ReleaseError, match="rule violations"):
        rel.publish([_deb(tmp_path, "x_0.0.post7_all.deb")], "0.0.post7", COMMIT, gh=Refused())


def test_an_upload_another_run_made_meanwhile_is_not_a_failure(tmp_path):
    gh = FakeGh(race={"x_0.0.post7_all.deb"})
    rel.publish([_deb(tmp_path, "x_0.0.post7_all.deb")], "0.0.post7", COMMIT, gh=gh)


def test_a_file_another_commit_s_run_put_on_an_older_release_meanwhile_is_kept_there_only(tmp_path):
    # Runs of different commits are not serialised: the other one's upload lands between our check and ours.
    gh = FakeGh({"build-0.0.post6": set()}, elsewhere={"x_0.0.post5_all.deb": "build-0.0.post6"})
    deb = _deb(tmp_path, "x_0.0.post5_all.deb")
    assert rel.publish([deb], "0.0.post7", COMMIT, gh=gh) == []
    assert gh.releases == {"build-0.0.post6": {"x_0.0.post5_all.deb"}, "build-0.0.post7": set()}


def test_a_file_published_while_earlier_files_uploaded_is_not_uploaded_again(tmp_path):
    gh = FakeGh({"build-0.0.post6": set()})
    a, b = _deb(tmp_path, "a_0.0.post7_all.deb"), _deb(tmp_path, "b_0.0.post5_all.deb")
    real = gh.__call__

    def other_run_publishes_b(*args):
        if args[:2] == ("release", "upload") and args[3].endswith("a_0.0.post7_all.deb"):
            gh.releases["build-0.0.post6"].add("b_0.0.post5_all.deb")
        return real(*args)

    assert rel.publish([a, b], "0.0.post7", COMMIT, gh=other_run_publishes_b) == ["a_0.0.post7_all.deb"]
    assert gh.releases["build-0.0.post7"] == {"a_0.0.post7_all.deb"}


def test_an_upload_that_really_failed_is_a_failure(tmp_path):
    class Broken(FakeGh):
        def __call__(self, *args):
            if args[:2] == ("release", "upload"):
                raise rel.ReleaseError("gh release upload: HTTP 500")
            return super().__call__(*args)

    with pytest.raises(rel.ReleaseError, match="500"):
        rel.publish([_deb(tmp_path, "x_0.0.post7_all.deb")], "0.0.post7", COMMIT, gh=Broken())


def test_a_release_view_that_fails_for_another_reason_is_reported_as_itself(tmp_path):
    """Only a missing release is created; an auth or network failure must not turn into a bogus create."""

    class Offline(FakeGh):
        def __call__(self, *args):
            if args[:2] == ("release", "view"):
                raise rel.ReleaseError("gh release view: HTTP 401: Bad credentials")
            return super().__call__(*args)

    gh = Offline()
    with pytest.raises(rel.ReleaseError, match="401"):
        rel.publish([_deb(tmp_path, "x_0.0.post7_all.deb")], "0.0.post7", COMMIT, gh=gh)
    assert not gh.created()


def test_an_asset_is_uploaded_under_the_name_github_stores(tmp_path):
    """GitHub turns `~` into a dot. Uploaded as built, the next run would not find it and would upload again."""
    assert rel.stored_name("p_0.0.post7~deb12_armhf.deb") == "p_0.0.post7.deb12_armhf.deb"
    assert rel.stored_name("p_20261001+gabc_all.deb") == "p_20261001+gabc_all.deb"
    gh = FakeGh()
    deb = _deb(tmp_path, "p_0.0.post7~deb12_armhf.deb")
    rel.publish([deb], "0.0.post7", COMMIT, gh=gh)
    assert gh.releases["build-0.0.post7"] == {"p_0.0.post7.deb12_armhf.deb"}
    assert rel.publish([deb], "0.0.post7", COMMIT, gh=gh) == []


def test_two_files_stored_under_one_name_are_refused(tmp_path):
    a = _deb(tmp_path, "p_1~a_all.deb")
    (tmp_path / "other").mkdir()
    b = _deb(tmp_path / "other", "p_1.a_all.deb")
    with pytest.raises(rel.ReleaseError, match="both be stored"):
        rel.publish([a, b], "0.0.post7", COMMIT, gh=FakeGh())


# -- the version ---------------------------------------------------------------------------------------------


def _git(repo, *args):
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "PATH": "/usr/bin:/bin"}
    ident = ["-c", "user.name=t", "-c", "user.email=t@example.org", "-c", "commit.gpgsign=false"]
    return subprocess.run(
        ["git", "-C", str(repo), *ident, *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def test_a_build_tag_is_never_taken_for_the_series_tag(tmp_path):
    """The version counts from the `vX.Y` tag. A `build-*` tag nearer to HEAD must not become its base, and
    the version must be the one the debs carry (packaging/acorn-pcie/build_debs.py's)."""
    debs = _load("packaging/acorn-pcie/build_debs.py", "acorn_pcie_build_debs")
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "root")
    _git(tmp_path, "tag", "v0.0")
    assert rel.repo_version(tmp_path) == "0.0"
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "one")
    _git(tmp_path, "tag", "build-0.0.post1")
    _git(tmp_path, "tag", "-a", "-m", "annotated", "build-annotated")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "two")
    assert rel.repo_version(tmp_path) == debs.git_version(tmp_path) == "0.0.post2"
    assert rel.head_commit(tmp_path) == _git(tmp_path, "rev-parse", "HEAD")


def test_no_series_tag_is_an_error_not_a_guess(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "root")
    with pytest.raises(rel.ReleaseError, match="shallow clone"):
        rel.repo_version(tmp_path)
