#!/usr/bin/env python3
# designs/ethernet-test/host/test_ethernet.py
"""Host-side Ethernet test script.

Runs on the Raspberry Pi.  Tests Ethernet connectivity to an FPGA running
a LiteX SoC with LiteEth.

Steps:
  1. Detect the USB Ethernet adapter connected to the FPGA
  2. Attach to the design's LiteX BIOS over the UART and ask for its ident: it must be the Ethernet test
     design for this board (nothing is read from what the BIOS printed while it booted)
  3. Configure the adapter with static IP 192.168.1.100/24
  4. Send ARP requests: the reply must come from the BIOS's MAC (LiteX's 10:e2:d5:00:00:00)
  5. Send ICMP pings and verify the replies

The last line of output is the result for fpgas-verify: RESULT_JSON {"test": "ethernet", "result": ...}.

Usage:
    sudo python3 host/test_ethernet.py --board arty --uart-port /dev/ttyUSB1
    sudo python3 host/test_ethernet.py --board netv2 --uart-port /dev/ttyAMA0

Needs root, to configure the adapter and to send ARP: it asks to be rerun as root rather than calling sudo
itself (the boot check, fpgas-verify.service, runs as root already).
"""

import argparse
import ipaddress
import os
import re
import subprocess
import sys
import time

# In the repository the helper is in designs/_host; installed, it is beside this script.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_host"))

import bios_console

# -- Constants -----------------------------------------------------------------

FPGA_IP = "192.168.1.50"
HOST_IP = "192.168.1.100"
NETMASK = "255.255.255.0"
ATTACH_TIMEOUT_S = 60  # the BIOS tries a network boot before its first prompt

# What the BIOS's ident must contain: the design, and the board it was built for.
DESIGN_IDENT = "Ethernet Test SoC"
BOARD_IDENT = {"arty": "Arty A7", "netv2": "NeTV2"}

# The MAC the LiteX BIOS gives the design (litex/soc/software/bios/boot.c, macadr): an ARP reply from any
# other means something else on the link has the FPGA's address.
LITEX_MAC = "10:e2:d5:00:00:00"
MAC_RE = re.compile(r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})")

# -- Network interface detection -----------------------------------------------


def pick_test_interface(usb_ifaces, in_use):
    """The one USB Ethernet adapter that is free for the test, or None with the reason.

    An interface the Pi itself uses (it carries the default route or an address of its own) is never a
    candidate, whatever bus it is on: a Pi 3B+'s only Ethernet port is itself on USB (smsc95xx/lan78xx), and
    readdressing it takes the NFS root away and hangs the Pi (pi-sw1-p10, 2026-09-29). Two free adapters are
    refused rather than guessed between.
    """
    free = sorted(i for i in usb_ifaces if i not in in_use)
    if len(free) == 1:
        return free[0], None
    if not free:
        busy = ", ".join(sorted(set(usb_ifaces) & set(in_use)))
        return None, "no USB Ethernet adapter free for the test" + (f" ({busy}: the Pi's own link)" if busy else "")
    return None, f"more than one free USB Ethernet adapter ({', '.join(free)}): pass --interface"


def interfaces_in_use(default_routes, ipv4_addrs):
    """The interfaces the Pi itself uses, from `ip -o route show default` and `ip -o -4 addr show`.

    Any interface named by a default route (multipath `nexthop ... dev X` included), and any holding an IPv4
    address other than the test's own 192.168.1.100 or an IPv4 link-local 169.254/16 (which an idle adapter
    can pick up by itself at boot).
    """
    in_use = set(re.findall(r"\bdev\s+(\S+)", default_routes))
    for m in re.finditer(r"^\d+:\s+(\S+)\s+inet\s+(\S+)", ipv4_addrs, re.M):
        if not m.group(2).startswith((f"{HOST_IP}/", "169.254.")):
            in_use.add(m.group(1))
    return in_use


def find_usb_ethernet_interface(sysfs="/sys/class/net", ip=None):
    """(interface, None) for the USB Ethernet adapter cabled to the FPGA, or (None, reason).

    USB adapters are found by their sysfs device path. The Pi's own interfaces are those interfaces_in_use()
    names, plus any enslaved to another interface (a bridge, bond or VLAN's lower device: `master` or
    `upper_*` in sysfs), whose address sits on the upper interface.
    """
    ip = ip or (lambda *args: subprocess.run(["ip", *args], capture_output=True, text=True, check=True).stdout)
    usb, enslaved = [], set()
    for iface in sorted(os.listdir(sysfs)):
        if iface == "lo":
            continue
        if "/usb" in os.path.realpath(f"{sysfs}/{iface}/device"):
            usb.append(iface)
        if os.path.lexists(f"{sysfs}/{iface}/master") or any(
            n.startswith("upper_") for n in os.listdir(f"{sysfs}/{iface}")
        ):
            enslaved.add(iface)
    in_use = interfaces_in_use(ip("-o", "route", "show", "default"), ip("-o", "-4", "addr", "show")) | enslaved
    return pick_test_interface(usb, in_use)


def not_root_reason(iface, euid=None):
    """None when running as root; otherwise what to tell the user, who has to rerun the test as root."""
    if (os.geteuid() if euid is None else euid) == 0:
        return None
    return (
        f"FAIL - not running as root: configuring {iface} and sending ARP need root. "
        "Rerun this test as root (e.g. with sudo)."
    )


def configure_interface(iface, ip, netmask):
    """Configure network interface with static IP."""
    prefix_len = ipaddress.IPv4Network(f"0.0.0.0/{netmask}").prefixlen
    print(f"Configuring {iface} with {ip}/{prefix_len}...")
    subprocess.run(["ip", "addr", "flush", "dev", iface], check=True)
    subprocess.run(["ip", "addr", "add", f"{ip}/{prefix_len}", "dev", iface], check=True)
    subprocess.run(["ip", "link", "set", iface, "up"], check=True)
    # Poll for link to come up (carrier detect)
    for _ in range(40):
        try:
            with open(f"/sys/class/net/{iface}/carrier") as f:
                if f.read().strip() == "1":
                    break
        except OSError:
            pass
        time.sleep(0.1)
    print(f"  {iface} configured: {ip}/{prefix_len}")


# -- The BIOS -------------------------------------------------------------------


def check_bios(bios, board, timeout=ATTACH_TIMEOUT_S):
    """(ident, None) when the Ethernet test design for `board` answers at its prompt, else (ident, reason)."""
    try:
        bios.attach(timeout)
        ident = bios.ident()
    except bios_console.NoPrompt as e:
        return None, f"{e}: nothing on the UART answers as a LiteX BIOS"
    name = BOARD_IDENT[board]
    if not ident or DESIGN_IDENT not in ident or name not in ident:
        return ident, f"the design on the UART is {ident!r}, not the {DESIGN_IDENT} for the {name}"
    return ident, None


# -- Network tests --------------------------------------------------------------


def test_arp(fpga_ip, interface, timeout=10, run=subprocess.run):
    """Send ARP requests. Returns (replied, the replying MAC or None, reason or None)."""
    print(f"ARP test: arping {fpga_ip} on {interface}...")
    try:
        result = run(
            ["arping", "-c", "5", "-w", str(timeout), "-I", interface, fpga_ip], capture_output=True, text=True
        )
    except FileNotFoundError:
        return False, None, "'arping' not found: install iputils-arping (or arping)"
    print(f"  stdout: {result.stdout.strip()}")
    if result.returncode != 0:
        return False, None, f"no ARP reply from {fpga_ip}"
    macs = sorted({m.lower() for m in MAC_RE.findall(result.stdout)})
    if macs != [LITEX_MAC]:
        return True, ", ".join(macs) or None, f"ARP replies came from {', '.join(macs) or 'no MAC'}, not {LITEX_MAC}"
    return True, LITEX_MAC, None


def test_ping(fpga_ip, interface, count=10, timeout=2, run=subprocess.run):
    """Send ICMP pings. Returns {"ping_sent", "ping_received", "rtt_avg_ms"} and the reason it failed, or None.

    The LiteEth BIOS's ICMP handler takes one packet at a time and can miss about half the pings at one a
    second, so at least 2 replies out of 10 is a pass.
    """
    print(f"Ping test: ping {fpga_ip} via {interface} (count={count})...")
    result = run(
        ["ping", "-c", str(count), "-W", str(timeout), "-I", interface, fpga_ip], capture_output=True, text=True
    )
    print(f"  stdout: {result.stdout.strip()}")
    found = {"ping_sent": count, "ping_received": 0}
    m = re.search(r"(\d+) packets transmitted, (\d+) received", result.stdout)
    if m:
        found["ping_sent"], found["ping_received"] = int(m.group(1)), int(m.group(2))
    rtt = re.search(r"= [0-9.]+/([0-9.]+)/", result.stdout)
    if rtt:
        found["rtt_avg_ms"] = float(rtt.group(1))
    if found["ping_received"] < 2:
        return found, f"{found['ping_received']} of {found['ping_sent']} pings answered"
    return found, None


# -- Main test runner -----------------------------------------------------------


def run_test(board, uart_port, baud, eth_interface=None, run=subprocess.run, euid=None):
    """Run the full Ethernet test sequence. Returns the result's fields ("result", "reason", ...)."""
    found = {"test": "ethernet", "board": board}

    def failed(reason):
        print(f"FAIL: {reason}")
        return {**found, "result": "fail", "reason": reason}

    print(f"=== Ethernet Test ({board}) ===")
    print(f"UART:     {uart_port} @ {baud}")
    print(f"FPGA IP:  {FPGA_IP}")
    print(f"Host IP:  {HOST_IP}")
    print()

    # Step 1: the USB Ethernet adapter, and root to configure it and send ARP
    if eth_interface:
        iface = eth_interface
    else:
        print("Detecting USB Ethernet adapter...", flush=True)
        iface, why = find_usb_ethernet_interface()
        if not iface:
            return failed(why)
        print(f"  found: {iface}")
    found["interface"] = iface
    why = not_root_reason(iface, euid)
    if why:
        print(why, file=sys.stderr)
        return {**found, "result": "fail", "reason": "not running as root"}

    # Step 2: the design answering on the UART
    try:
        ser = bios_console.open_port(uart_port, baud)
    except (OSError, ImportError) as e:  # no such port, port in use, no pyserial
        return failed(f"cannot open {uart_port}: {e}")
    try:
        found["ident"], why = check_bios(bios_console.BiosConsole(ser, clock=time.monotonic), board)
    except OSError as e:  # the port went away (pyserial's SerialException is one)
        why = f"the UART failed: {e}"
    finally:
        ser.close()
    if why:
        return failed(why)
    print(f"PASS: {found['ident']}")

    # Steps 3-5: the network
    configure_interface(iface, HOST_IP, NETMASK)
    faults = []
    print()
    found["arp"], found["mac"], why = test_arp(FPGA_IP, iface, run=run)
    if why:
        faults.append(why)
    else:
        print(f"PASS: ARP: {FPGA_IP} is at {found['mac']}")
    print()
    ping, why = test_ping(FPGA_IP, iface, run=run)
    found.update(ping)
    if why:
        faults.append(why)
    else:
        print(f"PASS: ping: {ping['ping_received']} of {ping['ping_sent']} answered")

    if faults:
        for fault in faults:
            print(f"FAIL: {fault}")
        return {**found, "result": "fail", "reason": "; ".join(faults)}
    return {**found, "result": "pass"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Ethernet Test (host-side)")
    parser.add_argument("--board", required=True, choices=list(BOARD_IDENT), help="Target board")
    parser.add_argument(
        "--uart-port", default=None, help="UART port (default: /dev/ttyUSB1 for arty, /dev/ttyAMA0 for netv2)"
    )
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--interface", default=None, help="Network interface (auto-detect if not specified)")
    args = parser.parse_args(argv)

    if args.uart_port is None:
        args.uart_port = "/dev/ttyUSB1" if args.board == "arty" else "/dev/ttyAMA0"

    try:
        found = run_test(args.board, args.uart_port, args.baud, args.interface)
    except (subprocess.SubprocessError, OSError) as e:  # `ip` refused the adapter, ping missing, ...
        found = {"test": "ethernet", "board": args.board, "result": "fail", "reason": f"the test could not run: {e}"}
        print(f"FAIL: {found['reason']}")
    print()
    print(
        "RESULT: PASS — Ethernet test completed successfully"
        if found["result"] == "pass"
        else "RESULT: FAIL — Ethernet test had failures"
    )
    bios_console.print_result_json(found)
    return 0 if found["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
