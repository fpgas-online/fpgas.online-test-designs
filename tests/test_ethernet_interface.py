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


# Real `ip -o` output, 2026-09-30.
NETV2_ROUTES = "default via 10.21.0.1 dev eth-uplink \n"  # pi-sw1-p12, a Pi 3B+
NETV2_ADDRS = (
    "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever\n"
    "2: eth-uplink    inet 10.21.1.12/16 brd 10.21.255.255 scope global eth-uplink\\       valid_lft forever\n"
)
ARTY_ROUTES = "default via 10.21.0.1 dev eth0 \n"  # pi-sw2-p12, a Pi 4, after an earlier test run
ARTY_ADDRS = (
    "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever preferred_lft forever\n"
    "2: eth0    inet 10.21.2.12/16 brd 10.21.255.255 scope global eth0\\       valid_lft forever\n"
    "3: eth1    inet 192.168.1.100/24 scope global eth1\\       valid_lft forever preferred_lft forever\n"
)


def test_the_pis_own_link_is_in_use_and_an_adapter_left_at_the_test_address_is_not():
    assert te.interfaces_in_use(NETV2_ROUTES, NETV2_ADDRS) == {"lo", "eth-uplink"}
    assert te.interfaces_in_use(ARTY_ROUTES, ARTY_ADDRS) == {"lo", "eth0"}


def test_link_local_and_multipath_routes():
    addrs = "3: eth1    inet 169.254.7.9/16 brd 169.254.255.255 scope link eth1\\ valid_lft forever\n"
    assert te.interfaces_in_use("", addrs) == set()  # an idle adapter's IPv4LL address is not the Pi's link
    routes = ("default proto static metric 100 \\\tnexthop via 10.0.0.1 dev eth0 weight 1 "
              "\\\tnexthop via 10.0.1.1 dev wlan0\n")  # fmt: skip
    assert te.interfaces_in_use(routes, "") == {"eth0", "wlan0"}
    both = "3: eth1    inet 192.168.1.100/24 scope global eth1\n3: eth1    inet 10.9.0.2/24 scope global eth1\n"
    assert te.interfaces_in_use("", both) == {"eth1"}  # the test's address does not hide a real one


def _sysfs(tmp_path, **ifaces):
    """{name: (bus, extra files)}: /sys/class/net/<name>/device pointing into a USB or platform path."""
    net = tmp_path / "net"
    for name, (bus, extra) in ifaces.items():
        target = tmp_path / "devices" / ("usb1/1-1/1-1.2:1.0" if bus == "usb" else "platform/fd580000.ethernet")
        target.mkdir(parents=True, exist_ok=True)
        (net / name).mkdir(parents=True)
        (net / name / "device").symlink_to(target)
        for f in extra:
            (net / name / f).write_text("")
    return str(net)


def test_find_on_a_pi3b_picks_nothing_and_on_a_pi4_picks_the_adapter(tmp_path):
    netv2 = _sysfs(tmp_path / "a", **{"eth-uplink": ("usb", [])})
    ip = {("-o", "route", "show", "default"): NETV2_ROUTES, ("-o", "-4", "addr", "show"): NETV2_ADDRS}
    assert te.find_usb_ethernet_interface(netv2, lambda *a: ip[a])[0] is None
    arty = _sysfs(tmp_path / "b", eth0=("platform", []), eth1=("usb", []))
    ip = {("-o", "route", "show", "default"): ARTY_ROUTES, ("-o", "-4", "addr", "show"): ARTY_ADDRS}
    assert te.find_usb_ethernet_interface(arty, lambda *a: ip[a]) == ("eth1", None)


def test_a_usb_adapter_under_a_bridge_or_vlan_is_in_use(tmp_path):
    sysfs = _sysfs(tmp_path, eth1=("usb", ["master"]), eth2=("usb", ["upper_eth2.5"]))
    iface, why = te.find_usb_ethernet_interface(sysfs, lambda *a: "")
    assert iface is None and "eth1, eth2" in why


def test_two_free_adapters_are_refused_not_guessed():
    iface, why = te.pick_test_interface(["eth1", "eth2"], {"eth0"})
    assert iface is None
    assert why == "more than one free USB Ethernet adapter (eth1, eth2): pass --interface"
