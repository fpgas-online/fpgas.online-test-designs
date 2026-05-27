"""Tests for the board-validation logic in identify_pmod_pins.py.

These cover the pure expected-vs-decoded comparison used by `--board` mode.
The GPIO bit-bang reading needs real hardware (and libgpiod), but the
wiring-verdict logic must be correct without either — a miswired or
unprogrammed board must never be scored PASS.
"""

import importlib.util
import pathlib

# Import the host script directly by path (it lives in a hyphenated design
# directory that isn't a Python package). The module guards `import gpiod`,
# so this works on a dev machine with no libgpiod present.
_MOD_PATH = pathlib.Path(__file__).with_name("identify_pmod_pins.py")
_spec = importlib.util.spec_from_file_location("identify_pmod_pins", _MOD_PATH)
ident = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ident)


def test_acorn_board_map_matches_p2_header():
    # The Acorn P2 connector wiring documented in docs/hardware/acorn-pinmap.md.
    pins = {gpio: ball for gpio, ball, _label in ident.BOARDS["acorn"]["pins"]}
    assert pins == {14: "K2", 15: "J2", 3: "J5", 4: "H5"}


def test_evaluate_all_correct_passes():
    decoded = {14: "K2", 15: "J2", 3: "J5", 4: "H5"}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is True
    assert all(r["ok"] for r in rows)
    assert len(rows) == 4


def test_evaluate_one_miswired_fails():
    # GPIO14 and GPIO15 swapped -> both wrong -> overall FAIL.
    decoded = {14: "J2", 15: "K2", 3: "J5", 4: "H5"}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is False
    bad = {r["gpio"] for r in rows if not r["ok"]}
    assert bad == {14, 15}


def test_evaluate_missing_signal_fails():
    # GPIO4 reads nothing (None) -> that pin fails, overall FAIL.
    decoded = {14: "K2", 15: "J2", 3: "J5", 4: None}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is False
    failed = [r for r in rows if not r["ok"]]
    assert len(failed) == 1 and failed[0]["gpio"] == 4
    assert failed[0]["got"] is None


def test_evaluate_garbled_decode_fails():
    # A "?"-prefixed garbled decode must not be treated as a match.
    decoded = {14: "K2", 15: "J2", 3: "?Jx", 4: "H5"}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is False
    failed = [r for r in rows if not r["ok"]]
    assert len(failed) == 1 and failed[0]["gpio"] == 3


def test_evaluate_unprogrammed_board_all_none_fails():
    # No bitstream loaded -> every pin silent -> FAIL, not a false PASS.
    all_ok, rows = ident.evaluate_board("acorn", {})
    assert all_ok is False
    assert all(r["got"] is None and not r["ok"] for r in rows)
