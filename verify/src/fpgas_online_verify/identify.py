"""fpgas-verify --identify: who this host's board (or boards) is, as one document (identity.document()).

  * Live, the reads are the ones that disturb nothing: the JTAG IDCODE, the device DNA (over BAR0 or JTAG's
    FUSE_DNA) and, on the Acorn, the flash's identity over BAR0. Each board is read under its own lock, so a
    check or a debug session running on it finishes first.
  * Anything only a loaded design can read (the Arty's and NeTV2's flash, through openFPGALoader's
    SPI-over-JTAG bridge) comes from the boot report (runner.REPORT), when the board there is this one (the
    same USB serial, PCI slot or IDCODE); the board's dict lists those fields in "from_report".
  * Inside fpgas-verify --label (FPGAS_VERIFY_IDENTITY names the document the outer run read), --identify
    prints that file unchanged and does nothing else: no lock, no board code, and never the hardware, even
    when the file is missing or bad (that is an error). Every other mode refuses, so the outer run's locks
    and rpi-hwid's labels are never raced or looped.

The document is printed whatever was read; the exit status is 0 only when every board's identity is whole
(each of its label_fields read, no <field>_error). Readers use the document and ignore the exit status.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import json
import os
import pathlib
import sys

from . import config, identity, runner
from .board import installed
from .core import Problem, hold_lock, pci_devices, usb_devices

ENV = "FPGAS_VERIFY_IDENTITY"
MATCH_KEYS = ("serial", "bdf", "idcode")  # what says a board in the boot report is this one, strongest first


class BadDocument(Exception):
    """The outer run's document is missing, unreadable, or not an identity document this reader knows."""


def outer_path():
    """The outer run's document, when this runs inside fpgas-verify --label; else None."""
    return os.environ.get(ENV)


def load_outer(path):
    """The outer run's document, as its text: checked, never changed."""
    try:
        text = pathlib.Path(path).read_text()
    except (OSError, UnicodeDecodeError) as e:
        raise BadDocument(f"cannot read {path}: {e}") from None
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise BadDocument(f"{path} is not JSON: {e}") from None
    if not isinstance(doc, dict) or doc.get("schema") != identity.DOCUMENT_SCHEMA:
        raise BadDocument(f"{path} is not an identity document (schema {identity.DOCUMENT_SCHEMA})")
    version = doc.get("identity_version")
    if type(version) is not int or version != identity.IDENTITY_VERSION:
        raise BadDocument(f"{path} is identity_version {version!r}; this reader takes only "
                          f"{identity.IDENTITY_VERSION}")  # fmt: skip
    if not isinstance(doc.get("boards"), list):
        raise BadDocument(f"{path} has no list of boards")
    return text


def nested(prog, identifying):
    """The whole of a run inside fpgas-verify --label: print the outer run's document, or refuse."""
    path = outer_path()
    if not identifying:
        print(f"{prog}: {ENV} is set, so this runs inside fpgas-verify --label: only --identify may run",
              file=sys.stderr)  # fmt: skip
        return 2
    try:
        text = load_outer(path)
    except BadDocument as e:
        print(f"{prog}: {ENV}: {e}", file=sys.stderr)
        return 1
    sys.stdout.write(text)
    return 0


def dumps(doc):
    return json.dumps(doc, indent=2) + "\n"


# -- the live read ---------------------------------------------------------------------------------------


def _boot_report(path):
    """The boot report's board identities, or [] when there is none to read."""
    try:
        report = json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError):
        return []
    boards = report.get("boards") if isinstance(report, dict) else None
    return [b["identity"] for b in boards or [] if isinstance(b, dict) and isinstance(b.get("identity"), dict)]


def from_report(board, live, previous):
    """`live`, with the fields only the boot check reads taken from the boot report's identity of this board."""
    if not board.report_fields:
        return live
    key = next((k for k in MATCH_KEYS if live.get(k)), None)
    match = key and next((p for p in previous if p.get("kind") == live.get("kind") and p.get(key) == live[key]), None)
    if not match:
        return live
    taken = {k: v for k, v in match.items() if k not in live and k.startswith(board.report_fields)}
    if not taken:
        return live
    return {**live, **taken, "from_report": sorted(taken)}


def missing(board, ident):
    """What keeps an identity from being whole: the label fields not read, and the reads that failed."""
    return [f for f in board.label_fields if f not in ident] + sorted(k for k in ident if k.endswith("_error"))


def read(options, boards=None, usb=None, pci=None):
    """(the document, [what is not whole, in words]). options["boot_report"]: the boot report (runner.REPORT)."""
    report = options.get("boot_report") or runner.REPORT
    boards = installed() if boards is None else boards
    try:
        if options.get("board"):
            mode = options["board"]
        else:
            mode, _ = config.configured(options.get("mode_dir", config.MODE_DIR),
                                        options.get("admin_dir", config.ADMIN_DIR))  # fmt: skip
        usb = usb_devices() if usb is None else usb
        pci = pci_devices() if pci is None else pci
        targets, _ = runner.find(boards, mode, options, usb, pci)
    except Problem as p:
        return identity.document([]), [f"{p.result}: {p.reason}"]
    out, gaps = [], []
    for (board, host, found), key in zip(targets, runner._keys(targets)):
        board_options = {**{k: v for k, v in options.items() if k != "event"}, "board_key": key}
        try:
            with hold_lock(board.lock, board.title):
                ident = board.identify(host, found, board_options)
                ident = from_report(board, ident, _boot_report(report))
        except Problem as p:
            ident = identity.base(key, board.name, found)
            gaps.append(f"{key}: {p.result}: {p.reason}")
        except Exception as e:  # a bug in a board's read: that board is not whole, the others are still read
            ident = identity.base(key, board.name, found)
            gaps.append(f"{key}: the read crashed: {type(e).__name__}: {e}")
        out.append(ident)
        gaps += [f"{key}: not read: {f}" for f in missing(board, ident)]
    return identity.document(out), gaps


def run(options, prog="fpgas-verify", boards=None):
    """Print the document; 0 if every board's identity is whole, 1 otherwise (and say why on stderr)."""
    doc, gaps = read(options, boards)
    sys.stdout.write(dumps(doc))
    for gap in gaps:
        print(f"{prog} --identify: {gap}", file=sys.stderr)
    return 1 if gaps or not doc["boards"] else 0
