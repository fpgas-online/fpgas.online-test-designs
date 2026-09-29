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


# -- main(): --board versus an explicit pin selection -----------------------------


def _main(monkeypatch, argv, decoded):
    scanned = []
    monkeypatch.setattr(ident.sys, "argv", ["identify_pmod_pins.py", *argv])
    monkeypatch.setattr(ident, "release_kernel_gpio_drivers", lambda: None)
    monkeypatch.setattr(ident, "detect_gpio_chip", lambda: "/dev/gpiochip0")
    monkeypatch.setattr(ident, "scan_gpios", lambda gpios, chip: scanned.extend(gpios) or dict(decoded))
    try:
        ident.main()
        code = 0
    except SystemExit as e:
        code = e.code
    return code, scanned


def test_board_mode_fails_a_miswired_board(monkeypatch):
    code, scanned = _main(monkeypatch, ["--board", "tt"], {8: "13"})
    assert code == 1 and scanned == [gpio for gpio, _b, _l in ident.BOARDS["tt"]["pins"]]


def test_an_explicit_hat_port_after_board_is_a_discovery_scan(monkeypatch):
    """fpgas-<board>-debug test pin-id -- --hat-port JA appends to the boot check's --board arguments."""
    code, scanned = _main(monkeypatch, ["--board", "arty", "--hat-port", "JA"], {8: "G13"})
    assert scanned == ident.PMOD_HAT_PORTS["JA"] and code in (0, None)


# -- iCE40 pin numbers, and the Arty / TT HAT maps -------------------------------


def test_ice40_package_pin_numbers_are_valid_labels():
    """The TT FPGA and Fomu designs send "13", "45", ...: all TT pins used to read as garbled."""
    frames = [(b, True) for b in b"13\r\n13\r\n13\r\n"]
    assert ident.label_from_frames(frames) == "13"
    assert ident.is_valid_label("2") and ident.is_valid_label("48")
    assert not ident.is_valid_label("0") and not ident.is_valid_label("100")


def test_the_shared_hat_gpios_are_not_part_of_a_wiring_check():
    """GPIO10/9/11 are HAT JA pins 2-4 and JB pins 2-4 at once: two cables drive them."""
    for board in ("arty", "tt"):
        gpios = [gpio for gpio, _ball, _label in ident.BOARDS[board]["pins"]]
        assert not {9, 10, 11} & set(gpios), board
        assert len(gpios) == len(set(gpios)) == 18, board


def _decoded(board):
    return {gpio: ball for gpio, ball, _label in ident.BOARDS[board]["pins"]}


def test_a_straight_through_arty_passes_and_welland_p12_as_cabled_fails():
    assert ident.evaluate_board("arty", _decoded("arty"))[0]
    # pi-sw2-p12, 2026-09-29: HAT JA <- Arty JC, JB <- Arty JD, JC <- Arty JB; Arty JA not cabled.
    p12 = {8: "V12", 19: "U14", 21: "V14", 20: "T13", 18: "U13", 7: "D4", 26: "E2", 13: "D2", 3: "H2", 2: "G2",
           16: "E15", 14: "E16", 15: "D15", 17: "C15", 4: "J17", 12: "J18", 5: "K15", 6: "J15"}  # fmt: skip
    all_ok, rows = ident.evaluate_board("arty", p12)
    assert not all_ok
    assert not any(r["ok"] for r in rows)


def test_a_tt_cabled_as_documented_passes_and_welland_as_cabled_fails():
    assert ident.evaluate_board("tt", _decoded("tt"))[0]
    # pi-sw2-p33/p35/p36, 2026-09-29: ui_in on HAT JA and uo_out on HAT JC (the doc has them the other way).
    welland = {8: "13", 19: "23", 21: "25", 20: "26", 18: "27", 7: "2", 26: "9", 13: "10", 3: "11", 2: "12",
               16: "38", 14: "42", 15: "43", 17: "44", 4: "45", 12: "46", 5: "47", 6: "48"}  # fmt: skip
    all_ok, rows = ident.evaluate_board("tt", welland)
    assert not all_ok
    assert [r["gpio"] for r in rows if r["ok"]] == [7, 26, 13, 3, 2]  # uio on JB matches
