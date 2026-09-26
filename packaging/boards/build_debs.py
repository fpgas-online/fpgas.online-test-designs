#!/usr/bin/env python3
"""Build the debs for the Arty A7, NeTV2, Fomu EVT and TT FPGA boards, and the boot-time verify around them.

For each board (designs/_host/board_verify.py BOARDS says which, and what each has):

  fpgas-online-<board>-bitstreams  the board's test bitstreams from this commit's CI builds (the Collect
                                   Bitstreams bundle), with a manifest of their sha256s.
  fpgas-online-<board>-tools       fpgas-<board>-verify (board_verify.py), the host test scripts it runs, and
                                   its entry in /usr/share/fpgas-online/verify.d/ for fpgas-verify.
  fpgas-online-<board>-debug       fpgas-<board>-debug (board_debug.py) and the tests the boot check leaves out.

and, for every board, the Acorn's too (fpgas-online-acorn-tools registers itself the same way):

  fpgas-online-verify              fpgas-verify and fpgas-verify.service, enabled: at boot, find the board and
                                   run its verify. Every board's tools package Recommends it.
  fpgas-online-verify-all          depends on every board's tools: one install for a netboot root that has to
                                   verify whichever board the booting Pi has, or for a lazy host.

Everything is versioned by the repository (`X.Y.postN` from git describe), as fpgas-online-acorn-tools is, and
each board's three packages depend on exactly each other's version. Every bitstream must be in the bundle: a
missing one fails the build rather than ship a board that cannot be checked.

    uv run --python 3.12 packaging/boards/build_debs.py --bitstreams bitstreams/ --out dist/
"""

import argparse
import hashlib
import importlib.util
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
HOST = REPO / "designs" / "_host"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bv = _load("board_verify", HOST / "board_verify.py")
acorn = _load("acorn_build_debs", REPO / "packaging" / "acorn-pcie" / "build_debs.py")  # git_version, run_nfpm

BuildError = acorn.BuildError
MAINTAINER, HOMEPAGE = acorn.MAINTAINER, acorn.HOMEPAGE
EXE = {"file_info": {"mode": 0o755}}
DATA = {"file_info": {"mode": 0o644}}
REGISTRY = "/usr/share/fpgas-online/verify.d"
VERIFY_LIB = "/usr/lib/fpgas-online/verify"
OPENFPGALOADER = "openfpgaloader-fpgasonline | openfpgaloader-fpgasonline-git | openfpgaloader"
# Each board's programmer. The fpgas.online builds of openFPGALoader (fpgas.online-fpga-tools) come first; both
# Provide openfpgaloader, and Debian's own satisfies a host without that repository, though only the
# fpgas.online builds have the Pi 5 rp1pio cable the NeTV2 uses on a Pi 5.
PROGRAMMER = {"arty": [OPENFPGALOADER], "fomu": [OPENFPGALOADER], "netv2": [OPENFPGALOADER, "openocd"], "tt": []}
ACORN_TOOLS = "fpgas-online-acorn-tools"


def _common(name, version, description):
    return {
        "name": name,
        "arch": "all",
        "platform": "linux",
        "version": version,
        "version_schema": "none",  # keep 0.0.post590 as it is: nfpm's semver parsing would rewrite it
        "maintainer": MAINTAINER,
        "homepage": HOMEPAGE,
        "license": "Apache-2.0",
        "description": description,
    }


def pkg(board, part):
    return f"fpgas-online-{bv.BOARDS[board]['slug']}-{part}"


def selected(board):
    """[(test, variant, artifact path)] of every bitstream the board's packages carry."""
    cfg = bv.BOARDS[board]
    return [
        (test, variant, bv.artifact_path(board, test, variant)) for test in cfg["tests"] for variant in cfg["variants"]
    ]


def scripts_for(board):
    """(the scripts the tools package carries, the ones only the debug package carries)."""
    tests = bv.BOARDS[board]["tests"].values()
    tools = {t["script"] for t in tests if t.get("verify")}
    if board == "tt":
        tools |= set(bv.TT_SCRIPTS)
    debug = {t["script"] for t in tests} - tools
    return sorted(tools), sorted(debug)


# -- the bitstreams --------------------------------------------------------------------------------------


def stage_bitstreams(board, bundle, root, version, commit):
    """Copy the board's bitstreams out of the CI bundle under `root`, with a manifest; returns the images dir."""
    images = pathlib.Path(root) / "usr/share/fpgas-online" / bv.BOARDS[board]["slug"] / "bitstreams"
    files = []
    for test, variant, path in selected(board):
        src = pathlib.Path(bundle) / path
        if not src.is_file():
            raise BuildError(f"{path} is not in {bundle}: the {test} build for {board} {variant} is missing")
        data = src.read_bytes()
        dst = images / path
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
        files.append({"path": path, "test": test, "variant": variant, "size": len(data),
                      "sha256": hashlib.sha256(data).hexdigest()})  # fmt: skip
    manifest = {"board": board, "version": version, "commit": commit, "files": files}
    (images / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    # nfpm's tree copies modes as they are on disk, so set them rather than inherit the builder's umask.
    for path in [images, *images.rglob("*")]:
        path.chmod(0o755 if path.is_dir() else 0o644)
    return images


def bitstreams_nfpm(board, version, images):
    cfg = bv.BOARDS[board]
    return {
        **_common(pkg(board, "bitstreams"), version, (
            f"fpgas.online {cfg['title']} test bitstreams\n"
            f"The {cfg['title']}'s test designs ({', '.join(cfg['tests'])}) as built by this commit's CI, for\n"
            f"{', '.join(cfg['variants'])}, with a manifest of their sha256s. Loaded by fpgas-{cfg['slug']}-verify\n"
            f"and fpgas-{cfg['slug']}-debug."
        )),
        "contents": [{"src": str(images), "dst": f"/usr/share/fpgas-online/{cfg['slug']}/bitstreams", "type": "tree"}],
    }  # fmt: skip


# -- the tools and the debug tools -----------------------------------------------------------------------


def registration(board):
    """The board's entry in verify.d: what fpgas-verify runs, and how it spots the board."""
    cfg = bv.BOARDS[board]
    detect = cfg["detect"]
    entry = {"board": board, "title": cfg["title"], "command": [f"/usr/bin/fpgas-{cfg['slug']}-verify"],
             "report": f"/run/fpgas-online/{cfg['slug']}-verify.json"}  # fmt: skip
    if "usb" in detect:
        entry["detect"] = {"usb": [[v, p] for v, p in detect["usb"]]}
    else:
        entry["detect"] = {"jtag": True}
    return entry


def tools_nfpm(board, version, staging, repo=REPO):
    cfg = bv.BOARDS[board]
    lib = f"/usr/lib/fpgas-online/{cfg['slug']}"
    tools, _ = scripts_for(board)
    reg = pathlib.Path(staging) / f"{cfg['slug']}.json"
    reg.write_text(json.dumps(registration(board), indent=2) + "\n")
    tests = [t for t in cfg["tests"] if cfg["tests"][t].get("verify")]
    conf = {
        **_common(pkg(board, "tools"), version, (
            f"fpgas.online {cfg['title']} check\n"
            f"fpgas-{cfg['slug']}-verify loads each of the {cfg['title']}'s test bitstreams ({', '.join(tests)})\n"
            "and runs its host test, and reports and publishes the result. fpgas-verify (fpgas-online-verify)\n"
            "runs it at boot when it finds this board."
        )),
        "depends": ["python3", "python3-serial", f"{pkg(board, 'bitstreams')} (= {version})", *PROGRAMMER[board]],
        # fpgas-verify and its boot unit: what runs this at boot. Recommends, so installing one board's tools on
        # a Pi gets the boot check, and --no-install-recommends gets just the command.
        "recommends": ["fpgas-online-verify", *(["micropython-mpremote"] if board == "tt" else [])],
        # fleet-event, which the result is published through; publish() copes without it. Not Recommends: apt
        # installs those by default, and fpgas-online-setup-pi turns any host into a fleet node.
        "suggests": [pkg(board, "debug"), "fpgas-online-setup-pi"],
        "contents": [
            {"src": str(HOST / "board_verify.py"), "dst": f"{lib}/board_verify.py", **EXE},
            *({"src": str(repo / bv.SCRIPTS[s]), "dst": f"{lib}/{s}", **DATA} for s in tools),
            {"src": f"{lib}/board_verify.py", "dst": f"/usr/bin/fpgas-{cfg['slug']}-verify", "type": "symlink"},
            {"src": str(reg), "dst": f"{REGISTRY}/{cfg['slug']}.json", **DATA},
        ],
    }  # fmt: skip
    if board == "tt":
        # micropython-mpremote is in trixie but only bookworm-backports; without it the verify reports an error.
        conf["description"] += "\nLoading the board needs mpremote (micropython-mpremote, or pip)."
    return conf


def debug_nfpm(board, version, repo=REPO):
    cfg = bv.BOARDS[board]
    lib = f"/usr/lib/fpgas-online/{cfg['slug']}"
    _, debug = scripts_for(board)
    extra = [t for t in cfg["tests"] if not cfg["tests"][t].get("verify")]
    recommends = ["kmod"]  # rmmod: the PMOD tests free the SPI pins first
    if "ethernet" in cfg["tests"]:
        recommends += ["iproute2", "iputils-ping", "iputils-arping | arping", "sudo"]
    return {
        **_common(pkg(board, "debug"), version, (
            f"fpgas.online {cfg['title']} debugging tools\n"
            f"For when fpgas-{cfg['slug']}-verify fails: fpgas-{cfg['slug']}-debug detects the board, checks the\n"
            "installed bitstreams, and loads any test design and runs its test one step at a time with its\n"
            f"output live, including the tests the boot check leaves out ({', '.join(extra)})."
        )),
        "depends": [f"{pkg(board, 'tools')} (= {version})", "python3-libgpiod"],
        "recommends": recommends,
        "contents": [
            {"src": str(HOST / "board_debug.py"), "dst": f"{lib}/board_debug.py", **EXE},
            *({"src": str(repo / bv.SCRIPTS[s]), "dst": f"{lib}/{s}", **DATA} for s in debug),
            {"src": f"{lib}/board_debug.py", "dst": f"/usr/bin/fpgas-{cfg['slug']}-debug", "type": "symlink"},
        ],
    }  # fmt: skip


# -- the boot-time dispatcher and the everything package ------------------------------------------------------


def verify_nfpm(version):
    return {
        **_common("fpgas-online-verify", version, (
            "fpgas.online boot-time FPGA board check\n"
            "fpgas-verify.service runs fpgas-verify once per boot: it finds which fpgas.online FPGA board the Pi\n"
            "has, among the boards whose fpgas-online-<board>-tools are installed, and runs that board's verify.\n"
            "Enabled on install (not started: the verify loads test bitstreams into the board)."
        )),
        "depends": ["python3", "init-system-helpers"],
        "contents": [
            {"src": str(HOST / "fpgas_verify.py"), "dst": f"{VERIFY_LIB}/fpgas_verify.py", **EXE},
            {"src": f"{VERIFY_LIB}/fpgas_verify.py", "dst": "/usr/bin/fpgas-verify", "type": "symlink"},
            {"src": str(HERE / "fpgas-verify.service"), "dst": "/usr/lib/systemd/system/fpgas-verify.service", **DATA},
            {"dst": REGISTRY, "type": "dir", "file_info": {"mode": 0o755}},
        ],
        "scripts": {
            "postinstall": str(HERE / "fpgas-online-verify.postinst"),
            "postremove": str(HERE / "fpgas-online-verify.postrm"),
        },
    }  # fmt: skip


def verify_all_nfpm(version):
    boards = sorted(bv.BOARDS)
    return {
        **_common("fpgas-online-verify-all", version, (
            "fpgas.online boot-time check for every FPGA board\n"
            "Installs fpgas-online-verify and every board's tools, so a netboot root verifies whichever board\n"
            "the booting Pi has: Acorn, Arty A7, NeTV2, Fomu EVT or TT FPGA. Recommends each board's debug tools."
        )),
        "depends": [
            f"fpgas-online-verify (= {version})",
            ACORN_TOOLS,  # built by acorn-debs.yml from the same commit; its bitstreams follow their own pin
            *(f"{pkg(b, 'tools')} (= {version})" for b in boards),
        ],
        "recommends": [pkg(b, "debug") for b in boards],
    }  # fmt: skip


def git_commit(repo=REPO):
    return subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True,
                          text=True).stdout.strip()  # fmt: skip


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bitstreams", type=pathlib.Path, required=True, help="the all-bitstreams bundle")
    parser.add_argument("--out", type=pathlib.Path, required=True, help="where the .deb files go")
    parser.add_argument("--board", action="append", choices=sorted(bv.BOARDS), help="only this board's packages")
    parser.add_argument("--nfpm", default="nfpm", help="the nfpm binary")
    args = parser.parse_args(argv)

    try:
        version, commit = acorn.git_version(), git_commit()
        with tempfile.TemporaryDirectory() as tmp:
            for board in args.board or sorted(bv.BOARDS):
                root = pathlib.Path(tmp) / board
                images = stage_bitstreams(board, args.bitstreams, root / "tree", version, commit)
                acorn.run_nfpm(bitstreams_nfpm(board, version, images), args.out, args.nfpm)
                acorn.run_nfpm(tools_nfpm(board, version, root), args.out, args.nfpm)
                acorn.run_nfpm(debug_nfpm(board, version), args.out, args.nfpm)
                shutil.rmtree(root)
            if not args.board:
                acorn.run_nfpm(verify_nfpm(version), args.out, args.nfpm)
                acorn.run_nfpm(verify_all_nfpm(version), args.out, args.nfpm)
    except BuildError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
