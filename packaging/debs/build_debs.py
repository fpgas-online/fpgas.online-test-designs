#!/usr/bin/env python3
"""Build every fpgas-online-verify deb: the shared core, and each board's tools, debug tools, bitstreams and
mode package, plus the multi-board ones (docs/plans/2026-09-26-fpgas-online-verify-design.md).

  fpgas-online-verify           the fpgas_online_verify Python package without its boards, the host test
                                scripts, fpgas-verify and fpgas-verify.service (enabled by a mode package)
  fpgas-online-<b>-tools        the board's module, fpgas-<b>-verify; only the board's own tooling
  fpgas-online-<b>-debug        fpgas-<b>-debug and what the tests the boot check leaves out need
  fpgas-online-<b>-bitstreams   the test boards': this commit's CI bitstreams and a manifest. The Acorn's come
                                from its pinned Vivado release (packaging/acorn-pcie/build_debs.py)
  fpgas-online-<b>              the mode package: this host has board <b>. Conflicts with every other one
  fpgas-online-multi-board      the mode package for fpga-board = auto: whichever installed board is there
  fpgas-online-all-boards       fpgas-online-multi-board and every board's tools

Everything but the Acorn's bitstreams is versioned by the repository (`X.Y.postN` from git describe), and a
board's packages depend on exactly each other's version. Every test bitstream must be in the bundle: a
missing one fails the build rather than ship a board that cannot be checked.

    uv run --python 3.12 packaging/debs/build_debs.py --bitstreams bitstreams/ --out dist/
"""

import argparse
import hashlib
import importlib.util
import inspect
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = REPO / "verify" / "src"
PKG = SRC / "fpgas_online_verify"
sys.path.insert(0, str(SRC))

from fpgas_online_verify import host_tests  # noqa: E402
from fpgas_online_verify.board import installed  # noqa: E402
from fpgas_online_verify.testbench import TestBoard  # noqa: E402

_spec = importlib.util.spec_from_file_location("acorn_build_debs", REPO / "packaging" / "acorn-pcie" / "build_debs.py")
acorn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(acorn)  # the pin, the Acorn's bitstreams deb, git_version and run_nfpm

BuildError = acorn.BuildError
DIST = "/usr/lib/python3/dist-packages/fpgas_online_verify"
MODE_DIR = "/usr/share/fpgas-online/verify/mode.d"
MODE = "fpgas-online-verify-mode"  # virtual: every mode package Provides and Conflicts it, so there is one
EXE = {"file_info": {"mode": 0o755}}
DATA = {"file_info": {"mode": 0o644}}
OPENFPGALOADER = "openfpgaloader-fpgasonline | openfpgaloader-fpgasonline-git | openfpgaloader"
# What each board's verify needs, and nothing it does not: the Acorn's is PCIe and the stdlib.
TOOLS_DEPENDS = {
    "acorn": [],
    "arty": ["python3-serial", OPENFPGALOADER],
    "netv2": ["python3-serial", OPENFPGALOADER, "openocd"],
    "fomu": ["python3-serial", OPENFPGALOADER],
    "tt": ["python3-serial"],
}
TOOLS_RECOMMENDS = {"tt": ["micropython-mpremote"]}  # in trixie; only bookworm-backports has it for bookworm
# What fpgas-<b>-debug needs on top: the Acorn's conversion from SQRL's factory image loads a .bit over JTAG,
# and fpgas-acorn-flash --uart talks UARTBone; the PMOD tests read GPIOs; the Ethernet test configures a link.
DEBUG_DEPENDS = {
    "acorn": [OPENFPGALOADER, "python3-serial"],
    "arty": ["python3-libgpiod"],
    "netv2": ["python3-libgpiod"],
    "fomu": ["python3-libgpiod"],
    "tt": ["python3-libgpiod"],
}
ETHERNET = ["iproute2", "iputils-ping", "iputils-arping | arping", "sudo"]
BOARDS = installed()


def _common(name, version, description):
    return {
        "name": name,
        "arch": "all",
        "platform": "linux",
        "version": version,
        "version_schema": "none",  # keep 0.0.post590 as it is: nfpm's semver parsing would rewrite it
        "maintainer": acorn.MAINTAINER,
        "homepage": acorn.HOMEPAGE,
        "license": "Apache-2.0",
        "description": description,
    }


def _py(src, rel):
    return {"src": str(src), "dst": f"{DIST}/{rel}", **DATA}


def board_files(board):
    """(source, path under fpgas_online_verify) of a board's module: one file, or a package directory."""
    module = inspect.getmodule(type(board))
    path = pathlib.Path(module.__file__)
    files = sorted(path.parent.glob("*.py")) if path.name == "__init__.py" else [path]
    return [(f, f.relative_to(PKG).as_posix()) for f in files]


def core_files():
    board_dirs = PKG / "boards"
    return [(f, f.relative_to(PKG).as_posix()) for f in sorted(PKG.rglob("*.py")) if board_dirs not in f.parents]


def wrapper(staging, command, call):
    """A /usr/bin script. No bytecode: root running it would leave __pycache__ in dist-packages, which dpkg
    does not own."""
    path = pathlib.Path(staging) / command
    path.write_text(
        f"#!/usr/bin/python3\nimport sys\n\nsys.dont_write_bytecode = True\n{call[0]}\n\nsys.exit({call[1]}())\n"
    )
    path.chmod(0o755)
    return {"src": str(path), "dst": f"/usr/bin/{command}", **EXE}


BOARD_MAIN = ("from fpgas_online_verify.cli import board_main", "board_main")


# -- the shared core, and the multi-board packages ----------------------------------------------------------


def verify_nfpm(version, staging):
    scripts = [
        {"src": str(REPO / src), "dst": f"{DIST}/scripts/{name}", **DATA} for name, src in host_tests.SCRIPTS.items()
    ]
    return {
        **_common("fpgas-online-verify", version, (
            "fpgas.online boot-time FPGA board verification (core)\n"
            "fpgas-verify checks the board (or boards) the host is set up for with the fpgas.online test\n"
            "bitstreams and compares it with the state recorded last time. Each board's module comes in\n"
            "fpgas-online-<board>-tools; install fpgas-online-<board> (or fpgas-online-all-boards) to set a host up."
        )),
        "depends": ["python3 (>= 3.9)"],
        "suggests": ["fpgas-online-all-boards", "fpgas-online-setup-pi"],  # fleet-event, for publishing
        "contents": [
            *(_py(src, rel) for src, rel in core_files()),
            *scripts,
            wrapper(staging, "fpgas-verify", ("from fpgas_online_verify.cli import verify_main", "verify_main")),
            {"src": str(HERE / "fpgas-verify.service"), "dst": "/usr/lib/systemd/system/fpgas-verify.service", **DATA},
            {"dst": MODE_DIR, "type": "dir", "file_info": {"mode": 0o755}},
        ],
    }  # fmt: skip


def mode_nfpm(name, version, setting, depends, description, staging):
    ini = pathlib.Path(staging) / f"{name}.ini"
    ini.write_text(f"# Installed by {name}: which board(s) fpgas-verify checks. Override in /etc/fpgas-verify/*.ini.\n"
                   f"[verify]\nfpga-board = {setting}\n")  # fmt: skip
    return {
        **_common(name, version, description),
        "depends": depends,
        "provides": [MODE],
        "conflicts": [MODE],
        "contents": [{"src": str(ini), "dst": f"{MODE_DIR}/{name}.ini", **DATA}],
        "scripts": {"postinstall": str(HERE / "mode.postinst"), "postremove": str(HERE / "mode.postrm")},
    }


def multi_board_nfpm(version, staging):
    return mode_nfpm("fpgas-online-multi-board", version, "auto", [f"fpgas-online-verify (= {version})"], (
        "fpgas.online boot-time check: whichever installed board is there\n"
        "Sets fpgas-verify to fpga-board = auto and enables it at boot: it looks for every board whose\n"
        "fpgas-online-<board>-tools is installed, and finding none is a fatal error. Install the boards'\n"
        "tools packages alongside (or fpgas-online-all-boards for every board)."
    ), staging)  # fmt: skip


def all_boards_nfpm(version):
    return {
        **_common("fpgas-online-all-boards", version, (
            "fpgas.online boot-time check for every FPGA board\n"
            "fpgas-online-multi-board and every board's tools, so a netboot root verifies whichever board the\n"
            "booting Pi has: Acorn, Arty A7, NeTV2, Fomu EVT or TT FPGA. Recommends each board's debug tools."
        )),
        "depends": [f"fpgas-online-multi-board (= {version})",
                    *(f"{b.package} (= {version})" for b in BOARDS.values())],
        "recommends": [f"fpgas-online-{b.slug}-debug" for b in BOARDS.values()],
    }  # fmt: skip


# -- a board's packages ----------------------------------------------------------------------------------------


def tools_nfpm(board, version, bitstreams, staging):
    contents = [_py(src, rel) for src, rel in board_files(board)]
    contents.append(wrapper(staging, f"fpgas-{board.slug}-verify", BOARD_MAIN))
    if board.name == "acorn":
        contents.append(wrapper(staging, "fpgas-acorn-flash",
                                ("from fpgas_online_verify.boards.acorn.spi_flash import main", "main")))  # fmt: skip
    what = (
        f"loads each of its test designs ({', '.join(board.verify_tests)}) and runs its host test"
        if isinstance(board, TestBoard)
        else "checks the running image and the flash over PCIe, reading only"
    )
    return {
        **_common(board.package, version, (
            f"fpgas.online {board.title} check\n"
            f"fpgas-{board.slug}-verify finds the {board.title}, {what},\n"
            "and records its identity and flash so a later change is caught. Set a host up for it with\n"
            f"fpgas-online-{board.slug}, which runs it at boot."
        )),
        "depends": [f"fpgas-online-verify (= {version})", f"fpgas-online-{board.slug}-bitstreams (= {bitstreams})",
                    *TOOLS_DEPENDS[board.name]],
        **({"recommends": TOOLS_RECOMMENDS[board.name]} if board.name in TOOLS_RECOMMENDS else {}),
        "suggests": [f"fpgas-online-{board.slug}-debug"],
        "contents": contents,
    }  # fmt: skip


def debug_nfpm(board, version, staging):
    recommends = ["kmod"] if isinstance(board, TestBoard) else []  # rmmod: the PMOD tests free the SPI pins
    if isinstance(board, TestBoard) and "ethernet" in board.tests:
        recommends += ETHERNET
    extra = [t for t in getattr(board, "tests", {}) if not board.tests[t].get("verify")]
    what = (f"loads any test design and runs its test with its output live, including the tests the\n"
            f"boot check leaves out ({', '.join(extra)})." if extra else
            "reads the running build and the flash's identity; with openFPGALoader, a board still on SQRL's\n"
            "factory image can be converted.")  # fmt: skip
    return {
        **_common(f"fpgas-online-{board.slug}-debug", version, (
            f"fpgas.online {board.title} debugging tools\n"
            f"For when fpgas-{board.slug}-verify fails: fpgas-{board.slug}-debug detects the board and\n{what}"
        )),
        "depends": [f"{board.package} (= {version})", *DEBUG_DEPENDS[board.name]],
        **({"recommends": recommends} if recommends else {}),
        "contents": [wrapper(staging, f"fpgas-{board.slug}-debug", BOARD_MAIN)],
    }  # fmt: skip


def board_mode_nfpm(board, version, staging):
    return mode_nfpm(f"fpgas-online-{board.slug}", version, board.name, [f"{board.package} (= {version})"], (
        f"fpgas.online boot-time check for a {board.title}\n"
        f"Sets this host up as having a {board.title}: fpgas-verify checks it at every boot, and not finding\n"
        "it is a fatal error, whatever else is attached. Conflicts with the other boards' packages: for more\n"
        "than one board, install fpgas-online-multi-board or fpgas-online-all-boards instead."
    ), staging)  # fmt: skip


def stage_test_bitstreams(board, bundle, root, version, commit):
    """Copy a test board's bitstreams out of the CI bundle under `root`, with a manifest; returns the dir."""
    images = pathlib.Path(root) / "usr/share/fpgas-online" / board.slug / "bitstreams"
    files = []
    for test in board.tests:
        for variant in board.variants:
            path = board.artifact(test, variant)
            src = pathlib.Path(bundle) / path
            if not src.is_file():
                raise BuildError(f"{path} is not in {bundle}: the {test} build for {board.name} {variant} is missing")
            data = src.read_bytes()
            (images / path).parent.mkdir(parents=True, exist_ok=True)
            (images / path).write_bytes(data)
            files.append({"path": path, "test": test, "variant": variant, "size": len(data),
                          "sha256": hashlib.sha256(data).hexdigest()})  # fmt: skip
    manifest = {"board": board.name, "version": version, "commit": commit, "files": files}
    (images / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for path in [images, *images.rglob("*")]:  # nfpm keeps the modes files have on disk
        path.chmod(0o755 if path.is_dir() else 0o644)
    return images


def test_bitstreams_nfpm(board, version, images):
    return {
        **_common(f"fpgas-online-{board.slug}-bitstreams", version, (
            f"fpgas.online {board.title} test bitstreams\n"
            f"The {board.title}'s test designs ({', '.join(board.tests)}) as built by this commit's CI, for\n"
            f"{', '.join(board.variants)}, with a manifest of their sha256s."
        )),
        "contents": [{"src": str(images), "dst": f"/usr/share/fpgas-online/{board.slug}/bitstreams", "type": "tree"}],
    }  # fmt: skip


def git_commit(repo=REPO):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()  # fmt: skip


def build(bundle, out, nfpm="nfpm", acorn_from_dir=None, skip_acorn_bitstreams=False):
    version, commit = acorn.git_version(), git_commit()
    acorn_bits = acorn.bitstreams_version(acorn.read_pin()["tag"])
    if not skip_acorn_bitstreams:
        acorn.build(out, nfpm, acorn_from_dir)
    with tempfile.TemporaryDirectory() as tmp:
        staging = pathlib.Path(tmp)
        acorn.run_nfpm(verify_nfpm(version, staging), out, nfpm)
        acorn.run_nfpm(multi_board_nfpm(version, staging), out, nfpm)
        acorn.run_nfpm(all_boards_nfpm(version), out, nfpm)
        for board in BOARDS.values():
            own = staging / board.slug
            own.mkdir()
            bits = acorn_bits
            if isinstance(board, TestBoard):
                images = stage_test_bitstreams(board, bundle, own / "tree", version, commit)
                acorn.run_nfpm(test_bitstreams_nfpm(board, version, images), out, nfpm)
                bits = version
            acorn.run_nfpm(tools_nfpm(board, version, bits, own), out, nfpm)
            acorn.run_nfpm(debug_nfpm(board, version, own), out, nfpm)
            acorn.run_nfpm(board_mode_nfpm(board, version, own), out, nfpm)
            shutil.rmtree(own)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bitstreams", type=pathlib.Path, required=True, help="the all-bitstreams bundle")
    parser.add_argument("--out", type=pathlib.Path, required=True, help="where the .deb files go")
    parser.add_argument("--acorn-from-dir", type=pathlib.Path, help="a staged Acorn release instead of GitHub's")
    parser.add_argument("--skip-acorn-bitstreams", action="store_true", help="it does not change with the commit")
    parser.add_argument("--nfpm", default="nfpm", help="the nfpm binary")
    args = parser.parse_args(argv)
    try:
        build(args.bitstreams, args.out, args.nfpm, args.acorn_from_dir, args.skip_acorn_bitstreams)
    except BuildError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
