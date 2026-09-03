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


# Canonical fleet wiring (docs/hardware/acorn-pinmap.md, revised 2026-09-03):
# FPGA TX K2 -> Pi RXD0 (GPIO15), FPGA RX J2 <- Pi TXD0 (GPIO14),
# J5 -> GPIO3, H5 -> GPIO4.
CANONICAL = {15: "K2", 14: "J2", 3: "J5", 4: "H5"}


def test_acorn_board_map_matches_p2_header():
    pins = {gpio: ball for gpio, ball, _label in ident.BOARDS["acorn"]["pins"]}
    assert pins == CANONICAL


def test_evaluate_all_correct_passes():
    all_ok, rows = ident.evaluate_board("acorn", dict(CANONICAL))
    assert all_ok is True
    assert all(r["ok"] for r in rows)
    assert len(rows) == 4


def test_evaluate_one_miswired_fails():
    # Serial pair swapped (K2 on GPIO14, J2 on GPIO15) -> both wrong -> FAIL.
    decoded = {15: "J2", 14: "K2", 3: "J5", 4: "H5"}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is False
    bad = {r["gpio"] for r in rows if not r["ok"]}
    assert bad == {14, 15}


def test_evaluate_p47_reversed_connector_fails_all_four():
    # pi-sw2-p47 on 2026-08-31: both pairs transposed.
    decoded = {14: "K2", 15: "J2", 3: "H5", 4: "J5"}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is False
    assert {r["gpio"] for r in rows if not r["ok"]} == {3, 4, 14, 15}


def test_evaluate_missing_signal_fails():
    # GPIO4 reads nothing (None) -> that pin fails, overall FAIL.
    decoded = {15: "K2", 14: "J2", 3: "J5", 4: None}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is False
    failed = [r for r in rows if not r["ok"]]
    assert len(failed) == 1 and failed[0]["gpio"] == 4
    assert failed[0]["got"] is None


def test_evaluate_garbled_decode_fails():
    # A "?"-prefixed garbled decode must not be treated as a match.
    decoded = {15: "K2", 14: "J2", 3: "?Jx", 4: "H5"}
    all_ok, rows = ident.evaluate_board("acorn", decoded)
    assert all_ok is False
    failed = [r for r in rows if not r["ok"]]
    assert len(failed) == 1 and failed[0]["gpio"] == 3


def test_evaluate_unprogrammed_board_all_none_fails():
    # No bitstream loaded -> every pin silent -> FAIL, not a false PASS.
    all_ok, rows = ident.evaluate_board("acorn", {})
    assert all_ok is False
    assert all(r["got"] is None and not r["ok"] for r in rows)


# -- Edge-timestamp UART decoder ------------------------------------------------

BIT_NS = int(1e9 / 1200)


def _edges_for(text, start_ns=1_000_000, baud_bit_ns=BIT_NS):
    """Synthesise (level, timestamp_ns) edge events for 8N1 frames of *text*,
    idle-high, back to back, exactly as gpiomon would report them."""
    bits = []
    for ch in text.encode():
        bits += [0] + [(ch >> k) & 1 for k in range(8)] + [1]
    events = []
    level = 1
    t = start_ns
    for b in bits:
        if b != level:
            events.append((b, t))
            level = b
        t += baud_bit_ns
    return events


def test_decode_edges_recovers_clean_frames():
    events = _edges_for("J5\r\nJ5\r\n")
    frames = ident.decode_edges(events, baud=1200)
    assert [b for b, _ok in frames] == list(b"J5\r\nJ5\r\n")
    assert all(ok for _b, ok in frames)


def test_decode_edges_tolerates_baud_error_and_jitter():
    # 2% slow transmitter plus +-40 us of edge jitter must still decode.
    import random
    rnd = random.Random(1)
    events = [(lvl, t + rnd.randint(-40_000, 40_000)) for lvl, t in
              _edges_for("K2\r\n" * 3, baud_bit_ns=int(BIT_NS * 1.02))]
    frames = ident.decode_edges(events, baud=1200)
    assert [b for b, _ok in frames] == list(b"K2\r\n" * 3)


def test_decode_edges_resyncs_from_any_capture_phase():
    # A capture can start on any edge of the periodic "XX\r\n" stream. From
    # every possible starting edge the decoder must lock onto the real start
    # bits, not alias onto a wrong falling edge for the whole capture (which
    # is what happened on pi-sw2-p46 GPIO3: a stable 4-byte garbage pattern
    # with no newline ever decoded).
    full = _edges_for("J5\r\n" * 6)
    for drop in range(0, 12):
        frames = ident.decode_edges(full[drop:], baud=1200)
        text = bytes(b for b, ok in frames if ok)
        assert b"J5\r\nJ5\r\nJ5\r\n" in text, f"drop={drop}: {text!r}"


def test_labels_from_frames_votes_on_valid_labels():
    frames = [(b, True) for b in b"\xabJ5\r\nJ5\r\nJ5\r\n"]
    assert ident.label_from_frames(frames) == "J5"


def test_labels_from_frames_returns_garbled_marker_without_valid_label():
    frames = [(b, True) for b in b"\xab\xd6\x0a\xab\xd6\x0a"]
    got = ident.label_from_frames(frames)
    assert got is not None and got.startswith("?")


def test_labels_from_frames_none_when_silent():
    assert ident.label_from_frames([]) is None
