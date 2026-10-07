"""fpgas-verify --identify: who this host's board (or boards) is, as one document (identity.document()).

  * Live, the reads are the ones that disturb nothing: the JTAG IDCODE, the device DNA (over BAR0, or JTAG's
    FUSE_DNA on the Acorn, Arty and NeTV2) and, on the Acorn, the flash's identity over BAR0. Each board is
    read under its own lock, so a check or a debug session running on it finishes first; it waits at most
    LOCK_WAIT seconds for the lock, and a board still busy then has its fields missing, for the reason "board
    busy". A board found only by
    driving its pins (the NeTV2's JTAG scan) is looked for under its lock too, never before it is held; one
    that could not be looked for, its lock being busy, is in the document all the same, with every field
    missing for that reason, whatever else was found; so is one whose look failed (a JTAG scan that left a pin
    driven, or a lock that could not be opened), with the look's reason. Only one board's lock is held at a time.
  * Anything only the boot check reads (the Arty's and NeTV2's flash, which needs a design loaded for
    openFPGALoader's SPI-over-JTAG bridge; the TT FPGA's fields from rpi-hwid, which need the board's port, held
    by fpgas-tt.service outside the check) comes from the boot report (runner.REPORT), when the board there is
    this one by a key no other board has (its USB serial, PCI slot or device DNA); the board's dict lists those
    fields in "from_report". An IDCODE names a part, not a board, so a board known only by its IDCODE (a NeTV2
    whose DNA could not be read) gets nothing from the report: those fields stay missing, for the reason NO_MATCH.
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
import signal
import sys

from . import config, identity, runner
from .board import installed
from .core import BUSY, Busy, Problem, hold_lock, pci_devices, usb_devices

ENV = "FPGAS_VERIFY_IDENTITY"
LOCK_WAIT = 30  # seconds --identify waits for a board's lock before it says the board is busy
# What says a board in the boot report is this one: keys no two boards share (a Tiny Tapeout board's
# usb_serial, USB serial, PCI slot, device DNA), the first the live read has. Never the IDCODE, which every
# board with the same part has.
MATCH_KEYS = ("usb_serial", "serial", "bdf", "dna")
NO_MATCH = "no board-unique match in the boot report"
NOT_IN_REPORT = "this board is not in the boot report"


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
    """(`live` with the fields only the boot check reads taken from the boot report's identity of this board,
    why none were taken or None)."""
    if not board.report_fields:
        return live, None
    key = next((k for k in MATCH_KEYS if live.get(k)), None)
    if key is None:
        return live, NO_MATCH
    match = next((p for p in previous if p.get("kind") == live.get("kind") and p.get(key) == live[key]), None)
    if not match:
        return live, NOT_IN_REPORT
    taken = {k: v for k, v in match.items() if k not in live and k.startswith(board.report_fields)}
    if not taken:
        return live, None
    return {**live, **taken, "from_report": sorted(taken)}, None


def missing(board, ident, why=None):
    """What keeps an identity from being whole, as [(field, why)]: each label field not read, and each read that
    failed (a <field>_error, whose text is the why). `why`: {field prefix: reason} for a field not read that has
    no <field>_error of its own (the boot report's fields, or "" for every field of a read that stopped)."""
    why = why or {}
    out = []
    for f in board.label_fields:
        if f not in ident:
            reason = ident.get(f"{f}_error") or next((w for pre, w in why.items() if f.startswith(pre)), "not read")
            out.append((f, str(reason)))
    named = {f for f, _ in out}
    failed = [(k.removesuffix("_error"), str(ident[k])) for k in sorted(ident) if k.endswith("_error")]
    return out + [(f, reason) for f, reason in failed if f not in named]


class _Locks:
    """The boards' locks --identify takes, each waited for at most `wait` (LOCK_WAIT) seconds.

    It holds at most one board's lock at a time, both while looking for a board and while reading one, so it
    can never take two in an order that deadlocks with another tool's (rpi-hwid takes acorn < arty < netv2).
    Should two ever have to be held together, take them in that sorted order."""

    def __init__(self, wait):
        self.wait, self.skip_busy = wait, False
        self.skipped = []  # the boards not looked for because their lock stayed held
        self.failed = []  # (board, Problem): the boards whose look (driving their pins) failed

    @contextlib.contextmanager
    def probing(self, board):
        """runner.find's `probing`: hold `board`'s lock while it is looked for by driving its pins, and let it go
        as soon as it has been (its read takes it again). A lock that stays busy: with skip_busy (`auto`) the
        board is skipped, and listed in `skipped`; else Busy, with .board. A look that fails (a Problem), or a
        lock that cannot be opened (a symlink, a file it may not open), is listed in `failed` and goes on to
        runner.find, which may keep a weak claim and say so only in its `how`."""
        with contextlib.ExitStack() as stack:
            try:
                stack.enter_context(hold_lock(board.lock, board.title, timeout=self.wait))
            except Busy as busy:
                if not self.skip_busy:
                    busy.board = board
                    raise
                self.skipped.append(board)
                yield False
                return
            except Problem as p:  # a lock that cannot be opened (a symlink, someone else's file): a failed look
                self.failed.append((board, p))
                raise
            try:
                yield True
            except Problem as p:
                self.failed.append((board, p))
                raise


def _unread(key, board, found, reason):
    """A board found but not read: how it was found, and each label field that leaves missing, for `reason`
    (only those: finding the NeTV2 reads its IDCODE). With none missing, the read itself is the gap."""
    ident = identity.base(key, board.name, found)
    fields = missing(board, ident, {"": reason}) or [("read", reason)]
    return ident, [f"{key}: {f}: {why}" for f, why in fields]


def _busy(key, board, found):
    """A board whose lock stayed held: how it was found, and every field that leaves missing, for that reason."""
    return _unread(key, board, found, BUSY)


def _failed(board, problem):
    """A board whose look (driving its pins) failed: every field missing, for the look's reason."""
    return _unread(board.name, board, {}, f"{problem.result}: {problem.reason}")


def _terminated(signum, frame):
    """SIGTERM during the read (rpi-hwid stops a slow --identify with SIGTERM, then SIGKILL): leave through every
    finally, so pins, locks and the PCI COMMAND register are put back. A second SIGTERM is ignored meanwhile, so
    it cannot cut the putting back short."""
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    raise SystemExit(128 + signum)


@contextlib.contextmanager
def _sigterm_exits():
    """Make SIGTERM raise SystemExit(143) for the duration; the previous handler is put back afterwards."""
    try:
        previous = signal.signal(signal.SIGTERM, _terminated)
    except ValueError:  # not the main thread: signals are not ours to handle
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def read(options, boards=None, usb=None, pci=None):
    """(the document, [what is not whole, in words]). options["boot_report"]: the boot report (runner.REPORT).
    A SIGTERM meanwhile exits 143, with everything a board's read changed put back.

    Nothing touches a board's pins before its lock is held: a board found by driving its JTAG (the NeTV2's
    scan) is looked for under its lock, which is let go before any other board's is taken, and taken again
    for its read. No two boards' locks are ever held at once."""
    report = options.get("boot_report") or runner.REPORT
    boards = installed() if boards is None else boards
    with _sigterm_exits():
        locks = _Locks(options.get("lock_wait", LOCK_WAIT))
        out, gaps = [], []
        try:
            if options.get("board"):
                mode = options["board"]
            else:
                mode, _ = config.configured(options.get("mode_dir", config.MODE_DIR),
                                            options.get("admin_dir", config.ADMIN_DIR))  # fmt: skip
            locks.skip_busy = mode == config.AUTO
            usb = usb_devices() if usb is None else usb
            pci = pci_devices() if pci is None else pci
            targets, _ = runner.find(boards, mode, {**options, "probing": locks.probing}, usb, pci)
        except Busy as b:  # configured for a board found by driving its pins, busy before it could be looked for
            ident, gaps = _busy(b.board.name, b.board, {})
            return identity.document([ident]), gaps
        except Problem as p:
            targets = []
            said = any(p is f for _, f in locks.failed)  # a failed look: said by its board below
            if not (said or (locks.skipped and p.result == "missing")):  # "none found": said by the busy board
                gaps.append(f"{p.result}: {p.reason}")
        for (board, host, found), key in zip(targets, runner._keys(targets)):
            why = {}
            # configured as in runner.verify: the Acorn reads a card it cannot name by its IDs only then (#155)
            board_options = {**{k: v for k, v in options.items() if k != "event"}, "board_key": key,
                             "configured": mode != config.AUTO}  # fmt: skip
            try:
                with hold_lock(board.lock, board.title, timeout=locks.wait):  # the only lock held meanwhile
                    ident = board.identify(host, found, board_options)
                    ident, report_why = from_report(board, ident, _boot_report(report))
                    why = dict.fromkeys(board.report_fields, report_why) if report_why else {}
            except Busy:
                ident, busy = _busy(key, board, found)
                out.append(ident)
                gaps += busy
                continue
            except Problem as p:
                ident, why = identity.base(key, board.name, found), {"": f"{p.result}: {p.reason}"}
            except Exception as e:  # a bug in a board's read: that board is not whole, the others are still read
                ident = identity.base(key, board.name, found)
                why = {"": f"the read crashed: {type(e).__name__}: {e}"}
            out.append(ident)
            fields = missing(board, ident, why)
            if not fields and "" in why:  # a board with no label fields whose read stopped
                fields = [("read", why[""])]
            gaps += [f"{key}: {f}: {reason}" for f, reason in fields]
        # With `auto`, a board that could not be looked for because its lock stayed held is never dropped, even
        # when other boards were found (runner.find keeps a weak claim when probing fails, and says so only in
        # its `how`): it is in the document with every field missing, for the reason "board busy".
        for board in locks.skipped:
            ident, busy = _busy(board.name, board, {})
            out.append(ident)
            gaps += busy
        # Likewise a board whose look failed (the NeTV2's scan left a pin driven): beside a weak claim,
        # runner.find keeps the claim and says the probe failed only in its `how`. It is in the document, unread.
        for board, problem in locks.failed:
            ident, failed = _failed(board, problem)
            out.append(ident)
            gaps += failed
    return identity.document(out), gaps


def run(options, prog="fpgas-verify", boards=None):
    """Print the document; 0 if every board's identity is whole, 1 otherwise (and say why on stderr)."""
    doc, gaps = read(options, boards)
    sys.stdout.write(dumps(doc))
    for gap in gaps:
        print(f"{prog} --identify: {gap}", file=sys.stderr)
    return 1 if gaps or not doc["boards"] else 0
