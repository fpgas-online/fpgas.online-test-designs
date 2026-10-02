"""fpgas-verify --identify: who this host's board (or boards) is, as one document (identity.document()).

  * Live, the reads are the ones that disturb nothing: the JTAG IDCODE, the device DNA (over BAR0 or JTAG's
    FUSE_DNA) and, on the Acorn, the flash's identity over BAR0. Each board is read under its own lock, so a
    check or a debug session running on it finishes first; it waits at most LOCK_WAIT seconds for the lock,
    and a board still busy then has its fields missing, for the reason "board busy". A board found only by
    driving its pins (the NeTV2's JTAG scan) is looked for under its lock too, never before it is held.
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

import contextlib
import json
import os
import pathlib
import sys

from . import config, identity, runner
from .board import installed
from .core import BUSY, Busy, Problem, hold_lock, pci_devices, usb_devices

ENV = "FPGAS_VERIFY_IDENTITY"
LOCK_WAIT = 30  # seconds --identify waits for a board's lock before it says the board is busy
MATCH_KEYS = ("serial", "bdf", "idcode")  # what says a board in the boot report is this one, strongest first


class BadDocument(Exception):
    """The outer run's document is missing, unreadable, or not an identity document this reader knows."""


def outer_path():
    """The outer run's document, when this runs inside fpgas-verify --label; else None. An empty
    FPGAS_VERIFY_IDENTITY counts as not set (label contract §22)."""
    return os.environ.get(ENV) or None


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
    """The document as printed: sorted keys, indent 1, a trailing newline (as tests/data's golden fixture)."""
    return json.dumps(doc, indent=1, sort_keys=True) + "\n"


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


class _Locks:
    """The boards' locks --identify holds: each taken at most once, and waited for at most LOCK_WAIT seconds."""

    def __init__(self, stack, wait):
        self.stack, self.wait, self.held, self.busy = stack, wait, set(), set()

    def take(self, board):
        """Hold `board`'s lock until the read is done; Busy (with .board) if it is not free in time."""
        if board.lock in self.held:
            return
        if board.lock not in self.busy:
            try:
                self.stack.enter_context(hold_lock(board.lock, board.title, timeout=self.wait))
                self.held.add(board.lock)
                return
            except Busy:
                self.busy.add(board.lock)
        busy = Busy(board.title, self.wait)
        busy.board = board
        raise busy


def _busy(key, board, found):
    """A board whose lock stayed held: how it was found, and every field missing for that reason."""
    return identity.base(key, board.name, found), [f"{key}: {f}: {BUSY}" for f in board.label_fields]


def read(options, boards=None, usb=None, pci=None):
    """(the document, [what is not whole, in words]). options["boot_report"]: the boot report (runner.REPORT).

    Nothing touches a board's pins before its lock is held: a board found by driving its JTAG (the NeTV2's
    scan) is looked for under its lock, which is then kept for its read."""
    report = options.get("boot_report") or runner.REPORT
    boards = installed() if boards is None else boards
    with contextlib.ExitStack() as stack:
        locks = _Locks(stack, options.get("lock_wait", LOCK_WAIT))
        mode = None
        try:
            if options.get("board"):
                mode = options["board"]
            else:
                mode, _ = config.configured(options.get("mode_dir", config.MODE_DIR),
                                            options.get("admin_dir", config.ADMIN_DIR))  # fmt: skip
            usb = usb_devices() if usb is None else usb
            pci = pci_devices() if pci is None else pci
            targets, _ = runner.find(boards, mode, {**options, "before_probe": locks.take}, usb, pci)
        except Busy as b:  # a board that is found by driving its pins was busy before it could be looked for
            if mode == config.AUTO:
                return identity.document([]), [f"{b.board.name}: not looked for: {BUSY}"]
            ident, gaps = _busy(b.board.name, b.board, {})
            return identity.document([ident]), gaps
        except Problem as p:
            return identity.document([]), [f"{p.result}: {p.reason}"]
        out, gaps = [], []
        for (board, host, found), key in zip(targets, runner._keys(targets)):
            board_options = {**{k: v for k, v in options.items() if k != "event"}, "board_key": key}
            try:
                with contextlib.ExitStack() as own:
                    if board.lock not in locks.held:  # held since it was looked for, or only for this read
                        own.enter_context(hold_lock(board.lock, board.title, timeout=locks.wait))
                    ident = board.identify(host, found, board_options)
                    ident = from_report(board, ident, _boot_report(report))
            except Busy:
                ident, busy = _busy(key, board, found)
                out.append(ident)
                gaps += busy
                continue
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
