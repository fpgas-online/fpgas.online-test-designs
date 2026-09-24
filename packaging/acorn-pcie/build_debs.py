#!/usr/bin/env python3
"""Build the Acorn debs: fpgas-online-acorn-bitstreams and fpgas-online-acorn-tools.

fpgas-online-acorn-bitstreams carries the images a Pi uses, taken from the GitHub Release pinned in
release.toml: for each board, the two images its flash should hold, the register maps (csr.json/csr.csv) of
the builds that can be running, and the operational build's .bit for loading it into SRAM over JTAG (how a
board still on SQRL's factory image is converted). The rest of the release stays on GitHub. Its version comes
from the release (`20260921+gf3355dccf443`), so the package, and the apt pool that keeps every version, only
grows when a reviewed PR moves the pin: moving the pin is also what changes which images the fleet expects.

fpgas-online-acorn-tools carries acorn_verify.py, spi_flash.py, uartbone_link.py and the boot unit. Its
version is the repository's (`X.Y.postN` from git describe, as the other fpgas.online debs do) and it
depends on exactly the pinned bitstreams version, and on an openFPGALoader to load the .bit with.

Nothing is trusted on the way: the manifest must hash to release.toml's manifest_sha256, and every asset to
its manifest entry.

    uv run --python 3.12 packaging/acorn-pcie/build_debs.py --out dist/          # from the pinned release
    uv run --python 3.12 packaging/acorn-pcie/build_debs.py --out dist/ --from-dir tmp/acorn-pcie-release
"""

import argparse
import hashlib
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

import tomllib

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
PIN = HERE / "release.toml"
TAG_RE = re.compile(r"^vivado-bitstreams-acorn-pcie-(\d{8})-g([0-9a-f]{12})$")
IMAGES_DST = "usr/share/fpgas-online/acorn-pcie/images"
LIB_DST = "/usr/lib/fpgas-online/acorn-pcie"
MAINTAINER = "fpgas.online <fpgas@fpgas.online>"
HOMEPAGE = "https://github.com/fpgas-online/fpgas.online-test-designs"


class BuildError(Exception):
    pass


# -- the pinned release ----------------------------------------------------------------------------------


def read_pin(path=PIN):
    pin = tomllib.loads(pathlib.Path(path).read_text())
    for key in ("repo", "tag", "manifest_sha256"):
        if not isinstance(pin.get(key), str):
            raise BuildError(f"{path}: {key} is missing")
    return pin


def bitstreams_version(tag):
    """`vivado-bitstreams-acorn-pcie-YYYYMMDD-g<sha12>` -> `YYYYMMDD+g<sha12>`: newer releases sort higher."""
    m = TAG_RE.match(tag or "")
    if not m:
        raise BuildError(f"{tag!r} is not an acorn-pcie release tag (vivado-bitstreams-acorn-pcie-YYYYMMDD-g<sha>)")
    return f"{m.group(1)}+g{m.group(2)}"


def load_manifest(path, pinned_sha256):
    raw = pathlib.Path(path).read_bytes()
    got = hashlib.sha256(raw).hexdigest()
    if got != pinned_sha256:
        raise BuildError(f"{path} hashes to {got}, not the manifest_sha256 {pinned_sha256} in release.toml")
    return json.loads(raw)


def select_assets(manifest):
    """What a Pi needs, by name: each board's two flash images, the running builds' CSR maps, one .bit."""
    files = {f["asset"]: f for f in manifest["files"]}
    chosen = set()
    for board, layout in manifest["flash_layout"].items():
        if set(layout) != {"0x000000", "0x400000"}:
            raise BuildError(f"flash_layout for {board} does not name exactly the two slots: {sorted(layout)}")
        for asset in layout.values():
            if asset not in files:
                raise BuildError(f"flash_layout names {asset}, which the manifest does not list")
            chosen.add(asset)
        for asset in layout.values():
            chosen |= _named(files, files[asset]["variant"], "csr.json", "csr.csv")
        chosen |= _named(files, files[layout["0x400000"]]["variant"], "sqrl_acorn.bit")
    return sorted(chosen)


def _named(files, variant, *names):
    found = {f["asset"] for f in files.values() if f["variant"] == variant and f["file"] in names}
    if len(found) != len(names):
        raise BuildError(f"the release has no {' / '.join(names)} for the {variant} build")
    return found


def local_fetcher(directory):
    directory = pathlib.Path(directory)
    return lambda asset: (directory / asset).read_bytes()


def release_fetcher(repo, tag):
    def fetch(asset):
        url = f"https://github.com/{repo}/releases/download/{tag}/{asset}"
        with urllib.request.urlopen(url, timeout=120) as r:
            return r.read()

    return fetch


def stage_bitstreams(manifest, fetch, root, raw_manifest=None):
    """Write the installed tree under `root`, refusing any asset that is not what the manifest says."""
    files = {f["asset"]: f for f in manifest["files"]}
    images = pathlib.Path(root) / IMAGES_DST
    images.mkdir(parents=True, exist_ok=True)
    for asset in select_assets(manifest):
        data = fetch(asset)
        want = files[asset]
        if len(data) != want["size"] or hashlib.sha256(data).hexdigest() != want["sha256"]:
            raise BuildError(f"{asset} does not match its manifest size/sha256")
        (images / asset).write_bytes(data)
    text = raw_manifest if raw_manifest is not None else (json.dumps(manifest, indent=2) + "\n").encode()
    (images / "manifest.json").write_bytes(text)
    # nfpm's tree copies modes as they are on disk, so set them rather than inherit the builder's umask.
    for path in [images, *images.parents[: len(pathlib.Path(IMAGES_DST).parts) - 1]]:
        path.chmod(0o755)
    for path in images.iterdir():
        path.chmod(0o644)
    return images


# -- nfpm ------------------------------------------------------------------------------------------------


def bitstreams_nfpm(version, root, tag):
    return {
        "name": "fpgas-online-acorn-bitstreams",
        "arch": "all",
        "platform": "linux",
        "version": version,
        # nfpm otherwise parses the version as semver and rewrites 20260921+gf3355dccf443 to
        # 20260921.0.0+gf3355dccf443, which the tools package's exact Depends would never match.
        "version_schema": "none",
        "maintainer": MAINTAINER,
        "homepage": HOMEPAGE,
        "license": "Apache-2.0",
        "description": (
            f"fpgas.online Acorn PCIe SoC images ({tag})\n"
            "The golden and operational flash images for each Acorn variant, the register maps of those\n"
            "builds and the operational build's .bit, from the pinned GitHub Release. Read by\n"
            "fpgas-acorn-verify; written to a board only by an operator (fpgas-acorn-flash)."
        ),
        "contents": [{"src": str(pathlib.Path(root) / IMAGES_DST), "dst": f"/{IMAGES_DST}", "type": "tree"}],
    }


def tools_nfpm(version, bitstreams, repo=REPO):
    host = pathlib.Path(repo) / "designs" / "acorn-pcie" / "host"
    unit = pathlib.Path(repo) / "packaging" / "acorn-pcie" / "fpgas-acorn-verify.service"
    exe = {"file_info": {"mode": 0o755}}
    data = {"file_info": {"mode": 0o644}}
    return {
        "name": "fpgas-online-acorn-tools",
        "arch": "all",
        "platform": "linux",
        "version": version,
        # nfpm otherwise parses the version as semver and rewrites 20260921+gf3355dccf443 to
        # 20260921.0.0+gf3355dccf443, which the tools package's exact Depends would never match.
        "version_schema": "none",
        "maintainer": MAINTAINER,
        "homepage": HOMEPAGE,
        "license": "Apache-2.0",
        "description": (
            "fpgas.online Acorn checks and flash tool\n"
            "fpgas-acorn-verify checks, on every boot, that an Acorn runs the expected fpgas.online image and\n"
            "that its flash holds the expected images, reading only. fpgas-acorn-flash (spi_flash.py) identifies,\n"
            "dumps, verifies and, when asked, writes the flash over PCIe."
        ),
        "depends": [
            "python3",
            f"fpgas-online-acorn-bitstreams (= {bitstreams})",
            # Loads the bitstreams package's .bit into SRAM over GPIO JTAG, which is how a board on SQRL's factory
            # image is converted. The fpgas.online builds (fpgas.online-fpga-tools) first; both Provide
            # openfpgaloader, and Debian's own openfpgaloader satisfies a host without that repository.
            "openfpgaloader-fpgasonline | openfpgaloader-fpgasonline-git | openfpgaloader",
        ],
        # fleet-event, which the boot check publishes through; publish() copes without it. Not Recommends: apt
        # installs those by default, and fpgas-online-setup-pi turns any host into a fleet node.
        "suggests": ["fpgas-online-setup-pi"],
        "contents": [
            {"src": str(host / "acorn_verify.py"), "dst": f"{LIB_DST}/acorn_verify.py", **exe},
            {"src": str(host / "spi_flash.py"), "dst": f"{LIB_DST}/spi_flash.py", **exe},
            {"src": str(host / "uartbone_link.py"), "dst": f"{LIB_DST}/uartbone_link.py", **data},
            {"src": f"{LIB_DST}/acorn_verify.py", "dst": "/usr/bin/fpgas-acorn-verify", "type": "symlink"},
            {"src": f"{LIB_DST}/spi_flash.py", "dst": "/usr/bin/fpgas-acorn-flash", "type": "symlink"},
            {"src": str(unit), "dst": "/usr/lib/systemd/system/fpgas-acorn-verify.service", **data},
        ],
    }


def git_version(repo=REPO):
    """`X.Y` at a vX.Y tag, `X.Y.postN` N commits later: the scheme the other fpgas.online debs use."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "describe", "--tags", "--long", "--match", "v[0-9]*.[0-9]*"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except subprocess.CalledProcessError as e:
        raise BuildError(f"git describe found no vX.Y tag (a shallow clone?): {e.stderr.strip()}") from None
    m = re.fullmatch(r"v(\d+)\.(\d+)-(\d+)-g[0-9a-f]+", out)
    if not m:
        raise BuildError(f"unexpected git describe output {out!r}")
    major, minor, n = m.groups()
    return f"{major}.{minor}" if n == "0" else f"{major}.{minor}.post{n}"


def run_nfpm(config, out_dir, nfpm="nfpm"):
    out_dir = pathlib.Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", dir=out_dir, delete=False) as f:
        json.dump(config, f, indent=2)  # JSON is YAML
        cfg = pathlib.Path(f.name)
    try:
        subprocess.run([nfpm, "package", "--config", str(cfg), "--packager", "deb", "--target", str(out_dir)],
                       check=True)  # fmt: skip
    finally:
        cfg.unlink()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=pathlib.Path, required=True, help="where the .deb files go")
    parser.add_argument("--from-dir", type=pathlib.Path, help="a staged release instead of the GitHub Release")
    parser.add_argument("--only", choices=("bitstreams", "tools"), help="build just one package")
    parser.add_argument("--nfpm", default="nfpm", help="the nfpm binary")
    parser.add_argument("--pin", type=pathlib.Path, default=PIN)
    args = parser.parse_args(argv)

    try:
        pin = read_pin(args.pin)
        bits_version = bitstreams_version(pin["tag"])
        if args.only != "tools":
            fetch = local_fetcher(args.from_dir) if args.from_dir else release_fetcher(pin["repo"], pin["tag"])
            raw = fetch("manifest.json")
            if hashlib.sha256(raw).hexdigest() != pin["manifest_sha256"]:
                raise BuildError(f"the manifest of {pin['tag']} does not match release.toml's manifest_sha256")
            manifest = json.loads(raw)
            if manifest.get("tag") != pin["tag"]:
                raise BuildError(f"the manifest names release {manifest.get('tag')!r}, not {pin['tag']!r}")
            with tempfile.TemporaryDirectory() as root:
                stage_bitstreams(manifest, fetch, root, raw_manifest=raw)
                run_nfpm(bitstreams_nfpm(bits_version, root, pin["tag"]), args.out, args.nfpm)
        if args.only != "bitstreams":
            run_nfpm(tools_nfpm(git_version(), bits_version), args.out, args.nfpm)
    except BuildError as e:
        sys.exit(f"error: {e}")


if __name__ == "__main__":
    main()
