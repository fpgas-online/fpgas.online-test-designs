"""What a board module provides, and finding the installed ones.

Each board is a module in the `fpgas_online_verify.boards` namespace package with a `BOARD` object; each
ships in its own package (fpgas-online-<board>-tools), so the boards this host can verify are exactly the
modules that are installed. A board module is the only place that knows its board.
"""

import importlib
import pkgutil

from .core import host_facts


class Board:
    """The interface. `found` is whatever `spot`/`probe` returned for one board: a dict with at least
    "variant", and what identifies it (a USB serial, a PCI slot, an IDCODE)."""

    name = ""  # as written in fpga-board = ..., and in reports
    slug = ""  # in package and command names: fpgas-online-<slug>-tools, fpgas-<slug>-verify
    title = ""
    probes = False  # True when finding it means driving something (a JTAG scan over the GPIO header)

    def facts(self, port=None):
        """What the check needs to know about this host."""
        return {**host_facts(), "port": port}

    @property
    def lock(self):
        """Held while the board is used: one user at a time, the verify or fpgas-<board>-debug."""
        return f"/run/fpgas-online/{self.slug}.lock"

    @property
    def package(self):
        return f"fpgas-online-{self.slug}-tools"

    def spot(self, host, usb, pci):
        """The boards of this kind visible without driving anything: from USB and PCI IDs."""
        return []

    def probe(self, host):
        """The boards found by actively looking (only for `probes` boards)."""
        return []

    def find(self, host, usb, pci):
        return self.spot(host, usb, pci) or (self.probe(host) if self.probes else [])

    def check(self, host, found, options):
        """Verify one found board: a dict with "result", maybe "reason", and the details; "state" holds the
        facts that must not change between runs (see state.py)."""
        raise NotImplementedError


def installed():
    """{name: Board} for every board module installed."""
    from . import boards

    found = {}
    for info in pkgutil.iter_modules(boards.__path__, boards.__name__ + "."):
        module = importlib.import_module(info.name)
        board = getattr(module, "BOARD", None)
        if isinstance(board, Board):
            found[board.name] = board
    return dict(sorted(found.items()))
