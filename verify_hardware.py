#!/usr/bin/env python3
"""Automated hardware verification runner.

Runs all confirmed-passing test designs on actual FPGA hardware, one at a time.
Builds incrementally — start with known-good tests and expand as more are verified.

Each test: uploads bitstream + script -> programs FPGA -> runs test -> checks result.
The individual test scripts handle their own timeouts and boot-wait logic, so this
runner never sleeps — it just orchestrates.

Usage:
    uv run python verify_hardware.py              # Run all enabled tests
    uv run python verify_hardware.py --test uart   # Run only UART tests
    uv run python verify_hardware.py --host pi3    # Run only tests on pi3
    uv run python verify_hardware.py --board arty  # Run only Arty tests
    uv run python verify_hardware.py --list        # List all tests
"""

import argparse
import os
import re
import shlex
import subprocess
import sys
import time

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(REPO_DIR, "artifacts")
# Jump hosts. Welland's tweed was reinstalled 2026-08-30; the old restricted
# `pi@tweed.welland.mithis.com` account is gone and the public name now resolves
# to a reverse proxy. tweed's eth-local address is reachable over WireGuard
# (wg-desktop) and accepts the operator's own key. PS1 is unchanged (unverified
# since 2026-03).
GATEWAYS = {
    "welland": "tim@10.21.0.1",
    "ps1": "pi@ps1.fpgas.online",
}
SSH_BASE_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]

# PoE switches, keyed by the `switch` field of a host's `poe` entry. The S3300
# at Welland answers SNMP from tweed (read community `public` verified
# 2026-09-03). Port power is POWER-ETHERNET-MIB pethPsePortAdminEnable
# (.1.3.6.1.2.1.105.1.1.1.3.<group>.<port>): 1 = enable, 2 = disable.
POE_SWITCHES = {
    "sw2": {"address": "10.1.5.11", "group": 1},
}
POE_ADMIN_ENABLE_OID = "1.3.6.1.2.1.105.1.1.1.3"
# The SNMP write community is deliberately not in the repo. Export it as
# FPGAS_POE_COMMUNITY (it lives in fpgas.online-infra) before running tests
# that need a power cycle; without it poe_reset() reports and returns False.
POE_COMMUNITY_ENV = "FPGAS_POE_COMMUNITY"


def poe_snmp_cmd(host_name, enable, community):
    """snmpset argv (run on the gateway) that turns a host's PoE port on/off."""
    poe = HOSTS[host_name]["poe"]  # KeyError for hosts without PoE info
    sw = POE_SWITCHES[poe["switch"]]
    oid = f"{POE_ADMIN_ENABLE_OID}.{sw['group']}.{poe['port']}"
    return ["snmpset", "-v2c", "-c", community, sw["address"], oid, "i", "1" if enable else "2"]


# ---------------------------------------------------------------------------
# Host definitions — each RPi we can reach
# ---------------------------------------------------------------------------

HOSTS = {
    # Welland site (via the tweed gateway, see GATEWAYS).
    # Legacy 10.21.0.1NN addresses from the 2026-03 survey — not re-probed since
    # the VLAN-per-port move (2026-08-23); see docs/hardware/site-welland.md.
    "welland-pi3": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.103", "board": "arty"},
    "welland-pi5": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.105", "board": "arty"},
    "welland-pi9": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.109", "board": "arty"},
    # welland-pi11: arty — FTDI disconnected, cannot program/test
    "welland-pi13": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.113", "board": "arty"},
    "welland-pi17": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.117", "board": "fomu"},
    "welland-pi21": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.121", "board": "fomu"},
    "welland-pi10": {
        "ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.110",
        "board": "netv2", "variant": "a7-35",
    },
    "welland-pi12": {
        "ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.112",
        "board": "netv2", "variant": "a7-35",
    },
    "welland-pi14": {
        "ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.114",
        "board": "netv2", "variant": "a7-35",
    },
    "welland-pi16": {
        "ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.116",
        "board": "netv2", "variant": "a7-35",
    },
    "welland-pi18": {
        "ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.118",
        "board": "netv2", "variant": "a7-35",
    },
    # Sqrl Acorn CLE-215+ on RPi 5 (VLAN-per-port names since 2026-08-23, see
    # docs/hardware/site-welland.md). Login is the `pi` user with passwordless
    # sudo; root login is refused. PoE port = switch port = host suffix.
    **{
        f"welland-sw2-p{port}": {
            "ssh_type": "gateway", "gateway": "welland",
            "target": f"10.21.2.{port}", "user": "pi",
            "board": "acorn", "variant": "cle-215+",
            "poe": {"switch": "sw2", "port": port},
        }
        for port in (29, 43, 44, 46, 47, 48)
    },
    "welland-pi27": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.127", "board": "tt"},
    "welland-pi29": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.129", "board": "tt"},
    "welland-pi31": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.131", "board": "tt"},
    "welland-pi33": {"ssh_type": "gateway", "gateway": "welland", "target": "10.21.0.133", "board": "tt"},
    # PS1 site (via pi@ps1.fpgas.online gateway)
    "ps1-pi2": {"ssh_type": "gateway", "gateway": "ps1", "target": "10.21.0.102", "board": "arty"},  # [offline]
    "ps1-pi3": {"ssh_type": "gateway", "gateway": "ps1", "target": "10.21.0.103", "board": "arty"},
    "ps1-pi5": {"ssh_type": "gateway", "gateway": "ps1", "target": "10.21.0.105", "board": "arty"},
    "ps1-pi7": {"ssh_type": "gateway", "gateway": "ps1", "target": "10.21.0.107", "board": "arty"},
    "ps1-pi9": {"ssh_type": "gateway", "gateway": "ps1", "target": "10.21.0.109", "board": "arty"},
    "ps1-pi11": {"ssh_type": "gateway", "gateway": "ps1", "target": "10.21.0.111", "board": "arty"},
    "ps1-pi13": {"ssh_type": "gateway", "gateway": "ps1", "target": "10.21.0.113", "board": "arty"},
    "ps1-pi17": {"ssh_type": "gateway", "gateway": "ps1", "target": "10.21.0.117", "board": "arty"},
    # Direct SSH
    "rpi5-netv2": {
        "ssh_type": "direct",
        "target": "tim@rpi5-netv2.iot.welland.mithis.com",
        "board": "netv2",
        "variant": "a7-100",
        "serial_port": "/dev/ttyAMA0",
    },
    "rpi3-netv2": {
        "ssh_type": "direct",
        "target": "pi@rpi3-netv2.iot.welland.mithis.com",
        "board": "netv2",
        "variant": "a7-35",
        "serial_port": "/dev/serial0",
    },
}

# Board-specific FPGA programming commands (use {bitstream} placeholder)
PROGRAM_CMD = {
    "arty": "openFPGALoader -b arty {bitstream}",
    "fomu": "openFPGALoader -b fomu {bitstream}",
    "tt": "python3 ~/tt_fpga_program.py /dev/ttyACM0 {bitstream}",
    # Acorn on RPi 5 (docs/hardware/acorn-pinmap.md, "Pi 5" notes):
    #  1. detach the PCIe endpoint — reconfiguring an enumerated endpoint
    #     crashes the Pi 5 (2026-08-31, pi-sw2-p47);
    #  2. openFPGALoader 0.10.0 opens /dev/gpiochip0 but the header is
    #     gpiochip15 (devtmpfs symlink, lost at reboot);
    #  3. libgpiod bit-bang JTAG, pin order TDI:TDO:TCK:TMS (~16 s);
    #  4. rescan so the flash-resident endpoint (or the new design's) is back.
    "acorn": (
        "if [ -e /sys/bus/pci/devices/0001:01:00.0 ]; then"
        " echo 1 > /sys/bus/pci/devices/0001:01:00.0/remove; fi;"
        " ln -sfn /dev/gpiochip15 /dev/gpiochip0;"
        " openFPGALoader --cable libgpiod --pins 10:9:11:8 {bitstream};"
        " echo 1 > /sys/bus/pci/rescan"
    ),
    # NeTV2 varies by host — handled per-host below
}

# Per-host overrides for programming command
_NETV2_OPENOCD = "openocd -f ~/netv2/alphamax-rpi.cfg -c 'init; pld load 0 {bitstream_abs}; exit'"
HOST_PROGRAM_CMD = {
    "rpi5-netv2": "sudo openFPGALoader -c rp1pio --pins 27:22:4:17 {bitstream}",
    "rpi3-netv2": f"sudo {_NETV2_OPENOCD}",
    # NeTV2 pool hosts (RPi 3B+ with GPIO JTAG, same config as rpi3-netv2)
    "welland-pi10": _NETV2_OPENOCD,
    "welland-pi12": _NETV2_OPENOCD,
    "welland-pi14": _NETV2_OPENOCD,
    "welland-pi16": _NETV2_OPENOCD,
    "welland-pi18": _NETV2_OPENOCD,
}


# ---------------------------------------------------------------------------
# Test design definitions — what bitstream + script + args for each design
# ---------------------------------------------------------------------------

DESIGNS = {
    "uart": {
        "test_script": "designs/uart/host/test_uart.py",
        "boards": {
            "arty": {"artifact": "uart-test-arty/digilent_arty.bit", "test_args": "--port /dev/ttyUSB1 --board arty"},
            "netv2": {
                "artifact": "uart-test-netv2/kosagi_netv2.bit",
                "test_args": "--port /dev/ttyAMA0 --board netv2 --skip-banner",
                "pre_test": (
                    "sudo systemctl stop 'serial-getty@*' 2>&1;"
                    " test -x /home/pi/n/bin/node"
                    " && /home/pi/n/bin/node /home/pi/n/lib/node_modules/pm2/bin/pm2 stop all 2>&1;"
                    " pkill -f netv2-status 2>&1;"
                    " sudo fuser -k /dev/ttyAMA0 /dev/serial0 2>&1;"
                    " sudo chmod 666 /dev/ttyAMA0 /dev/serial0 2>&1;"
                    " which pinctrl >/dev/null && sudo pinctrl set 14 a4 && sudo pinctrl set 15 a4;"
                    " true"
                ),
            },
            "fomu": {
                "artifact": "uart-test-fomu/kosagi_fomu_evt.bin",
                "test_args": "--port /dev/serial0 --board fomu --skip-banner",
                "pre_test": (
                    "systemctl mask serial-getty@ttyAMA0 2>&1;"
                    " systemctl stop serial-getty@ttyAMA0 2>&1;"
                    " fuser -k /dev/serial0 2>&1;"
                    " chmod 666 /dev/serial0 2>&1;"
                    " true"
                ),
            },
            "tt": {
                "artifact": "uart-test-tt-fpga/tt_fpga_platform.bin",
                "test_args": "--port /dev/ttyACM0 --board tt --skip-banner",
            },
            "acorn": {
                "artifact": "uart-test-acorn-cle-215plus/sqrl_acorn.bit",
                "test_args": "--port /dev/ttyAMA0 --board acorn --skip-banner",
                "pre_test": "systemctl stop serial-getty@ttyAMA0 2>&1; true",
            },
        },
    },
    "ddr": {
        "test_script": "designs/ddr-memory/host/test_ddr.py",
        "boards": {
            "arty": {"artifact": "ddr-test-arty/digilent_arty.bit", "test_args": "--port /dev/ttyUSB1 --board arty"},
            "netv2": {
                "artifact": "ddr-test-netv2/kosagi_netv2.bit",
                "test_args": "--port /dev/ttyAMA0 --board netv2",
                "pre_test": "systemctl stop serial-getty@ttyAMA0 2>&1; true",
            },
            "acorn": {
                "artifact": "ddr-test-acorn-cle-215plus/sqrl_acorn.bit",
                "test_args": "--port /dev/ttyAMA0 --board acorn",
                "pre_test": "systemctl stop serial-getty@ttyAMA0 2>&1; true",
            },
        },
    },
    "ethernet": {
        "test_script": "designs/ethernet-test/host/test_ethernet.py",
        "boards": {
            "arty": {
                "artifact": "ethernet-test-arty-a7-35t/digilent_arty.bit",
                "test_args": "--board arty --uart-port /dev/ttyUSB1",
            },
            "netv2": {
                "artifact": "ethernet-test-netv2/kosagi_netv2.bit",
                "test_args": "--board netv2 --uart-port /dev/ttyAMA0",
                "pre_test": "systemctl stop serial-getty@ttyAMA0 2>&1; true",
            },
        },
    },
    "spiflash": {
        "test_script": "designs/spi-flash-id/host/test_spiflash.py",
        "boards": {
            "arty": {
                "artifact": "spiflash-test-arty/digilent_arty.bit",
                "test_args": "--port /dev/ttyUSB1 --board arty",
            },
            "netv2": {
                "artifact": "spiflash-test-netv2/kosagi_netv2.bit",
                "test_args": "--port /dev/ttyAMA0 --board netv2",
                "pre_test": "systemctl stop serial-getty@ttyAMA0 2>&1; true",
            },
            "fomu": {
                "artifact": "spiflash-test-fomu/kosagi_fomu_evt.bin",
                "test_args": "--port /dev/serial0 --board fomu",
                "pre_test": (
                    "sudo systemctl stop 'serial-getty@*' 2>&1;"
                    " sudo fuser -k /dev/serial0 2>&1;"
                    " sudo chmod 666 /dev/serial0 2>&1;"
                    " which pinctrl >/dev/null && sudo pinctrl set 14 a4 && sudo pinctrl set 15 a4;"
                    " true"
                ),
            },
            "tt": {
                "artifact": "spiflash-test-tt-fpga/tt_fpga_platform.bin",
                "test_args": "--port /dev/ttyACM0 --board tt",
            },
            "acorn": {
                "artifact": "spiflash-test-acorn-cle-215plus/sqrl_acorn.bit",
                "test_args": "--port /dev/ttyAMA0 --board acorn",
                "pre_test": "systemctl stop serial-getty@ttyAMA0 2>&1; true",
            },
        },
    },
    "pmod": {
        "test_script": "designs/pmod-loopback/host/test_pmod_loopback.py",
        "boards": {
            "arty": {
                "artifact": "gpio-loopback-arty-a7-35t/top.bit",
                "test_args": "--board arty",
                "pre_test": "rmmod spidev spi_bcm2835 2>&1; true",
            },
            "netv2": {"artifact": "gpio-loopback-netv2/top.bit", "test_args": "--board netv2"},
            "fomu": {
                "artifact": "gpio-loopback-fomu-evt/top.bin",
                "test_args": "--board fomu",
                "pre_test": "rmmod spidev spi_bcm2835 2>&1; true",
            },
            "tt": {
                "artifact": "gpio-loopback-tt-fpga/top.bin",
                "test_args": "--board tt",
                "pre_test": "rmmod spidev spi_bcm2835 2>&1; true",
                "program_cmd": "python3 ~/tt_fpga_program.py /dev/ttyACM0 {bitstream} --gpio-release",
            },
            "acorn": {
                "artifact": "gpio-loopback-acorn-cle-215plus/sqrl_acorn.bit",
                "test_args": "--board netv2",  # Same 1-bit serial loopback as NeTV2
            },
        },
    },
    "pcie": {
        "test_script": "designs/pcie-enumeration/host/test_pcie_enumeration.py",
        "boards": {
            "acorn": {
                "artifact": "pcie-test-acorn-cle-215plus/sqrl_acorn.bit",
                "test_args": "--board acorn",
            },
        },
    },
    # Pin identification — each FPGA ball transmits its own name at 1200 baud.
    # The host script reads RPi GPIOs and validates the decoded names against
    # the expected wiring (verifies the RPi<->FPGA cabling itself, not a SoC).
    "pin-id": {
        "test_script": "designs/pmod-pin-id/host/identify_pmod_pins.py",
        "boards": {
            "acorn": {
                # pmod_pin_id_acorn.py calls platform.build() directly, so the
                # bitstream is build/acorn/top.bit and CI uploads that name.
                "artifact": "pmod-pin-id-acorn-cle-215plus/top.bit",
                "test_args": "--board acorn",
                # Stop the login console so the host script can read GPIO14/15,
                # and make sure GPIO14 is a plain input: with pin-ID loaded
                # every P2 ball is an FPGA *output*, so the Pi must not drive it.
                "pre_test": (
                    "systemctl stop serial-getty@ttyAMA0 2>&1;"
                    " pinctrl set 14 ip pn; pinctrl set 15 ip pn;"
                    " true"
                ),
            },
        },
    },
}

# Extra files that certain boards need uploaded
EXTRA_UPLOADS = {
    "tt": [
        ("designs/_host/tt_fpga_program.py", "~/tt_fpga_program.py"),
        ("designs/_host/tt_test_wrapper.py", "~/tt_test_wrapper.py"),
    ],
}


# ---------------------------------------------------------------------------
# SSH transport
# ---------------------------------------------------------------------------


def host_user(host_name):
    """Login user on the target. Gateway hosts default to root (legacy);
    direct hosts carry the user in `target`."""
    host = HOSTS[host_name]
    if host["ssh_type"] == "direct":
        return host["target"].split("@", 1)[0]
    return host.get("user", "root")


def remote_home(host_name):
    user = host_user(host_name)
    return "/root" if user == "root" else f"/home/{user}"


def _build_ssh_cmd(host_name, remote_cmd, as_root=True):
    """Build the ssh argv for *remote_cmd* on *host_name*.

    Gateway hosts go through OpenSSH ProxyJump (one hop, no nested quoting).
    When the login user is not root and *as_root* is set, the command is run
    under `sudo -n sh -c` so rmmod, PCI sysfs writes and openFPGALoader work.
    """
    host = HOSTS[host_name]
    user = host_user(host_name)
    if as_root and user != "root":
        remote_cmd = f"sudo -n sh -c {shlex.quote(remote_cmd)}"
    cmd = ["ssh", *SSH_BASE_OPTS]
    if host["ssh_type"] == "gateway":
        cmd += ["-o", f"ProxyJump={GATEWAYS[host['gateway']]}"]
        cmd += [f"{user}@{host['target']}", remote_cmd]
    else:
        cmd += [host["target"], remote_cmd]
    return cmd


def ssh_run(host_name, cmd, timeout=180, as_root=True):
    """Run a command on a remote RPi. Returns (returncode, stdout, stderr)."""
    full_cmd = _build_ssh_cmd(host_name, cmd, as_root=as_root)
    result = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def ssh_upload(host_name, local_path, remote_path, timeout=120):
    """Upload a file to a remote RPi by piping through SSH stdin.

    Returns True on success.
    """
    # Read file locally and pipe through SSH stdin — avoids shell escaping
    # issues with file paths entirely.
    with open(local_path, "rb") as f:
        file_data = f.read()

    # Uploads land in the login user's home (no sudo); commands that read
    # them later use absolute paths, so root can find them too.
    write_cmd = f"cat > {remote_path}"
    full_cmd = _build_ssh_cmd(host_name, write_cmd, as_root=False)

    result = subprocess.run(
        full_cmd,
        input=file_data,
        capture_output=True,
        timeout=timeout,
    )
    return result.returncode == 0


def ssh_check_connectivity(host_name, timeout=10):
    """Quick connectivity check. Returns True if host responds."""
    try:
        rc, stdout, _ = ssh_run(host_name, "echo ok", timeout=timeout, as_root=False)
        return rc == 0 and "ok" in stdout
    except (subprocess.TimeoutExpired, OSError):
        return False


def poe_reset(host_name, off_seconds=5, boot_timeout_s=240):
    """Power-cycle a PoE-powered RPi by toggling its switch port over SNMP.

    The snmpset runs on the site gateway (which can reach the switch's
    management address). Needs FPGAS_POE_COMMUNITY in the environment.
    Returns True once the host answers ssh again.
    """
    host = HOSTS[host_name]
    if "poe" not in host or host["ssh_type"] != "gateway":
        print(f"  Cannot PoE-reset {host_name}: no PoE port recorded for this host")
        return False
    community = os.environ.get(POE_COMMUNITY_ENV)
    if not community:
        print(f"  Cannot PoE-reset {host_name}: {POE_COMMUNITY_ENV} is not set — power-cycle by hand")
        return False
    gateway = GATEWAYS[host["gateway"]]

    def on_gateway(argv):
        return subprocess.run(
            ["ssh", *SSH_BASE_OPTS, gateway, shlex.join(argv)],
            timeout=20,
            capture_output=True,
            text=True,
        )

    print(f"  PoE reset: {host['poe']['switch']} port {host['poe']['port']} off...")
    try:
        r = on_gateway(poe_snmp_cmd(host_name, enable=False, community=community))
        if r.returncode != 0:
            print(f"  snmpset failed: {r.stderr.strip()}")
            return False
        # Poll until the host is unreachable (confirms power is off).
        for _ in range(off_seconds * 2):
            if not ssh_check_connectivity(host_name, timeout=1):
                break
            time.sleep(0.5)
        r = on_gateway(poe_snmp_cmd(host_name, enable=True, community=community))
        if r.returncode != 0:
            print(f"  snmpset failed: {r.stderr.strip()}")
            return False
    except (subprocess.TimeoutExpired, OSError) as e:
        print(f"  PoE reset failed: {e}")
        return False
    # Poll for the host to come back; a Pi 5 needs more than 90 s.
    print(f"  Waiting for {host_name} to boot (a Pi 5 needs > 90 s)...")
    deadline = time.monotonic() + boot_timeout_s
    while time.monotonic() < deadline:
        if ssh_check_connectivity(host_name, timeout=10):
            print(f"  {host_name} is back online")
            return True
    print(f"  {host_name} did not come back after PoE reset")
    return False


# ---------------------------------------------------------------------------
# Test generation — expand designs x hosts into concrete test cases
# ---------------------------------------------------------------------------


def generate_tests():
    """Generate test cases from DESIGNS x HOSTS."""
    tests = []
    for design_name, design in DESIGNS.items():
        for host_name, host in HOSTS.items():
            board = host["board"]
            if board not in design["boards"]:
                continue

            board_cfg = design["boards"][board]
            artifact = board_cfg["artifact"]
            test_args = board_cfg["test_args"]

            # Host-specific serial port override (e.g. rpi5 uses ttyAMA0,
            # rpi3 uses serial0 for the same GPIO UART pins).
            serial_port = host.get("serial_port")
            if serial_port and "--port" in test_args:
                test_args = re.sub(r"--port\s+\S+", f"--port {serial_port}", test_args)

            # NeTV2 variant selection: prefer variant-specific artifact if it exists.
            # CI builds separate a7-35t and a7-100t artifacts for NeTV2.
            variant = host.get("variant")
            if variant:
                # e.g. "uart-test-netv2/x.bit" -> "uart-test-netv2-a7-100t/x.bit"
                parts = artifact.split("/", 1)
                variant_artifact = f"{parts[0]}-{variant}t/{parts[1]}"
                if os.path.exists(os.path.join(ARTIFACTS_DIR, variant_artifact)):
                    artifact = variant_artifact

            # Remote paths are absolute in the login user's home: uploads run
            # as that user while program/test commands may run under sudo,
            # where `~` would resolve to /root instead.
            home = remote_home(host_name)
            ext = os.path.splitext(artifact)[1]
            remote_bitstream = f"{home}/{design_name}_{board}{ext}"
            remote_script = f"{home}/test_{design_name}.py"

            # Determine programming command (priority: per-board-config > per-host > per-board)
            if "program_cmd" in board_cfg:
                prog_cmd = board_cfg["program_cmd"].format(bitstream=remote_bitstream)
            elif host_name in HOST_PROGRAM_CMD:
                prog_template = HOST_PROGRAM_CMD[host_name]
                prog_cmd = prog_template.format(bitstream=remote_bitstream, bitstream_abs=remote_bitstream)
            else:
                prog_cmd = PROGRAM_CMD[board].format(bitstream=remote_bitstream)

            tests.append(
                {
                    "name": f"{design_name.upper()} on {board} ({host_name})",
                    "test_type": design_name,
                    "host": host_name,
                    "board": board,
                    "enabled": True,
                    "artifact": artifact,
                    "test_script": design["test_script"],
                    "remote_bitstream": remote_bitstream,
                    "remote_script": remote_script,
                    "program_cmd": prog_cmd,
                    "test_cmd": f"python3 {remote_script} {test_args}",
                    "pre_test": board_cfg.get("pre_test"),
                }
            )

    return tests


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def run_single_test(test, skip_upload=False):
    """Run a single hardware test. Returns True (pass), False (fail), or None (skip)."""
    print("\n" + "=" * 60)
    print("TEST: {}".format(test["name"]))
    print("=" * 60)

    # Connectivity check — fail fast if host is unreachable
    print("  Checking host connectivity...")
    if not ssh_check_connectivity(test["host"]):
        print("  FAIL: Host {} is unreachable".format(test["host"]))
        return False

    if not skip_upload:
        # Upload bitstream
        bitstream_path = os.path.join(ARTIFACTS_DIR, test["artifact"])
        if not os.path.exists(bitstream_path):
            print("  SKIP: Bitstream not found: {}".format(test["artifact"]))
            return None

        print("  Uploading bitstream...")
        if not ssh_upload(test["host"], bitstream_path, test["remote_bitstream"]):
            print("  FAIL: Could not upload bitstream")
            return False

        # Upload test script
        script_path = os.path.join(REPO_DIR, test["test_script"])
        print("  Uploading test script...")
        if not ssh_upload(test["host"], script_path, test["remote_script"]):
            print("  FAIL: Could not upload test script")
            return False

        # Upload extra files if needed
        for local_rel, remote in EXTRA_UPLOADS.get(test["board"], []):
            local_path = os.path.join(REPO_DIR, local_rel)
            if os.path.exists(local_path):
                ssh_upload(test["host"], local_path, remote)

    # Pre-test command BEFORE programming — stop serial-getty, unload
    # conflicting kernel modules, etc. Must run before FPGA programming
    # so the BIOS boots into a clean serial port (no getty interference).
    if test.get("pre_test"):
        print("  Pre-test: {}".format(test["pre_test"]))
        ssh_run(test["host"], test["pre_test"], timeout=30)

    # TT FPGA boards: RP2350 sits between RPi and FPGA.
    # UART/spiflash: combined program + bridge + test (UART goes through RP2350).
    # PMOD: program via RP2350 wrapper (handles reset/retry), then test via RPi GPIO.
    if test["board"] == "tt" and test["test_type"] in ("uart", "spiflash"):
        wrapper_cmd = "python3 ~/tt_test_wrapper.py /dev/ttyACM0 {} {}".format(
            test["remote_bitstream"], test["test_cmd"]
        )
        print("  Running combined program + bridge + test...")
        rc, stdout, stderr = ssh_run(test["host"], wrapper_cmd, timeout=240)
        output = stdout + stderr
        for line in output.strip().split("\n"):
            print(f"    {line}")
        passed = check_test_result(output, rc)
        print("  RESULT: {}".format("PASS" if passed else "FAIL"))
        return passed

    # Program FPGA
    print("  Programming FPGA...")
    rc, stdout, stderr = ssh_run(test["host"], test["program_cmd"], timeout=120)
    output = stdout + stderr
    # Check for successful programming indicators:
    # - openFPGALoader: prints "done 1" in FPGA status register output
    # - tt_fpga_program.py: returns rc=0
    programming_ok = rc == 0 or "done 1" in output.lower()
    if not programming_ok:
        # For Fomu: DFU bootloader may have timed out. PoE-reset to
        # reboot into DFU mode and retry programming immediately.
        if test["board"] == "fomu" and not programming_ok:
            print("  Fomu DFU timeout — PoE resetting to re-enter bootloader...")
            if poe_reset(test["host"]):
                # Re-upload files (PXE tmpfs lost on reboot)
                print("  Re-uploading bitstream and test script...")
                bitstream_path = os.path.join(ARTIFACTS_DIR, test["artifact"])
                ssh_upload(test["host"], bitstream_path, test["remote_bitstream"])
                script_path = os.path.join(REPO_DIR, test["test_script"])
                ssh_upload(test["host"], script_path, test["remote_script"])
                # Re-run pre_test (e.g. stop serial-getty, lost on reboot)
                if test.get("pre_test"):
                    ssh_run(test["host"], test["pre_test"], timeout=30)
                print("  Retrying FPGA programming...")
                rc, stdout, stderr = ssh_run(test["host"], test["program_cmd"], timeout=120)
                output = stdout + stderr
                programming_ok = rc == 0 or "done 1" in output.lower()
        if not programming_ok:
            print(f"  FAIL: FPGA programming failed (rc={rc})")
            for line in output.strip().split("\n"):
                print(f"    {line}")
            return False
    print("  FPGA programmed successfully")

    # Run test — the test script handles its own boot-wait and timeouts
    print("  Running test...")
    rc, stdout, stderr = ssh_run(test["host"], test["test_cmd"], timeout=180)
    output = stdout + stderr

    # Print test output
    for line in output.strip().split("\n"):
        print(f"    {line}")

    # Determine pass/fail from test script output
    passed = check_test_result(output, rc)
    print("  RESULT: {}".format("PASS" if passed else "FAIL"))
    return passed


def check_test_result(output, returncode):
    """Determine if a test passed based on its output and return code.

    Test scripts use consistent markers:
    - "RESULT: PASS" or just "PASS" at the end for success
    - "RESULT: FAIL" or "FAIL" for failure
    - Return code 0 for pass, non-zero for fail
    """
    lines = output.strip().split("\n")
    # Check last few lines for result markers
    tail = "\n".join(lines[-5:]) if len(lines) >= 5 else output

    if "RESULT: PASS" in tail:
        return True
    if "RESULT: FAIL" in tail:
        return False

    # Fallback: check for PASS/FAIL in final lines
    return bool(returncode == 0 and "PASS" in tail)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Automated hardware verification runner")
    parser.add_argument(
        "--test", default=None, help="Run only tests of this type (uart, ddr, ethernet, pmod, spiflash, pcie)"
    )
    parser.add_argument(
        "--host", default=None, help="Run only tests on this host (pi3, pi5, pi9, pi17, pi21, pi27, etc.)"
    )
    parser.add_argument("--board", default=None, help="Run only tests for this board (arty, netv2, fomu, tt)")
    parser.add_argument("--list", action="store_true", help="List all tests without running them")
    parser.add_argument(
        "--skip-upload", action="store_true", help="Skip uploading files (use already-uploaded files on RPis)"
    )
    args = parser.parse_args()

    all_tests = generate_tests()
    tests = [t for t in all_tests if t["enabled"]]

    if args.test:
        tests = [t for t in tests if t["test_type"] == args.test]
    if args.host:
        tests = [t for t in tests if t["host"] == args.host]
    if args.board:
        tests = [t for t in tests if t["board"] == args.board]

    if args.list:
        print(f"Enabled tests ({len(tests)} total):")
        for i, t in enumerate(tests, 1):
            print("  {:2d}. [{:10s}] {}".format(i, t["test_type"], t["name"]))
        return 0

    if not tests:
        print("No tests match the given filters.")
        return 1

    start = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"Running {len(tests)} tests...")
    print(f"Start: {start}")

    results = {}
    for test in tests:
        try:
            result = run_single_test(test, skip_upload=args.skip_upload)
            results[test["name"]] = result
        except subprocess.TimeoutExpired:
            print("  TIMEOUT: Test exceeded time limit")
            results[test["name"]] = False
        except Exception as e:
            print(f"  ERROR: {e}")
            results[test["name"]] = False

    # Summary
    end = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print(f"Start: {start}  End: {end}")
    print()

    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)

    for name, result in results.items():
        status = "PASS" if result is True else "FAIL" if result is False else "SKIP"
        print(f"  [{status}] {name}")

    print()
    print(f"{passed} passed, {failed} failed, {skipped} skipped (out of {len(results)})")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
