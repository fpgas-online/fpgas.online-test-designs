#!/usr/bin/env python3
"""Verify the PMOD ribbon wiring between a Tiny Tapeout demo board and the Pi.

Runs on the Raspberry Pi. The demo board's RP2040/RP2350 (running the Tiny
Tapeout MicroPython SDK) drives one TT signal at a time while the Pi samples
every GPIO behind the Digilent PMOD HAT, so the ribbon between each demo-board
PMOD connector (ui_in, uio, uo_out) and each HAT port (JA, JB, JC) is checked
bit for bit. No bitstream and no ASIC design are needed, so this also works on
the deployed TT ASIC boards.

Only one party ever drives a net:

* ``ui_in`` nets are driven by the RP2 (exactly what the SDK does in
  ``ASIC_RP_CONTROL`` mode); the Pi only reads. Bits something else holds
  (a DIP switch, the Pi's console UART) are detected first and left alone.
* ``uio`` nets are driven by the RP2 only once the chip is known not to: the
  shuttle's ``tt_um_factory_test`` is selected and *confirmed* on-board (the
  RP2 reads its own ``uo_out`` pins following what it drives on ``uio``).
  Without that confirmation only bits that follow the RP2's weak pulls are
  driven.
* ``uo_out`` nets are only ever driven by the ASIC. With the factory test
  (``uo_out = uio_in``, ``uio_oe = 0`` while ``ui_in[0]`` is low) walking
  ``uio`` also exercises the ``uo_out`` ribbon through the chip. Without it,
  ``uo_out`` is reported as not tested, never as PASS.

A contention-free *reverse walk* (the Pi pulls one line up, the RP2 reads its
inputs) attributes each direct connection independently of the chip, so a
swapped JA/JB pair cannot hide behind the loopback, and a *latch test* on
the HAT's shared JA2-4/JB2-4 lines catches an open on either ribbon.

Usage (on the Pi, as root or with passwordless sudo):

    python3 check_tt_pmod_wiring.py                       # verify standard cabling
    python3 check_tt_pmod_wiring.py --discover            # just print what is wired where
    python3 check_tt_pmod_wiring.py --asic-project none   # do not touch the ASIC project
    python3 check_tt_pmod_wiring.py --controller rp2350   # demo board v3

The script stops the ``fpgas-tt`` daemon (which owns the serial port) and
restarts it afterwards, disables SysRq for the duration (the serial console
shares GPIO14/15 with HAT port JC), and unloads the SPI kernel modules that
claim GPIO7-11. Requirements: python3-libgpiod (v1.6+ or v2.x).

Prints ``RESULT: PASS`` or ``RESULT: FAIL`` as the last line and exits 0/1.
"""

import argparse
import json
import os
import pathlib
import re
import select
import subprocess
import sys
import termios
import time
import tty

# gpiod only exists on the Raspberry Pi (it wraps libgpiod). Guard the import so
# the protocol, discovery and verdict logic can be imported and unit-tested on a
# development machine. Anything that touches real GPIO checks for None.
try:
    import gpiod
except ImportError:  # pragma: no cover - exercised only off-target
    gpiod = None

# -- PMOD HAT: port pins -> Pi BCM GPIO -----------------------------------------

# Source: docs/hardware/rpi-hat-pmod.md. Order is PMOD pins 1,2,3,4,7,8,9,10,
# i.e. signal bits 0..7 of whichever TT group the ribbon carries.
# JA2-4 and JB2-4 are the *same* Pi lines (GPIO10/9/11, the SPI0 bus).
PMOD_HAT_PORTS = {
    "JA": [8, 10, 9, 11, 19, 21, 20, 18],
    "JB": [7, 10, 9, 11, 26, 13, 3, 2],
    "JC": [16, 14, 15, 17, 4, 12, 5, 6],
}
PMOD_PIN_NUMBERS = [1, 2, 3, 4, 7, 8, 9, 10]

# Every Raspberry Pi has 1.8 kOhm pull-ups to 3.3 V on the I2C1 pins. The Pi's
# and the RP2's ~50 kOhm internal pulls cannot move them, so these lines
# (HAT JB9/JB10) always read 1 unless something drives them low.
PI_FIXED_PULLUP_GPIOS = {2, 3}

ALL_HAT_GPIOS = []
for _port in ("JA", "JB", "JC"):
    for _gpio in PMOD_HAT_PORTS[_port]:
        if _gpio not in ALL_HAT_GPIOS:
            ALL_HAT_GPIOS.append(_gpio)

# GPIO -> "JA1" / "JA2/JB2" style label.
HAT_GPIO_LABELS = {}
for _port, _gpios in PMOD_HAT_PORTS.items():
    for _gpio, _pin in zip(_gpios, PMOD_PIN_NUMBERS):
        HAT_GPIO_LABELS.setdefault(_gpio, []).append(f"{_port}{_pin}")
HAT_GPIO_LABELS = {g: "/".join(labels) for g, labels in HAT_GPIO_LABELS.items()}

# -- Demo board controller: TT signal -> RP2 GPIO ---------------------------------

# Data GPIOs are identical on every RP2040 demo board (TT04 through TT08: the
# GPIOMapTT04 and GPIOMapTT06 classes in the SDK differ only in control pins).
# RP2350 numbers are the demo board v3 (TT09+, TT FPGA) map.
# Source: docs/hardware/pmod-tt.md, tt-micropython-firmware gpio_map.py.
CONTROLLERS = {
    "rp2040": {
        "ui_in": [9, 10, 11, 12, 17, 18, 19, 20],
        "uio": [21, 22, 23, 24, 25, 26, 27, 28],
        "uo_out": [5, 6, 7, 8, 13, 14, 15, 16],
    },
    "rp2350": {
        "ui_in": [17, 18, 19, 20, 21, 22, 23, 24],
        "uio": [25, 26, 27, 28, 29, 30, 31, 32],
        "uo_out": [33, 34, 35, 36, 37, 38, 39, 40],
    },
}

GROUPS = ("ui_in", "uio", "uo_out")

# -- Expected cabling: TT group -> HAT port --------------------------------------

CABLINGS = {
    # Measured on the TT FPGA hosts (docs/hardware/tt-fpga-pin-mapping.md).
    "fpga": {"ui_in": "JC", "uio": "JB", "uo_out": "JA"},
    # Measured on the TT ASIC hosts on 2026-09-04 (pi-sw2-p6 first): the
    # mirror image, which puts the HAT's shared JA2-4/JB2-4 lines between
    # ui_in[1:3] and uio[1:3] instead of between uio[1:3] and uo_out[1:3].
    "asic": {"ui_in": "JA", "uio": "JB", "uo_out": "JC"},
}

RP2_GROUPS = ("ui_in", "uio")  # the groups the RP2 may drive


def signal_name(group, bit):
    return f"{group}[{bit}]"


def signal_bit(name):
    return int(name[:-1].split("[")[1])


def profile_lines(cabling):
    """``{signal: pi_gpio}`` for all 24 signals under a cabling profile."""
    ports = CABLINGS[cabling]
    return {signal_name(g, b): PMOD_HAT_PORTS[ports[g]][b] for g in GROUPS for b in range(8)}


def expected_direct(cabling):
    """Expected Pi GPIO of each RP2-driven signal's own ribbon line."""
    lines = profile_lines(cabling)
    return {n: g for n, g in lines.items() if not n.startswith("uo_out")}


def shared_partners(cabling):
    """``{signal: [other RP2-driven signals on the same Pi line]}`` under a profile.

    Two RP2 outputs on one HAT line (e.g. ui_in[1] and uio[1] with the asic
    cabling) must never be driven against each other.
    """
    direct = expected_direct(cabling)
    partners = {}
    for name, line in direct.items():
        partners[name] = [o for o, ol in direct.items() if o != name and ol == line]
    return partners


def connected_uio(cabling, name):
    """uio bits whose net is driven whenever *name* is driven (itself, or via a shared line)."""
    lines = profile_lines(cabling)
    return [j for j in range(8) if lines[signal_name("uio", j)] == lines[name]]


def latch_bits(cabling):
    """uio bits whose HAT line is also the same bit of uo_out (the chip loops back onto it)."""
    lines = profile_lines(cabling)
    return [k for k in range(8) if lines[signal_name("uio", k)] == lines[signal_name("uo_out", k)]]


def expected_map(cabling, asic_loopback):
    """Expected Pi GPIO set for every RP2-driven signal in the forward walk.

    A signal reaches its own HAT line and, with the factory-test loopback
    (``uo_out = uio_in``), the ``uo_out[j]`` line of every uio bit whose net
    it drives (itself for ``uio[j]``, or a shared-line partner).
    """
    lines = profile_lines(cabling)
    expected = {}
    for name in expected_direct(cabling):
        pins = {lines[name]}
        if asic_loopback:
            pins |= {lines[signal_name("uo_out", j)] for j in connected_uio(cabling, name)}
        expected[name] = pins
    return expected


def expected_followers(cabling, asic_loopback, name):
    """RP2 pins that legitimately follow *name* on the board side."""
    follow = set(shared_partners(cabling)[name])
    if asic_loopback:
        follow |= {signal_name("uo_out", j) for j in connected_uio(cabling, name)}
    else:
        # Unknown project: its own reactions on uio/uo_out are not faults.
        follow |= {signal_name(g, b) for g in ("uio", "uo_out") for b in range(8)}
    return follow


def choose_cabling(observed_ui_in, reverse):
    """Pick the profile that best explains the ui_in walk and the reverse walk."""
    best, best_score = None, -1
    for name in CABLINGS:
        lines = profile_lines(name)
        score = sum(1 for s, pins in observed_ui_in.items() if lines[s] in pins)
        score += sum(1 for s, pins in reverse.items() if pins == {lines[s]})
        if score > best_score:
            best, best_score = name, score
    return best, best_score


# -- MicroPython side ----------------------------------------------------------------

# A tiny command server run on the RP2 through the raw REPL. Every command is
# answered with exactly one "TTW ..." line (OK / VAL / VALS / ERR / PONG / BYE /
# READY); WARN lines may precede it. Inputs are requested with an explicit
# pull=None so the intent (no pull, whatever the SDK had set) is visible.
# "out" reads the pin back so the Pi can see a lost fight immediately.
FIRMWARE = r"""
import sys, time
from machine import Pin
DATA = __DATA__
_pins = {}
_tt = None
_saved_mode = None
_drive_warned = False
_PULLS = {'none': None, 'up': Pin.PULL_UP, 'down': Pin.PULL_DOWN}

def _emit(s):
    sys.stdout.write('TTW ' + s + '\n')

def _release_all():
    for g in DATA:
        _pins[g] = Pin(g, Pin.IN, None)

def _out(g, v, d):
    global _drive_warned
    try:
        p = Pin(g, Pin.OUT, value=v, drive=getattr(Pin, 'DRIVE_%d' % d))
    except (TypeError, AttributeError):
        if not _drive_warned:
            _drive_warned = True
            _emit('WARN drive strength unsupported by this firmware; using the default')
        p = Pin(g, Pin.OUT, value=v)
    _pins[g] = p
    return p

def _clock_stop(t):
    try:
        t.clock_project_stop()
    except Exception as e:
        _emit('WARN clock_project_stop: %r' % e)

def _find_tt():
    global _tt
    if _tt is None:
        t = globals().get('tt')
        if t is None:
            from ttboard.demoboard import DemoBoard
            t = DemoBoard.get() if hasattr(DemoBoard, 'get') else DemoBoard()
        _tt = t
    return _tt

def _sdk(args):
    global _saved_mode
    op = args[0]
    t = _find_tt()
    if op == 'init':
        _saved_mode = t.mode
        _clock_stop(t)
        _emit('OK mode=%s' % _saved_mode)
    elif op == 'project':
        name = args[1]
        sh = t.shuttle
        p = sh.get(name) if hasattr(sh, 'get') else getattr(sh, name)
        p.enable()
        # enable() applies the project's config.ini section, which may
        # restart the auto-clock (and change the mode); stop it again.
        _clock_stop(t)
        en = getattr(sh, 'enabled', None)
        _emit('OK enabled=%s mode=%s' % (getattr(en, 'name', en), t.mode))
    elif op == 'reset':
        _clock_stop(t)
        t.reset_project(True)
        time.sleep_ms(5)
        try:
            for _ in range(4):
                t.clock_project_once()
        except Exception as e:
            _emit('WARN clock_project_once: %r' % e)
        time.sleep_ms(5)
        t.reset_project(False)
        _emit('OK')
    elif op == 'restore':
        _release_all()
        if _saved_mode is not None:
            # Go through SAFE first in case the mode setter is a no-op for
            # an unchanged value; the SDK must re-own its pins.
            try:
                from ttboard.mode import RPMode
                t.mode = RPMode.SAFE
            except Exception as e:
                _emit('WARN mode SAFE: %r' % e)
            t.mode = _saved_mode
        _emit('OK mode=%s' % t.mode)
    else:
        _emit('ERR sdk: unknown op %s' % op)

def _txid(args):
    # Transmit each pin's label as 1200 baud 8N1 frames, like the FPGA
    # pin-id design, until a line arrives on stdin. All pins step together
    # once per bit period; setting them one after another costs a few
    # microseconds of constant skew per pin, well inside the 833 us bit.
    import select
    pins = []
    frames = []
    for a in args:
        g, label = a.split('=')
        pins.append(_out(int(g), 1, 1))
        bits = []
        for ch in (label + '\r\n').encode():
            bits.append(0)
            for i in range(8):
                bits.append((ch >> i) & 1)
            bits.append(1)
        frames.append(bits)
    n = max(len(f) for f in frames)
    for f in frames:
        f.extend([1] * (n - len(f)))
    slots = [[(pins[i], frames[i][s]) for i in range(len(pins))] for s in range(n)]
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)
    _emit('OK started')
    t = time.ticks_us()
    while True:
        for slot in slots:
            for p, v in slot:
                p.value(v)
            t = time.ticks_add(t, 833)
            while time.ticks_diff(t, time.ticks_us()) > 0:
                pass
        if poll.poll(0):
            sys.stdin.readline()
            break
        t = time.ticks_us()
    for p in pins:
        p.value(1)
    _emit('OK stopped')

_emit('READY')
try:
    while True:
        line = sys.stdin.readline()
        if not line:
            continue
        parts = line.split()
        if not parts:
            continue
        cmd, args = parts[0], parts[1:]
        try:
            if cmd == 'out':
                g = int(args[0])
                p = _out(g, int(args[1]), int(args[2]) if len(args) > 2 else 1)
                time.sleep_us(50)
                _emit('OK %d' % p.value())
            elif cmd == 'in':
                g = int(args[0])
                _pins[g] = Pin(g, Pin.IN, _PULLS[args[1]])
                _emit('OK')
            elif cmd == 'read':
                g = int(args[0])
                p = _pins.get(g)
                if p is None:
                    p = _pins[g] = Pin(g, Pin.IN, None)
                _emit('VAL %d %d' % (g, p.value()))
            elif cmd == 'readall':
                vals = []
                for g in DATA:
                    p = _pins.get(g)
                    if p is None:
                        p = _pins[g] = Pin(g, Pin.IN, None)
                    vals.append(str(p.value()))
                _emit('VALS ' + ' '.join(vals))
            elif cmd == 'txid':
                _txid(args)
            elif cmd == 'creset':
                # Demo board v3 only: CRESET_B of the iCE40 breakout is RP2350
                # GPIO1; low holds the FPGA unconfigured with every pin high-Z.
                Pin(1, Pin.OUT, value=int(args[0]))
                _emit('OK')
            elif cmd == 'release':
                _release_all()
                _emit('OK')
            elif cmd == 'sdk':
                _sdk(args)
            elif cmd == 'ping':
                _emit('PONG')
            elif cmd == 'quit':
                _emit('BYE')
                break
            else:
                _emit('ERR unknown command %s' % cmd)
        except Exception as e:
            _emit('ERR %s: %r' % (cmd, e))
finally:
    _release_all()
"""


def build_firmware(controller):
    table = CONTROLLERS[controller]
    data = table["ui_in"] + table["uio"] + table["uo_out"]
    return FIRMWARE.replace("__DATA__", repr(data))


class ProtocolError(Exception):
    """The RP2 answered with ERR, went silent, or left the command loop."""


class Rp2Link:
    """Speak the TTW command protocol over an already-opened file descriptor.

    The descriptor is normally the raw serial port after :func:`start_firmware`;
    tests pass one end of a socketpair driven by a fake board.
    """

    RAW_REPL_BANNER = b"raw REPL; CTRL-B to exit"

    def __init__(self, fd, timeout=5.0, log=None):
        self.fd = fd
        self.timeout = timeout
        self.log = log or (lambda _msg: None)
        self._buf = b""
        self.warnings = []

    # -- byte level -------------------------------------------------------------

    def discard_input(self):
        self._buf = b""
        while True:
            r, _, _ = select.select([self.fd], [], [], 0.05)
            if self.fd not in r:
                return
            try:
                if not os.read(self.fd, 4096):
                    return
            except OSError:
                return

    def write(self, data):
        if isinstance(data, str):
            data = data.encode()
        while data:
            n = os.write(self.fd, data)
            data = data[n:]

    def _fill(self, deadline):
        """Read more input before *deadline*; return False on timeout/EOF."""
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        r, _, _ = select.select([self.fd], [], [], min(remaining, 0.2))
        if self.fd not in r:
            return True
        try:
            data = os.read(self.fd, 4096)
        except OSError:
            return False
        if not data:
            return False
        self._buf += data
        return True

    def read_line(self, timeout=None):
        """Return the next ``\\n``-terminated line (without the newline) or None."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while b"\n" not in self._buf:
            if not self._fill(deadline):
                return None
        line, self._buf = self._buf.split(b"\n", 1)
        return line.rstrip(b"\r")

    def wait_for(self, marker, timeout=None):
        """Consume input until *marker* (bytes) has been seen; return the text before it."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while marker not in self._buf:
            if not self._fill(deadline):
                return None
        before, self._buf = self._buf.split(marker, 1)
        return before

    # -- protocol level ---------------------------------------------------------

    def expect(self, timeout=None):
        """Return the fields of the next ``TTW`` reply, collecting WARN lines."""
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ProtocolError("timeout waiting for the RP2")
            line = self.read_line(remaining)
            if line is None:
                raise ProtocolError("timeout waiting for the RP2")
            text = line.decode("utf-8", errors="replace")
            if b"\x04" in line or text.startswith("Traceback"):
                # The firmware left its command loop (exception or Ctrl-D).
                rest = self.read_line(0.5) or b""
                raise ProtocolError(f"RP2 firmware exited: {text} {rest.decode('utf-8', 'replace')}".strip())
            if not text.startswith("TTW "):
                self.log(f"  rp2: {text}")
                continue
            fields = text[4:].split()
            if fields and fields[0] == "WARN":
                self.warnings.append(" ".join(fields[1:]))
                self.log(f"  rp2 warning: {' '.join(fields[1:])}")
                continue
            return fields

    def cmd(self, text, timeout=None):
        """Send one command line; return the reply fields after ``TTW``.

        Raises :class:`ProtocolError` on an ``ERR`` reply, a timeout, or a
        firmware exit.
        """
        self.write(text + "\n")
        fields = self.expect(timeout)
        if not fields or fields[0] == "ERR":
            raise ProtocolError(f"{text!r} -> {' '.join(fields[1:]) if fields else '(empty reply)'}")
        return fields


def open_raw_serial(port):
    """Open a serial port in raw mode at 115200 baud using termios (no pyserial)."""
    fd = os.open(port, os.O_RDWR | os.O_NOCTTY)
    tty.setraw(fd)
    attrs = termios.tcgetattr(fd)
    baud = termios.B115200
    if hasattr(termios, "cfsetispeed"):
        termios.cfsetispeed(attrs, baud)
        termios.cfsetospeed(attrs, baud)
    else:
        attrs[4] = baud
        attrs[5] = baud
    attrs[6][termios.VMIN] = 0
    attrs[6][termios.VTIME] = 1
    termios.tcsetattr(fd, termios.TCSANOW, attrs)
    return fd


def start_firmware(link, firmware):
    """Enter the raw REPL on *link* and start the command server."""
    # Interrupt anything running (twice, like mpremote), then Ctrl-A.
    link.write(b"\r\x03\x03")
    time.sleep(0.3)
    link.discard_input()
    link.write(b"\r\x01")
    if link.wait_for(Rp2Link.RAW_REPL_BANNER, timeout=3.0) is None:
        raise ProtocolError("no raw REPL banner; is this a MicroPython board and is the port free?")
    link.wait_for(b">", timeout=1.0)
    # Feed the script in small chunks; the classic raw REPL has no flow control.
    code = firmware.encode()
    for i in range(0, len(code), 256):
        link.write(code[i : i + 256])
        time.sleep(0.01)
    link.write(b"\x04")
    # The raw REPL acknowledges compilation with "OK" before the script's output.
    if link.wait_for(b"OK", timeout=5.0) is None:
        raise ProtocolError("raw REPL did not accept the firmware")
    fields = link.expect(timeout=10.0)
    if fields[:1] != ["READY"]:
        raise ProtocolError(f"unexpected first reply from the RP2: {fields}")


def stop_firmware(link):
    """Leave the command loop and return the board to the friendly REPL.

    The firmware releases every pin on its way out (``finally``), also when
    it is interrupted with Ctrl-C because the protocol got stuck.
    """
    try:
        link.cmd("quit", timeout=3.0)
    except ProtocolError as e:
        link.log(f"  rp2: quit failed ({e}); interrupting")
        link.write(b"\x03")
    link.wait_for(b"\x04>", timeout=2.0)
    link.write(b"\r\x02")  # Ctrl-B: friendly REPL, as the fpgas-tt daemon expects
    time.sleep(0.2)


# -- Pi side: gpiod reader -------------------------------------------------------------

GPIO_CHIP_LABELS = {
    "pinctrl-rp1",  # RPi 5
    "pinctrl-bcm2711",  # RPi 4
    "pinctrl-bcm2835",  # RPi 3 / Zero
}

_GPIOD_V2 = hasattr(gpiod, "request_lines")


def detect_gpio_chip():
    """Find the gpiochip for the 40-pin header by label (node numbers vary by kernel)."""
    if gpiod is None:
        raise RuntimeError("python3-libgpiod (the `gpiod` module) is not installed on this Pi.")
    for chip_path in sorted(pathlib.Path("/dev").glob("gpiochip*")):
        try:
            chip = gpiod.Chip(str(chip_path))
            label = chip.get_info().label if _GPIOD_V2 else chip.label()
            chip.close()
            if label in GPIO_CHIP_LABELS:
                return str(chip_path)
        except (OSError, PermissionError):
            continue
    raise RuntimeError("Cannot find a GPIO chip with a known label. Is this a Raspberry Pi?")


class HatGpio:
    """Read a set of Pi GPIOs as inputs with chosen biases (gpiod v1.6+ or v2.x).

    ``set_bias("down")`` holds otherwise-floating ribbon lines low so they
    cannot couple onto a neighbour; ``set_bias("none")`` is needed while the
    RP2 probes with its own weak pulls; ``set_bias("down", pull_up={g})``
    pulls one line up for the reverse walk. Requesting a line also moves it
    away from any alternate function, e.g. the console UART on GPIO14/15.
    """

    CONSUMER = "tt-pmod-wiring"

    def __init__(self, gpios, chip_path=None):
        self.gpios = list(gpios)
        self.chip_path = chip_path or detect_gpio_chip()
        self.bias = None
        self._request = None  # v2
        self._chip = None  # v1
        self._lines = []  # v1: one bulk request per bias group

    def open(self, bias="down"):
        self.set_bias(bias)

    def set_bias(self, bias, pull_up=()):
        self.close()
        groups = {}
        for g in self.gpios:
            groups.setdefault("up" if g in pull_up else bias, []).append(g)
        if _GPIOD_V2:
            biases = {
                "down": gpiod.line.Bias.PULL_DOWN,
                "up": gpiod.line.Bias.PULL_UP,
                "none": gpiod.line.Bias.DISABLED,
            }
            config = {
                tuple(gs): gpiod.LineSettings(direction=gpiod.line.Direction.INPUT, bias=biases[b])
                for b, gs in groups.items()
            }
            self._request = gpiod.request_lines(self.chip_path, consumer=self.CONSUMER, config=config)
        else:
            flags = {
                "down": gpiod.LINE_REQ_FLAG_BIAS_PULL_DOWN,
                "up": gpiod.LINE_REQ_FLAG_BIAS_PULL_UP,
                "none": gpiod.LINE_REQ_FLAG_BIAS_DISABLE,
            }
            self._chip = gpiod.Chip(self.chip_path)
            for b, gs in groups.items():
                lines = self._chip.get_lines(gs)
                lines.request(consumer=self.CONSUMER, type=gpiod.LINE_REQ_DIR_IN, flags=flags[b])
                self._lines.append((gs, lines))
        self.bias = bias

    def read_all(self):
        """Return ``{gpio: 0/1}`` for every line."""
        if _GPIOD_V2:
            values = self._request.get_values(self.gpios)
            return {g: (1 if v == gpiod.line.Value.ACTIVE else 0) for g, v in zip(self.gpios, values)}
        result = {}
        for gs, lines in self._lines:
            for g, v in zip(gs, lines.get_values()):
                result[g] = int(v)
        return result

    def close(self):
        if self._request is not None:
            self._request.release()
            self._request = None
        for _gs, lines in self._lines:
            lines.release()
        self._lines = []
        if self._chip is not None:
            self._chip.close()
            self._chip = None


# -- Discovery ---------------------------------------------------------------------------


class UnstableReading(ProtocolError):
    """Repeated samples of the Pi GPIOs did not agree."""


class WiringProbe:
    """Drive TT signals from the RP2 and observe which Pi GPIOs follow.

    *rp2* needs ``cmd(text) -> fields``; *hat* needs ``read_all()`` and
    ``set_bias(bias, pull_up=())``. Both are duck-typed so the sequence can be
    exercised against a simulated board.
    """

    def __init__(self, rp2, hat, controller, samples=3, settle=0.002, log=print):
        self.rp2 = rp2
        self.hat = hat
        self.controller = controller
        self.table = CONTROLLERS[controller]
        self.data_gpios = self.table["ui_in"] + self.table["uio"] + self.table["uo_out"]
        self.samples = samples
        self.settle = settle
        self.log = log
        self.drive_failures = {}  # signal -> what the RP2 read back
        self.outputs = set()  # signals currently driven by the RP2

    # -- primitives --------------------------------------------------------------

    def sample(self):
        """Read the HAT lines *samples* times; they must all agree."""
        for _attempt in range(5):
            time.sleep(self.settle)
            readings = []
            for _ in range(self.samples):
                readings.append(self.hat.read_all())
                time.sleep(0.001)
            if all(r == readings[0] for r in readings):
                return readings[0]
        raise UnstableReading("Pi GPIO samples keep changing while nothing is toggling")

    def signals(self, group, bits=None):
        return [
            (signal_name(group, bit), gpio)
            for bit, gpio in enumerate(self.table[group])
            if bits is None or bit in bits
        ]

    def gpio_of(self, name):
        group, bit = name[:-1].split("[")
        return self.table[group][int(bit)]

    def name_of(self, gpio):
        for group in GROUPS:
            if gpio in self.table[group]:
                return signal_name(group, self.table[group].index(gpio))
        return f"GPIO{gpio}"

    def drive(self, name, value, strength=1):
        """Drive *name* and check the RP2 reads it back; return True if it took."""
        gpio = self.gpio_of(name)
        fields = self.rp2.cmd(f"out {gpio} {value} {strength}")
        self.outputs.add(name)
        got = int(fields[1]) if len(fields) > 1 else value
        if got != value:
            self.drive_failures[name] = got
            self.log(f"  {name}: RP2 drove {value} but reads back {got} (something else drives this net)")
            return False
        return True

    def read_rp2(self):
        """Read every RP2 data pin; return ``{signal: 0/1}``."""
        vals = self.rp2.cmd("readall")[1:]
        return {self.name_of(g): int(v) for g, v in zip(self.data_gpios, vals)}

    def release_all(self):
        self.rp2.cmd("release")
        self.outputs.clear()

    def hold_low(self, group, bits=None, strength=1):
        """Drive every chosen signal of *group* low and leave it that way.

        ``ui_in`` stays held low for the whole run: the factory test keys
        ``uo_out = uio_in`` / ``uio_oe = 0`` off ``ui_in[0]`` being low, and
        a floating ``ui_in`` would let the DIP switches decide.
        """
        for name, _gpio in self.signals(group, bits):
            self.drive(name, 0, strength)

    def set_inputs(self, group, bits=None, pull="none"):
        for name, gpio in self.signals(group, bits):
            self.rp2.cmd(f"in {gpio} {pull}")
            self.outputs.discard(name)

    # -- measurements --------------------------------------------------------------

    def probe_floating(self, group, bits=None):
        """Which bits of *group* follow the RP2's weak pulls (nothing else holds them).

        Returns ``{signal: True/False}``. The Pi's own bias is disabled during
        the probe so the RP2's ~50k pulls are the only weak thing on the net.
        """
        self.hat.set_bias("none")
        try:
            result = {}
            for name, gpio in self.signals(group, bits):
                self.rp2.cmd(f"in {gpio} up")
                time.sleep(self.settle)
                up = int(self.rp2.cmd(f"read {gpio}")[2])
                self.rp2.cmd(f"in {gpio} down")
                time.sleep(self.settle)
                down = int(self.rp2.cmd(f"read {gpio}")[2])
                self.rp2.cmd(f"in {gpio} none")
                self.outputs.discard(name)
                result[name] = up == 1 and down == 0
                held = "floating" if result[name] else ("held high" if up == down == 1 else "held low")
                self.log(f"  {name:<10} (RP2 GPIO{gpio:<2}) pull-up reads {up}, pull-down reads {down}: {held}")
            return result
        finally:
            self.hat.set_bias("down")

    def walk(self, group, bits=None, strength=1, partners=None):
        """Walk a 1 across *group*; return ``({signal: set(pi_gpio)}, {signal: [rp2 signals]})``.

        Every chosen signal is an output held low except the one under test,
        which is taken high then low; a Pi GPIO that reads 1 in the high step
        and 0 in the low step belongs to that signal. The second map lists
        every RP2 *input* pin that followed the signal on the board side; the
        caller decides which of those are legitimate. *partners* maps a
        signal to RP2-driven signals known to share its HAT line; any of them
        currently held low is released to input for the signal's step so two
        RP2 outputs never fight through the HAT. The chosen signals are left
        as outputs held low.
        """
        chosen = self.signals(group, bits)
        partners = partners or {}
        for name, _gpio in chosen:
            self.drive(name, 0, strength)
        baseline = self.sample()
        stuck = sorted(g for g, v in baseline.items() if v)
        if stuck:
            self.log(f"  note: with all {group} low these Pi GPIOs read high: {describe_gpios(stuck)}")
        observed = {}
        follows = {}
        for name, _gpio in chosen:
            released = [p for p in partners.get(name, ()) if p in self.outputs]
            for p in released:
                self.rp2.cmd(f"in {self.gpio_of(p)} none")
                self.outputs.discard(p)
            if not self.drive(name, 1, strength):
                self.drive(name, 0, strength)
                observed[name] = set()
            else:
                high = self.sample()
                rp2_high = self.read_rp2()
                self.drive(name, 0, strength)
                low = self.sample()
                rp2_low = self.read_rp2()
                observed[name] = {g for g in high if high[g] == 1 and low[g] == 0}
                followers = [o for o in rp2_high if o != name and rp2_high[o] == 1 and rp2_low[o] == 0]
                if followers:
                    follows[name] = followers
                self.log(
                    f"  {name:<10} (RP2 GPIO{self.gpio_of(name):<2}) -> "
                    f"{describe_gpios(sorted(observed[name])) or '(nothing)'}"
                    + (f"; RP2 pins following: {', '.join(followers)}" if followers else "")
                )
            for p in released:
                self.drive(p, 0, strength)
        return observed, follows

    def walk_twice(self, group, bits=None, strength=1, partners=None):
        """Run :meth:`walk` twice; both passes must agree."""
        first = self.walk(group, bits, strength, partners)
        second = self.walk(group, bits, strength, partners)
        if first != second:

            def differs(name):
                return first[0][name] != second[0][name] or first[1].get(name) != second[1].get(name)

            diff = sorted(name for name in first[0] if differs(name))
            raise UnstableReading(f"the two {group} passes disagree on {', '.join(diff)} (intermittent contact?)")
        return first

    def reverse_walk(self, names):
        """Attribute direct connections from the Pi side without driving anything.

        The Pi pulls one HAT line up and the rest down while the RP2 reads
        the pins in *names* as inputs with no pull. Returns
        ``({signal: pi_gpio}, held)`` where *held* lists the Pi lines that
        did not follow their pull (driven by the chip, or with a fixed
        pull-up). Lines in *held* and the shared JA/JB lines cannot be
        attributed this way.
        """
        for name in names:
            self.rp2.cmd(f"in {self.gpio_of(name)} none")
        self.hat.set_bias("down")
        time.sleep(self.settle)
        base_pi = self.sample()
        base_rp2 = self.read_rp2()
        held = sorted(g for g, v in base_pi.items() if v)
        attributed = {}
        try:
            for pi_gpio in ALL_HAT_GPIOS:
                if pi_gpio in held:
                    continue
                self.hat.set_bias("down", pull_up={pi_gpio})
                pi_now = self.sample()
                if not pi_now.get(pi_gpio):
                    held.append(pi_gpio)
                    continue
                rp2_now = self.read_rp2()
                for name in names:
                    if rp2_now[name] == 1 and base_rp2[name] == 0:
                        attributed.setdefault(name, set()).add(pi_gpio)
        finally:
            self.hat.set_bias("down")
        self.hat.set_bias("up")
        time.sleep(self.settle)
        held_low = sorted(g for g, v in self.hat.read_all().items() if not v)
        self.hat.set_bias("down")
        for name in sorted(attributed):
            self.log(f"  {name:<10} <- {describe_gpios(sorted(attributed[name]))}")
        if held:
            self.log(f"  Pi lines not following the Pi's pull-down (driven or pulled up): "
                     f"{describe_gpios(sorted(held))}")
        if held_low:
            self.log(f"  Pi lines not following the Pi's pull-up (driven low): {describe_gpios(held_low)}")
        return attributed, sorted(set(held) | set(held_low))

    def confirm_factory_test(self, uio_floating):
        """Prove ``uo_out = uio_in`` and ``cnt == 0`` on-board before trusting the loopback.

        Drives patterns on the *uio_floating* bits (already known to be
        undriven) and reads the RP2's own ``uo_out`` pins; then raises
        ``ui_in[0]`` and checks ``uo_out`` (the counter) and ``uio`` read 0.
        Returns None on success, else the reason.
        """
        bits = [int(n[:-1].split("[")[1]) for n in uio_floating]
        if len(bits) < 2:
            return f"only {len(bits)} uio bits float, cannot confirm the loopback"
        for pattern in (0x5A, 0xA5, 0x00):
            for bit in bits:
                if not self.drive(signal_name("uio", bit), (pattern >> bit) & 1):
                    self.set_inputs("uio")
                    return f"uio[{bit}] could not be driven"
            time.sleep(self.settle)
            rp2 = self.read_rp2()
            for bit in bits:
                want = (pattern >> bit) & 1
                got = rp2[signal_name("uo_out", bit)]
                if got != want:
                    self.set_inputs("uio")
                    return f"uo_out[{bit}] reads {got} for uio[{bit}]={want}: not uo_out = uio_in"
        self.set_inputs("uio")
        # Counter check: ui_in[0]=1 puts cnt on uo_out and uio.
        self.drive("ui_in[0]", 1)
        time.sleep(self.settle)
        rp2 = self.read_rp2()
        self.drive("ui_in[0]", 0)
        nonzero = [n for n, v in rp2.items() if v and (n.startswith("uo_out") or n.startswith("uio"))]
        if nonzero:
            return f"counter not zero after reset ({', '.join(nonzero)} read 1 with ui_in[0]=1)"
        return None

    def latch_test(self, bits, strength=3):
        """For JA/JB-shorted bits: is the loop through *both* ribbons closed?

        With ``uo_out[k] = uio_in[k]`` and JA and JB tied on the HAT, the
        chip's output feeds its own input through the two ribbon wires. Drive
        ``uio[k]`` high, release it to a pull-down, read: 1 means the loop
        holds (both wires present), 0 means one of them is open.
        """
        result = {}
        for bit in bits:
            name = signal_name("uio", bit)
            gpio = self.gpio_of(name)
            if not self.drive(name, 1, strength):
                self.drive(name, 0, strength)
                result[name] = False
                continue
            time.sleep(self.settle)
            self.rp2.cmd(f"in {gpio} down")
            time.sleep(self.settle)
            latched = int(self.rp2.cmd(f"read {gpio}")[2]) == 1
            # Break the latch again before moving on.
            self.drive(name, 0, strength)
            result[name] = latched
            self.log(f"  {name:<10} latch through JA/JB: {'closed' if latched else 'OPEN (one ribbon wire missing)'}")
        return result


# -- Pin-id mode: the RP2 transmits each signal's name, like the FPGA design ------------


def pin_id_label(name):
    """The label a signal transmits: ui_in[k] -> UIk, uio[k] -> IOk (2-4 chars, as the decoder expects)."""
    return ("UI" if name.startswith("ui_in") else "IO") + str(signal_bit(name))


def load_pin_id_module(script_dir):
    """Import identify_pmod_pins.py (the bit-bang decoder) from next to this script or the repo."""
    import importlib.util

    for candidate in (
        script_dir / "identify_pmod_pins.py",
        script_dir.parent.parent / "pmod-pin-id" / "host" / "identify_pmod_pins.py",
    ):
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("identify_pmod_pins", candidate)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod
    return None


def expected_labels(cabling, asic_loopback, transmitting):
    """``{pi_gpio: label}`` for one pin-id round given who transmits what."""
    lines = profile_lines(cabling)
    expected = {}
    for name, label in transmitting.items():
        expected[lines[name]] = label
    if asic_loopback:
        for name, label in transmitting.items():
            for j in connected_uio(cabling, name):
                expected[lines[signal_name("uo_out", j)]] = label
    return expected


def evaluate_pin_id(decoded, expected, ignore=()):
    """Compare one round's decoded labels with the expected ones; return ``(ok, rows)``."""
    rows = []
    ok = True
    for gpio in ALL_HAT_GPIOS:
        got = decoded.get(gpio)
        want = expected.get(gpio)
        if want is None:
            if got is None or gpio in ignore:
                status = "idle"
            else:
                status = "unexpected"
                ok = False
        elif got == want:
            status = "ok"
        elif got is None:
            status = "open"
            ok = False
        elif got.startswith("?"):
            status = "garbled"
            ok = False
        else:
            status = "wrong"
            ok = False
        rows.append({"gpio": gpio, "expected": want, "decoded": got, "status": status})
    return ok, rows


def run_pin_id_round(rp2, probe, scanner, transmitting, partners, log):
    """Have the RP2 transmit *transmitting* (``{signal: label}``) while *scanner* decodes every HAT line."""
    released = []
    for name in transmitting:
        for p in partners.get(name, ()):
            if p in probe.outputs:
                rp2.cmd(f"in {probe.gpio_of(p)} none")
                probe.outputs.discard(p)
                released.append(p)
    # "txid" answers OK once it is transmitting; any later line stops it and
    # is answered with a second OK.
    rp2.cmd("txid " + " ".join(f"{probe.gpio_of(n)}={label}" for n, label in transmitting.items()))
    try:
        decoded = scanner()
    finally:
        rp2.cmd("stop", timeout=10)
    for name in transmitting:
        probe.drive(name, 0)
    for p in released:
        probe.drive(p, 0)
    for gpio in ALL_HAT_GPIOS:
        got = decoded.get(gpio)
        if got:
            log(f"  GPIO{gpio:<2} ({HAT_GPIO_LABELS[gpio]:<8}) <- {got}")
    return decoded


def make_pin_id_scanner(pinid, attempts=5):
    """A scanner over all HAT lines using identify_pmod_pins' GpioReader/identify_pin."""

    def scan():
        chip = pinid.detect_gpio_chip()
        decoded = {}
        for gpio in ALL_HAT_GPIOS:
            reader = pinid.GpioReader(gpio, chip)
            try:
                reader.open()
                decoded[gpio] = pinid.identify_pin(reader, attempts=attempts)
            finally:
                reader.close()
        return decoded

    return scan


def format_pin_id_table(rounds):
    """Per Pi line, the label decoded in each round."""
    names = list(rounds)
    head = "| RPi GPIO | HAT      | " + " | ".join(f"{n} round" for n in names) + " |"
    lines = [head, "|" + "-" * (len(head) - 2) + "|"]
    for gpio in ALL_HAT_GPIOS:
        cells = [pin_id_display(rounds[n]["decoded"].get(gpio)) for n in names]
        lines.append(f"| GPIO{gpio:<4} | {HAT_GPIO_LABELS[gpio]:<8} | " + " | ".join(f"{c:<14}" for c in cells) + " |")
    return "\n".join(lines)


def pin_id_display(label):
    """A decoded label for printing: garbage bytes are not shown verbatim."""
    if label is None:
        return "—"
    if label.startswith("?"):
        return "(garbled)"
    return label


def describe_gpios(gpios):
    return ", ".join(f"GPIO{g} ({HAT_GPIO_LABELS.get(g, '?')})" for g in gpios)


# -- Verdict -----------------------------------------------------------------------------


def classify(expected, observed):
    """Compare one signal's expected and observed Pi GPIO sets."""
    if observed == expected:
        return "ok"
    if not observed:
        return "open"
    missing = expected - observed
    extra = observed - expected
    if missing and extra:
        return "miswired"
    if extra:
        return "short"
    return "partial"


def evaluate(observed, expected, tested, required, direct=None, reverse=None, follows=None,
             drive_failures=None, latch=None):
    """Build the per-signal verdict rows.

    *observed*: ``{signal: set}`` from the forward walk; *expected*:
    ``{signal: set}`` for every signal; *tested*: signals that were walked;
    *required*: signals that must be ``ok`` for a PASS. Optional cross-checks:
    *direct*/*reverse* (expected and reverse-walk attribution of each
    signal's own line), *follows* (RP2 pins that followed a signal on the
    board side: a short), *drive_failures* (RP2 could not impose its level:
    contention), *latch* (JA/JB loop check for the shorted bits). Returns
    ``(all_ok, rows, shorts)`` where *shorts* maps a Pi GPIO seen for more
    than one signal to those signals.
    """
    direct = direct or {}
    reverse = reverse or {}
    follows = follows or {}
    drive_failures = drive_failures or {}
    latch = latch or {}
    rows = []
    all_ok = True
    for name, exp in expected.items():
        detail = ""
        if name in drive_failures:
            status = "contention"
            detail = f"RP2 could not drive it (read back {drive_failures[name]})"
        elif name in tested:
            status = classify(exp, observed.get(name, set()))
            if status == "ok" and name in reverse and name in direct and direct[name] not in reverse[name]:
                status = "miswired"
                detail = f"its own line is {describe_gpios(sorted(reverse[name]))}, not the expected direct one"
            if status == "ok" and name in follows:
                status = "short"
                detail = f"RP2 pins {', '.join(follows[name])} follow it on the board side"
            if status == "ok" and latch.get(name) is False:
                status = "partial"
                detail = "JA/JB loop open: one of the two ribbon wires is missing"
        else:
            status = "untested"
        got = sorted(observed.get(name, set())) if name in tested else []
        row = {
            "signal": name,
            "expected": sorted(exp),
            "observed": got,
            "status": status,
            "required": name in required,
            "detail": detail,
        }
        if name in required and status != "ok":
            all_ok = False
        rows.append(row)
    seen = {}
    for name in tested:
        for g in observed.get(name, ()):
            seen.setdefault(g, []).append(name)
    shorts = {g: names for g, names in seen.items() if len(names) > 1}
    return all_ok, rows, shorts


def format_rows(rows):
    lines = [
        "| Signal     | Expected Pi GPIO        | Observed Pi GPIO        | Status     |",
        "|------------|-------------------------|-------------------------|------------|",
    ]
    for r in rows:
        exp = ", ".join(f"{g} ({HAT_GPIO_LABELS.get(g, '?')})" for g in r["expected"])
        got = ", ".join(f"{g} ({HAT_GPIO_LABELS.get(g, '?')})" for g in r["observed"])
        status = r["status"] if r["required"] or r["status"] == "ok" else f"{r['status']} (not required)"
        lines.append(f"| {r['signal']:<10} | {exp:<23} | {got:<23} | {status:<10} |")
        if r.get("detail"):
            lines.append(f"|            | {r['detail']:<71} |")
    return "\n".join(lines)


def format_docs_table(observed, controller, cabling, asic_loopback):
    """The measured map in the docs/hardware/tt-fpga-pin-mapping.md format."""
    table = CONTROLLERS[controller]
    lines = profile_lines(cabling)
    out = []
    for group in GROUPS:
        out.append(f"### {group}")
        out.append("")
        out.append(f"| Bit       | {controller.upper()} GPIO | PMOD HAT Pin | RPi GPIO | Verified |")
        out.append("| --------- | ----------- | ------------ | -------- | -------- |")
        for bit in range(8):
            name = signal_name(group, bit)
            rp2_gpio = table[group][bit]
            if group == "uo_out":
                # uo_out is only reachable through the chip: with the factory
                # test, uo_out[k] follows uio[k]'s net, so it is the Pi GPIO
                # observed for uio[k] beyond uio[k]'s own line (or that line
                # itself where the two share one).
                via = signal_name("uio", bit)
                seen = set(observed.get(via, set()))
                own = {lines[via]}
                pins = seen if lines[via] == lines[name] else seen - own
                verified = f"factory-test loopback via {via}" if asic_loopback and via in observed else "not tested"
                if not asic_loopback:
                    pins = set()
            else:
                pins = set(observed.get(name, set()))
                verified = "wiring test" if name in observed else "not tested"
            if pins:
                hat = ", ".join(HAT_GPIO_LABELS.get(g, "?") for g in sorted(pins))
                rpi = ", ".join(str(g) for g in sorted(pins))
            else:
                hat, rpi = "—", "—"
            out.append(f"| {name:<9} | {rp2_gpio:<11} | {hat:<12} | {rpi:<8} | {verified} |")
        out.append("")
    return "\n".join(out)


# -- Pi housekeeping -----------------------------------------------------------------------


def _sudo(cmd):
    return cmd if os.geteuid() == 0 else ["sudo", "-n", *cmd]


def run_quiet(cmd, check=False):
    result = subprocess.run(_sudo(cmd), capture_output=True, text=True)
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
    return result


_PINCTRL_ALT = re.compile(r"\b(?:alt=|a)(\d)\b")


class PiEnvironment:
    """Take over the serial port and the HAT GPIOs for the test; undo it after.

    * ``fpgas-tt`` owns ``/dev/ttboard`` on every deployed TT host; stop it
      and start it again afterwards (the board is off the public site while
      stopped, so never leave it stopped). A systemd timer restarts it in ten
      minutes regardless, in case this process is killed mid-run.
    * The kernel console is on GPIO14/15 = HAT JC2/JC3. Driving those from the
      RP2 has triggered SysRq (reboot/crash) on other hosts, so SysRq is
      disabled for the duration, the getty is stopped, and the pins' UART
      function is put back afterwards where ``pinctrl``/``raspi-gpio`` exist.
    * SPI0 kernel modules claim GPIO7-11 (JA1/JB1 and the shared JA/JB 2-4).
    """

    CONSOLE_GPIOS = (14, 15)
    SPI_MODULES = ("spidev", "spi_bcm2835")
    RESTART_UNIT = "tt-pmod-wiring-restart"

    def __init__(self, manage_daemon=True, unload_modules=True, log=print):
        self.manage_daemon = manage_daemon
        self.unload_modules = unload_modules
        self.log = log
        self.daemon_was_active = False
        self.sysrq_before = None
        self.console_alt = {}
        self.gettys = []

    def _pin_tool(self):
        for tool in ("pinctrl", "raspi-gpio"):
            if run_quiet(["which", tool]).returncode == 0:
                return tool
        return None

    def enter(self):
        if os.geteuid() != 0 and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0:
            raise RuntimeError("root or passwordless sudo is required (systemctl, sysctl, rmmod)")
        if self.manage_daemon:
            active = run_quiet(["systemctl", "is-active", "fpgas-tt"]).stdout.strip()
            self.daemon_was_active = active == "active"
            if self.daemon_was_active:
                self.log("Stopping fpgas-tt (it owns the serial port; restarted afterwards)")
                # A dead-man restart in case this process is killed mid-run;
                # clear any stale one from an earlier aborted run first.
                run_quiet(["systemctl", "stop", f"{self.RESTART_UNIT}.timer"])
                armed = run_quiet(
                    ["systemd-run", "--quiet", "--on-active=600", f"--unit={self.RESTART_UNIT}",
                     "systemctl", "start", "fpgas-tt"]
                )
                if armed.returncode != 0:
                    self.log(f"WARNING: could not arm the fpgas-tt restart timer: {armed.stderr.strip()}")
                run_quiet(["systemctl", "stop", "fpgas-tt"], check=True)
                time.sleep(0.5)
        try:
            self.sysrq_before = pathlib.Path("/proc/sys/kernel/sysrq").read_text().strip()
        except OSError:
            self.sysrq_before = None
        if self.sysrq_before not in (None, "0"):
            self.log(f"Disabling SysRq for the test (was {self.sysrq_before})")
            run_quiet(["sysctl", "-q", "-w", "kernel.sysrq=0"])
        listed = run_quiet(
            ["systemctl", "list-units", "--plain", "--no-legend", "--state=active", "serial-getty@*"]
        ).stdout
        self.gettys = [line.split()[0] for line in listed.splitlines() if line.strip()]
        if self.gettys:
            self.log(f"Stopping {', '.join(self.gettys)} (restarted afterwards)")
            run_quiet(["systemctl", "stop", *self.gettys])
        tool = self._pin_tool()
        if tool:
            for g in self.CONSOLE_GPIOS:
                out = run_quiet([tool, "get", str(g)]).stdout
                m = _PINCTRL_ALT.search(out)
                if m:
                    self.console_alt[g] = m.group(1)
        if self.unload_modules:
            unloaded = [m for m in self.SPI_MODULES if run_quiet(["rmmod", m]).returncode == 0]
            if unloaded:
                self.log(f"Unloaded kernel modules: {', '.join(unloaded)}")

    def leave(self):
        tool = self._pin_tool()
        if tool and self.console_alt:
            for g, alt in self.console_alt.items():
                run_quiet([tool, "set", str(g), f"a{alt}"])
            self.log(f"Restored UART function on GPIO{'/'.join(str(g) for g in self.console_alt)}")
        if self.sysrq_before not in (None, "0"):
            run_quiet(["sysctl", "-q", "-w", f"kernel.sysrq={self.sysrq_before}"])
        if self.gettys:
            run_quiet(["systemctl", "start", *self.gettys])
        if self.manage_daemon and self.daemon_was_active:
            self.log("Restarting fpgas-tt")
            result = run_quiet(["systemctl", "start", "fpgas-tt"])
            if result.returncode != 0:
                self.log(f"WARNING: could not restart fpgas-tt: {result.stderr.strip()}")
            run_quiet(["systemctl", "stop", f"{self.RESTART_UNIT}.timer"])


# -- Test sequence ---------------------------------------------------------------------------


def run_wiring_test(rp2, hat, args, log=print, pin_scanner=None):
    """The whole measurement on already-opened *rp2* and *hat*. Returns a result dict.

    *pin_scanner* (pin-id mode) decodes every HAT line and returns
    ``{pi_gpio: label|None}``; it is called while the RP2 transmits.
    """
    probe = WiringProbe(rp2, hat, args.controller, samples=args.samples, log=log)
    want_loopback = args.asic_project != "none"
    asic_loopback = False
    notes = []

    rp2.cmd("ping")
    probe.release_all()
    if args.fpga_reset:
        # TT FPGA board: whatever bitstream is loaded may be driving the
        # lines; hold the iCE40 in reset (all pins high-Z) for the test.
        rp2.cmd("creset 0")
        notes.append("iCE40 held in reset for the test (CRESET_B low); it reloads from flash afterwards")
        log("FPGA held in reset (CRESET_B low)")

    if args.sdk:
        try:
            fields = rp2.cmd("sdk init", timeout=15)
            log(f"SDK: {' '.join(fields[1:])}")
        except ProtocolError as e:
            notes.append(f"SDK init failed: {e}")
            log(f"WARNING: {notes[-1]}")
    project_selected = False
    if want_loopback and args.sdk:
        try:
            fields = rp2.cmd(f"sdk project {args.asic_project}", timeout=30)
            log(f"ASIC project: {' '.join(fields[1:])}")
            rp2.cmd("sdk reset", timeout=10)
            project_selected = True
        except ProtocolError as e:
            notes.append(f"could not select {args.asic_project}: {e}")
            log(f"WARNING: {notes[-1]}")
    elif want_loopback:
        notes.append("ASIC loopback requested but --no-sdk given")

    # ui_in: anything a DIP switch or the Pi's console still holds is left alone.
    # ui_in[0] is probed first and then held low: the factory test's uio_oe
    # follows it, and a floating ui_in[0] would let the chip drive uio, which
    # shares HAT lines with ui_in[1:3] on the asic cabling.
    log("\n== ui_in: checking nothing else holds the lines ==")
    ui_floating = probe.probe_floating("ui_in", bits={0})
    if ui_floating["ui_in[0]"]:
        probe.hold_low("ui_in", {0})
    ui_floating.update(probe.probe_floating("ui_in", bits=set(range(1, 8))))
    ui_bits = {b for b, (n, _g) in enumerate(probe.signals("ui_in")) if ui_floating[n]}
    for name, ok in ui_floating.items():
        if ok:
            continue
        # ui_in is an input of the chip, so what holds it is a DIP switch (a
        # resistor to a rail, which the RP2 out-drives every day in
        # ASIC_RP_CONTROL mode), the console UART, or a wiring fault. Try to
        # impose both levels; if the RP2 wins, test the bit and say so.
        gpio = probe.gpio_of(name)
        wins = probe.drive(name, 1) and probe.drive(name, 0)
        probe.drive_failures.pop(name, None)
        rp2.cmd(f"in {gpio} none")
        probe.outputs.discard(name)
        if wins:
            ui_bits.add(signal_bit(name))
            notes.append(f"{name} is held weakly by something (DIP switch on?); the RP2 out-drives it, tested anyway")
        else:
            notes.append(f"{name} is held hard by something else (shorted to a rail? console UART?): not driven")
    if 0 not in ui_bits and project_selected:
        notes.append("ui_in[0] is held externally, so the factory-test loopback cannot be used")
        project_selected = False
    probe.hold_low("ui_in", ui_bits)  # ui_in stays low from here on

    # Reverse walk: Pi pulls, RP2 reads. ui_in[0] stays driven so the chip's
    # uio_oe cannot flip while its inputs float.
    log("\n== reverse walk: Pi pulls one line up, RP2 reads its inputs ==")
    reverse_names = [n for n, _g in probe.signals("ui_in", ui_bits - {0})] + [n for n, _g in probe.signals("uio")]
    reverse, held = probe.reverse_walk(reverse_names)
    probe.hold_low("ui_in", ui_bits)
    # RP2-driven signals the reverse walk found on one and the same Pi line.
    measured_partners = {}
    for a, pa in reverse.items():
        measured_partners[a] = [b for b, pb in reverse.items() if b != a and pb == pa]

    # Loopback confirmation, entirely on-board.
    uio_floating = {}
    if project_selected:
        log("\n== uio: probing which bits nothing else holds ==")
        uio_floating = probe.probe_floating("uio")
        candidates = [n for n, ok in uio_floating.items() if ok]
        log("\n== confirming tt_um_factory_test on-board (uo_out = uio_in, counter = 0) ==")
        reason = probe.confirm_factory_test(candidates)
        if reason is None:
            asic_loopback = True
            log("  confirmed")
        else:
            notes.append(f"factory test not confirmed: {reason}; uo_out loopback disabled")
            log(f"WARNING: {notes[-1]}")

    log("\n== ui_in: RP2 drives, Pi reads ==")
    observed, follows = probe.walk_twice("ui_in", ui_bits, partners=measured_partners)

    # Which cabling profile are we looking at?
    if args.cabling == "auto":
        cabling, score = choose_cabling(observed, reverse)
        log(f"\nCabling profile: {cabling} (score {score}/{len(observed) + len(reverse)})")
        if score < 8:
            notes.append(f"no known cabling profile fits well (best: {cabling}, score {score})")
    else:
        cabling = args.cabling
    partners = dict(measured_partners)
    for name, ps in shared_partners(cabling).items():
        partners[name] = sorted(set(partners.get(name, [])) | set(ps))

    if asic_loopback:
        # Confirmed uio_oe = 0: every uio bit is safe to drive, including the
        # ones sharing a line with the chip's uo_out, where the chip agrees
        # with the RP2 once it has propagated. Drive strongly for that hand-over.
        drivable = set(range(8))
        strength = 3
    else:
        if not uio_floating:
            log("\n== uio: probing which bits nothing else holds ==")
            uio_floating = probe.probe_floating("uio")
        drivable = {b for b, (n, _g) in enumerate(probe.signals("uio")) if uio_floating[n]}
        strength = 0  # unknown project: keep any surprise fight current-limited
        for name, ok in uio_floating.items():
            if ok:
                continue
            if args.fpga_reset:
                # No chip can be driving with the iCE40 in reset; what holds
                # the line is its weak configuration pull-up or a Pi pull-up.
                wins = probe.drive(name, 1) and probe.drive(name, 0)
                probe.drive_failures.pop(name, None)
                rp2.cmd(f"in {probe.gpio_of(name)} none")
                probe.outputs.discard(name)
                if wins:
                    drivable.add(signal_bit(name))
                    continue
                notes.append(f"{name} is held hard by something: not driven")
                continue
            notes.append(f"{name} is held (chip, a shared line, or a Pi pull-up): not driven")

    log("\n== uio: RP2 drives, Pi reads" + (" (uo_out follows through the chip)" if asic_loopback else "") + " ==")
    if drivable:
        uio_observed, uio_follows = probe.walk_twice("uio", drivable, strength, partners)
        observed.update(uio_observed)
        follows.update(uio_follows)
    latch = {}
    latch_targets = set(latch_bits(cabling)) & drivable
    if asic_loopback and latch_targets:
        log("\n== uio: latch test on the bits sharing a line with uo_out ==")
        latch = probe.latch_test(sorted(latch_targets))
    probe.set_inputs("uio")

    # Pin-id rounds: the RP2 transmits names, the Pi decodes them per line.
    pin_id = {}
    if pin_scanner is not None:
        ui_names = [n for n, _g in probe.signals("ui_in", ui_bits)]
        rounds = []
        if asic_loopback and "ui_in[0]" in ui_names:
            # The factory test's uio_oe follows ui_in[0]: while the other
            # ui_in bits transmit, ui_in[0] must stay low so the chip never
            # drives uio (which shares lines with ui_in on the asic cabling).
            # ui_in[0] transmits alone afterwards: the chip then drives uio
            # to its zero counter, and nothing else is driving those nets.
            others = {n: pin_id_label(n) for n in ui_names if n != "ui_in[0]"}
            if others:
                rounds.append(("ui_in", others))
            rounds.append(("ui_in[0]", {"ui_in[0]": pin_id_label("ui_in[0]")}))
        elif ui_names:
            rounds.append(("ui_in", {n: pin_id_label(n) for n in ui_names}))
        if drivable:
            rounds.append(("uio", {n: pin_id_label(n) for n, _g in probe.signals("uio", drivable)}))
        hat.close()  # the decoder requests lines one at a time
        for round_name, transmitting in rounds:
            log(f"\n== pin-id: RP2 transmits {round_name} names, Pi decodes every HAT line ==")
            decoded = run_pin_id_round(rp2, probe, pin_scanner, transmitting, partners, log)
            pin_id[round_name] = {"transmitting": transmitting, "decoded": decoded}
        probe.set_inputs("uio")
        probe.hold_low("ui_in", ui_bits)

    expected = expected_map(cabling, asic_loopback)
    direct = expected_direct(cabling)
    tested = set(observed)
    required = {signal_name("ui_in", b) for b in range(8)}
    if args.strict:
        required |= {signal_name("uio", b) for b in range(8)}
    else:
        required |= {signal_name("uio", b) for b in drivable}
    judged = observed
    if not asic_loopback:
        # An unknown project may loop ui_in or uio onto uo_out. Lines the
        # reverse walk found held (chip-driven or pulled up) are therefore
        # not evidence of a ribbon fault for RP2-driven rows; a ribbon short
        # to a chip-driven line shows up as contention on the RP2 side.
        judged = {}
        for name, pins in observed.items():
            ignore = (set(held) - {direct.get(name)}) & pins
            judged[name] = pins - ignore
            if ignore:
                notes.append(f"{name} also seen on {describe_gpios(sorted(ignore))}: chip-driven line, ignored")
    bad_follows = {}
    for name, followers in follows.items():
        unexpected = [f for f in followers if f not in expected_followers(cabling, asic_loopback, name)]
        if unexpected:
            bad_follows[name] = unexpected
    all_ok, rows, shorts = evaluate(
        judged, expected, tested, required,
        direct=direct, reverse=reverse, follows=bad_follows,
        drive_failures=probe.drive_failures, latch=latch,
    )
    if want_loopback and not asic_loopback and args.strict:
        all_ok = False
    pin_id_ok = True
    chip_lines = {profile_lines(cabling)[signal_name(g, b)] for g in ("uio", "uo_out") for b in range(8)}
    for round_name, data in pin_id.items():
        exp = expected_labels(cabling, asic_loopback, data["transmitting"])
        ignore = () if asic_loopback else held
        if round_name == "ui_in[0]":
            # The factory test toggles uio_oe and uo_out with ui_in[0], so the
            # chip's lines carry garbage in this round; only ui_in[0]'s own
            # line is judged.
            ignore = chip_lines
        ok, prows = evaluate_pin_id(data["decoded"], exp, ignore=ignore)
        data["expected"] = exp
        data["rows"] = prows
        data["ok"] = ok
        pin_id_ok = pin_id_ok and ok
    return {
        "controller": args.controller,
        "cabling": cabling,
        "asic_loopback": asic_loopback,
        "observed": {k: sorted(v) for k, v in observed.items()},
        "reverse": {k: sorted(v) for k, v in reverse.items()},
        "held": held,
        "latch": latch,
        "rows": rows,
        "shorts": {str(g): names for g, names in shorts.items()},
        "pin_id": pin_id,
        "pin_id_ok": pin_id_ok,
        "notes": notes + [f"rp2: {w}" for w in getattr(rp2, "warnings", [])],
        "pass": all_ok and pin_id_ok,
    }


def report(result, discover, log=print):
    log("")
    log(f"Cabling profile: {result['cabling']} "
        f"(ui_in <- HAT {CABLINGS[result['cabling']]['ui_in']}, uio <- {CABLINGS[result['cabling']]['uio']}, "
        f"uo_out <- {CABLINGS[result['cabling']]['uo_out']})")
    log("")
    observed = {k: set(v) for k, v in result["observed"].items()}
    log(format_docs_table(observed, result["controller"], result["cabling"], result["asic_loopback"]))
    if result.get("pin_id"):
        log("### Pin-id decode (label transmitted by the RP2, as received on each Pi line)")
        log("")
        log(format_pin_id_table(result["pin_id"]))
        log("")
    if result["held"]:
        log("Pi lines held by something (the chip's uo_out, or the Pi's I2C pull-ups on GPIO2/3):")
        log(f"  {describe_gpios(result['held'])}")
        log("")
    if result["shorts"]:
        log("Pi GPIOs that follow more than one signal (a shared HAT line, or a short between ribbon lines):")
        for g, names in result["shorts"].items():
            log(f"  GPIO{g} ({HAT_GPIO_LABELS.get(int(g), '?')}): {', '.join(names)}")
        log("")
    for note in result["notes"]:
        log(f"note: {note}")
    if discover:
        n = sum(1 for v in result["observed"].values() if v)
        log(f"\n{n} signals reached a Pi GPIO.")
        return
    log(f"\n== Wiring check: {result['cabling']} cabling ==\n")
    log(format_rows(result["rows"]))
    n_ok = sum(1 for r in result["rows"] if r["status"] == "ok")
    n_req = sum(1 for r in result["rows"] if r["required"])
    n_tested = sum(1 for r in result["rows"] if r["status"] != "untested")
    log(f"\n{n_ok}/{n_tested} tested signals match; {n_req} required.")
    for round_name, data in result.get("pin_id", {}).items():
        bad = [r for r in data["rows"] if r["status"] not in ("ok", "idle")]
        log(f"pin-id {round_name} round: {'ok' if data['ok'] else 'FAIL'}"
            + (": " + ", ".join(f"GPIO{r['gpio']} {r['status']} (expected {r['expected']}, "
                                f"got {pin_id_display(r['decoded'])})" for r in bad) if bad else ""))
    if not result["asic_loopback"]:
        log("uo_out was NOT tested (no ASIC loopback).")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", default=None, help="serial port (default: /dev/ttboard, else /dev/ttyACM0)")
    parser.add_argument("--controller", choices=sorted(CONTROLLERS), default="rp2040")
    parser.add_argument(
        "--cabling", choices=["auto", *sorted(CABLINGS)], default="auto",
        help="expected cabling profile, or auto to pick the best fit (default)",
    )
    parser.add_argument(
        "--method", choices=["walk", "pin-id", "both"], default="both",
        help="walk: RP2 walks a 1; pin-id: RP2 transmits each signal's name at 1200 baud (default: both)",
    )
    parser.add_argument("--discover", action="store_true", help="print the measured map only, no verdict")
    parser.add_argument(
        "--asic-project",
        default="tt_um_factory_test",
        help="shuttle project to select for the uo_out loopback, or 'none' (default: %(default)s)",
    )
    parser.add_argument("--no-sdk", dest="sdk", action="store_false", help="never import the ttboard SDK on the RP2")
    parser.add_argument(
        "--fpga-reset", dest="fpga_reset", action="store_true", default=None,
        help="hold the iCE40 of a TT FPGA board in reset during the test (default for --controller rp2350)",
    )
    parser.add_argument("--no-fpga-reset", dest="fpga_reset", action="store_false")
    parser.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        help="do not fail when the ASIC loopback is unavailable or uio bits are externally driven",
    )
    parser.add_argument("--no-daemon", dest="daemon", action="store_false", help="do not stop/start fpgas-tt")
    parser.add_argument("--no-unload", dest="unload", action="store_false", help="do not rmmod the SPI modules")
    parser.add_argument("--samples", type=int, default=3, help="agreeing samples per step (default 3)")
    parser.add_argument("--json", help="also write the result as JSON to this path")
    args = parser.parse_args(argv)
    # Without the ASIC loopback, uio bits the chip drives cannot be tested and
    # uo_out is never tested; only the ui_in rows and the drivable uio rows count.
    if args.asic_project == "none":
        args.strict = False
    if args.fpga_reset is None:
        args.fpga_reset = args.controller == "rp2350"
    if args.port is None:
        args.port = "/dev/ttboard" if os.path.exists("/dev/ttboard") else "/dev/ttyACM0"
    return args


def main(argv=None):
    args = parse_args(argv)
    print("=== TT PMOD wiring test ===")
    print(f"Port: {args.port}   Controller: {args.controller}   ASIC project: {args.asic_project}")
    env = PiEnvironment(manage_daemon=args.daemon, unload_modules=args.unload)
    pin_scanner = None
    if args.method in ("pin-id", "both"):
        pinid = load_pin_id_module(pathlib.Path(__file__).resolve().parent)
        if pinid is None:
            print("ERROR: identify_pmod_pins.py (the pin-id decoder) not found next to this script")
            print("RESULT: FAIL")
            return 1
        pin_scanner = make_pin_id_scanner(pinid)
    result = None
    link = None
    hat = None
    try:
        env.enter()
        # All 21 lines in one request: nothing is driven until every line,
        # the console UART's included, is a plain input.
        hat = HatGpio(ALL_HAT_GPIOS)
        hat.open("down")
        print(f"GPIO chip: {hat.chip_path}, {len(ALL_HAT_GPIOS)} HAT lines as inputs")
        fd = open_raw_serial(args.port)
        link = Rp2Link(fd, log=print)
        try:
            start_firmware(link, build_firmware(args.controller))
        except ProtocolError:
            # Do not leave the board in the raw REPL for the daemon to find.
            link.write(b"\r\x03\x02")
            raise
        print("RP2 command server running")
        try:
            result = run_wiring_test(link, hat, args, pin_scanner=pin_scanner)
        finally:
            if args.fpga_reset:
                try:
                    link.cmd("creset 1", timeout=5)
                except ProtocolError as e:
                    print(f"WARNING: could not release the FPGA reset: {e}")
            if args.sdk:
                try:
                    link.cmd("sdk restore", timeout=10)
                except ProtocolError as e:
                    print(f"WARNING: SDK restore failed: {e}")
            stop_firmware(link)
    except (ProtocolError, RuntimeError, OSError) as e:
        print(f"ERROR: {e}")
    finally:
        if link is not None:
            os.close(link.fd)
        if hat is not None:
            hat.close()
        env.leave()

    if result is None:
        print("RESULT: FAIL")
        return 1
    report(result, args.discover)
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(result, indent=2))
    ok = any(result["observed"].values()) if args.discover else result["pass"]
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
