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
import shlex
import subprocess
import sys
import time


REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ARTIFACTS_DIR = os.path.join(REPO_DIR, "artifacts")
TWEED = "root@tweed.welland.mithis.com"


# ---------------------------------------------------------------------------
# Host definitions — each RPi we can reach
# ---------------------------------------------------------------------------

HOSTS = {
    # Tweed-connected (via double-hop SSH)
    "pi3":  {"ssh_type": "tweed", "target": "10.21.0.103", "board": "arty"},
    "pi5":  {"ssh_type": "tweed", "target": "10.21.0.105", "board": "arty"},
    "pi9":  {"ssh_type": "tweed", "target": "10.21.0.109", "board": "arty"},
    "pi17": {"ssh_type": "tweed", "target": "10.21.0.117", "board": "fomu"},
    "pi21": {"ssh_type": "tweed", "target": "10.21.0.121", "board": "fomu"},
    "pi27": {"ssh_type": "tweed", "target": "10.21.0.127", "board": "tt"},
    "pi29": {"ssh_type": "tweed", "target": "10.21.0.129", "board": "tt"},
    "pi31": {"ssh_type": "tweed", "target": "10.21.0.131", "board": "tt"},
    "pi33": {"ssh_type": "tweed", "target": "10.21.0.133", "board": "tt"},
    # Direct SSH
    "rpi5-netv2": {"ssh_type": "direct", "target": "tim@rpi5-netv2.iot.welland.mithis.com", "board": "netv2"},
    "rpi3-netv2": {"ssh_type": "direct", "target": "pi@rpi3-netv2.iot.welland.mithis.com", "board": "netv2"},
}

# Board-specific FPGA programming commands (use {bitstream} placeholder)
PROGRAM_CMD = {
    "arty":  "openFPGALoader -b arty {bitstream}",
    "fomu":  "dfu-util -D {bitstream}",
    "tt":    "python3 ~/tt_fpga_program.py /dev/ttyACM0 {bitstream}",
    # NeTV2 varies by host — handled per-host below
}

# Per-host overrides for programming command
HOST_PROGRAM_CMD = {
    "rpi5-netv2": "sudo openFPGALoader -c rp1pio --pins 27:22:4:17 {bitstream}",
    "rpi3-netv2": "sudo openocd -f ~/netv2/alphamax-rpi.cfg -c 'init; pld load xc7.pld {bitstream_abs}; exit'",
}


# ---------------------------------------------------------------------------
# Test design definitions — what bitstream + script + args for each design
# ---------------------------------------------------------------------------

DESIGNS = {
    "uart": {
        "test_script": "designs/uart/host/test_uart.py",
        "boards": {
            "arty":  {"artifact": "uart-test-arty/digilent_arty.bit",
                       "test_args": "--port /dev/ttyUSB1 --board arty"},
            "netv2": {"artifact": "uart-test-netv2/kosagi_netv2.bit",
                       "test_args": "--port /dev/ttyAMA0 --board netv2"},
            "fomu":  {"artifact": "uart-test-fomu/kosagi_fomu_evt.bin",
                       "test_args": "--port /dev/ttyUSB0 --board fomu"},
            "tt":    {"artifact": "uart-test-tt-fpga/tt_fpga_platform.bin",
                       "test_args": "--port /dev/ttyACM0 --board tt --skip-banner"},
        },
    },
    "ddr": {
        "test_script": "designs/ddr-memory/host/test_ddr.py",
        "boards": {
            "arty":  {"artifact": "ddr-test-arty/digilent_arty.bit",
                       "test_args": "--port /dev/ttyUSB1 --board arty"},
            "netv2": {"artifact": "ddr-test-netv2/kosagi_netv2.bit",
                       "test_args": "--port /dev/ttyAMA0 --board netv2"},
        },
    },
    "ethernet": {
        "test_script": "designs/ethernet-test/host/test_ethernet.py",
        "boards": {
            "arty":  {"artifact": "ethernet-test-arty-a7-35t/digilent_arty.bit",
                       "test_args": "--board arty --uart-port /dev/ttyUSB1"},
            "netv2": {"artifact": "ethernet-test-netv2/kosagi_netv2.bit",
                       "test_args": "--board netv2 --uart-port /dev/ttyAMA0"},
        },
    },
    "spiflash": {
        "test_script": "designs/spi-flash-id/host/test_spiflash.py",
        "boards": {
            "arty":  {"artifact": "spiflash-test-arty/digilent_arty.bit",
                       "test_args": "--port /dev/ttyUSB1 --board arty"},
            "netv2": {"artifact": "spiflash-test-netv2/kosagi_netv2.bit",
                       "test_args": "--port /dev/ttyAMA0 --board netv2"},
            "fomu":  {"artifact": "spiflash-test-fomu/kosagi_fomu_evt.bin",
                       "test_args": "--port /dev/ttyUSB0 --board fomu"},
            "tt":    {"artifact": "spiflash-test-tt-fpga/tt_fpga_platform.bin",
                       "test_args": "--port /dev/ttyACM0 --board tt"},
        },
    },
    "pmod": {
        "test_script": "designs/pmod-loopback/host/test_pmod_loopback.py",
        "boards": {
            "arty":  {"artifact": "gpio-loopback-arty-a7-35t/top.bit",
                       "test_args": "--board arty",
                       "pre_test": "rmmod spidev spi_bcm2835 2>&1; true"},
            "netv2": {"artifact": "gpio-loopback-netv2/top.bit",
                       "test_args": "--board netv2"},
            "fomu":  {"artifact": "gpio-loopback-fomu-evt/top.bin",
                       "test_args": "--board fomu"},
            "tt":    {"artifact": "gpio-loopback-tt-fpga/top.bin",
                       "test_args": "--board tt"},
        },
    },
}

# Extra files that certain boards need uploaded
EXTRA_UPLOADS = {
    "tt": [
        ("designs/_shared/tt_fpga_program.py", "~/tt_fpga_program.py"),
        ("designs/_shared/tt_test_wrapper.py", "~/tt_test_wrapper.py"),
    ],
}


# ---------------------------------------------------------------------------
# SSH transport
# ---------------------------------------------------------------------------

def _build_ssh_cmd(host_name, remote_cmd):
    """Build the full SSH command list for a given host.

    For tweed-connected hosts, this produces a double-hop SSH command.
    Commands are properly shell-escaped at each hop to avoid quoting bugs.
    """
    host = HOSTS[host_name]
    if host["ssh_type"] == "tweed":
        # Double-hop: local -> tweed -> rpi
        # The inner command must be shell-escaped for the tweed shell,
        # and the remote_cmd must be escaped for the rpi shell.
        inner_cmd = "ssh root@{} {}".format(
            host["target"], shlex.quote(remote_cmd))
        return ["ssh", TWEED, inner_cmd]
    else:
        return ["ssh", host["target"], remote_cmd]


def ssh_run(host_name, cmd, timeout=180):
    """Run a command on a remote RPi. Returns (returncode, stdout, stderr)."""
    full_cmd = _build_ssh_cmd(host_name, cmd)
    result = subprocess.run(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def ssh_upload(host_name, local_path, remote_path, timeout=120):
    """Upload a file to a remote RPi by piping through SSH stdin.

    Returns True on success.
    """
    host = HOSTS[host_name]
    # Read file locally and pipe through SSH stdin — avoids shell escaping
    # issues with file paths entirely.
    with open(local_path, "rb") as f:
        file_data = f.read()

    write_cmd = "cat > {}".format(remote_path)
    full_cmd = _build_ssh_cmd(host_name, write_cmd)

    result = subprocess.run(
        full_cmd,
        input=file_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )
    return result.returncode == 0


def ssh_check_connectivity(host_name, timeout=10):
    """Quick connectivity check. Returns True if host responds."""
    try:
        rc, stdout, _ = ssh_run(host_name, "echo ok", timeout=timeout)
        return rc == 0 and "ok" in stdout
    except (subprocess.TimeoutExpired, OSError):
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

            # Determine remote paths
            ext = os.path.splitext(artifact)[1]
            remote_bitstream = "~/{}_{}{}".format(design_name, board, ext)
            remote_script = "~/test_{}.py".format(design_name)

            # Determine programming command
            if host_name in HOST_PROGRAM_CMD:
                prog_template = HOST_PROGRAM_CMD[host_name]
                # rpi3-netv2 needs absolute path (openocd doesn't expand ~)
                home_dir = "/home/pi" if host_name == "rpi3-netv2" else "/home/tim"
                bitstream_abs = remote_bitstream.replace("~", home_dir)
                prog_cmd = prog_template.format(
                    bitstream=remote_bitstream,
                    bitstream_abs=bitstream_abs)
            else:
                prog_cmd = PROGRAM_CMD[board].format(bitstream=remote_bitstream)

            tests.append({
                "name": "{} on {} ({})".format(design_name.upper(), board, host_name),
                "test_type": design_name,
                "host": host_name,
                "board": board,
                "enabled": True,
                "artifact": artifact,
                "test_script": design["test_script"],
                "remote_bitstream": remote_bitstream,
                "remote_script": remote_script,
                "program_cmd": prog_cmd,
                "test_cmd": "python3 {} {}".format(remote_script, test_args),
                "pre_test": board_cfg.get("pre_test"),
            })

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

    # Pre-test command (e.g. unload conflicting kernel modules)
    if test.get("pre_test"):
        print("  Pre-test: {}".format(test["pre_test"]))
        ssh_run(test["host"], test["pre_test"], timeout=30)

    # TT FPGA boards with UART-based tests need a combined program + bridge
    # + test flow because the FPGA UART goes through the RP2350 (not USB).
    if test["board"] == "tt" and test["test_type"] in ("uart", "spiflash"):
        wrapper_cmd = "python3 ~/tt_test_wrapper.py /dev/ttyACM0 {} {}".format(
            test["remote_bitstream"], test["test_cmd"])
        print("  Running combined program + bridge + test...")
        rc, stdout, stderr = ssh_run(test["host"], wrapper_cmd, timeout=240)
        output = stdout + stderr
        for line in output.strip().split("\n"):
            print("    {}".format(line))
        passed = check_test_result(output, rc)
        print("  RESULT: {}".format("PASS" if passed else "FAIL"))
        return passed

    # Program FPGA
    print("  Programming FPGA...")
    rc, stdout, stderr = ssh_run(test["host"], test["program_cmd"], timeout=120)
    output = stdout + stderr
    # Check for successful programming indicators from each tool:
    # - openFPGALoader: prints "done 1" in FPGA status register output
    # - dfu-util: prints "state(2) = dfuIDLE" on success
    # - tt_fpga_program.py: returns rc=0
    programming_ok = (
        rc == 0
        or "done 1" in output.lower()
        or "dfuIDLE" in output
    )
    if not programming_ok:
        print("  FAIL: FPGA programming failed (rc={})".format(rc))
        for line in output.strip().split("\n"):
            print("    {}".format(line))
        return False
    print("  FPGA programmed successfully")

    # Run test — the test script handles its own boot-wait and timeouts
    print("  Running test...")
    rc, stdout, stderr = ssh_run(test["host"], test["test_cmd"], timeout=180)
    output = stdout + stderr

    # Print test output
    for line in output.strip().split("\n"):
        print("    {}".format(line))

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
    if returncode == 0 and "PASS" in tail:
        return True

    return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Automated hardware verification runner")
    parser.add_argument(
        "--test", default=None,
        help="Run only tests of this type (uart, ddr, ethernet, pmod, spiflash, pcie)")
    parser.add_argument(
        "--host", default=None,
        help="Run only tests on this host (pi3, pi5, pi9, pi17, pi21, pi27, etc.)")
    parser.add_argument(
        "--board", default=None,
        help="Run only tests for this board (arty, netv2, fomu, tt)")
    parser.add_argument(
        "--list", action="store_true",
        help="List all tests without running them")
    parser.add_argument(
        "--skip-upload", action="store_true",
        help="Skip uploading files (use already-uploaded files on RPis)")
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
        print("Enabled tests ({} total):".format(len(tests)))
        for i, t in enumerate(tests, 1):
            print("  {:2d}. [{:10s}] {}".format(i, t["test_type"], t["name"]))
        return 0

    if not tests:
        print("No tests match the given filters.")
        return 1

    start = time.strftime("%Y-%m-%d %H:%M:%S")
    print("Running {} tests...".format(len(tests)))
    print("Start: {}".format(start))

    results = {}
    for test in tests:
        try:
            result = run_single_test(test, skip_upload=args.skip_upload)
            results[test["name"]] = result
        except subprocess.TimeoutExpired:
            print("  TIMEOUT: Test exceeded time limit")
            results[test["name"]] = False
        except Exception as e:
            print("  ERROR: {}".format(e))
            results[test["name"]] = False

    # Summary
    end = time.strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)
    print("Start: {}  End: {}".format(start, end))
    print()

    passed = sum(1 for v in results.values() if v is True)
    failed = sum(1 for v in results.values() if v is False)
    skipped = sum(1 for v in results.values() if v is None)

    for name, result in results.items():
        status = "PASS" if result is True else "FAIL" if result is False else "SKIP"
        print("  [{}] {}".format(status, name))

    print()
    print("{} passed, {} failed, {} skipped (out of {})".format(
        passed, failed, skipped, len(results)))

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
