"""Where a board's installed bitstreams are, and checking a file against their manifest before it is used."""

import hashlib
import importlib.util
import json
import os
import pathlib

from .core import Problem

SHARE = pathlib.Path("/usr/share/fpgas-online")


def images_dir(slug, override=None):
    """A board's installed bitstreams: `override`, else $FPGAS_ONLINE_BITSTREAMS_<SLUG>, else the deb's path
    (fpgas-online-<slug>-bitstreams), else a pip-installed fpgas_online_bitstreams_<slug> package."""
    if override:
        return pathlib.Path(override)
    env = os.environ.get("FPGAS_ONLINE_BITSTREAMS_" + slug.upper().replace("-", "_"))
    if env:
        return pathlib.Path(env)
    deb = SHARE / slug / "bitstreams"
    if deb.is_dir():
        return deb
    spec = importlib.util.find_spec("fpgas_online_bitstreams_" + slug.replace("-", "_"))
    if spec and spec.submodule_search_locations:
        return pathlib.Path(next(iter(spec.submodule_search_locations)))
    return deb


def load_manifest(images, package):
    path = pathlib.Path(images) / "manifest.json"
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise Problem("error", f"{path} is missing: is {package} installed?") from None
    except (OSError, ValueError) as e:
        raise Problem("error", f"cannot read {path}: {e}") from None


def checked(images, entry, key="path"):
    """The bytes of an installed file, refused unless they are the size and sha256 its manifest entry says."""
    path = pathlib.Path(images) / entry[key]
    try:
        data = path.read_bytes()
    except OSError as e:
        raise Problem("error", f"cannot read {path}: {e}") from None
    if ("size" in entry and len(data) != entry["size"]) or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise Problem("error", f"{path} does not match its manifest: the installed package is damaged")
    return path, data


def entry_for(manifest, path, package):
    entry = next((f for f in manifest.get("files", []) if f.get("path") == path), None)
    if entry is None:
        raise Problem("error", f"{package} {manifest.get('version', '')} has no {path}")
    return entry
