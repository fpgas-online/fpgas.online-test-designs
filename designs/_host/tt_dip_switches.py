#!/usr/bin/env python3
"""Say whether any of a Tiny Tapeout demo board's eight DIP switches is on (#166).

Each switch of the demo board's SW1, when on, ties its `ui_in` line to 3.3 V through 1 kOhm (Tiny Tapeout's
tt-demo-pcb schematic: switch 1 on `ui_in[0]` to switch 8 on `ui_in[7]`; the board has no other pull on those
lines). The check's tests drive and read `ui_in` from the Raspberry Pi and from the demo board's RP2350, so a
switch left on stands against them: it holds a line high that nothing drives, and loads every low level.
Tiny Tapeout's own guides say all of them should be off, and so does this check.

The read is made by the RP2350, over its raw REPL, in RAM: nothing is written to the board. For each line it
drives the pin low for a moment, then makes it an input with the RP2350's pull-down and reads it: a switch
that is on reads 1 (1 kOhm against tens of kOhm), one that is off reads 0. Driving it low first is for the
RP2350's erratum E9 (a pad held up by its leakage after it was last high, which a weak pull-down cannot pull
back down); it is the same load a switch that is on puts on the tests. The pins are left as inputs with the
pull-down, which is how the Tiny Tapeout SDK sets them on a board with the FPGA breakout.

Nothing else may hold the lines while they are read, so it runs:
  - after the check has loaded the display design (designs/tt-display) with --gpio-release: that design
    drives only uo_out and leaves ui_in and uio undriven with the iCE40's pull-up off (an unused iCE40 pin
    keeps a weak pull-up, which would stand against the pull-down), and --gpio-release has made the RP2350's
    signal pins inputs;
  - with the Raspberry Pi's eight GPIOs on HAT JA (ui_in) set to inputs with their pull-down, for the read
    only, then put back as they were, with pinctrl. JA pins 2 to 4 are also JB's: the HAT joins ui_in[1..3]
    to uio[1..3]. On the demo board the uio[1..3] nets carry only the BIDIR Pmod, the breakout, a pin header
    and the RP2350's GPIO26 to GPIO28, no resistor (tt-demo-pcb's schematic, rev 3.3 at bbf3dd1, its exported
    netlist), so those three RP2350 pads are driven low and given the pull-down too, with their ui_in partner.
A Pi whose pinctrl cannot read a pin's pull (a Pi 3 and older) is refused before anything is changed: the pull
could not be put back.

Exit 0: every switch is off. Exit 1: names each switch that is on. Exit 2: the switches could not be read,
and why. The last line starting DIP_SWITCHES: is the result.

Usage (on the Pi, with fpgas-tt.service stopped):
    python3 tt_dip_switches.py /dev/ttyACM0
"""

import argparse
import re
import signal
import subprocess
import sys

SWITCHES = 8
FIRST_GPIO = 17  # the RP2350's GPIO17 is ui_in[0] (switch 1), to GPIO24, ui_in[7] (switch 8)
# ui_in[n] -> the RP2350 GPIO of the uio signal the Pmod HAT joins it to (JA and JB pins 2 to 4 are one Pi GPIO):
# uio[1] to uio[3] are the RP2350's GPIO26 to GPIO28 (GPIO25 + n).
JOINED = {1: 26, 2: 27, 3: 28}
# The Raspberry Pi GPIOs on Pmod HAT JA, ui_in[0] to ui_in[7] as the boards are cabled (identify_pmod_pins.py,
# BOARDS["tt"]): JA pins 1, 2, 3, 4, 7, 8, 9, 10.
PI_GPIOS = (8, 10, 9, 11, 19, 21, 20, 18)
ADVICE = "set all DIP switches off"
TIMEOUT = 60
PINCTRL_TIMEOUT = 10
# Run on the board, in RAM. It writes no file.
READ = (
    "from machine import Pin\n"
    "import time\n"
    f"joined = {JOINED!r}\n"
    "r = ''\n"
    f"for n in range({SWITCHES}):\n"
    f"    pins = [Pin(g, Pin.OUT, value=0) for g in [{FIRST_GPIO} + n] + ([joined[n]] if n in joined else [])]\n"
    "    time.sleep_ms(1)\n"
    "    for q in pins:\n"
    "        q.init(Pin.IN, Pin.PULL_DOWN)\n"
    "    time.sleep_ms(5)\n"
    "    r += str(pins[0].value())\n"
    "print('DIP', r)\n"
)
# pinctrl get: "8: ip    pu | hi // GPIO8 = input", "10: a0    pn | lo // GPIO10 = SPI0_MOSI": the function, the
# pull ("--" where the SoC cannot read it back) and the level (the form of core.PIN_RE in fpgas_online_verify).
PIN_RE = re.compile(r"^\s*(\d+):\s+(\w+)(?:\s+(?:d[hl]|--))?\s+(p[udn]|--)\s*\|\s*(\w+|--)", re.MULTILINE)


def said(line):
    print(f"DIP_SWITCHES: {line}")


def on_switches(bits):
    """'00001001' (switch 1 first) -> [5, 8]: the switches that read on."""
    return [n + 1 for n, bit in enumerate(bits) if bit == "1"]


def verdict(rc, out, err):
    """(exit code, what to say) from the board's read."""
    m = re.search(rf"^DIP ([01]{{{SWITCHES}}})\s*$", out, re.MULTILINE)
    if rc != 0 or not m:
        why = " ".join((err.strip() or out.strip()).splitlines()[-2:]) or "it printed nothing"
        return 2, f"the DIP switches could not be read from the board (exit {rc}): {why}"
    on = on_switches(m.group(1))
    if not on:
        return 0, f"all {SWITCHES} DIP switches are off"
    which = ", ".join(f"switch {n} is on" for n in on)
    return 1, f"{which}: {ADVICE}"


def read_board(port, timeout=TIMEOUT, run=subprocess.run):
    """(returncode, stdout, stderr) of the read; mpremote hanging is 124, mpremote not installed 127."""
    try:
        p = run(["mpremote", "connect", port, "exec", READ], capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, "", f"mpremote did not finish within {timeout} s"
    except FileNotFoundError:
        return 127, "", "mpremote is not installed"
    return p.returncode, p.stdout, p.stderr


def pinctrl(args, run=subprocess.run):
    """(returncode, output) of pinctrl; 127 when it is not installed."""
    try:
        p = run(["pinctrl", *args], capture_output=True, text=True, timeout=PINCTRL_TIMEOUT)
    except FileNotFoundError:
        return 127, "pinctrl is not installed"
    except subprocess.TimeoutExpired:
        return 124, f"pinctrl did not finish within {PINCTRL_TIMEOUT} s"
    return p.returncode, p.stdout + p.stderr


def pi_pins(run=subprocess.run):
    """{gpio: (function, pull, level)} of PI_GPIOS, or a str saying why they could not be read."""
    rc, out = pinctrl(["get", ",".join(map(str, PI_GPIOS))], run)
    found = {int(g): (f, pull, level) for g, f, pull, level in PIN_RE.findall(out)}
    if rc != 0 or set(found) != set(PI_GPIOS):
        return f"the Pi's GPIOs on HAT JA could not be read with pinctrl: {out.strip()[:200]}"
    return found


def set_pins(states, run=subprocess.run):
    """Set each GPIO to (function, pull, level): an output goes back at the level it had, and a pull that could
    not be read is left as it is. Returns the faults."""
    faults = []
    for gpio, (func, pull, level) in sorted(states.items()):
        drive = ["dh" if level == "hi" else "dl"] if func == "op" else []
        args = ["set", str(gpio), func, *([] if pull == "--" else [pull]), *drive]
        rc, out = pinctrl(args, run)
        if rc != 0:
            faults.append(f"GPIO{gpio} could not be set to {' '.join(args[2:])}: {out.strip()[:200]}")
    return faults


def check(port, run=subprocess.run):
    """(exit code, what to say): the Pi's JA GPIOs made inputs with their pull-down, the board read, the
    GPIOs put back."""
    saved = pi_pins(run)
    if isinstance(saved, str):
        return 2, f"{saved}: the DIP switches were not read"
    unread = sorted(g for g, (_f, pull, _l) in saved.items() if pull == "--")
    if unread:
        return 2, (f"this Pi's pinctrl cannot read the pull of GPIO{', GPIO'.join(map(str, unread))}, so it could "
                   "not be put back after the read: the DIP switches were not read")  # fmt: skip
    signal.signal(signal.SIGTERM, _stop)  # a stopped check still puts the Pi's pins back (the finally below)
    try:
        faults = set_pins({g: ("ip", "pd", "--") for g in PI_GPIOS}, run)
        if faults:
            why = "; ".join(faults)
            code, line = 2, f"the Pi's GPIOs on HAT JA could not be made inputs ({why}): the DIP switches were not read"
        else:
            code, line = verdict(*read_board(port, run=run))
    finally:
        back = set_pins(saved, run)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
    if back:
        print("Not put back: " + "; ".join(back))
        code, line = 2, f"{line}; and the Pi's GPIOs on HAT JA were not put back as they were ({'; '.join(back)})"
    return code, line


def _stop(signum, frame):
    raise SystemExit(f"stopped by signal {signum}")


def main():
    parser = argparse.ArgumentParser(description="Say whether a Tiny Tapeout demo board's DIP switches are off")
    parser.add_argument("port", help="the demo board's serial port")
    args = parser.parse_args()
    code, line = check(args.port)
    said(line)
    return code


if __name__ == "__main__":
    sys.exit(main())
