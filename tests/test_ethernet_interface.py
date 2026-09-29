"""designs/ethernet-test/host/test_ethernet.py must only ever readdress a USB adapter the Pi does not use itself.

A Pi 3B+'s only Ethernet port is on USB. The old chooser returned the only USB interface it found, readdressed
it to 192.168.1.100, and took pi-sw1-p10's NFS root away (2026-09-29; the Pi had to be PoE-cycled).
"""

import importlib.util
import pathlib

_HOST = pathlib.Path(__file__).resolve().parents[1] / "designs" / "ethernet-test" / "host"
_spec = importlib.util.spec_from_file_location("test_ethernet_host", _HOST / "test_ethernet.py")
te = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(te)


def test_a_pi_whose_only_usb_ethernet_is_its_own_link_gets_no_interface():
    iface, why = te.pick_test_interface(["eth-uplink"], {"eth-uplink"})
    assert iface is None
    assert why == "no USB Ethernet adapter free for the test (eth-uplink: the Pi's own link)"


def test_the_adapter_cabled_to_the_fpga_is_picked_beside_the_pis_own_link():
    """A Pi 4: eth0 is on-board (not USB) and carries the Pi's address; eth1 is the USB adapter to the Arty."""
    assert te.pick_test_interface(["eth1"], {"eth0"}) == ("eth1", None)
    # A Pi 3B+ with a second adapter: its own link is USB too, but it is in use.
    assert te.pick_test_interface(["eth0", "eth1"], {"eth0"}) == ("eth1", None)


def test_no_usb_adapter_at_all():
    assert te.pick_test_interface([], {"eth0"}) == (None, "no USB Ethernet adapter free for the test")


def test_two_free_adapters_are_refused_not_guessed():
    iface, why = te.pick_test_interface(["eth1", "eth2"], {"eth0"})
    assert iface is None
    assert why == "more than one free USB Ethernet adapter (eth1, eth2): pass --interface"
