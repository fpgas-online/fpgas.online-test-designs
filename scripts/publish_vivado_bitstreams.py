#!/usr/bin/env python3
"""Build Vivado-requiring FPGA bitstreams and publish them as a GitHub Release.

This repo's GitHub Actions CI can build the open-source flows (openXC7 /
yosys+nextpnr-ice40), but the Vivado-requiring flows must be built locally
because Vivado is commercial software that cannot run in public CI. This
script is the one-command workflow that:

  1. Runs pre-flight checks (Vivado present, `gh` authenticated, tree clean).
  2. Invokes the existing Makefile targets that build every Xilinx design
     under the `vivado-vivado` and `yosys-vivado` flows (see mk/three-flows.mk
     and the top-level Makefile `build-all-xilinx-*` targets).
  3. Collects the resulting bitstreams into a staging directory, renaming
     each to a canonical `<design>_<board>-<variant>_<flow>.<ext>` form.
  4. Emits a `manifest.json` (schema-versioned, with SHA-256 per artifact)
     and a plain `SHA256SUMS` file next to the bitstreams.
  5. Publishes a GitHub Release tagged with the output of
     `git describe --tags --always --dirty` (optionally prefixed), attaching
     every bitstream plus the manifest and checksums.

Usage:
    uv run python scripts/publish_vivado_bitstreams.py                  # publish
    uv run python scripts/publish_vivado_bitstreams.py --dry-run        # local only
    uv run python scripts/publish_vivado_bitstreams.py --skip-build     # reuse prior build
    uv run python scripts/publish_vivado_bitstreams.py --flows vivado-vivado
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# The two flows that require Vivado. The third flow ('yosys-nextpnr') is the
# fully open-source path and is already covered by GitHub Actions CI.
VIVADO_FLOWS: tuple[str, ...] = ("vivado-vivado", "yosys-vivado")

# Every supported flow — used only to validate directory-name parses. Keeps
# us from silently accepting typos in future flow names.
ALL_KNOWN_FLOWS: tuple[str, ...] = ("vivado-vivado", "yosys-vivado", "yosys-nextpnr")

DEFAULT_VIVADO_SETTINGS = "/opt/Xilinx/2025.2/Vivado/settings64.sh"
DEFAULT_TAG_PREFIX = "vivado-bitstreams"

# Extensions we treat as bitstream artifacts. `.bit` is the standard Xilinx
# programming file; `.bin` is the raw bitstream; `.mcs` / `.svf` / `.prg` are
# vendor-tool formats emitted by some designs.
BITSTREAM_EXTS: tuple[str, ...] = (".bit", ".bin", ".mcs", ".svf", ".prg")

STAGING_REL_PATH = Path("tmp/vivado-release")

# Build-output directory names take the form `<board>-<variant>-<flow>`, where
# `<flow>` is one of ALL_KNOWN_FLOWS. The variant may contain '+', '.', or
# '-' (e.g. 'cle-215+', 'a7-100'), so the regex pins the flow suffix as the
# tail and treats everything before the final flow boundary as variant.
BUILD_DIR_RE = re.compile(
    r"^(?P<board>[a-z0-9]+)-(?P<variant>.+?)-(?P<flow>"
    + "|".join(re.escape(f) for f in ALL_KNOWN_FLOWS)
    + r")$"
)

# Parse `git@github.com:owner/repo(.git)` or `https://.../owner/repo(.git)`.
# The `(?:\.git)?` swallows an optional .git suffix; the final `/?$` allows a
# trailing slash on HTTPS URLs.
GITHUB_REMOTE_RE = re.compile(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/]+?)(?:\.git)?/?$")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Artifact:
    """One bitstream file, located + named + hashed."""
    source_path: Path
    design: str
    board: str
    variant: str
    flow: str
    staged_name: str
    sha256: str = ""
    size_bytes: int = 0


@dataclass
class GitInfo:
    describe: str
    sha: str
    branch: str
    dirty: bool


@dataclass
class BuildSummary:
    """Terse record of what was attempted and what succeeded. Used in release notes
    so a third party can reproduce the build."""
    flows: list[str]
    make_targets: list[str] = field(default_factory=list)
    jobs: int = 1
    vivado_settings: str = ""
    vivado_version: str = ""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def die(msg: str, code: int = 1) -> None:
    """Print an error to stderr and exit non-zero."""
    print(f"ERROR: {msg}", file=sys.stderr)
    raise SystemExit(code)


def run_capture(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command and capture stdout/stderr. Caller decides what to do with
    the exit code. Stderr is still visible via the returned object."""
    return subprocess.run(cmd, capture_output=True, text=True, check=False, **kwargs)


def run_streaming(cmd: list[str], **kwargs) -> int:
    """Run a command, streaming stdout+stderr to the console. Returns exit code."""
    print(f"$ {' '.join(cmd)}")
    return subprocess.run(cmd, check=False, **kwargs).returncode


def must_run(cmd: list[str], context: str, **kwargs) -> str:
    """Run a command, fail loudly on non-zero. Returns trimmed stdout."""
    r = run_capture(cmd, **kwargs)
    if r.returncode != 0:
        die(f"{context}: `{' '.join(cmd)}` failed ({r.returncode})\n"
            f"stdout: {r.stdout.strip()}\nstderr: {r.stderr.strip()}")
    return r.stdout.strip()


def sha256_file(path: Path) -> str:
    """Compute the SHA-256 digest of a file using 1 MiB chunks."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Repo / git helpers
# ---------------------------------------------------------------------------

def find_repo_root() -> Path:
    """Return the top-level directory of the git working tree we were invoked in."""
    root = must_run(["git", "rev-parse", "--show-toplevel"], "detecting repo root")
    return Path(root).resolve()


def git_describe() -> str:
    # --tags: consider lightweight tags (not just annotated).
    # --always: fall back to bare abbrev SHA if there are no tags at all.
    # --dirty: append '-dirty' when tracked files have uncommitted changes.
    return must_run(
        ["git", "describe", "--tags", "--always", "--dirty"],
        "running git describe",
    )


def git_head_sha() -> str:
    return must_run(["git", "rev-parse", "HEAD"], "reading HEAD sha")


def git_current_branch() -> str:
    # Returns 'HEAD' for a detached HEAD, which is informative enough.
    return must_run(["git", "rev-parse", "--abbrev-ref", "HEAD"], "reading current branch")


def git_info() -> GitInfo:
    describe = git_describe()
    return GitInfo(
        describe=describe,
        sha=git_head_sha(),
        branch=git_current_branch(),
        # 'git describe --dirty' is the source of truth for dirtiness — it
        # checks only tracked files, matching our definition (untracked
        # build caches like chipdb/ shouldn't count as dirty).
        dirty=describe.endswith("-dirty"),
    )


def detect_github_repo(remote: str = "origin") -> str:
    """Parse `git remote get-url <remote>` into `owner/repo`."""
    url = must_run(["git", "remote", "get-url", remote], f"reading {remote} URL")
    m = GITHUB_REMOTE_RE.search(url)
    if not m:
        die(f"Cannot parse GitHub owner/repo from remote URL: {url!r}")
    return f"{m.group('owner')}/{m.group('repo')}"


# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

def preflight(args: argparse.Namespace, repo_root: Path) -> None:
    """All checks that must pass before any long-running build starts. Any
    failure here exits immediately with a clear message."""
    print("=== Pre-flight checks ===")

    # gh CLI authenticated (only required for a real publish).
    if not args.dry_run:
        r = run_capture(["gh", "auth", "status"])
        if r.returncode != 0:
            die("`gh auth status` failed. Run `gh auth login` first, or use "
                f"--dry-run for a local-only run.\nstderr: {r.stderr.strip()}")
        print("  gh: authenticated")

    # Vivado settings file exists. We delegate the deeper check (actually
    # sourcing it and running `vivado -version`) to `make check-vivado` so
    # we share one source of truth with the rest of the build system.
    settings = Path(args.vivado_settings)
    if not settings.is_file():
        die(f"Vivado settings not found at {settings}. Either install Vivado "
            f"or pass --vivado-settings PATH.")
    if not args.skip_build:
        check_env = dict(os.environ, VIVADO_SETTINGS=str(settings))
        rc = run_streaming(["make", "check-vivado"], cwd=repo_root, env=check_env)
        if rc != 0:
            die(f"`make check-vivado` failed (exit {rc}). Vivado may be "
                f"installed but broken, or settings path wrong.")
    print(f"  vivado: {settings}")

    # Working tree clean, unless --allow-dirty. `git describe --dirty` only
    # flags modified tracked files, so untracked build caches don't poison
    # this check. A dry-run is allowed on a dirty tree regardless because
    # the result won't be published anyway.
    describe = git_describe()
    if describe.endswith("-dirty") and not args.allow_dirty and not args.dry_run:
        porcelain = must_run(["git", "status", "--porcelain"], "reading git status")
        die("Working tree is dirty (modified tracked files present). Pass "
            "--allow-dirty to publish anyway (the release tag will carry a "
            f"-dirty suffix).\nStatus:\n{porcelain}")
    print(f"  git: {describe}")

    # Informational only — building from other branches is allowed because
    # the operator might be on a feature branch and know what they're doing.
    branch = git_current_branch()
    if branch != "vivado-xilinx-flows":
        print(f"  WARNING: on branch '{branch}', not 'vivado-xilinx-flows'. "
              "This branch may not have the required Makefile targets.")


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------

def run_builds(flows: list[str], jobs: int, vivado_settings: str,
               repo_root: Path) -> list[str]:
    """Invoke one `make build-all-xilinx-<flow>` per requested flow. Sequential
    so that log streams are readable and a failing flow surfaces clearly.
    Returns the list of make targets that were invoked (for the manifest)."""
    print("\n=== Building bitstreams ===")
    targets: list[str] = []
    env = dict(os.environ, VIVADO_SETTINGS=vivado_settings)
    for flow in flows:
        target = f"build-all-xilinx-{flow}"
        targets.append(target)
        cmd = ["make", f"-j{jobs}", target]
        rc = run_streaming(cmd, cwd=repo_root, env=env)
        if rc != 0:
            die(f"`make {target}` failed (exit {rc}). No release will be "
                "published. Fix the build and re-run (optionally pass "
                "--skip-build on re-run if the fix is out-of-tree).")
    return targets


# ---------------------------------------------------------------------------
# Artifact collection
# ---------------------------------------------------------------------------

def discover_designs(repo_root: Path) -> list[str]:
    """Return design directory names under `designs/`, excluding the shared
    helper dirs (`_shared`, `_host`, etc.) whose names start with '_'."""
    designs_dir = repo_root / "designs"
    return sorted(
        d.name for d in designs_dir.iterdir()
        if d.is_dir() and not d.name.startswith("_") and not d.name.startswith(".")
    )


def collect_artifacts(repo_root: Path, requested_flows: set[str]) -> list[Artifact]:
    """Walk every `designs/*/build/<board>-<variant>-<flow>/gateware/*` and
    return one Artifact per bitstream-extension file whose flow is in
    `requested_flows`. Silently skips designs that don't have Vivado flow
    output (e.g. Fomu/TT FPGA targets, which are iCE40-only)."""
    artifacts: list[Artifact] = []
    for design in discover_designs(repo_root):
        build_dir = repo_root / "designs" / design / "build"
        if not build_dir.is_dir():
            continue
        for flow_dir in sorted(build_dir.iterdir()):
            if not flow_dir.is_dir():
                continue
            m = BUILD_DIR_RE.match(flow_dir.name)
            if not m:
                continue
            flow = m.group("flow")
            if flow not in requested_flows:
                continue
            gateware_dir = flow_dir / "gateware"
            if not gateware_dir.is_dir():
                continue
            for f in sorted(gateware_dir.iterdir()):
                if not f.is_file() or f.suffix not in BITSTREAM_EXTS:
                    continue
                board = m.group("board")
                variant = m.group("variant")
                # Include the source file stem in the staged name because
                # some boards produce multiple distinct bitstream flavors
                # per variant (Acorn emits default / fallback / operational
                # — all with the same extension). Appending the stem keeps
                # them disambiguated while preserving the
                # design_board-variant_flow grouping.
                staged_name = f"{design}_{board}-{variant}_{flow}_{f.stem}{f.suffix}"
                artifacts.append(Artifact(
                    source_path=f,
                    design=design,
                    board=board,
                    variant=variant,
                    flow=flow,
                    staged_name=staged_name,
                ))
    return artifacts


def hash_and_size_artifacts(artifacts: list[Artifact]) -> None:
    """Compute SHA-256 and size for each artifact in place."""
    for a in artifacts:
        a.size_bytes = a.source_path.stat().st_size
        a.sha256 = sha256_file(a.source_path)


def stage_artifacts(artifacts: list[Artifact], staging_dir: Path) -> None:
    """Copy each artifact into `staging_dir` under its canonical `staged_name`.
    Clears any prior files in the staging dir first so residue from a previous
    run can never end up attached to the new release."""
    staging_dir.mkdir(parents=True, exist_ok=True)
    for existing in staging_dir.iterdir():
        if existing.is_file():
            existing.unlink()
    for a in artifacts:
        shutil.copy2(a.source_path, staging_dir / a.staged_name)


# ---------------------------------------------------------------------------
# Manifest + checksums + release notes
# ---------------------------------------------------------------------------

def get_vivado_version(settings_path: str) -> str:
    """Return the `vivado -version` first line, or an explanation on failure."""
    if not Path(settings_path).is_file():
        return "(settings file missing)"
    # Xilinx's settings64.sh uses the bash-only `source` builtin internally,
    # so we must invoke bash (not /bin/sh, which is dash on Debian/Ubuntu).
    # `shlex.quote` protects against paths containing spaces or shell
    # metacharacters since settings_path comes from a CLI argument.
    cmd = f". {shlex.quote(settings_path)} && vivado -version | head -n 1"
    r = run_capture(["bash", "-c", cmd])
    if r.returncode != 0:
        return f"(vivado -version failed: {r.stderr.strip() or r.stdout.strip()})"
    return r.stdout.strip() or "(no output)"


def write_manifest(artifacts: list[Artifact], git: GitInfo, build: BuildSummary,
                   staging_dir: Path) -> Path:
    manifest = {
        "schema": 1,
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "git": {
            "describe": git.describe,
            "sha": git.sha,
            "branch": git.branch,
            "dirty": git.dirty,
        },
        "tool": {
            "vivado_version": build.vivado_version,
            "settings_path": build.vivado_settings,
        },
        "build": {
            "flows": build.flows,
            "make_targets": build.make_targets,
            "jobs": build.jobs,
        },
        "artifacts": [
            {
                "filename": a.staged_name,
                "design": a.design,
                "board": a.board,
                "variant": a.variant,
                "flow": a.flow,
                "size_bytes": a.size_bytes,
                "sha256": a.sha256,
            }
            for a in sorted(artifacts, key=lambda x: x.staged_name)
        ],
    }
    out = staging_dir / "manifest.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n")
    return out


def write_sha256sums(artifacts: list[Artifact], staging_dir: Path) -> Path:
    out = staging_dir / "SHA256SUMS"
    with out.open("w") as f:
        for a in sorted(artifacts, key=lambda x: x.staged_name):
            # Format matches `sha256sum -b` output: two-space separator is
            # required for `sha256sum -c` to parse correctly.
            f.write(f"{a.sha256}  {a.staged_name}\n")
    return out


def write_release_notes(artifacts: list[Artifact], git: GitInfo,
                        build: BuildSummary, staging_dir: Path,
                        repo: str) -> Path:
    lines: list[str] = []
    lines.append(f"# Vivado-built bitstreams — `{git.describe}`")
    lines.append("")
    lines.append(f"Built from commit [`{git.sha[:7]}`]"
                 f"(https://github.com/{repo}/commit/{git.sha}) on branch "
                 f"`{git.branch}`.")
    if git.dirty:
        lines.append("")
        lines.append("> **Warning:** this build was made from a **dirty** "
                     "working tree (uncommitted changes). It is not fully "
                     "reproducible from the source commit alone.")
    lines.append("")
    lines.append("## Build")
    lines.append("")
    lines.append(f"- Flows: `{', '.join(build.flows)}`")
    lines.append(f"- Make targets: `{', '.join(build.make_targets) or '(skipped)'}`")
    lines.append(f"- Vivado: `{build.vivado_version}`")
    lines.append(f"- Parallel jobs: `{build.jobs}`")
    lines.append("")
    lines.append("## Reproduce")
    lines.append("")
    lines.append("```")
    lines.append(f"git checkout {git.sha}")
    for t in build.make_targets:
        lines.append(f"make -j{build.jobs} {t}")
    lines.append("```")
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")

    # Group by design for easier scanning.
    by_design: dict[str, list[Artifact]] = {}
    for a in artifacts:
        by_design.setdefault(a.design, []).append(a)
    for design in sorted(by_design):
        lines.append(f"### `{design}`")
        lines.append("")
        lines.append("| File | Board | Variant | Flow | Size | SHA-256 |")
        lines.append("|------|-------|---------|------|-----:|:-------:|")
        for a in sorted(by_design[design], key=lambda x: x.staged_name):
            size_kb = max(1, a.size_bytes // 1024)
            short_hash = a.sha256[:12]
            lines.append(
                f"| `{a.staged_name}` | {a.board} | {a.variant} | {a.flow} "
                f"| {size_kb} KiB | `{short_hash}…` |"
            )
        lines.append("")

    lines.append("## Verify")
    lines.append("")
    lines.append("Download `SHA256SUMS` alongside the bitstreams and verify with:")
    lines.append("```")
    lines.append("sha256sum -c SHA256SUMS")
    lines.append("```")

    out = staging_dir / "RELEASE_NOTES.md"
    out.write_text("\n".join(lines) + "\n")
    return out


# ---------------------------------------------------------------------------
# GitHub release
# ---------------------------------------------------------------------------

def resolve_existing_release_action(
    tag: str, exists: bool, git_dirty: bool, allow_dirty: bool,
) -> tuple[str, str]:
    """Decide how to handle an existing release whose tag collides with ours.

    Returns (action, message) where action is one of:
      - "proceed"       — no existing release; publish normally
      - "replace_dirty" — existing dirty release to delete + recreate
      - "abort"         — clean release exists, never overwrite

    Split from main() so the safety-critical decision is directly unit-testable.
    """
    if not exists:
        return ("proceed", "")
    if git_dirty and allow_dirty:
        return ("replace_dirty", f"Existing dirty release {tag} — will replace.")
    return (
        "abort",
        f"Release {tag} already exists. Refusing to overwrite a clean "
        "release. If this is intentional, delete it manually with "
        "`gh release delete`.",
    )


def release_exists(repo: str, tag: str) -> bool:
    r = run_capture(["gh", "release", "view", tag, "--repo", repo])
    return r.returncode == 0


def delete_release(repo: str, tag: str) -> None:
    # --cleanup-tag removes the underlying git tag so `gh release create` can
    # recreate it cleanly at the new SHA.
    must_run(
        ["gh", "release", "delete", tag, "--repo", repo, "--yes", "--cleanup-tag"],
        f"deleting existing dirty release {tag}",
    )


def publish_release(repo: str, tag: str, target_sha: str, title: str,
                    notes_path: Path, staging_dir: Path) -> None:
    """Create the release with every staged file attached. The title is
    `Vivado-built bitstreams — <describe>`; the body is read from
    `notes_path` so the operator can inspect it before we commit."""
    # `gh release create` takes positional file arguments for attachments.
    # We attach every file in the staging dir — bitstreams, manifest.json,
    # SHA256SUMS, release notes themselves aren't attached (they become
    # the body instead).
    files = sorted(
        str(p) for p in staging_dir.iterdir()
        if p.is_file() and p.name != "RELEASE_NOTES.md"
    )
    cmd = [
        "gh", "release", "create", tag,
        "--repo", repo,
        "--target", target_sha,
        "--title", title,
        "--notes-file", str(notes_path),
        *files,
    ]
    rc = run_streaming(cmd)
    if rc != 0:
        die(f"`gh release create` failed (exit {rc}).")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def parse_flows(raw: str) -> list[str]:
    """Parse a comma-separated flows list, validate against VIVADO_FLOWS."""
    flows = [f.strip() for f in raw.split(",") if f.strip()]
    if not flows:
        raise argparse.ArgumentTypeError("at least one flow must be given")
    for f in flows:
        if f not in VIVADO_FLOWS:
            raise argparse.ArgumentTypeError(
                f"unknown flow {f!r}; expected one of {VIVADO_FLOWS}"
            )
    return flows


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Build Vivado-requiring bitstreams and publish to GitHub.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--flows", type=parse_flows, default=list(VIVADO_FLOWS),
        help=f"Comma-separated subset of {VIVADO_FLOWS}. "
             f"Default: both Vivado-requiring flows.",
    )
    p.add_argument(
        "--vivado-settings", default=DEFAULT_VIVADO_SETTINGS,
        help=f"Path to Vivado settings64.sh (default: {DEFAULT_VIVADO_SETTINGS})",
    )
    p.add_argument(
        "--tag-prefix", default=DEFAULT_TAG_PREFIX,
        help=f"Release tag prefix (default: {DEFAULT_TAG_PREFIX}). "
             f"Full tag is <prefix>-<git describe>.",
    )
    p.add_argument(
        "--repo", default=None,
        help="Override the GitHub owner/repo. Default: parsed from `git remote "
             "get-url origin`.",
    )
    p.add_argument(
        "--allow-dirty", action="store_true",
        help="Allow publishing from a dirty working tree. The tag will carry "
             "a -dirty suffix; existing dirty releases with the same tag are "
             "deleted and recreated.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Build + collect + write manifest, but do not call `gh release`. "
             "Staging dir is left populated for inspection.",
    )
    p.add_argument(
        "--skip-build", action="store_true",
        help="Skip the make invocation; assume bitstreams are already built. "
             "Useful after a manual build or a previous failed publish.",
    )
    p.add_argument(
        "--jobs", type=int, default=1,
        help="Parallel job count passed to `make -j`. Default: 1 (Vivado "
             "itself parallelizes internally).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    repo_root = find_repo_root()
    os.chdir(repo_root)

    preflight(args, repo_root)

    git = git_info()
    release_tag = f"{args.tag_prefix}-{git.describe}"
    repo = args.repo or detect_github_repo()
    print(f"\n  Repo: {repo}")
    print(f"  Tag:  {release_tag}")

    # Guard against accidentally overwriting a clean, immutable release. We
    # allow the dirty case because a -dirty tag is already a "this is
    # provisional" marker by construction.
    if not args.dry_run:
        action, msg = resolve_existing_release_action(
            release_tag,
            release_exists(repo, release_tag),
            git.dirty,
            args.allow_dirty,
        )
        if action == "replace_dirty":
            print(f"  {msg}")
            delete_release(repo, release_tag)
        elif action == "abort":
            die(msg)

    build = BuildSummary(
        flows=list(args.flows),
        jobs=args.jobs,
        vivado_settings=args.vivado_settings,
        vivado_version=get_vivado_version(args.vivado_settings),
    )
    if not args.skip_build:
        build.make_targets = run_builds(
            args.flows, args.jobs, args.vivado_settings, repo_root,
        )
    else:
        print("\n=== Skipping build (--skip-build) ===")

    print("\n=== Collecting artifacts ===")
    artifacts = collect_artifacts(repo_root, set(args.flows))
    if not artifacts:
        die("No bitstreams found for requested flows. Expected outputs under "
            "designs/*/build/*-{vivado-vivado,yosys-vivado}/gateware/. Did "
            "the build succeed?")
    print(f"  Found {len(artifacts)} bitstream(s).")
    hash_and_size_artifacts(artifacts)

    staging_dir = repo_root / STAGING_REL_PATH
    print(f"  Staging at {staging_dir}")
    stage_artifacts(artifacts, staging_dir)
    manifest_path = write_manifest(artifacts, git, build, staging_dir)
    sums_path = write_sha256sums(artifacts, staging_dir)
    notes_path = write_release_notes(artifacts, git, build, staging_dir, repo)
    print(f"  Wrote {manifest_path.name}, {sums_path.name}, {notes_path.name}")

    if args.dry_run:
        print("\n=== Dry run complete ===")
        print(f"  Would publish to: {repo} (tag: {release_tag})")
        print("  Staged artifacts:")
        for a in sorted(artifacts, key=lambda x: x.staged_name):
            print(f"    {a.staged_name}  ({a.size_bytes:>10} bytes, {a.sha256[:12]}…)")
        print("\n  Re-run without --dry-run to publish.")
        return 0

    print("\n=== Publishing release ===")
    title = f"Vivado-built bitstreams — {git.describe}"
    publish_release(repo, release_tag, git.sha, title, notes_path, staging_dir)

    print("\n=== Done ===")
    print(f"  Published {len(artifacts)} bitstream(s) as "
          f"https://github.com/{repo}/releases/tag/{release_tag}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
