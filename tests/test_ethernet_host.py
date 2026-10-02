"""Unit tests for designs/ethernet-test/host/test_ethernet.py's run: the design is asked for its ident over the
UART (a fake BIOS) before the network is tested (arping and ping, faked)."""

import importlib.util
import json
import pathlib
import subprocess

import pytest

from .bios_fakes import FakeBios, ddr_replies, lines

_HOST = pathlib.Path(__file__).resolve().parents[1] / "designs" / "ethernet-test" / "host"
_spec = importlib.util.spec_from_file_location("test_ethernet_run", _HOST / "test_ethernet.py")
te = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(te)

ARTY = {"ident": lines("Ident: fpgas-online Ethernet Test SoC -- Arty A7 2026-10-03 08:40:00")}
ARP_OK = "ARPING 192.168.1.50 from 192.168.1.100 eth1\nUnicast reply from 192.168.1.50 [10:E2:D5:00:00:00]  0.789ms\n"
PING_OK = (
    "10 packets transmitted, 6 received, 40% packet loss, time 9012ms\n"
    "rtt min/avg/max/mdev = 0.412/0.501/0.611/0.061 ms\n"
)


def network(arp=(0, ARP_OK), ping=(0, PING_OK)):
    calls = []

    def run(argv, **kwargs):
        calls.append(argv[0])
        rc, out = {"arping": arp, "ping": ping}[argv[0]]
        return subprocess.CompletedProcess(argv, rc, out, "")

    return run, calls


@pytest.fixture
def board(monkeypatch):
    """The fake BIOS behind the UART; the adapter is configured only on paper."""
    state = {"fake": FakeBios(ARTY), "configured": []}
    monkeypatch.setattr(te.bios_console, "open_port", lambda port, baud: state["fake"])
    monkeypatch.setattr(te.time, "monotonic", lambda: state["fake"].now)
    monkeypatch.setattr(te, "configure_interface", lambda *args: state["configured"].append(args))
    return state


def run(run_network, board="arty"):
    return te.run_test(board, "/dev/ttyUSB1", 115200, eth_interface="eth1", run=run_network, euid=0)


def test_the_ethernet_design_that_answers_arp_and_ping_passes(board):
    run_network, calls = network()
    found = run(run_network)
    assert found["result"] == "pass"
    assert found["ident"] == "fpgas-online Ethernet Test SoC -- Arty A7 2026-10-03 08:40:00"
    assert (found["mac"], found["ping_sent"], found["ping_received"], found["rtt_avg_ms"]) == (
        te.LITEX_MAC,
        10,
        6,
        0.501,
    )
    assert board["fake"].commands == ["", "", "ident"]
    assert calls == ["arping", "ping"]


def test_another_design_fails_before_the_network_is_touched(board):
    board["fake"] = FakeBios(ddr_replies("arty"))
    run_network, calls = network()
    found = run(run_network)
    assert found["result"] == "fail"
    assert "not the Ethernet Test SoC for the Arty A7" in found["reason"]
    assert calls == [] and board["configured"] == []


def test_the_design_for_another_board_fails(board):
    found = run(network()[0], "netv2")
    assert found["result"] == "fail"
    assert "for the NeTV2" in found["reason"]


def test_nothing_on_the_uart_fails(board):
    board["fake"] = FakeBios(silent=True)
    found = run(network()[0])
    assert found["result"] == "fail"
    assert "nothing on the UART answers as a LiteX BIOS" in found["reason"]


def test_no_arp_reply_fails(board):
    found = run(network(arp=(1, "Sent 5 probes (5 broadcast(s))\nReceived 0 response(s)\n"))[0])
    assert found["result"] == "fail"
    assert "no ARP reply from 192.168.1.50" in found["reason"]


def test_an_arp_reply_from_another_mac_fails(board):
    other = "Unicast reply from 192.168.1.50 [B8:27:EB:12:34:56]  0.300ms\n"
    found = run(network(arp=(0, other))[0])
    assert found["result"] == "fail"
    assert "b8:27:eb:12:34:56, not 10:e2:d5:00:00:00" in found["reason"]


def test_one_ping_answered_of_ten_fails(board):
    found = run(network(ping=(1, "10 packets transmitted, 1 received, 90% packet loss, time 9012ms\n"))[0])
    assert found["result"] == "fail"
    assert "1 of 10 pings answered" in found["reason"]


def test_not_root_fails_without_touching_anything(board):
    run_network, calls = network()
    found = te.run_test("arty", "/dev/ttyUSB1", 115200, eth_interface="eth1", run=run_network, euid=1000)
    assert found["result"] == "fail"
    assert found["reason"] == "not running as root"
    assert calls == [] and board["fake"].commands == []


def test_a_port_that_cannot_be_opened_fails(board, monkeypatch):
    def opener(port, baud):
        raise OSError(2, "No such file or directory", port)

    monkeypatch.setattr(te.bios_console, "open_port", opener)
    found = run(network()[0])
    assert found["result"] == "fail"
    assert "cannot open /dev/ttyUSB1" in found["reason"]


def test_main_ends_with_the_result_line(board, monkeypatch, capsys):
    monkeypatch.setattr(te, "run_test", lambda *args: {"test": "ethernet", "board": "arty", "result": "pass"})
    assert te.main(["--board", "arty"]) == 0
    last = capsys.readouterr().out.strip().splitlines()[-1]
    assert last.startswith("RESULT_JSON ")
    assert json.loads(last[len("RESULT_JSON ") :])["result"] == "pass"
