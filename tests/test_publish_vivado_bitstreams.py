"""Tests for scripts/publish_vivado_bitstreams.py.

Covers the pure-Python logic — regex parsers, artifact collection, manifest
emission — without invoking Vivado, make, or gh. The orchestration paths are
verified end-to-end by running the script with --dry-run against the worktree.

Run with:
    uv run --extra dev pytest tests/test_publish_vivado_bitstreams.py -v
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pytest

# Ensure scripts/ is importable so we can test the module directly without
# turning the repo into a package.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import publish_vivado_bitstreams as pvb  # noqa: E402

# ---------------------------------------------------------------------------
# BUILD_DIR_RE — parses `<board>-<variant>-<flow>` directory names
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("name,board,variant,flow", [
    ("arty-a7-35-vivado-vivado", "arty", "a7-35", "vivado-vivado"),
    ("arty-a7-100-yosys-vivado", "arty", "a7-100", "yosys-vivado"),
    ("netv2-a7-35-yosys-nextpnr", "netv2", "a7-35", "yosys-nextpnr"),
    # Variant with a '+' suffix — matches 'cle-215+' on the Acorn CLE-215+ board.
    ("acorn-cle-215+-vivado-vivado", "acorn", "cle-215+", "vivado-vivado"),
    ("acorn-cle-101-yosys-vivado", "acorn", "cle-101", "yosys-vivado"),
])
def test_build_dir_regex_valid(name, board, variant, flow):
    m = pvb.BUILD_DIR_RE.match(name)
    assert m is not None, f"should match: {name}"
    assert m.group("board") == board
    assert m.group("variant") == variant
    assert m.group("flow") == flow


@pytest.mark.parametrize("name", [
    "arty-a7-35-not-a-real-flow",   # unknown flow suffix
    "arty-a7-35",                    # missing flow suffix
    "vivado-vivado",                 # flow only, no board/variant
    "",                              # empty
    "arty",                          # just a word
])
def test_build_dir_regex_rejects(name):
    assert pvb.BUILD_DIR_RE.match(name) is None, f"should NOT match: {name}"


# ---------------------------------------------------------------------------
# GITHUB_REMOTE_RE — parses owner/repo from assorted remote URL shapes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url,owner,repo", [
    ("git@github.com:fpgas-online/fpgas.online-test-designs.git",
     "fpgas-online", "fpgas.online-test-designs"),
    ("git@github.com:fpgas-online/fpgas.online-test-designs",
     "fpgas-online", "fpgas.online-test-designs"),
    ("https://github.com/fpgas-online/fpgas.online-test-designs.git",
     "fpgas-online", "fpgas.online-test-designs"),
    ("https://github.com/fpgas-online/fpgas.online-test-designs",
     "fpgas-online", "fpgas.online-test-designs"),
    ("https://github.com/fpgas-online/fpgas.online-test-designs/",
     "fpgas-online", "fpgas.online-test-designs"),
    ("https://user@github.com/a/b.git", "a", "b"),
])
def test_github_remote_regex(url, owner, repo):
    m = pvb.GITHUB_REMOTE_RE.search(url)
    assert m is not None, f"should parse: {url}"
    assert m.group("owner") == owner
    assert m.group("repo") == repo


@pytest.mark.parametrize("url", [
    "git@gitlab.com:foo/bar.git",    # not github
    "foo/bar",                        # no github host
    "",
])
def test_github_remote_regex_rejects(url):
    assert pvb.GITHUB_REMOTE_RE.search(url) is None


# ---------------------------------------------------------------------------
# parse_flows — CLI flag validator
# ---------------------------------------------------------------------------

def test_parse_flows_both():
    assert pvb.parse_flows("vivado-vivado,yosys-vivado") == [
        "vivado-vivado", "yosys-vivado",
    ]


def test_parse_flows_single():
    assert pvb.parse_flows("vivado-vivado") == ["vivado-vivado"]


def test_parse_flows_strips_whitespace():
    assert pvb.parse_flows(" vivado-vivado , yosys-vivado ") == [
        "vivado-vivado", "yosys-vivado",
    ]


def test_parse_flows_rejects_unknown():
    # yosys-nextpnr is a real flow but not a *Vivado* flow — the script only
    # publishes what can't be built in CI, so we reject it at parse time.
    with pytest.raises(argparse.ArgumentTypeError):
        pvb.parse_flows("yosys-nextpnr")


def test_parse_flows_rejects_empty():
    with pytest.raises(argparse.ArgumentTypeError):
        pvb.parse_flows("")


# ---------------------------------------------------------------------------
# sha256_file — matches hashlib.sha256 on known content
# ---------------------------------------------------------------------------

def test_sha256_file_matches_hashlib(tmp_path):
    data = b"hello fpga world" * 1024
    f = tmp_path / "sample.bin"
    f.write_bytes(data)
    expected = hashlib.sha256(data).hexdigest()
    assert pvb.sha256_file(f) == expected


def test_sha256_file_empty(tmp_path):
    f = tmp_path / "empty.bin"
    f.write_bytes(b"")
    # SHA-256 of empty input is a well-known constant.
    assert pvb.sha256_file(f) == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


# ---------------------------------------------------------------------------
# discover_designs / collect_artifacts — filesystem walk + flow filter
# ---------------------------------------------------------------------------

def _make_fake_repo(root: Path, layout: dict[str, list[str]]) -> None:
    """Create `designs/<name>/build/<dir>/gateware/<files>` from a dict mapping
    `"<design>/<build-dir>"` to a list of bitstream filenames."""
    for key, files in layout.items():
        design, flow_dir = key.split("/", 1)
        gateware = root / "designs" / design / "build" / flow_dir / "gateware"
        gateware.mkdir(parents=True, exist_ok=True)
        for name in files:
            (gateware / name).write_bytes(b"fake bitstream " + name.encode())


def test_discover_designs_excludes_underscore_dirs(tmp_path):
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    (tmp_path / "designs" / "ethernet-test").mkdir(parents=True)
    (tmp_path / "designs" / "_shared").mkdir(parents=True)  # helper dir
    (tmp_path / "designs" / "_host").mkdir(parents=True)    # helper dir
    assert pvb.discover_designs(tmp_path) == ["ethernet-test", "uart"]


def test_collect_artifacts_only_requested_flows(tmp_path):
    _make_fake_repo(tmp_path, {
        "uart/arty-a7-35-vivado-vivado":   ["digilent_arty.bit"],
        "uart/arty-a7-35-yosys-vivado":    ["digilent_arty.bit"],
        "uart/arty-a7-35-yosys-nextpnr":   ["digilent_arty.bit"],  # must be ignored
        "uart/fomu-evt-yosys-nextpnr":     ["fomu.bin"],           # must be ignored
    })

    artifacts = pvb.collect_artifacts(tmp_path, {"vivado-vivado", "yosys-vivado"})
    names = sorted(a.staged_name for a in artifacts)
    assert names == [
        "uart_arty-a7-35_vivado-vivado_digilent_arty.bit",
        "uart_arty-a7-35_yosys-vivado_digilent_arty.bit",
    ]


def test_collect_artifacts_handles_acorn_plus_variant(tmp_path):
    # The '+' in 'cle-215+' is the edge case that BUILD_DIR_RE must not choke on.
    # (Note: in practice LiteX translates '+' to 'p' in directory names, but
    # the regex must still handle the literal case defensively.)
    _make_fake_repo(tmp_path, {
        "uart/acorn-cle-215+-vivado-vivado": ["sqrl_acorn.bit"],
    })
    artifacts = pvb.collect_artifacts(tmp_path, {"vivado-vivado"})
    assert len(artifacts) == 1
    a = artifacts[0]
    assert a.board == "acorn"
    assert a.variant == "cle-215+"
    assert a.flow == "vivado-vivado"
    assert a.staged_name == "uart_acorn-cle-215+_vivado-vivado_sqrl_acorn.bit"


def test_collect_artifacts_disambiguates_multiple_flavors(tmp_path):
    # Acorn boards produce three distinct bitstream flavors per variant
    # (default, fallback, operational) — all with the same .bit extension.
    # The staged_name must include the file stem so these don't collide
    # when staged, or the release would attach only one of them.
    _make_fake_repo(tmp_path, {
        "uart/acorn-cle-101-vivado-vivado": [
            "sqrl_acorn.bit",
            "sqrl_acorn_fallback.bit",
            "sqrl_acorn_operational.bit",
            "sqrl_acorn.bin",
            "sqrl_acorn_fallback.bin",
            "sqrl_acorn_operational.bin",
        ],
    })
    artifacts = pvb.collect_artifacts(tmp_path, {"vivado-vivado"})
    names = sorted(a.staged_name for a in artifacts)
    assert names == [
        "uart_acorn-cle-101_vivado-vivado_sqrl_acorn.bin",
        "uart_acorn-cle-101_vivado-vivado_sqrl_acorn.bit",
        "uart_acorn-cle-101_vivado-vivado_sqrl_acorn_fallback.bin",
        "uart_acorn-cle-101_vivado-vivado_sqrl_acorn_fallback.bit",
        "uart_acorn-cle-101_vivado-vivado_sqrl_acorn_operational.bin",
        "uart_acorn-cle-101_vivado-vivado_sqrl_acorn_operational.bit",
    ]
    # All six must be unique — the whole point of including the stem.
    assert len(set(names)) == len(names)


def test_collect_artifacts_ignores_non_bitstream_extensions(tmp_path):
    # LiteX leaves many non-bitstream files in gateware/ (logs, reports, tcl).
    # We only want the programming files.
    _make_fake_repo(tmp_path, {
        "uart/arty-a7-35-vivado-vivado": [
            "digilent_arty.bit",
            "digilent_arty.log",     # report, not a bitstream
            "digilent_arty.tcl",     # build script
            "digilent_arty.runs",    # directory-looking file
        ],
    })
    artifacts = pvb.collect_artifacts(tmp_path, {"vivado-vivado"})
    assert [a.staged_name for a in artifacts] == [
        "uart_arty-a7-35_vivado-vivado_digilent_arty.bit",
    ]


def test_collect_artifacts_empty_when_no_matches(tmp_path):
    (tmp_path / "designs" / "uart").mkdir(parents=True)
    assert pvb.collect_artifacts(tmp_path, {"vivado-vivado"}) == []


# ---------------------------------------------------------------------------
# stage_artifacts — staging dir is purged + populated
# ---------------------------------------------------------------------------

def test_stage_artifacts_purges_prior_files(tmp_path):
    src = tmp_path / "src.bit"
    src.write_bytes(b"fresh content")
    staging = tmp_path / "staging"
    staging.mkdir()
    # Stale file from a previous run that must be cleared so it can't leak
    # into the release.
    (staging / "old_artifact.bit").write_bytes(b"stale content")

    a = pvb.Artifact(
        source_path=src, design="uart", board="arty", variant="a7-35",
        flow="vivado-vivado", staged_name="uart_arty-a7-35_vivado-vivado.bit",
    )
    pvb.stage_artifacts([a], staging)

    remaining = sorted(p.name for p in staging.iterdir())
    assert remaining == ["uart_arty-a7-35_vivado-vivado.bit"]
    assert (staging / "uart_arty-a7-35_vivado-vivado.bit").read_bytes() == b"fresh content"


# ---------------------------------------------------------------------------
# write_sha256sums / write_manifest — output formats
# ---------------------------------------------------------------------------

def _one_artifact(sha: str = "a" * 64, size: int = 100) -> pvb.Artifact:
    return pvb.Artifact(
        source_path=Path("/fake"),
        design="uart", board="arty", variant="a7-35",
        flow="vivado-vivado",
        staged_name="uart_arty-a7-35_vivado-vivado.bit",
        sha256=sha, size_bytes=size,
    )


def test_write_sha256sums_format(tmp_path):
    artifacts = [_one_artifact("b" * 64), _one_artifact("a" * 64)]
    # Differentiate so sorting is testable.
    artifacts[0].staged_name = "b_design.bit"
    artifacts[1].staged_name = "a_design.bit"

    pvb.write_sha256sums(artifacts, tmp_path)
    content = (tmp_path / "SHA256SUMS").read_text()
    # Lines are two-space separated (sha256sum -c format) and sorted by filename.
    assert content == f"{'a' * 64}  a_design.bit\n{'b' * 64}  b_design.bit\n"


# ---------------------------------------------------------------------------
# resolve_existing_release_action — the safety-critical overwrite guard
# ---------------------------------------------------------------------------

def test_resolve_action_no_existing_release_proceeds():
    action, _ = pvb.resolve_existing_release_action(
        tag="vivado-bitstreams-v1", exists=False,
        git_dirty=False, allow_dirty=False,
    )
    assert action == "proceed"


def test_resolve_action_clean_tree_existing_release_aborts():
    # Existing release, clean tree: a clean release is immutable. Must abort
    # even if --allow-dirty is passed (it wouldn't apply anyway; tag is clean).
    action, msg = pvb.resolve_existing_release_action(
        tag="vivado-bitstreams-v1", exists=True,
        git_dirty=False, allow_dirty=False,
    )
    assert action == "abort"
    assert "vivado-bitstreams-v1" in msg
    assert "Refusing to overwrite" in msg


def test_resolve_action_clean_tree_allow_dirty_still_aborts():
    # --allow-dirty must NOT enable overwriting a clean release — the guard
    # applies regardless of the flag when the tree is clean.
    action, _ = pvb.resolve_existing_release_action(
        tag="vivado-bitstreams-v1", exists=True,
        git_dirty=False, allow_dirty=True,
    )
    assert action == "abort"


def test_resolve_action_dirty_with_allow_dirty_replaces():
    # Dirty tag + --allow-dirty is the only path that deletes an existing
    # release. Dirty tags are explicitly mutable by construction.
    action, msg = pvb.resolve_existing_release_action(
        tag="vivado-bitstreams-v1-dirty", exists=True,
        git_dirty=True, allow_dirty=True,
    )
    assert action == "replace_dirty"
    assert "vivado-bitstreams-v1-dirty" in msg


def test_resolve_action_dirty_without_allow_dirty_aborts():
    # Dirty tree without --allow-dirty: preflight would normally abort first,
    # but if somehow we got here this is the defence-in-depth.
    action, _ = pvb.resolve_existing_release_action(
        tag="vivado-bitstreams-v1-dirty", exists=True,
        git_dirty=True, allow_dirty=False,
    )
    assert action == "abort"


# ---------------------------------------------------------------------------
# write_release_notes — commit URL uses the repo argument
# ---------------------------------------------------------------------------

def test_release_notes_use_repo_arg_for_commit_url(tmp_path):
    # Verifies the fix for the hardcoded URL bug: `--repo other/fork` must
    # produce release notes that link to the fork's commit, not the canonical
    # repo.
    git = pvb.GitInfo(
        describe="v0.0-1-gabcdef0", sha="abcdef0" + "0" * 33,
        branch="vivado-xilinx-flows", dirty=False,
    )
    build = pvb.BuildSummary(
        flows=["vivado-vivado"], jobs=1,
        vivado_settings="/opt/Xilinx/2025.2/Vivado/settings64.sh",
        vivado_version="vivado v2025.2 (64-bit)",
    )
    a = _one_artifact()
    pvb.write_release_notes([a], git, build, tmp_path, "someone/a-fork")

    body = (tmp_path / "RELEASE_NOTES.md").read_text()
    assert "https://github.com/someone/a-fork/commit/" in body
    assert "fpgas-online/fpgas.online-test-designs" not in body


def test_write_manifest_schema(tmp_path):
    git = pvb.GitInfo(
        describe="v0.0-490-g99f0785", sha="99f0785" + "0" * 33,
        branch="vivado-xilinx-flows", dirty=False,
    )
    build = pvb.BuildSummary(
        flows=["vivado-vivado"],
        make_targets=["build-all-xilinx-vivado-vivado"],
        jobs=4, vivado_settings="/opt/Xilinx/2025.2/Vivado/settings64.sh",
    )
    a = _one_artifact()
    pvb.write_manifest([a], git, build, tmp_path)

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    assert manifest["schema"] == 1
    assert manifest["git"]["describe"] == "v0.0-490-g99f0785"
    assert manifest["git"]["dirty"] is False
    assert manifest["build"]["flows"] == ["vivado-vivado"]
    assert manifest["build"]["jobs"] == 4
    assert len(manifest["artifacts"]) == 1
    entry = manifest["artifacts"][0]
    assert entry["filename"] == a.staged_name
    assert entry["flow"] == "vivado-vivado"
    assert entry["sha256"] == "a" * 64
    assert entry["size_bytes"] == 100
