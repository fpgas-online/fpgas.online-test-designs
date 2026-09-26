#!/usr/bin/env python3
"""Check that one LitePCIe driver build fits every Acorn image of the pinned release.

Design: docs/plans/2026-09-25-acorn-litepcie-packages-design.md (§3.2).

The driver is generated from the cle-215+ operational SoC at this commit, but it must work unchanged on all six
images of the release in packaging/acorn-pcie/release.toml (golden and operational, cle-215+, cle-215,
cle-101). Every `CSR_*` name and every SoC constant the driver and tools sources reference, including those
they only test with `#ifdef`, must agree between the generated headers and all six `csr.json`, in presence
(defined everywhere or nowhere) and in value. A name present on one side only changes what the driver
compiles to without any error, so it fails the check as surely as a moved address does.

How the header names map to csr.json (as LiteX exports them):

    CSR_BASE, CSR_SIZE     memories["csr"]["base"], ["size"]
    CSR_<NAME>_ADDR        csr_registers["<name>"]["addr"]
    CSR_<NAME>_SIZE        csr_registers["<name>"]["size"]
    CSR_<NAME>_BASE        csr_bases["<name>"]
    <NAME> (soc.h)         constants["<name>"]

Any other `CSR_*` name the sources use (a field's _OFFSET, say) has no csr.json counterpart and fails.

    uv run --no-project python packaging/acorn-litepcie/csr_check.py dist/driver
    uv run --no-project python packaging/acorn-litepcie/csr_check.py dist/driver --from-dir <staged release>
"""

import argparse
import ast
import dataclasses
import hashlib
import importlib.util
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
RELEASE_PIN = REPO / "packaging" / "acorn-pcie" / "release.toml"
IMAGE_COUNT = 6
GENERATED = ("csr.h", "soc.h", "mem.h")

_spec = importlib.util.spec_from_file_location("acorn_pcie_build_debs", REPO / "packaging/acorn-pcie/build_debs.py")
bits = importlib.util.module_from_spec(_spec)  # the bitstreams builder: its pin reader and fetchers
_spec.loader.exec_module(bits)

ABSENT = object()


class CheckError(Exception):
    pass


# -- the generated headers -------------------------------------------------------------------------------

_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)(?!\()(?:[ \t]+(.*?))?\s*$", re.M)
_INT_SUFFIX = re.compile(r"\b(0[xX][0-9a-fA-F]+|\d+)[uUlL]+\b")


def parse_defines(text):
    """Object-like #defines: name -> the replacement text ('' for a bare `#define NAME`)."""
    return {m.group(1): (m.group(2) or "").strip() for m in _DEFINE.finditer(text)}


def _eval_node(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp):
        ops = {ast.Add: int.__add__, ast.Sub: int.__sub__, ast.Mult: int.__mul__, ast.LShift: int.__lshift__,
               ast.BitOr: int.__or__}  # fmt: skip
        if type(node.op) in ops:
            return ops[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    raise ValueError(ast.dump(node))


def evaluate(defines):
    """name -> int, str (a string literal), or None (a bare #define). Integer expressions are evaluated,
    names inside them resolved from the same headers; what cannot be evaluated is kept as its text."""
    out = {}

    def value(name, seen=()):
        if name in out:
            return out[name]
        text = defines[name]
        if not text:
            result = None
        elif text.startswith('"') and text.endswith('"'):
            try:
                result = ast.literal_eval(text)
            except (SyntaxError, ValueError):  # a C escape Python does not accept: compare the text
                result = text
        else:
            expr = _INT_SUFFIX.sub(r"\1", text)
            for ident in set(re.findall(r"\b[A-Za-z_]\w*\b", expr)):
                if ident not in defines or ident in seen:
                    return text
                inner = value(ident, (*seen, name))
                if not isinstance(inner, int):
                    return text
                expr = re.sub(rf"\b{ident}\b", str(inner), expr)
            try:
                result = _eval_node(ast.parse(expr, mode="eval").body)
            except (SyntaxError, ValueError):
                result = text
        out[name] = result
        return result

    for name in defines:
        value(name)
    return out


def header_values(driver_dir):
    kernel = pathlib.Path(driver_dir) / "kernel"
    text = "\n".join((kernel / name).read_text() for name in GENERATED if (kernel / name).exists())
    return evaluate(parse_defines(text))


# -- the sources -----------------------------------------------------------------------------------------

_COMMENT_OR_STRING = re.compile(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'', re.S)


def referenced_names(driver_dir):
    """Every identifier in the driver and tools sources, outside comments and strings, generated headers
    excluded."""
    names = set()
    for sub in ("kernel", "user"):
        for path in sorted((pathlib.Path(driver_dir) / sub).rglob("*")):
            if path.suffix not in (".c", ".h") or (sub == "kernel" and path.name in GENERATED):
                continue
            code = _COMMENT_OR_STRING.sub(" ", path.read_text(errors="replace"))
            names |= set(re.findall(r"\b[A-Za-z_]\w*\b", code))
    return names


# -- csr.json ----------------------------------------------------------------------------------------------


def json_value(csr, name):
    """What `csr` says for header name `name`: ABSENT, or the value. CheckError if the name maps to nothing."""
    if name in ("CSR_BASE", "CSR_SIZE"):
        return csr.get("memories", {}).get("csr", {}).get(name[4:].lower(), ABSENT)
    if name.startswith("CSR_"):
        m = re.fullmatch(r"CSR_(\w+)_(ADDR|SIZE|BASE)", name)
        if not m:
            raise CheckError(f"{name}: cannot map it to csr.json (only _ADDR, _SIZE and _BASE have a counterpart)")
        key, kind = m.group(1).lower(), m.group(2)
        if kind == "BASE":
            return csr.get("csr_bases", {}).get(key, ABSENT)
        register = csr.get("csr_registers", {}).get(key)
        return ABSENT if register is None else register.get(kind.lower(), ABSENT)
    return csr.get("constants", {}).get(name.lower(), ABSENT)


def _same(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return a.casefold() == b.casefold()  # csr.json lower-cases string constants
    return a == b


def _show(v):
    if v is ABSENT:
        return "absent"
    return f"{v:#x}" if isinstance(v, int) and v >= 0x1000 else repr(v)


@dataclasses.dataclass
class Row:
    name: str
    header: object
    problem: str | None


def compare(driver_dir, csrs):
    """One Row per checked name: every referenced CSR_* name, and every referenced name that soc.h or any
    image's constants define."""
    headers = header_values(driver_dir)
    names = referenced_names(driver_dir)
    constants = {k.upper() for csr in csrs.values() for k in csr.get("constants", {})}
    soc = parse_defines((pathlib.Path(driver_dir) / "kernel" / "soc.h").read_text())
    checked = sorted(n for n in names if n.startswith("CSR_") or n in soc or n in constants)
    rows = []
    for name in checked:
        header = headers.get(name, ABSENT)
        try:
            seen = {image: json_value(csr, name) for image, csr in sorted(csrs.items())}
        except CheckError as e:
            rows.append(Row(name, header, str(e)))
            continue
        bad = {image: v for image, v in seen.items() if (v is ABSENT) != (header is ABSENT) or not _same(v, header)}
        problem = None
        if bad:
            where = ", ".join(f"{image} {_show(v)}" for image, v in bad.items())
            problem = f"{name}: the generated headers have {_show(header)}, but {where}"
        rows.append(Row(name, header, problem))
    return rows


def check(driver_dir, csrs):
    """The problems; an empty list means the driver fits every image."""
    if len(csrs) != IMAGE_COUNT:
        return [f"expected the six csr.json of the release, got {len(csrs)}: {sorted(csrs)}"]
    rows = compare(driver_dir, csrs)
    if not any(r.name.startswith("CSR_") for r in rows):
        return [f"{driver_dir} references no CSR at all: not a LitePCIe driver tree"]
    return [r.problem for r in rows if r.problem]


# -- the release -------------------------------------------------------------------------------------------


def fetch_release_csrs(pin=RELEASE_PIN, from_dir=None):
    """{image variant: csr.json} for the pinned release, each file checked against the pinned manifest."""
    try:
        p = bits.read_pin(pin)
    except bits.BuildError as e:
        raise CheckError(str(e)) from None
    fetch = bits.local_fetcher(from_dir) if from_dir else bits.release_fetcher(p["repo"], p["tag"])
    raw = fetch("manifest.json")
    if hashlib.sha256(raw).hexdigest() != p["manifest_sha256"]:
        raise CheckError(f"the manifest of {p['tag']} does not match {pin}'s manifest_sha256")
    manifest = json.loads(raw)
    if manifest.get("tag") != p["tag"]:
        raise CheckError(f"the manifest names release {manifest.get('tag')!r}, not {p['tag']!r}")
    csrs = {}
    for entry in manifest["files"]:
        if entry["file"] != "csr.json":
            continue
        data = fetch(entry["asset"])
        if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise CheckError(f"{entry['asset']} does not match its manifest size/sha256")
        csrs[entry["variant"]] = json.loads(data)
    if len(csrs) != IMAGE_COUNT:
        raise CheckError(f"release {p['tag']} has {len(csrs)} csr.json, not {IMAGE_COUNT}: {sorted(csrs)}")
    return csrs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("driver", type=pathlib.Path, help="the generated driver tree (kernel/, user/)")
    parser.add_argument("--from-dir", type=pathlib.Path, help="a staged release instead of the GitHub Release")
    parser.add_argument("--pin", type=pathlib.Path, default=RELEASE_PIN)
    args = parser.parse_args(argv)
    try:
        csrs = fetch_release_csrs(args.pin, args.from_dir)
    except CheckError as e:
        sys.exit(f"error: {e}")
    rows = compare(args.driver, csrs)
    for r in rows:
        print(f"{'FAIL' if r.problem else 'ok  '} {r.name} = {_show(r.header)}")
    problems = check(args.driver, csrs)
    sys.stdout.flush()
    if problems:
        print(f"\n{len(problems)} problem(s): this driver does not fit every image of the release", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"\n{len(rows)} names agree across the generated headers and {', '.join(sorted(csrs))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
