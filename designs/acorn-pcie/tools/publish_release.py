#!/usr/bin/env python3
"""Publish built fpgas.online Acorn PCIe SoC images as a GitHub Release.

The images on the fleet's flash carry a build timestamp in their identifier
(`ident_version`), so a rebuild never reproduces them: the release is made
from the build tree that was actually flashed, not from a fresh build.

For each variant directory under the build tree (`acorn-<variant>[-golden]`,
as acorn_pcie_soc.py writes them) this takes the three images Vivado leaves
in gateware/ (`sqrl_acorn.bin`, `_fallback.bin`, `_operational.bin`, and
their .bit files) plus `csr.json` and `csr.csv`, and writes next to them:

  * manifest.json - per file: variant, golden, config_identifier (from
    csr.json), size, sha256, source commit, toolchain + version (from the
    .bit header), the IDCODE in the image, and the flash slot the image is
    for. The slot is read from the image's own configuration header with
    spi_flash.py's parser and slot check, the same one `spi_flash.py write`
    runs before it erases anything: `_fallback` chain-loads 0x400000 so it
    goes at 0x000000, `_operational` has the watchdog so it goes at
    0x400000, and the plain image is for loading into SRAM over JTAG only.
  * SHA256SUMS - `sha256sum -c` format, covering every asset and the manifest.

Asset names are `<variant dir>-<file>` with `+` spelled `p`, so they are
unique across variants. The tag is
`vivado-bitstreams-acorn-pcie-<commit date YYYYMMDD>-g<12-char sha>`, made
from the source commit alone. `git describe` would depend on which tags the
clone has (a shallow clone gives a bare sha) and would nest once a release
tag exists. Tag ruleset 13744509 lets the `vivado-bitstreams-` prefix through.

The build tree does not record which commit it was built from, so
`--source-commit` is corroborated. The worktree the build tree lives in must
have that commit checked out, with no uncommitted changes under designs/
(build/ itself is ignored). `--unverified-source-commit` skips the check, and
the manifest says so either way.

    uv run python designs/acorn-pcie/tools/publish_release.py \\
        --build-dir .worktrees/acorn-pcie-04-soc-board-id/designs/acorn-pcie/build \\
        --source-commit f3355dc                        # stage only
    ... --publish                                      # and create the release
"""

import argparse
import hashlib
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

_HERE = pathlib.Path(__file__).resolve()
_REPO = _HERE.parents[3]
_spec = importlib.util.spec_from_file_location(
    "spi_flash", _REPO / "verify" / "src" / "fpgas_online_verify" / "boards" / "acorn" / "spi_flash.py"
)
spi_flash = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(spi_flash)

TAG_PREFIX = "vivado-bitstreams-acorn-pcie"
SCHEMA_VERSION = 1
PLATFORM = "sqrl_acorn"
IMAGES = ("", "_fallback", "_operational")
CSR_FILES = ("csr.json", "csr.csv")
# The 28-bit IDCODE (silicon revision masked off) each variant's part reports.
PART_IDCODE = {"cle-215+": 0x3636093, "cle-215": 0x3636093, "cle-101": 0x3631093}
SLOTS = (spi_flash.GOLDEN_ADDR, spi_flash.OPERATIONAL_ADDR)
DEFAULT_OUT = _REPO / "tmp" / "acorn-pcie-release"


class ReleaseError(Exception):
    pass


def _slot_name(addr):
    return f"{addr:#08x}"


def asset_prefix(variant_dir):
    return variant_dir.replace("+", "p")


def release_tag(commit, date):
    """The release's name, from the commit alone: never from the tags a clone happens to have."""
    return f"{TAG_PREFIX}-{date}-g{commit[:12]}"


def _git_in(cwd, *args):
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, env={**os.environ, "TZ": "UTC"})
    if result.returncode:
        raise ReleaseError(f"git {' '.join(args)} in {cwd}: {result.stderr.strip()}")
    return result.stdout.strip()


def source_identity(repo_dir, rev):
    """The full sha and UTC committer date (YYYYMMDD) of `rev`."""
    commit = _git_in(repo_dir, "rev-parse", "--verify", f"{rev}^{{commit}}")
    date = _git_in(repo_dir, "log", "-1", "--format=%cd", "--date=format-local:%Y%m%d", commit)
    return {"commit": commit, "date": date}


def verify_source(build_dir, commit, unverified=False):
    """Corroborate that `build_dir` was built from `commit`. Returns what was checked, for the manifest."""
    build_dir = pathlib.Path(build_dir).resolve()
    try:
        top = _git_in(build_dir, "rev-parse", "--show-toplevel")
        head = _git_in(top, "rev-parse", "HEAD")
        dirty = _git_in(top, "status", "--porcelain", "--", "designs")
    except (ReleaseError, FileNotFoundError, NotADirectoryError) as e:
        if unverified:
            return "NOT CHECKED (--unverified-source-commit): the build dir is not in a git worktree"
        raise ReleaseError(f"cannot corroborate --source-commit: {build_dir} is not in a git worktree ({e})") from None
    problems = []
    if head != commit:
        problems.append(f"its worktree {top} has {head[:12]} checked out, not {commit[:12]}")
    if dirty:
        problems.append(f"{top} has uncommitted changes under designs/:\n{dirty}")
    if problems and not unverified:
        raise ReleaseError("cannot corroborate --source-commit: " + "; ".join(problems))
    if problems:
        return "NOT CHECKED (--unverified-source-commit): " + "; ".join(problems)
    return (
        f"build dir's worktree HEAD is {commit[:12]}, no uncommitted changes under designs/ (checked at publish time)"
    )


def bit_header(data):
    """Fields of a .bit file's header: design/userid/version string, part, date, time."""
    if data[:2] != b"\x00\x09":
        raise ReleaseError("not a Xilinx .bit file (bad header length)")
    pos = 2 + 9
    pos += 2  # the 0x0001 that precedes the first key
    fields = {}
    while pos < len(data):
        key = data[pos : pos + 1]
        pos += 1
        if key == b"e":
            break
        length = int.from_bytes(data[pos : pos + 2], "big")
        pos += 2
        fields[key.decode()] = data[pos : pos + length].rstrip(b"\x00").decode()
        pos += length
    if "a" not in fields:
        raise ReleaseError("a .bit header without its design field")
    design = dict(kv.split("=", 1) for kv in fields["a"].split(";")[1:] if "=" in kv)
    return {"design": fields["a"].split(";")[0], "version": design.get("Version"), "part": fields.get("b")}


def _slot_for(path, data, variant):
    """The flash slot an image is for, checked against what its file name says it is."""
    try:
        info = spi_flash.image_info(data)
    except spi_flash.FlashError as e:
        raise ReleaseError(f"{path}: {e}") from None
    want = PART_IDCODE[variant]
    if info["idcode"] is None or (info["idcode"] & spi_flash.IDCODE_MASK) != want:
        found = "none" if info["idcode"] is None else f"{info['idcode']:#010x}"
        raise ReleaseError(f"{path}: image IDCODE {found} is not the {variant} part's {want:#09x}")
    accepted = []
    for addr in SLOTS:
        try:
            spi_flash.check_image_for_slot(addr, data, info["idcode"], allow_golden=True)
        except spi_flash.FlashError:
            continue
        accepted.append(addr)
    name = path.name
    expected = {
        f"{PLATFORM}_fallback": [spi_flash.GOLDEN_ADDR],
        f"{PLATFORM}_operational": [spi_flash.OPERATIONAL_ADDR],
        PLATFORM: [],
    }[path.stem]
    if accepted != expected:
        role = "golden-slot (fallback)" if "fallback" in name else "operational" if "operational" in name else "plain"
        got = ", ".join(map(_slot_name, accepted)) or "no slot"
        raise ReleaseError(f"{path}: a {role} image, but its header makes it fit {got}")
    return (_slot_name(accepted[0]) if accepted else None), f"{info['idcode']:#010x}"


def _variant_of(dirname):
    if not dirname.startswith("acorn-"):
        raise ReleaseError(f"{dirname}: not an acorn-<variant> build directory")
    variant = dirname[len("acorn-") :]
    base = variant.removesuffix("-golden")
    if base not in PART_IDCODE:
        raise ReleaseError(f"{dirname}: unknown variant {base!r}")
    return variant, base, variant.endswith("-golden")


def collect(build_dir, source, variants=None):
    """Check a build tree and describe it. Returns (manifest, {asset name: source path}).

    `source` is {"commit", "date", "evidence"}: the source_identity() of the
    commit the tree was built from plus what verify_source() found.
    """
    build_dir = pathlib.Path(build_dir)
    source_commit = source["commit"]
    dirs = sorted(p for p in build_dir.iterdir() if p.is_dir() and p.name.startswith("acorn-"))
    if variants is not None:
        wanted = {f"acorn-{v}" for v in variants}
        missing = wanted - {d.name for d in dirs}
        if missing:
            raise ReleaseError(f"no build for {', '.join(sorted(missing))} under {build_dir}")
        dirs = [d for d in dirs if d.name in wanted]
    if not dirs:
        raise ReleaseError(f"no acorn-<variant> build directories under {build_dir}")

    files, staged, layout = [], {}, {}
    for vdir in dirs:
        variant, base, golden = _variant_of(vdir.name)
        csr_json = vdir / "csr.json"
        if not csr_json.exists():
            raise ReleaseError(f"{csr_json} is missing")
        ident = json.loads(csr_json.read_text())["constants"]["config_identifier"]
        if (" golden " in f" {ident} ") != golden:
            raise ReleaseError(f"{vdir.name}: identifier {ident!r} disagrees about being golden")

        sources = [vdir / "gateware" / f"{PLATFORM}{s}{ext}" for s in IMAGES for ext in (".bin", ".bit")]
        sources += [vdir / f for f in CSR_FILES]
        for src in sources:
            if not src.exists():
                raise ReleaseError(f"{src} is missing ({src.name})")

        versions = set()
        for src in sources:
            if src.suffix == ".bit":
                versions.add(bit_header(src.read_bytes())["version"])
        if len(versions) != 1 or None in versions:
            raise ReleaseError(
                f"{vdir.name}: .bit headers disagree on the Vivado version: {sorted(map(str, versions))}"
            )
        toolchain = {"name": "vivado", "version": versions.pop()}

        prefix = asset_prefix(vdir.name)
        for src in sources:
            data = src.read_bytes()
            slot, idcode = None, None
            if src.suffix == ".bin":
                slot, idcode = _slot_for(src, data, base)
            elif src.suffix == ".bit":
                idcode = f"{spi_flash.image_info(data)['idcode']:#010x}"
            asset = f"{prefix}-{src.name}"
            if asset in staged:
                raise ReleaseError(f"two files would be published as {asset}")
            staged[asset] = src
            files.append(
                {
                    "asset": asset,
                    "variant": variant,
                    "golden": golden,
                    "file": src.name,
                    "config_identifier": ident,
                    "slot": slot,
                    "idcode": idcode,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "source_commit": source_commit,
                    "toolchain": toolchain,
                }
            )
            if slot is not None and golden == (slot == _slot_name(spi_flash.GOLDEN_ADDR)):
                layout.setdefault(base, {})[slot] = asset

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "design": "designs/acorn-pcie (fpgas.online Acorn PCIe SoC)",
        "source_commit": source_commit,
        "source_commit_date": source["date"],
        "source_commit_evidence": source["evidence"],
        "tag": release_tag(source_commit, source["date"]),
        # What goes where on each board: the golden build's fallback image in
        # the golden slot, the operational build's operational image above it.
        "flash_layout": {b: dict(sorted(s.items())) for b, s in sorted(layout.items())},
        "files": files,
    }
    return manifest, staged


def _check_out_dir(out_dir, build_dir):
    """Refuse a staging directory that overlaps the build tree or holds anything a previous run did not stage."""
    out, build = out_dir.resolve(), build_dir.resolve()
    if out == build or build in out.parents or out in build.parents:
        raise ReleaseError(f"--out {out_dir} overlaps --build-dir {build_dir}: refusing to touch the build tree")
    if not out.exists():
        return []
    if not out.is_dir():
        raise ReleaseError(f"--out {out_dir} exists and is not a directory")
    present = {p.name for p in out.iterdir()}
    if not present:
        return []
    sums = out / "SHA256SUMS"
    listed = set()
    if sums.is_file() and (out / "manifest.json").is_file():
        listed = {line.split("  ", 1)[1] for line in sums.read_text().splitlines() if "  " in line}
    unknown = sorted(present - listed - {"SHA256SUMS"})
    if not listed or unknown or any(not (out / n).is_file() for n in present):
        shown = ", ".join(unknown[:5]) or "no SHA256SUMS/manifest.json"
        raise ReleaseError(f"--out {out_dir} is not empty and not a previous staging directory ({shown})")
    return [out / n for n in sorted(present)]


def stage(manifest, staged, out_dir, build_dir):
    out_dir, build_dir = pathlib.Path(out_dir), pathlib.Path(build_dir)
    for old in _check_out_dir(out_dir, build_dir):
        old.unlink()
    out_dir.mkdir(parents=True, exist_ok=True)
    for asset, src in staged.items():
        shutil.copyfile(src, out_dir / asset)
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    names = [*sorted(staged), "manifest.json"]
    sums = "".join(f"{hashlib.sha256((out_dir / n).read_bytes()).hexdigest()}  {n}\n" for n in names)
    (out_dir / "SHA256SUMS").write_text(sums)
    return [out_dir / n for n in names] + [out_dir / "SHA256SUMS"]


def release_notes(manifest):
    lines = [
        f"fpgas.online Acorn PCIe SoC images built with Vivado from {manifest['source_commit'][:12]} "
        f"(committed {manifest['source_commit_date']}).",
        "",
        f"Source commit evidence: {manifest['source_commit_evidence']}.",
        "",
        "Each board gets the golden build's fallback image at 0x000000 and the operational build's "
        "operational image at 0x400000 (`fpgas-acorn-flash write <file> <slot>`). The plain `sqrl_acorn.bin`/`.bit` "
        "are for loading into SRAM over JTAG only. `manifest.json` has every file's identifier, slot and "
        "sha256; `sha256sum -c SHA256SUMS` checks a download.",
        "",
        "| board | slot | asset | identifier |",
        "|---|---|---|---|",
    ]
    by_asset = {f["asset"]: f for f in manifest["files"]}
    for board, slots in manifest["flash_layout"].items():
        for slot, asset in slots.items():
            lines.append(f"| {board} | {slot} | `{asset}` | `{by_asset[asset]['config_identifier']}` |")
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--build-dir", required=True, type=pathlib.Path, help="designs/acorn-pcie/build to publish")
    parser.add_argument(
        "--source-commit",
        required=True,
        help="the commit the build tree was built from (the build tree does not record it)",
    )
    parser.add_argument(
        "--unverified-source-commit",
        action="store_true",
        help="publish even though the build dir's worktree does not show --source-commit checked out and clean",
    )
    parser.add_argument("--variants", nargs="+", help="variant directories to include (default: all)")
    parser.add_argument("--out", type=pathlib.Path, default=DEFAULT_OUT, help="staging directory")
    parser.add_argument("--repo", default="fpgas-online/fpgas.online-test-designs")
    parser.add_argument("--publish", action="store_true", help="create the GitHub Release (default: stage only)")
    args = parser.parse_args(argv)

    try:
        source = source_identity(_REPO, args.source_commit)
        source["evidence"] = verify_source(args.build_dir, source["commit"], args.unverified_source_commit)
        manifest, staged = collect(args.build_dir, source, args.variants)
        paths = stage(manifest, staged, args.out, args.build_dir)
    except ReleaseError as e:
        sys.exit(f"error: {e}")
    commit = source["commit"]
    print(f"source commit {commit[:12]}: {source['evidence']}")
    notes = args.out.parent / f"{args.out.name}-notes.md"
    notes.write_text(release_notes(manifest))
    print(f"staged {len(paths)} files in {args.out} for {manifest['tag']}")
    for board, slots in manifest["flash_layout"].items():
        for slot, asset in slots.items():
            print(f"  {board:9} {slot}  {asset}")
    if not args.publish:
        print("dry run: pass --publish to create the release")
        return
    subprocess.run(
        [
            "gh", "release", "create", manifest["tag"], *map(str, paths),
            "--repo", args.repo, "--target", commit,
            "--title", f"Acorn PCIe SoC images - {manifest['tag']}", "--notes-file", str(notes),
        ],
        check=True,
    )  # fmt: skip


if __name__ == "__main__":
    main()
