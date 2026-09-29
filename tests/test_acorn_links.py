"""The Acorn's P1 JTAG and P2 UART checks (boards/acorn/links.py), and how they fold into the board's result.

Real output from pi-sw2-p48 (2026-09-29): `openFPGALoader --cable libgpiod --pins 10:9:11:8 --detect` printed
"idcode 0x3636093", and a UARTBone read on /dev/ttyAMA0 returned the BAR0 identifier. pi-sw2-p47's P2 was once
reported dead (test-designs #55) with nothing in the boot check to say so.
"""

from fpgas_online_verify.boards.acorn import BOARD as ACORN
from fpgas_online_verify.boards.acorn import check as acorn_check
from fpgas_online_verify.boards.acorn import links, uartbone_link
from fpgas_online_verify.core import Problem

DETECT_OK = "index 0:\n\tidcode 0x3636093\n\tmanufacturer xilinx\n\tfamily artix a7 200t\n\tmodel  xc7a200\n"
IDENT = "fpgas-online Acorn PCIe SoC cle-215+ 2026-09-24 00:16:54"


class Run:
    def __init__(self, detect=(0, DETECT_OK)):
        self.detect, self.calls = detect, []

    def __call__(self, argv, timeout):
        self.calls.append(list(argv))
        if argv[0] == "openFPGALoader":
            if isinstance(self.detect, Exception):
                raise self.detect
            return self.detect
        return 0, ""


def _no_chip():
    pass


def test_a_chain_with_the_variants_fpga_passes_and_the_pins_are_released():
    run = Run()
    t = links.jtag("cle-215+", run, gpiochip=_no_chip)
    assert t["test"] == "jtag" and t["result"] == "pass"
    assert run.calls[0] == ["openFPGALoader", "--cable", "libgpiod", "--pins", "10:9:11:8", "--detect"]
    assert run.calls[-1] == ["pinctrl", "set", "8,9,10,11", "ip", "pd"]  # openFPGALoader leaves them driven


def test_an_empty_chain_fails():
    t = links.jtag("cle-215+", Run((1, "JTAG init failed with: no device found")), gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"] == "no device on the P1 JTAG chain"


def test_the_wrong_part_fails_and_says_which():
    t = links.jtag("cle-101", Run(), gpiochip=_no_chip)
    assert t["result"] == "fail" and t["reason"] == "P1 JTAG chain has 0x3636093, expected 0x3631093 for cle-101"


def test_a_probe_that_cannot_run_fails_and_still_releases_the_pins():
    run = Run(Problem("error", "openFPGALoader is not installed"))
    t = links.jtag("cle-215+", run, gpiochip=_no_chip)
    assert t["result"] == "fail" and "openFPGALoader is not installed" in t["reason"]
    assert run.calls[-1][0] == "pinctrl"


class Port:
    """A pyserial stand-in for a SoC answering UARTBone reads of the identifier memory."""

    def __init__(self, ident):
        self.ident, self.out = ident.encode() + b"\0", b""
        self.baudrate, self.break_condition = 1200, False

    def write(self, data):
        cmd, words, addr = data[0], data[1], int.from_bytes(data[2:6], "big") * 4
        assert cmd == uartbone_link.CMD_READ or cmd == uartbone_link.CMD_WRITE
        if cmd == uartbone_link.CMD_READ:
            base = (addr - uartbone_link.IDENT_ADDR) // 4
            for i in range(words):
                c = self.ident[base + i] if 0 <= base + i < len(self.ident) else 0
                self.out += c.to_bytes(4, "big")

    def read(self, n):
        data, self.out = self.out[:n], self.out[n:]
        return data

    def reset_input_buffer(self):
        self.out = b""

    def flush(self):
        pass

    def close(self):
        pass


def test_a_p2_uart_that_returns_the_bar0_identifier_passes():
    t = links.p2_uart(IDENT, open_port=lambda baud: Port(IDENT))
    assert t["result"] == "pass", t


def test_a_silent_p2_uart_fails():
    t = links.p2_uart(IDENT, open_port=lambda baud: Port(""))
    assert t["result"] == "fail" and t["reason"] == "no UARTBone reply on /dev/ttyAMA0 (P2 K2/J2)"


def test_a_p2_uart_answering_for_another_build_fails():
    t = links.p2_uart(IDENT, open_port=lambda baud: Port("fpgas-online Acorn PCIe SoC cle-215+ 2026-01-01 00:00:00"))
    assert t["result"] == "fail" and "is not the BAR0 identifier" in t["reason"]


FOUND = {"bdf": "0001:01:00.0", "ids": "10ee:7021", "subsystem": "1e24:021f", "kind": "fpgas-online",
         "variant": "cle-215+"}  # fmt: skip


def _checked(monkeypatch, tmp_path, run, port):
    monkeypatch.setattr(acorn_check, "load_release", lambda images: ({"tag": "t"}, {}))
    monkeypatch.setattr(acorn_check, "check_board",
                        lambda *a: {**FOUND, "result": "pass", "running": {"identifier": IDENT}})  # fmt: skip
    monkeypatch.setattr(links, "_header_gpiochip", _no_chip)
    return ACORN.check({}, FOUND, {"images": tmp_path, "run": run, "uart_opener": lambda baud: port})


def test_a_board_whose_links_work_passes_with_both_tests_reported(monkeypatch, tmp_path):
    report = _checked(monkeypatch, tmp_path, Run(), Port(IDENT))
    assert report["result"] == "pass"
    assert [(t["test"], t["result"]) for t in report["tests"]] == [("jtag", "pass"), ("p2-uart", "pass")]


def test_a_dead_p2_uart_fails_a_board_whose_pcie_side_passes(monkeypatch, tmp_path):
    report = _checked(monkeypatch, tmp_path, Run(), Port(""))
    assert report["result"] == "fail" and report["reason"] == "no UARTBone reply on /dev/ttyAMA0 (P2 K2/J2)"


def test_a_missing_jtag_chain_fails_the_board(monkeypatch, tmp_path):
    report = _checked(monkeypatch, tmp_path, Run((1, "")), Port(IDENT))
    assert report["result"] == "fail" and report["reason"] == "no device on the P1 JTAG chain"
