#!/usr/bin/env python3
"""
Host-side DDR memory test script.

Attaches to the LiteX BIOS of the DDR test design over the UART and asks it to test the memory now:

  1. `ident`       the design answering is the DDR test design for this board
  2. `mem_list`    where the DRAM is and how much the design has
  3. `sdram_init`  initialisation and read leveling again (a window on every byte lane), the BIOS's
                   2 MiB memtest, and its write and read speed
  4. `sdram_test`  a memtest over 1/32 of the DRAM
  5. `mem_write`, `flush_cpu_dcache`, `flush_l2_cache`, `mem_read`
                   a different word at the DRAM's base and at every address bit up to half its size, all
                   read back from the DRAM: a memtest over a small range passes on a board with half the
                   memory the design was built for, or with a broken address line

The design's DRAM size (`mem_list`) must be the board's.

The verdict is these runs', not the one the BIOS made while it booted: that output is gone before the
Pi's own UART is opened (the NeTV2), and is an old log on an FTDI UART (the Arty). See
designs/_host/bios_console.py.

The last line of output is the result for fpgas-verify: RESULT_JSON {"test": "ddr", "result": ...}.

Usage:
    uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyUSB1
    uv run python designs/ddr-memory/host/test_ddr.py --port /dev/ttyAMA0 --board netv2
"""

import argparse
import os
import re
import sys
import time

# In the repository the helper is in designs/_host; installed, it is beside this script.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "_host"))

import bios_console

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

BAUD_RATE = 115200
ATTACH_TIMEOUT_S = 60  # the BIOS waits for a serial boot before its first prompt

# What `ident` must contain: the design, and the board it was built for. `lanes` is the board's DDR3 byte
# lanes: read leveling must report each of them. `ram` is the DRAM the board has, which the design must
# have been built for: the Acorn's is 1 GiB on the CLE-215/215+ and 512 MiB on the CLE-101.
MIB = 1024**2
DESIGN_IDENT = "DDR Test SoC"
BOARDS = {
    "arty": {"ident": "Arty A7", "lanes": 2, "ram": (256 * MIB,)},
    "netv2": {"ident": "NeTV2", "lanes": 4, "ram": (512 * MIB,)},
    "acorn": {"ident": "Acorn", "lanes": 2, "ram": (512 * MIB, 1024 * MIB)},
}

# How long each command is given. sdram_test prints a progress line per 128 KiB: at 115200 baud that
# printing, not the memory, is most of its time.
COMMAND_TIMEOUT_S = {
    "ident": 10,
    "mem_list": 10,
    "sdram_init": 120,
    "sdram_test": 300,
    "mem_write": 10,
    "flush_cpu_dcache": 10,
    "flush_l2_cache": 10,
    "mem_read": 10,
}

UNITS = {"B": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}
SIZE_RE = re.compile(r"([0-9.]+)(B|KiB|MiB|GiB)")
MEMTEST_RE = re.compile(r"Memtest at (0x[0-9a-fA-F]+) \(([0-9.]+(?:B|KiB|MiB|GiB))\)")
ERRORS_RE = re.compile(r"(bus|addr|data) errors:\s*(\d+)/(\d+)")
BEST_RE = re.compile(r"best: (m\d+), (b\d+) delays: (\S+)")
SPEED_RE = re.compile(r"(Write|Read) speed: ([0-9.]+)MiB/s")
MAIN_RAM_RE = re.compile(r"MAIN_RAM\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)")
DUMP_RE = re.compile(r"^0x[0-9a-fA-F]+\s+((?:[0-9a-fA-F]{2} ){3}[0-9a-fA-F]{2})\b")
ADDRESS_WORD = 0xADD00000  # the address test's words: this plus the index of the address
ADDRESS_FAULTS_SHOWN = 4


# --------------------------------------------------------------------------- #
# Reading the BIOS's replies
# --------------------------------------------------------------------------- #


def parse_size(text):
    """Bytes of a size as the BIOS prints it: "2.0MiB", "128.0KiB", "0B"."""
    m = SIZE_RE.fullmatch(text)
    return int(float(m.group(1)) * UNITS[m.group(2)])


def parse_leveling(reply):
    """{"m0": "b01 14+-14", ...}: each byte lane's best bitslip and delay window, None where none was found."""
    found = {}
    for line in reply:
        m = BEST_RE.search(line)
        if m:
            found[m.group(1)] = None if m.group(3) == "-" else f"{m.group(2)} {m.group(3)}"
    return found


def parse_memtest(reply):
    """{"verdict": "OK" | "KO" | None, "bytes": tested, "errors": {"bus": (bad, of), ...}} of one memtest."""
    found = {"verdict": None, "bytes": 0, "errors": {}}
    for line in reply:
        m = MEMTEST_RE.search(line)
        if m:
            found["bytes"] = parse_size(m.group(2))
        m = ERRORS_RE.search(line)
        if m:
            found["errors"][m.group(1)] = (int(m.group(2)), int(m.group(3)))
        if "Memtest OK" in line:
            found["verdict"] = "OK"
        elif "Memtest KO" in line:
            found["verdict"] = "KO"
    return found


def parse_speed(reply):
    """{"write_mib_per_s": ..., "read_mib_per_s": ...}, with what the BIOS measured."""
    found = {}
    for line in reply:
        m = SPEED_RE.search(line)
        if m:
            found[f"{m.group(1).lower()}_mib_per_s"] = float(m.group(2))
    return found


def parse_word(reply):
    """The 32-bit word `mem_read <addr> 4` dumped (the CPU is little-endian), or None without a dump."""
    for line in reply:
        m = DUMP_RE.search(line)
        if m:
            return int.from_bytes(bytes.fromhex(m.group(1).replace(" ", "")), "little")
    return None


def memtest_fault(command, memtest, at_least=1):
    """Why this memtest is a failure, or None. It must have covered `at_least` bytes."""
    if memtest["verdict"] is None:
        return f"{command}: no memtest verdict"
    if memtest["verdict"] == "KO":
        counts = ", ".join(f"{kind} errors {bad}/{of}" for kind, (bad, of) in memtest["errors"].items())
        return f"{command}: Memtest KO ({counts})"
    if memtest["bytes"] == 0:
        return f"{command}: Memtest OK over 0 bytes"
    if memtest["bytes"] < at_least:
        return (
            f"{command}: Memtest OK over {memtest['bytes'] // 1024**2} MiB, "
            f"less than 1/32 of the DRAM ({at_least // 1024**2} MiB)"
        )
    return None


# --------------------------------------------------------------------------- #
# Test logic
# --------------------------------------------------------------------------- #


def address_test(ask, base, size):
    """(address bits tested, faults): does every address bit of the DRAM reach its own cell?

    A different word goes to the base and to base + 2**bit for every bit from 4 bytes up to half the size.
    The CPU's data cache and the L2 cache are then flushed, so the words are read back from the DRAM and
    not from a cache that still holds what was written. Where two addresses are one cell (an address bit
    the chip does not have, or a broken address line), one of them reads back the other's word.

    Not covered: addresses that are one cell only with several bits set at once, and the bits inside one
    L2 cache line (offsets 4 to 16), which reach the DRAM as one burst.
    """
    offsets = [0]
    bit = 2
    while 1 << bit < size:
        offsets.append(1 << bit)
        bit += 1
    words = {base + offset: ADDRESS_WORD + index for index, offset in enumerate(offsets)}
    for addr, word in words.items():
        ask(f"mem_write {addr:#x} {word:#x}")
    ask("flush_cpu_dcache")
    ask("flush_l2_cache")
    written_to = {word: addr for addr, word in words.items()}
    faults = []
    for addr, word in words.items():
        got = parse_word(ask(f"mem_read {addr:#x} 4"))
        if got == word:
            continue
        if got in written_to:
            faults.append(f"{addr:#x} holds the word written to {written_to[got]:#x}")
        elif got is None:
            faults.append(f"{addr:#x} could not be read")
        else:
            faults.append(f"{addr:#x} reads {got:#010x}, not {word:#010x}")
    return len(offsets) - 1, faults


def run_ddr_test(bios, board, attach_timeout=ATTACH_TIMEOUT_S):
    """Run the test on an open BIOS console. Returns the result's fields ("result", "reason", ...)."""
    found = {"test": "ddr", "board": board, "commands": []}

    def ask(command):
        name = command.split()[0]
        if name not in found["commands"]:
            found["commands"].append(name)
        return bios.command(command, COMMAND_TIMEOUT_S[name])

    def failed(reason):
        print(f"FAIL: {reason}")
        return {**found, "result": "fail", "reason": reason}

    try:
        bios.attach(attach_timeout)
    except bios_console.NoPrompt as e:
        return failed(f"{e}: nothing on the UART answers as a LiteX BIOS")
    print("PASS: the BIOS answers at its prompt")

    faults = []
    memtests = []
    address_faults = []
    try:
        found["commands"].append("ident")
        found["ident"] = ident = bios.ident()
        name = BOARDS[board]["ident"]
        if not ident or DESIGN_IDENT not in ident or name not in ident:
            return failed(f"the design on the UART is {ident!r}, not the {DESIGN_IDENT} for the {name}")
        print(f"PASS: {ident}")

        m = MAIN_RAM_RE.search("\n".join(ask("mem_list")))
        if m:
            found["main_ram_base"], found["main_ram_bytes"] = int(m.group(1), 16), int(m.group(2), 16)
            ram = found["main_ram_bytes"]
            print(f"  DRAM: {ram // MIB} MiB at {found['main_ram_base']:#x}")
            if ram not in BOARDS[board]["ram"]:
                has = " or ".join(str(size // MIB) for size in BOARDS[board]["ram"])
                faults.append(f"mem_list: the design has {ram // MIB} MiB of DRAM; the {name} has {has} MiB")
        else:
            faults.append("mem_list: the design has no MAIN_RAM region")

        reply = ask("sdram_init")
        found["leveling"] = leveling = parse_leveling(reply)
        for lane, window in sorted(leveling.items()):
            print(f"  read leveling {lane}: {window or 'no window'}")
        if not leveling:
            faults.append("sdram_init: no read leveling result")
        elif not all(leveling.values()):
            lanes = ", ".join(sorted(lane for lane, window in leveling.items() if not window))
            faults.append(f"sdram_init: read leveling found no window on {lanes}")
        if leveling and len(leveling) != BOARDS[board]["lanes"]:
            faults.append(
                f"sdram_init: read leveling reported {len(leveling)} byte lanes; "
                f"the {name} has {BOARDS[board]['lanes']}"
            )
        memtests.append(("sdram_init", parse_memtest(reply)))
        found.update(parse_speed(reply))

        memtests.append(("sdram_test", parse_memtest(ask("sdram_test"))))

        # Only on memory that passes its memtests: on memory that does not, every address would be a fault.
        if "main_ram_bytes" in found and all(m["verdict"] == "OK" for _, m in memtests):
            found["address_bits_tested"], bad = address_test(ask, found["main_ram_base"], found["main_ram_bytes"])
            if bad:
                shown = "; ".join(bad[:ADDRESS_FAULTS_SHOWN])
                more = f"; and {len(bad) - ADDRESS_FAULTS_SHOWN} more" if len(bad) > ADDRESS_FAULTS_SHOWN else ""
                address_faults.append(f"address test: {shown}{more}")
    except bios_console.NoPrompt as e:
        faults.append(str(e))
    except OSError as e:  # the port went away (pyserial's SerialException is one)
        faults.append(f"the UART failed during `{found['commands'][-1]}`: {e}")

    share = {"sdram_test": found.get("main_ram_bytes", 0) // 32}  # what sdram_test covers of the DRAM
    for command, memtest in memtests:
        fault = memtest_fault(command, memtest, share.get(command, 1))
        if fault:
            faults.append(fault)
        else:
            print(f"PASS: {command}: Memtest OK over {memtest['bytes'] // 1024**2} MiB")
    if "address_bits_tested" in found and not address_faults:
        print(f"PASS: address test: {found['address_bits_tested']} address bits each reach their own cell")
    faults += address_faults
    found["bytes_tested"] = max((m["bytes"] for _, m in memtests), default=0)
    found["errors"] = max((sum(bad for bad, _ in m["errors"].values()) for _, m in memtests), default=0)
    if "write_mib_per_s" in found:
        print(f"  speed: write {found['write_mib_per_s']} MiB/s, read {found['read_mib_per_s']} MiB/s")

    if faults:
        for fault in faults:
            print(f"FAIL: {fault}")
        return {**found, "result": "fail", "reason": "; ".join(faults)}
    return {**found, "result": "pass"}


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #


def open_port(port, baud, timeout):
    import serial

    return serial.Serial(port, baud, timeout=timeout)


def main(argv=None):
    parser = argparse.ArgumentParser(description="DDR memory test for FPGA boards")
    parser.add_argument(
        "--port",
        required=True,
        help="Serial port device path (e.g. /dev/ttyUSB1, /dev/ttyAMA0)",
    )
    parser.add_argument(
        "--board",
        default="arty",
        choices=list(BOARDS),
        help="Board under test (default: arty)",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=BAUD_RATE,
        help=f"Baud rate (default: {BAUD_RATE})",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=ATTACH_TIMEOUT_S,
        help=f"Seconds to wait for the BIOS prompt (default: {ATTACH_TIMEOUT_S})",
    )
    args = parser.parse_args(argv)

    print(f"Opening {args.port} at {args.baud} baud...")
    print(f"Board: {args.board}")
    print()

    # Whatever happens to the port, the script ends with a result line.
    found = {"test": "ddr", "board": args.board, "result": "fail"}
    try:
        ser = open_port(args.port, args.baud, 1)
    except (OSError, ImportError) as e:  # no such port, port in use, no pyserial
        found["reason"] = f"cannot open {args.port}: {e}"
        print(f"FAIL: {found['reason']}")
    else:
        try:
            found = run_ddr_test(bios_console.BiosConsole(ser, clock=time.monotonic), args.board, args.timeout)
        except OSError as e:  # the port went away before the BIOS answered
            found["reason"] = f"the UART failed: {e}"
            print(f"FAIL: {found['reason']}")
        except Exception as e:  # anything else still ends with the result line
            found["reason"] = f"the test failed: {type(e).__name__}: {e}"
            print(f"FAIL: {found['reason']}")
        finally:
            close = getattr(ser, "close", None)
            if close:
                close()

    print()
    if found["result"] == "pass":
        print("RESULT: PASS — DDR memory test completed successfully")
    else:
        print("RESULT: FAIL — DDR memory test had failures")
    bios_console.print_result_json(found)
    return 0 if found["result"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
