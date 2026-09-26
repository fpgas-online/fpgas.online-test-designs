#!/usr/bin/env python3
"""Check that an Arty A7, NeTV2, Fomu EVT or TT FPGA board works, using the fpgas.online test bitstreams.

Installed by fpgas-online-<board>-tools as fpgas-<board>-verify. At boot, fpgas-verify (fpgas-online-verify)
runs it when it finds this board, so one netboot root with every board's tools verifies whichever board a Pi
has; it also runs on demand. For each of the board's verify tests (UART, DDR, SPI
flash) it loads that test's bitstream, runs the host test script against it and records pass or fail:

  1. Detect the board: its USB device (Arty's FTDI, Fomu's DFU bootloader, the TT board's RP2350), or, for the
     NeTV2, which has no USB, a JTAG scan over the Pi's GPIO header. The JTAG IDCODE also says which NeTV2
     part (XC7A35T or XC7A100T) is fitted, so which variant's bitstreams to use. No board, or no Pi GPIO header
     to scan: "none", exit 0.
  2. Check every bitstream it will load against the manifest of fpgas-online-<board>-bitstreams (sha256).
  3. For each test: program the board, run the test script, keep the tail of its output.

The board is left running the last test's design. The Arty, NeTV2 and TT FPGA are loaded into SRAM and come
back to their own flash image at the next power cycle; the Fomu EVT is loaded by DFU (openFPGALoader -b fomu),
which writes the bootloader's user image, as verify_hardware.py has always done.

The result is written as JSON to /run/fpgas-online/<board>-verify.json, printed, and published as a fleet-event
`fpga-verified` stage. The exit status is 0 only for "pass" and "none", so a failure shows as a failed unit.
When a test fails, fpgas-online-<board>-debug has the tools to look closer (fpgas-<board>-debug).

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX. The host test scripts need python3-serial.

    sudo fpgas-arty-verify                        # check, report, publish
    sudo fpgas-netv2-verify --no-publish --report -
    sudo fpgas-tt-fpga-verify --test uart         # just one test
"""

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import re
import struct
import subprocess
import sys

SCHEMA_VERSION = 1
SEVERITY = ("none", "pass", "fail", "error")
OUTPUT_TAIL = 20  # lines of each step's output kept in the report
SHARE = pathlib.Path("/usr/share/fpgas-online")
LIB = pathlib.Path("/usr/lib/fpgas-online")
RUN = pathlib.Path("/run/fpgas-online")
SYSFS_USB = pathlib.Path("/sys/bus/usb/devices")
DT_MODEL = pathlib.Path("/proc/device-tree/model")
DT_SOC_RANGES = pathlib.Path("/proc/device-tree/soc/ranges")

# Xilinx IDCODEs, version nibble masked off: which NeTV2 part is on the JTAG chain.
XC7_PARTS = {0x0362D093: "a7-35", 0x03631093: "a7-100"}
# NeTV2 JTAG on the Pi header (docs/hardware/netv2.md): TCK GPIO4, TMS GPIO17, TDI GPIO27, TDO GPIO22.
NETV2_JTAG = {"tck": 4, "tms": 17, "tdi": 27, "tdo": 22}
PROGRAM_TIMEOUT = 300
TEST_TIMEOUT = 300

# What each board is, how to find it, how to load it and which tests it has. build_debs.py reads this too, to
# know which CI artifacts go into which package, so a test added here is packaged without another list to edit.
#
# Per test: `artifact` is the CI artifact path in the all-bitstreams bundle ({v} is the variant's suffix),
# `script` the host test script and `args` its arguments ({port} the board's UART), `verify` whether the boot
# check runs it (the others need extra wiring or a USB Ethernet adapter: fpgas-<board>-debug runs them), and
# `pre` any commands to run first (each may fail). `runner` "tt-bridge" runs the script through the TT board's
# RP2350 UART bridge; `program_args` are extra arguments to the programmer.
BOARDS = {
    "arty": {
        "slug": "arty",
        "title": "Digilent Arty A7",
        "doc": "arty-a7.md",
        "detect": {"usb": [("0403", "6010")]},  # the FT2232H: JTAG on interface 0, UART on interface 1
        "variants": {"a7-35": "a7-35t"},
        "port": "/dev/ttyUSB1",
        "tests": {
            "uart": {
                "artifact": "uart-test-arty/digilent_arty.bit",
                "script": "test_uart.py",
                "args": ["--port", "{port}", "--board", "arty"],
                "verify": True,
            },
            "ddr": {
                "artifact": "ddr-test-arty/digilent_arty.bit",
                "script": "test_ddr.py",
                "args": ["--port", "{port}", "--board", "arty"],
                "verify": True,
            },
            "spiflash": {
                "artifact": "spiflash-test-arty/digilent_arty.bit",
                "script": "test_spiflash.py",
                "args": ["--port", "{port}", "--board", "arty"],
                "verify": True,
            },
            "ethernet": {
                "artifact": "ethernet-test-arty-{v}/digilent_arty.bit",
                "script": "test_ethernet.py",
                "args": ["--board", "arty", "--uart-port", "{port}"],
            },
            "pmod": {
                "artifact": "gpio-loopback-arty-{v}/top.bit",
                "script": "test_pmod_loopback.py",
                "args": ["--board", "arty"],
                "pre": [["rmmod", "spidev", "spi_bcm2835"]],
            },
            "pin-id": {
                "artifact": "pmod-pin-id-arty-{v}/top.bit",
                "script": "identify_pmod_pins.py",
                "args": [],
                "pre": [["rmmod", "spidev", "spi_bcm2835"]],
            },
        },
    },
    "netv2": {
        "slug": "netv2",
        "title": "Kosagi NeTV2",
        "doc": "netv2.md",
        "detect": {"jtag": "netv2"},
        "variants": {"a7-35": "a7-35t", "a7-100": "a7-100t"},
        "port": "/dev/ttyAMA0",
        "tests": {
            "uart": {
                "artifact": "uart-test-netv2-{v}/kosagi_netv2.bit",
                "script": "test_uart.py",
                "args": ["--port", "{port}", "--board", "netv2", "--skip-banner"],
                "verify": True,
            },
            "ddr": {
                "artifact": "ddr-test-netv2-{v}/kosagi_netv2.bit",
                "script": "test_ddr.py",
                "args": ["--port", "{port}", "--board", "netv2"],
                "verify": True,
            },
            "spiflash": {
                "artifact": "spiflash-test-netv2-{v}/kosagi_netv2.bit",
                "script": "test_spiflash.py",
                "args": ["--port", "{port}", "--board", "netv2"],
                "verify": True,
            },
            "ethernet": {
                "artifact": "ethernet-test-netv2-{v}/kosagi_netv2.bit",
                "script": "test_ethernet.py",
                "args": ["--board", "netv2", "--uart-port", "{port}"],
            },
            "pmod": {
                "artifact": "gpio-loopback-netv2-{v}/top.bit",
                "script": "test_pmod_loopback.py",
                "args": ["--board", "netv2"],
            },
            "pin-id": {"artifact": "pmod-pin-id-netv2-{v}/top.bit", "script": "identify_pmod_pins.py", "args": []},
        },
    },
    "fomu": {
        "slug": "fomu",
        "title": "Fomu EVT",
        "doc": "fomu-evt.md",
        "detect": {"usb": [("1209", "5bf0")]},  # foboot's DFU bootloader, present from power-up until loaded
        "variants": {"evt": "evt"},
        "port": "/dev/serial0",
        "tests": {
            "uart": {
                "artifact": "uart-test-fomu/kosagi_fomu_evt.bin",
                "script": "test_uart.py",
                "args": ["--port", "{port}", "--board", "fomu", "--skip-banner"],
                "verify": True,
            },
            # Not in the boot check: loading a design leaves foboot's DFU bootloader until the next power cycle,
            # so a boot has room for one test. verify_hardware.py PoE-cycles the Pi between tests instead.
            "spiflash": {
                "artifact": "spiflash-test-fomu/kosagi_fomu_evt.bin",
                "script": "test_spiflash.py",
                "args": ["--port", "{port}", "--board", "fomu"],
            },
            "pmod": {
                "artifact": "gpio-loopback-fomu-{v}/top.bin",
                "script": "test_pmod_loopback.py",
                "args": ["--board", "fomu"],
                "pre": [["rmmod", "spidev", "spi_bcm2835"]],
            },
            "pin-id": {
                "artifact": "pmod-pin-id-fomu-{v}/top.bin",
                "script": "identify_pmod_pins.py",
                "args": [],
                "pre": [["rmmod", "spidev", "spi_bcm2835"]],
            },
        },
    },
    "tt": {
        "slug": "tt-fpga",
        "title": "TT FPGA Demo Board",
        "doc": "tt-fpga.md",
        "detect": {"usb": [("2e8a", None)]},  # the RP2350 running MicroPython (any Raspberry Pi USB product)
        "variants": {"tt-fpga": "tt-fpga"},
        "port": "/dev/ttyACM0",
        "tests": {
            "uart": {
                "artifact": "uart-test-tt-fpga/tt_fpga_platform.bin",
                "script": "test_uart.py",
                "args": ["--port", "{port}", "--board", "tt", "--skip-banner"],
                "verify": True,
                "runner": "tt-bridge",
            },
            "spiflash": {
                "artifact": "spiflash-test-tt-fpga/tt_fpga_platform.bin",
                "script": "test_spiflash.py",
                "args": ["--port", "{port}", "--board", "tt"],
                "verify": True,
                "runner": "tt-bridge",
            },
            "pmod": {
                "artifact": "gpio-loopback-{v}/top.bin",
                "script": "test_pmod_loopback.py",
                "args": ["--board", "tt"],
                "pre": [["rmmod", "spidev", "spi_bcm2835"]],
                "program_args": ["--gpio-release"],
            },
            "pin-id": {
                "artifact": "pmod-pin-id-{v}/top.bin",
                "script": "identify_pmod_pins.py",
                "args": [],
                "pre": [["rmmod", "spidev", "spi_bcm2835"]],
                "program_args": ["--gpio-release"],
            },
        },
    },
}

# Host scripts, by the name they are installed under, and where they are in this repository. A board's tools
# package carries the ones its verify tests use (and the TT programmer); its debug package the rest.
SCRIPTS = {
    "test_uart.py": "designs/uart/host/test_uart.py",
    "test_ddr.py": "designs/ddr-memory/host/test_ddr.py",
    "test_spiflash.py": "designs/spi-flash-id/host/test_spiflash.py",
    "test_ethernet.py": "designs/ethernet-test/host/test_ethernet.py",
    "test_pmod_loopback.py": "designs/pmod-loopback/host/test_pmod_loopback.py",
    "identify_pmod_pins.py": "designs/pmod-pin-id/host/identify_pmod_pins.py",
    "tt_fpga_program.py": "designs/_host/tt_fpga_program.py",
    "tt_test_wrapper.py": "designs/_host/tt_test_wrapper.py",
}
TT_SCRIPTS = ("tt_fpga_program.py", "tt_test_wrapper.py")


class Problem(Exception):
    """Something that stops a check, with the result it gives."""

    def __init__(self, result, reason):
        super().__init__(reason)
        self.result = result
        self.reason = reason


def board_for_program(argv0):
    """`fpgas-tt-fpga-verify` -> "tt": the board a command is for, from the name it was run by."""
    name = pathlib.Path(argv0).name
    for board, cfg in BOARDS.items():
        if re.fullmatch(rf"fpgas-{re.escape(cfg['slug'])}-(verify|debug)(\.py)?", name):
            return board
    return None


def verify_tests(board):
    return [name for name, t in BOARDS[board]["tests"].items() if t.get("verify")]


def artifact_path(board, test, variant):
    cfg = BOARDS[board]
    return cfg["tests"][test]["artifact"].format(v=cfg["variants"][variant])


def images_dir(board):
    return SHARE / BOARDS[board]["slug"] / "bitstreams"


def lib_dir(board):
    return LIB / BOARDS[board]["slug"]


def _tail(text, n=OUTPUT_TAIL):
    return [line for line in (text or "").splitlines() if line.strip()][-n:]


def _run(argv, timeout, **kw):
    """Run argv, returning (returncode, combined output). A missing program or a timeout is a Problem."""
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False, **kw)
    except FileNotFoundError:
        raise Problem("error", f"{argv[0]} is not installed") from None
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") + (e.stderr or "")
        if isinstance(out, bytes):
            out = out.decode(errors="replace")
        raise Problem("fail", f"{pathlib.Path(argv[0]).name} did not finish within {timeout} s: {out[-500:]}") from None
    return r.returncode, (r.stdout or "") + (r.stderr or "")


# -- the host ---------------------------------------------------------------------------------------------


def pi_model(path=DT_MODEL):
    try:
        return path.read_bytes().rstrip(b"\0").decode(errors="replace")
    except OSError:
        return ""


def is_pi5(model):
    return model.startswith("Raspberry Pi 5") or model.startswith("Raspberry Pi Compute Module 5")


def peripheral_base(ranges=DT_SOC_RANGES):
    """The SoC's peripheral base for openocd's bcm2835gpio: the CPU address of the first `soc` range.

    The ranges cells are big-endian u32s: <child-address> <parent-address> <size>, 0x3f000000 on a Pi 3 and
    0xfe000000 on a Pi 4. On a Pi 4 the parent address has two cells, so the second cell of that pair is it.
    """
    data = ranges.read_bytes()
    cells = struct.unpack(f">{len(data) // 4}I", data[: len(data) // 4 * 4])
    if len(cells) >= 4 and len(cells) % 4 == 0 and cells[1] == 0:  # <child> <parent-hi> <parent-lo> <size>
        return cells[2]
    if len(cells) >= 3:
        return cells[1]
    raise Problem("error", f"cannot read the peripheral base from {ranges}")


def usb_devices(root=SYSFS_USB):
    """(vendor, product) of every USB device, from sysfs."""
    found = []
    if not root.is_dir():
        return found
    for dev in sorted(root.iterdir()):
        try:
            found.append(((dev / "idVendor").read_text().strip(), (dev / "idProduct").read_text().strip()))
        except OSError:
            continue  # interfaces and hubs without IDs
    return found


def usb_present(wanted, devices):
    return any(v == wv and (wp is None or p == wp) for v, p in devices for wv, wp in wanted)


def parse_idcodes(text):
    """IDCODEs from openocd's `tap/device found: 0x...` or openFPGALoader's `idcode 0x...` lines."""
    return [int(m, 16) for m in re.findall(r"(?:device found:|idcode)\s*(0x[0-9a-fA-F]{1,8})", text)]


def xc7_variant(idcodes):
    for code in idcodes:
        part = XC7_PARTS.get(code & 0x0FFFFFFF)
        if part:
            return part, code
    return None, (idcodes[0] if idcodes else None)


# -- programming -----------------------------------------------------------------------------------------


def netv2_openocd_argv(base, commands):
    if base is None:
        raise Problem("error", f"cannot read the peripheral base from {DT_SOC_RANGES}: cannot drive JTAG")
    j = NETV2_JTAG
    adapter = (
        "adapter driver bcm2835gpio; "
        f"bcm2835gpio peripheral_base {base:#x}; "
        "bcm2835gpio speed_coeffs 100000 5; "
        f"bcm2835gpio jtag_nums {j['tck']} {j['tms']} {j['tdi']} {j['tdo']}; "
        "adapter speed 1000; transport select jtag"
    )
    return ["openocd", "-c", adapter, "-f", "cpld/xilinx-xc7.cfg", "-c", commands]


def netv2_rp1pio_args():
    j = NETV2_JTAG
    return ["-c", "rp1pio", "--pins", f"{j['tdi']}:{j['tdo']}:{j['tck']}:{j['tms']}"]


def program_argv(board, bitstream, host, test=None):
    """The command that loads `bitstream` into the board; `host` is {"model", "base", "lib", "port"}."""
    extra = BOARDS[board]["tests"].get(test, {}).get("program_args", []) if test else []
    if board == "arty":
        return ["openFPGALoader", "-b", "arty", str(bitstream)]
    if board == "fomu":
        return ["openFPGALoader", "-b", "fomu", str(bitstream)]
    if board == "tt":
        return [sys.executable, str(host["lib"] / "tt_fpga_program.py"), host["port"], str(bitstream), *extra]
    if board == "netv2":
        if is_pi5(host["model"]):
            return ["openFPGALoader", *netv2_rp1pio_args(), str(bitstream)]
        return netv2_openocd_argv(host["base"], f"init; pld load 0 {bitstream}; exit")
    raise ValueError(board)


def jtag_scan_argv(host):
    """The NeTV2's JTAG scan: prints the IDCODE of whatever answers on the header pins."""
    if is_pi5(host["model"]):
        return ["openFPGALoader", *netv2_rp1pio_args(), "--detect"]
    return netv2_openocd_argv(host["base"], "init; exit")


def detect(board, host, run=_run, devices=None):
    """Is the board there, and which variant? {"present", "variant", "how", "idcode"?, "output"?}."""
    cfg = BOARDS[board]
    if "usb" in cfg["detect"]:
        devices = usb_devices() if devices is None else devices
        present = usb_present(cfg["detect"]["usb"], devices)
        ids = ", ".join(f"{v}:{p or '*'}" for v, p in cfg["detect"]["usb"])
        return {"present": present, "variant": next(iter(cfg["variants"])) if present else None, "how": f"USB {ids}"}
    _rc, out = run(jtag_scan_argv(host), 60)
    variant, code = xc7_variant(parse_idcodes(out))
    found = {"present": code is not None, "variant": variant, "how": "JTAG scan", "output": _tail(out, 8)}
    if code is not None:
        found["idcode"] = f"{code:#010x}"
    return found


# -- the installed bitstreams -------------------------------------------------------------------------------


def load_manifest(images):
    path = pathlib.Path(images) / "manifest.json"
    try:
        manifest = json.loads(path.read_text())
    except FileNotFoundError:
        raise Problem("error", f"{path} is missing: is fpgas-online-<board>-bitstreams installed?") from None
    except (OSError, ValueError) as e:
        raise Problem("error", f"cannot read {path}: {e}") from None
    return manifest


def checked_bitstream(images, manifest, path):
    """The installed file for `path`, after checking it against the manifest."""
    entry = next((f for f in manifest.get("files", []) if f["path"] == path), None)
    if entry is None:
        raise Problem("error", f"the installed bitstreams ({manifest.get('version')}) have no {path}")
    file = pathlib.Path(images) / path
    try:
        data = file.read_bytes()
    except OSError as e:
        raise Problem("error", f"cannot read {file}: {e}") from None
    if len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
        raise Problem("error", f"{file} does not match the manifest: the package is damaged")
    return file


# -- running a test ---------------------------------------------------------------------------------------


def uart_pre(board, host):
    """Free the board's UART on the Pi: no login console on it, and on a Pi 5 its pins muxed to UART0."""
    port = host["port"]
    if not port.startswith("/dev/tty") and not port.startswith("/dev/serial"):
        return []
    tty = os.path.basename(os.path.realpath(port))
    steps = [["systemctl", "stop", f"serial-getty@{tty}.service"]]
    if board == "netv2" and is_pi5(host["model"]):
        steps += [["pinctrl", "set", "14", "a4"], ["pinctrl", "set", "15", "a4"]]
    return steps


def test_argv(board, test, host, bitstream):
    t = BOARDS[board]["tests"][test]
    script = [sys.executable, str(host["lib"] / t["script"]), *(a.format(port=host["port"]) for a in t["args"])]
    if t.get("runner") == "tt-bridge":
        return [sys.executable, str(host["lib"] / "tt_test_wrapper.py"), host["port"], str(bitstream), *script]
    return script


def run_test(board, test, variant, host, images, manifest, run=_run):
    """Program the board with a test's bitstream and run its test: {"test", "result", ...}."""
    t = BOARDS[board]["tests"][test]
    out = {"test": test, "bitstream": artifact_path(board, test, variant)}
    try:
        bitstream = checked_bitstream(images, manifest, out["bitstream"])
        steps = list(t.get("pre", []))
        if "{port}" in " ".join(t["args"]) and t.get("runner") != "tt-bridge":
            steps += uart_pre(board, host)
        for step in steps:
            with contextlib.suppress(Problem):
                run(step, 30)
        if t.get("runner") != "tt-bridge":  # the bridge programs the FPGA itself
            rc, text = run(program_argv(board, bitstream, host, test), PROGRAM_TIMEOUT)
            if rc != 0:
                return {**out, "result": "fail", "reason": f"programming failed (exit {rc})", "output": _tail(text)}
        rc, text = run(test_argv(board, test, host, bitstream), TEST_TIMEOUT)
    except Problem as p:
        return {**out, "result": p.result, "reason": p.reason}
    result = "pass" if rc == 0 else "fail"
    return {**out, "result": result, **({} if rc == 0 else {"reason": f"exit {rc}"}), "output": _tail(text)}


def host_facts(board, port=None):
    model = pi_model()
    host = {"model": model, "port": port or BOARDS[board]["port"], "lib": lib_dir(board), "base": None}
    if board == "netv2" and not is_pi5(model):
        try:
            host["base"] = peripheral_base()
        except (OSError, Problem):
            host["base"] = None
    return host


def verify(board, host, images, tests=None, variant=None, run=_run, devices=None):
    tests = tests or verify_tests(board)
    report = {
        "schema_version": SCHEMA_VERSION,
        "board": board,
        "result": "none",
        "bitstreams": None,
        "variant": None,
        "checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "host": host["model"] or None,
        "tests": [],
    }
    try:
        if "jtag" in BOARDS[board]["detect"]:
            if not host["model"].startswith("Raspberry Pi"):
                return {**report, "reason": "not a Raspberry Pi: no GPIO header to scan for JTAG"}
            if not is_pi5(host["model"]) and host["base"] is None:
                raise Problem("error", f"cannot read the peripheral base from {DT_SOC_RANGES}: cannot drive JTAG")
        found = detect(board, host, run=run, devices=devices)
        report["detected"] = found
        if not found["present"]:
            return {**report, "reason": f"no {BOARDS[board]['title']} found ({found['how']})"}
        variant = variant or found["variant"]
        if variant not in BOARDS[board]["variants"]:
            code = found.get("idcode", "?")
            raise Problem("error", f"the JTAG chain has IDCODE {code}, which is no {BOARDS[board]['title']} part")
        report["variant"] = variant
        manifest = load_manifest(images)
        report["bitstreams"] = manifest.get("version")
    except Problem as p:
        return {**report, "result": p.result, "reason": p.reason}
    for test in tests:
        report["tests"].append(run_test(board, test, variant, host, images, manifest, run=run))
    report["result"] = max((t["result"] for t in report["tests"]), key=SEVERITY.index, default="pass")
    return report


def exit_code(report):
    return 0 if report["result"] in ("pass", "none") else 1


# -- reporting ---------------------------------------------------------------------------------------


def fleet_event_argv(report):
    """`fleet-event fpga-verified` with a flat summary: fleet-event details are single strings."""
    details = {
        "result": report["result"],
        "board": report["board"],
        "variant": report["variant"] or "-",
        "bitstreams": report["bitstreams"] or "-",
    }
    for t in report["tests"]:
        details[f"test_{t['test']}"] = t["result"]
        if "reason" in t:
            details[f"test_{t['test']}_reason"] = t["reason"]
    if "reason" in report:
        details["reason"] = report["reason"]
    argv = ["fleet-event", "fpga-verified"]
    for k, v in details.items():
        argv += ["--detail", f"{k}={v}"]
    return argv


def publish(report, kept_in, prog):
    """Send the fleet-event. A failure is reported loudly but does not change the result."""
    try:
        subprocess.run(fleet_event_argv(report), check=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"{prog}: could not publish the result ({e}); the report is in {kept_in}", file=sys.stderr)
        return False
    return True


def summary(report):
    title = BOARDS[report["board"]]["title"]
    lines = [f"{title} verify: {report['result']} (variant {report['variant'] or '-'}, "
             f"bitstreams {report['bitstreams'] or '-'})"]  # fmt: skip
    if "reason" in report:
        lines.append(f"  {report['reason']}")
    for t in report["tests"]:
        lines.append(f"  {t['test']:<10} {t['result']}" + (f": {t['reason']}" if "reason" in t else ""))
        if t["result"] != "pass":
            lines += [f"      {line}" for line in t.get("output", [])[-8:]]
    if report["result"] in ("fail", "error"):
        lines.append(f"  more: fpgas-{BOARDS[report['board']]['slug']}-debug (fpgas-online-"
                     f"{BOARDS[report['board']]['slug']}-debug)")  # fmt: skip
    return "\n".join(lines)


@contextlib.contextmanager
def hold_lock(board):
    """One user of the board at a time: this check, or fpgas-<board>-debug."""
    RUN.mkdir(parents=True, exist_ok=True)
    with open(RUN / f"{BOARDS[board]['slug']}.lock", "w") as f:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"waiting for another user of the {BOARDS[board]['title']} to finish...", file=sys.stderr)
            fcntl.flock(f, fcntl.LOCK_EX)
        yield


def main(argv=None, prog=None):
    prog = prog or pathlib.Path(sys.argv[0]).name
    board = board_for_program(prog)
    parser = argparse.ArgumentParser(prog=prog, description=__doc__.split("\n\n")[0])
    parser.add_argument("--board", choices=sorted(BOARDS), default=board, required=board is None)
    parser.add_argument("--test", action="append", help="run only this test (repeatable)")
    parser.add_argument("--variant", help="use this variant's bitstreams instead of the detected one")
    parser.add_argument("--port", help="the board's UART on this Pi (default: the board's usual one)")
    parser.add_argument("--images", type=pathlib.Path, help="installed bitstreams (manifest.json)")
    parser.add_argument("--report", help="where to write the JSON report ('-' for stdout)")
    parser.add_argument("--no-publish", action="store_true", help="do not send the fleet-event")
    args = parser.parse_args(argv)

    known = BOARDS[args.board]["tests"]
    for t in args.test or []:
        if t not in known:
            parser.error(f"{args.board} has no test {t!r}: {', '.join(known)}")
    if args.variant and args.variant not in BOARDS[args.board]["variants"]:
        parser.error(f"{args.board} variants: {', '.join(BOARDS[args.board]['variants'])}")
    images = args.images or images_dir(args.board)
    report_to = args.report or str(RUN / f"{BOARDS[args.board]['slug']}-verify.json")

    with hold_lock(args.board):
        report = verify(args.board, host_facts(args.board, args.port), images, args.test, args.variant)
    text = json.dumps(report, indent=2) + "\n"
    if report_to == "-":
        sys.stdout.write(text)
    else:
        out = pathlib.Path(report_to)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)
    print(summary(report), file=sys.stderr)
    if not args.no_publish:
        publish(report, "stdout" if report_to == "-" else report_to, prog)
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
