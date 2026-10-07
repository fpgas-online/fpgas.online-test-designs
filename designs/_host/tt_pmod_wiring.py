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

The ``WIRING:`` line is the result, named by ribbon and Pmod pin; ``RESULT: PASS`` or ``RESULT: FAIL`` is the
last line. Exit 0: the wiring is right; 1: it is not, or readings were not steady; 2: the test could not be
made, or did not put the Pi or the board back (the boot check's `error`).
"""

import argparse
import contextlib
import json
import os
import pathlib
import select
import signal
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
PORTS = ("JA", "JB", "JC")

# -- Expected cabling: TT group -> HAT port --------------------------------------

CABLINGS = {
    # Measured on the TT FPGA hosts (docs/hardware/tt-fpga-pin-mapping.md).
    "fpga": {"ui_in": "JC", "uio": "JB", "uo_out": "JA"},
    # Measured on the TT ASIC hosts on 2026-09-04 (a TT06 board first): the
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
import gc, sys, time
from machine import Pin
DATA = __DATA__
_pins = {}
_tt = None
_saved_mode = None
_saved = None
_saved_apply = None
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
    # The SDK's own `tt`, which its main.py builds when the board starts. It is never imported or built here:
    # that needs more heap than the RP2040 has beside this server (MemoryError, 8 Oct 2026), and would be a
    # second board object on the same pins.
    global _tt
    if _tt is None:
        t = globals().get('tt')
        if t is None:
            raise RuntimeError('the SDK is not running on the board (no tt object): start it first')
        # The SDK's main.py logs to /boot.log until it has finished starting (it closes the file at its end): while
        # that is open, anything the SDK logs for us would be written to it. So not used then.
        lg = sys.modules.get('ttboard.log')
        if getattr(getattr(lg, 'Logger', None), 'OutFile', None) is not None:
            raise RuntimeError('the SDK is still logging to its boot.log (its start-up did not finish): not used')
        _tt = t
    return _tt

def _sdk(args):
    global _saved_mode, _saved, _saved_apply
    op = args[0]
    if op == 'restore':
        _release_all()
        if _tt is None or _saved is None:
            _emit('OK pins released; the SDK was not changed')
            return
    t = _find_tt()
    if op == 'init':
        # What the board is running, to put back from RAM afterwards (no reset): its mode, its project, its
        # project clock, and the SDK's own one-line description of all three, which restore must match.
        _saved_mode = t.mode
        _saved = (getattr(t.shuttle, 'enabled', None), t.auto_clocking_freq if t.is_auto_clocking else None,
                  repr(t))
        _clock_stop(t)
        _emit('OK mode=%s' % _saved_mode)
        _emit('WARN board was: %s' % _saved[2])
    elif op == 'project':
        name = args[1]
        sh = t.shuttle
        p = sh.get(name) if hasattr(sh, 'get') else getattr(sh, name)
        # enable() would apply the project's config.ini section (for the factory test: ui_in = 1 and a 10 Hz
        # clock), and the chip would then drive its counter onto uio[1:3], which the HAT joins to ui_in[1:3]:
        # turned off for our enable, back on for the restore's.
        _saved_apply = getattr(t, 'apply_configs', None)
        t.apply_configs = False
        p.enable()
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
        # Back as it was, from RAM: the mode (through SAFE, so the SDK re-owns its pins even when the setter would
        # be a no-op), the project (enabled again and reset), its clock. The SDK's description must then match.
        project, freq, was = _saved
        if _saved_apply is not None:
            t.apply_configs = _saved_apply
        try:
            from ttboard.mode import RPMode
            t.mode = RPMode.SAFE
        except Exception as e:
            _emit('WARN mode SAFE: %r' % e)
        t.mode = _saved_mode
        if project is not None:
            project.enable()
        _clock_stop(t)
        t.reset_project(True)
        time.sleep_ms(5)
        t.reset_project(False)
        if freq:
            t.clock_project_PWM(freq)
        now = repr(t)
        if now != was:
            _emit('ERR restore: the board was %s and is now %s' % (was, now))
        else:
            _emit('OK restored: %s' % now)
    else:
        _emit('ERR sdk: unknown op %s' % op)

def _txid(args):
    # Transmit each pin's label as 1200 baud 8N1 frames, like the FPGA
    # pin-id design, until a line arrives on stdin. All pins step together
    # once per bit period; setting them one after another costs a few
    # microseconds of constant skew per pin, well inside the 833 us bit.
    # The walks before it leave garbage: collected first, so the mem_free it reports is what the round holds.
    gc.collect()
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
    _emit('OK started mem_free=%d' % gc.mem_free())
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

gc.collect()
_emit('READY mem_free=%d' % gc.mem_free())
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
            elif cmd == 'group':
                # Drive several pins to one level at the same instant (RP2040 SIO, datasheet section 2.3.1:
                # GPIO_OUT_SET 0xd0000014, GPIO_OUT_CLR 0xd0000018, GPIO_OE_SET 0xd0000024): the level is set while
                # they are still inputs, then all their outputs are turned on in one write.
                import machine
                v, gs = int(args[0]), [int(a) for a in args[1:]]
                mask = 0
                for g in gs:
                    if not isinstance(_pins.get(g), Pin):
                        _pins[g] = Pin(g, Pin.IN, None)
                    mask |= 1 << g
                machine.mem32[0xd0000014 if v else 0xd0000018] = mask
                machine.mem32[0xd0000024] = mask
                time.sleep_us(50)
                _emit('VALS ' + ' '.join(str(Pin(g).value()) for g in gs))
            elif cmd == 'ungroup':
                # All their outputs off in one write (GPIO_OE_CLR 0xd0000028), then plain inputs.
                import machine
                gs = [int(a) for a in args]
                mask = 0
                for g in gs:
                    mask |= 1 << g
                machine.mem32[0xd0000028] = mask
                for g in gs:
                    _pins[g] = Pin(g, Pin.IN, None)
                _emit('OK')
            elif cmd == 'mem':
                gc.collect()
                _emit('VAL mem %d' % gc.mem_free())
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


# The least free heap the RP2's command server must find once it is loaded, beside the SDK's own objects. Measured
# in PR #179's live run 4 (8 Oct 2026, 06:08) on the TT07 board de641070db746f27 (RP2040, SDK 2.0.4), each figure
# after a collection: 69472 bytes free at load, 68832 before the walks, 52048 at the lowest (sending the 7 ui_in
# names), 68704 after. The largest drop from load is 17424 bytes; the floor is that plus about 9 kB of headroom.
# (Run 3's 8736 was taken with no collection, so it counted the walks' garbage.) A later measurement on another
# board, shuttle or SDK release moves it.
MIN_HEAP_FREE = 27000


def mem_free(fields):
    """The figure in a reply's ``mem_free=N`` (READY, txid's OK) or ``VAL mem N`` (mem); None if there is none."""
    for i, f in enumerate(fields or ()):
        if f.startswith("mem_free="):
            return int(f.split("=", 1)[1])
        if f == "mem" and i + 1 < len(fields):
            return int(fields[i + 1])
    return None


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

    def resync(self, timeout=5.0):
        """Bring replies back in step after a command was cut short: drop what has come, send ``ping`` and read up
        to its ``PONG``, so the next reply read is the next command's. Raises ProtocolError if no PONG comes."""
        self.discard_input()
        self.write("ping\n")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.expect(deadline - time.monotonic())[:1] == ["PONG"]:
                return
        raise ProtocolError("no PONG from the RP2 while bringing its replies back in step")

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
    return fields


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


# The one input held low through the walks: the factory test drives uio whenever it is high.
KEPT_LOW = "ui_in[0]"


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
        self.held_level = {}  # signal -> how probe_floating found it held: high, low, against the pulls
        self.uo_held = {}  # uo_out signal -> the level it read whatever its uio was set to (confirm_factory_test)
        self.held_low = []  # Pi lines the reverse walk found not following the Pi's pull-up: driven low
        self.outputs = set()  # signals currently driven by the RP2

    # -- primitives --------------------------------------------------------------

    def sample(self):
        """Read the HAT lines *samples* times; they must all agree, the first time (no retry: a line that flickers
        is a contact to look at, and is named)."""
        time.sleep(self.settle)
        readings = []
        for _ in range(self.samples):
            readings.append(self.hat.read_all())
            time.sleep(0.001)
        changing = sorted(g for g in readings[0] if any(r[g] != readings[0][g] for r in readings))
        if changing:
            raise UnstableReading(f"{hat_pins(changing)} changed between readings while nothing was switching")
        return readings[0]

    def signals(self, group, bits=None):
        return [
            (signal_name(group, bit), gpio) for bit, gpio in enumerate(self.table[group]) if bits is None or bit in bits
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
                self.held_level[name] = "high" if up == down == 1 else "low" if up == down == 0 else "against the pulls"
                held = "floating" if result[name] else f"held {self.held_level[name]}"
                self.log(f"  {name:<10} (RP2 GPIO{gpio:<2}) pull-up reads {up}, pull-down reads {down}: {held}")
            return result
        finally:
            self.hat.set_bias("down")

    def walk(self, group, bits=None, strength=1, partners=None):
        """Walk a 1 across *group*; return ``({signal: set(pi_gpio)}, {signal: [rp2 signals]})``.

        Only the signal under test is driven, high then low; every other chosen signal is an input meanwhile (a
        short between two wires then shows as one following the other, and never as two RP2 outputs fighting),
        except ui_in[0], which stays low throughout: the factory test's uio_oe follows it. A Pi GPIO that reads 1
        in the high step and 0 in the low step belongs to that signal. The second map lists every RP2 *input* pin
        that followed the signal on the board side; the caller decides which of those are legitimate. *partners*
        maps a signal to RP2-driven signals known to share its HAT line; any of them still an output is released
        to input for the signal's step. The chosen signals are left as inputs, ui_in[0] low.
        """
        chosen = self.signals(group, bits)
        partners = partners or {}
        for name, gpio in chosen:
            if name == KEPT_LOW:
                self.drive(name, 0, strength)
            elif name in self.outputs:
                self.rp2.cmd(f"in {gpio} none")
                self.outputs.discard(name)
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
            if name != KEPT_LOW:
                self.rp2.cmd(f"in {self.gpio_of(name)} none")
                self.outputs.discard(name)
            for p in released:
                if p == KEPT_LOW:
                    self.drive(p, 0, strength)
        return observed, follows

    def walk_together(self, names, strength=1):
        """Drive *names* high and low together (twice; both passes must agree) and return the Pi GPIOs that
        followed them, as one set. For uio[6:7]: driven in phase, the chip's copy of either (uo_out[6:7]) agrees
        with whatever a short joins it to among them, so no two drivers ever disagree on a net."""
        if self.controller != "rp2040":  # group/ungroup write the RP2040's SIO registers: other chips' differ
            raise ProtocolError(f"driving {', '.join(names)} together is written for the RP2040 only")
        gpios = " ".join(str(self.gpio_of(n)) for n in names)

        def group(value):
            vals = self.rp2.cmd(f"group {value} {gpios}")[1:]
            failed = [n for n, v in zip(names, vals) if int(v) != value]
            for n in failed:
                self.drive_failures[n] = 1 - value
            return not failed

        seen = []
        try:
            for _ in range(2):
                group(0)
                self.sample()
                took = group(1)
                high = self.sample()
                group(0)
                low = self.sample()
                seen.append({g for g in high if high[g] == 1 and low[g] == 0} if took else set())
        finally:
            self.rp2.cmd(f"ungroup {gpios}")
        if seen[0] != seen[1]:
            raise UnstableReading(f"the two passes of {', '.join(names)} disagree (intermittent contact?)")
        self.log(f"  {' and '.join(names)} together -> {describe_gpios(sorted(seen[0])) or '(nothing)'}")
        return seen[0]

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
        self.held_low = held_low
        self.hat.set_bias("down")
        for name in sorted(attributed):
            self.log(f"  {name:<10} <- {describe_gpios(sorted(attributed[name]))}")
        if held:
            self.log(
                f"  Pi lines not following the Pi's pull-down (driven or pulled up): {describe_gpios(sorted(held))}"
            )
        if held_low:
            self.log(f"  Pi lines not following the Pi's pull-up (driven low): {describe_gpios(held_low)}")
        return attributed, sorted(set(held) | set(held_low))

    def confirm_factory_test(self, uio_floating):
        """Prove ``uo_out = uio_in`` and ``cnt == 0`` on-board before trusting the loopback.

        Drives the *uio_floating* bits (already known to be undriven) one at a time, high then low, the rest
        inputs (two bits a short joins are then never driven against each other), and reads the RP2's own
        ``uo_out`` pin of that bit; then raises ``ui_in[0]`` and checks ``uo_out`` (the counter) and ``uio`` read
        0. Returns None on success, else the reason.
        """
        bits = [int(n[:-1].split("[")[1]) for n in uio_floating]
        if len(bits) < 2:
            return (
                f"only {len(bits)} uio bit{'' if len(bits) == 1 else 's'} float{'s' if len(bits) == 1 else ''}, "
                "so the loopback cannot be confirmed (the others' lines are "
                "held: by a ribbon on another port or turned round, or by the chip)"
            )
        self.set_inputs("uio")
        followed, wrong = [], []
        for bit in bits:  # every candidate, one at a time (each floats: nothing else drives it)
            got = {}
            for want in (1, 0):
                if not self.drive(signal_name("uio", bit), want):
                    self.set_inputs("uio")
                    return f"uio[{bit}] could not be driven"
                time.sleep(self.settle)
                got[want] = self.read_rp2()[signal_name("uo_out", bit)]
            self.set_inputs("uio", {bit})
            if got == {1: 1, 0: 0}:
                followed.append(bit)
            elif got[1] == got[0]:
                # held at one level whatever uio is: something on the uo_out line (a ribbon turned round puts
                # Pmod pins 1 and 7 on the HAT's ground), not the chip's copy failing; the walks say where
                self.uo_held[signal_name("uo_out", bit)] = "high" if got[1] else "low"
            else:
                wrong.append(f"uo_out[{bit}] reads {got[1]} for uio[{bit}]=1 and {got[0]} for 0")
        if wrong:
            return f"{'; '.join(wrong)}: not uo_out = uio_in"
        if len(followed) < 2:
            return (
                f"only {len(followed)} uo_out bit{'' if len(followed) == 1 else 's'} followed its uio bit, so "
                "the loopback cannot be confirmed (a "
                "ribbon on another port or turned round, or the chip)"
            )
        # Counter check: ui_in[0]=1 puts cnt on uo_out and uio. The chip then drives uio, so every other ui_in bit
        # (ui_in[1:3] share HAT lines with uio[1:3]) is an input meanwhile.
        held = [n for n in self.outputs if n.startswith("ui_in[") and n != "ui_in[0]"]
        for n in held:
            self.rp2.cmd(f"in {self.gpio_of(n)} none")
            self.outputs.discard(n)
        self.drive("ui_in[0]", 1)
        time.sleep(self.settle)
        rp2 = self.read_rp2()
        self.drive("ui_in[0]", 0)
        for n in held:
            self.drive(n, 0)
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


def load_sibling(name, script_dir=None):
    """Import the host script `name` (identify_pmod_pins, the bit-bang decoder; tt_dip_switches, the pinctrl
    helpers) from next to this script, as the package installs them, or from where the repository keeps it.
    None when it is in neither place."""
    import importlib.util

    script_dir = script_dir or pathlib.Path(__file__).resolve().parent
    for candidate in (
        script_dir / f"{name}.py",
        script_dir.parent.parent / "designs" / "pmod-pin-id" / "host" / f"{name}.py",
        script_dir.parent / "pmod-pin-id" / "host" / f"{name}.py",
    ):
        if candidate.exists():
            spec = importlib.util.spec_from_file_location(name, candidate)
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
    started = rp2.cmd("txid " + " ".join(f"{probe.gpio_of(n)}={label}" for n, label in transmitting.items()))
    names = f"{len(transmitting)} name{'' if len(transmitting) == 1 else 's'}"
    log(f"MEM: {mem_free(started)} bytes of the RP2's heap free while it sends {names}")
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


def make_pin_id_scanner(pinid):
    """A scanner over all HAT lines using identify_pmod_pins' GpioReader/identify_pin (each line listened to for
    its CAPTURE_SECONDS)."""

    def scan():
        chip = pinid.detect_gpio_chip()
        decoded = {}
        for gpio in ALL_HAT_GPIOS:
            reader = pinid.GpioReader(gpio, chip)
            try:
                reader.open()
                decoded[gpio] = pinid.identify_pin(reader)
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


def evaluate(
    observed, expected, tested, required, direct=None, reverse=None, follows=None, drive_failures=None, latch=None
):
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


# Every command the test runs on the Pi is bounded, so the teardown is (TEARDOWN_SECONDS).
COMMAND_TIMEOUT = 5
PINCTRL_TIMEOUT = 2


def run_quiet(cmd, check=False):
    try:
        result = subprocess.run(_sudo(cmd), capture_output=True, text=True, timeout=COMMAND_TIMEOUT)
    except subprocess.TimeoutExpired:
        result = subprocess.CompletedProcess(cmd, 124, "", f"{cmd[0]} did not finish within {COMMAND_TIMEOUT} s")
    if check and result.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd)} failed: {result.stderr.strip()}")
    return result


# -- Pulls a Pi 3 cannot read back ----------------------------------------------------------------------


# The BCM2835's pulls at power-on: GPIO0 to GPIO8 pulled up, GPIO9 to GPIO27 pulled down (Broadcom, "BCM2835
# ARM Peripherals", section 6.2, table 6-31, the "Pull" column; the BCM2837 of a Pi 3 has the same GPIO block).
def power_on_pull(gpio):
    return "pu" if gpio <= 8 else "pd"


DEVICE_TREE = pathlib.Path("/proc/device-tree")
_DT_PULL = {0: "pn", 1: "pd", 2: "pu"}  # brcm,pull (the bcm2835 pinctrl binding): 0 none, 1 down, 2 up


def _cells(path):
    data = path.read_bytes()
    return [int.from_bytes(data[i : i + 4], "big") for i in range(0, len(data) - 3, 4)]


def device_tree_pulls(root=DEVICE_TREE):
    """{gpio: (pull, the node that sets it)}: the pulls the running device tree gives a pin, where an enabled node
    (no status, or "okay") names in a pinctrl-N a pin group that has brcm,pull. That is what the kernel set on
    those pins when the node's driver took them. A pin no such group names is not in it."""
    root = root.resolve()
    groups, users = {}, []
    for here, _dirs, files in os.walk(root):
        node = pathlib.Path(here)
        if "brcm,pins" in files and "phandle" in files:
            pulls = _cells(node / "brcm,pull") if "brcm,pull" in files else None
            groups[_cells(node / "phandle")[0]] = (_cells(node / "brcm,pins"), pulls, node.name)
        status = (node / "status").read_bytes().rstrip(b"\0").decode() if "status" in files else "okay"
        if status in ("okay", "ok"):
            for f in files:
                if f.startswith("pinctrl-") and f[len("pinctrl-") :].isdigit():
                    users += [(ph, node.name) for ph in _cells(node / f)]
    found = {}
    for phandle, user in users:
        pins, pulls, name = groups.get(phandle, ((), None, ""))
        for i, gpio in enumerate(pins if pulls else ()):
            value = pulls[i] if len(pulls) > 1 else pulls[0]
            if value in _DT_PULL:
                found[gpio] = (_DT_PULL[value], f"the device tree's {name} pins of {user}")
    return found


def known_pulls(gpios, root=DEVICE_TREE):
    """{gpio: (pull, why)} for pins whose pull pinctrl cannot read: the running device tree's, else the SoC's
    power-on default."""
    try:
        from_tree = device_tree_pulls(root)
    except OSError:
        from_tree = {}
    return {g: from_tree.get(g, (power_on_pull(g), "the BCM2835 power-on default")) for g in gpios}


class PiEnvironment:
    """Take over the serial port and the HAT GPIOs for the test; undo it after.

    * ``fpgas-tt`` owns ``/dev/ttboard`` on every deployed TT host; stop it
      and start it again afterwards (the board is off the public site while
      stopped, so never leave it stopped). A systemd timer restarts it in ten
      minutes regardless, in case this process is killed mid-run. The boot
      check stops it itself and passes --no-daemon.
    * The kernel console is on GPIO14/15 = HAT JC2/JC3. Driving those from the
      RP2 has triggered SysRq (reboot/crash) on other hosts, so SysRq is
      disabled for the duration and the getty is stopped.
    * SPI0 kernel modules claim GPIO7-11 (JA1/JB1 and the shared JA/JB 2-4).
    * Every HAT GPIO's state (its function, its pull, an output's level: the UART
      function of GPIO14/15 among them) is read with pinctrl before anything is
      changed and set back afterwards. A pull pinctrl cannot read (a Pi 3 and
      older print ``--``) is set to a known one instead (known_pulls: the
      running device tree's for the pin, else the SoC's power-on default), and
      `assumed_pulls` says which and why. An output whose level cannot be read
      is refused before anything is changed.
    """

    SPI_MODULES = ("spidev", "spi_bcm2835")
    RESTART_UNIT = "tt-pmod-wiring-restart"

    def __init__(self, manage_daemon=True, unload_modules=True, log=print, pins=None):
        self.manage_daemon = manage_daemon
        self.unload_modules = unload_modules
        self.log = log
        self.pins = pins or load_sibling("tt_dip_switches")  # pinctrl, PIN_RE and set_pins
        if self.pins is not None:
            self.pins.PINCTRL_TIMEOUT = PINCTRL_TIMEOUT  # its own is 10 s: 22 calls in the teardown
        self.daemon_was_active = False
        self.sysrq_before = None
        self.saved_pins = None
        self.assumed_pulls = {}
        self.unloaded = []
        self.gettys = []

    def read_pins(self):
        """``{gpio: (function, pull, level)}`` of every HAT GPIO, read with pinctrl; RuntimeError if it cannot."""
        rc, out = self.pins.pinctrl(["get", ",".join(str(g) for g in sorted(ALL_HAT_GPIOS))])
        found = {int(g): (f, pull, level) for g, f, pull, level in self.pins.PIN_RE.findall(out)}
        if rc != 0 or set(found) != set(ALL_HAT_GPIOS):
            raise RuntimeError(f"the Pi's HAT GPIOs could not be read with pinctrl: {out.strip()[:200]}")
        return found

    def check_pins(self):
        """What pinctrl reads now that differs from what was set back: an input's level is the board's, not ours;
        a pull pinctrl cannot read is not compared."""
        try:
            now = self.read_pins()
        except RuntimeError as e:
            return [f"the HAT GPIOs could not be read back: {e}"]
        faults = []
        for g, (func, pull, level) in sorted(self.saved_pins.items()):
            f2, p2, l2 = now[g]
            if f2 != func or (p2 != "--" and p2 != pull) or (func == "op" and l2 != level):
                wanted = f"{func} {pull}" + (f" {level}" if func == "op" else "")
                faults.append(f"GPIO{g} reads back {f2} {p2} {l2}, not {wanted}")
        return faults

    def enter(self):
        if os.geteuid() != 0 and subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode != 0:
            raise RuntimeError("root or passwordless sudo is required (systemctl, sysctl, rmmod)")
        # Before anything changes: what cannot be put back stops the test here.
        saved = self.read_pins()
        unreadable = sorted(g for g, (f, _pull, level) in saved.items() if f == "op" and level == "--")
        if unreadable:
            raise RuntimeError(
                f"pinctrl cannot read the level of output GPIO{', GPIO'.join(map(str, unreadable))}, so it could "
                "not be put back after the test"
            )
        self.assumed_pulls = known_pulls(sorted(g for g, (_f, pull, _level) in saved.items() if pull == "--"))
        self.saved_pins = {g: (f, self.assumed_pulls[g][0] if g in self.assumed_pulls else pull, level)
                           for g, (f, pull, level) in saved.items()}  # fmt: skip
        if self.manage_daemon:
            active = run_quiet(["systemctl", "is-active", "fpgas-tt"]).stdout.strip()
            self.daemon_was_active = active == "active"
            if self.daemon_was_active:
                self.log("Stopping fpgas-tt (it owns the serial port; restarted afterwards)")
                # A dead-man restart in case this process is killed mid-run;
                # clear any stale one from an earlier aborted run first.
                run_quiet(["systemctl", "stop", f"{self.RESTART_UNIT}.timer"])
                armed = run_quiet(
                    [
                        "systemd-run",
                        "--quiet",
                        "--on-active=600",
                        f"--unit={self.RESTART_UNIT}",
                        "systemctl",
                        "start",
                        "fpgas-tt",
                    ]
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
        if self.unload_modules:
            self.unloaded = [m for m in self.SPI_MODULES if run_quiet(["rmmod", m]).returncode == 0]
            if self.unloaded:
                self.log(f"Unloaded kernel modules: {', '.join(self.unloaded)} (loaded again afterwards)")

    def leave(self):
        """Put back what enter() changed; return what could not be put back (empty when all was)."""
        faults = []
        if self.saved_pins is not None:
            faults += self.pins.set_pins(self.saved_pins)
            if not faults:
                faults += self.check_pins()
            if not faults:
                self.log(f"Put back the state of the {len(self.saved_pins)} HAT GPIOs (read back with pinctrl)")
            if self.assumed_pulls:
                by_why = {}
                for g, (pull, why) in sorted(self.assumed_pulls.items()):
                    by_why.setdefault(why, []).append(f"GPIO{g} {pull}")
                self.log("PULLS: pinctrl cannot read this Pi's pulls, so they were set to known ones: "
                         + "; ".join(f"{why}: {', '.join(pins)}" for why, pins in by_why.items()))  # fmt: skip
        for module in reversed(self.unloaded):  # spi_bcm2835 before spidev, which sits on it
            if run_quiet(["modprobe", module]).returncode != 0:
                faults.append(f"the {module} kernel module was not loaded again")
        put_back = ["sysctl", "-q", "-w", f"kernel.sysrq={self.sysrq_before}"]
        if self.sysrq_before not in (None, "0") and run_quiet(put_back).returncode != 0:
            faults.append(f"kernel.sysrq was not set back to {self.sysrq_before}")
        if self.gettys and run_quiet(["systemctl", "start", *self.gettys]).returncode != 0:
            faults.append(f"{', '.join(self.gettys)} not started again")
        if self.manage_daemon and self.daemon_was_active:
            self.log("Restarting fpgas-tt")
            result = run_quiet(["systemctl", "start", "fpgas-tt"])
            if result.returncode != 0:
                faults.append(f"fpgas-tt not started again: {result.stderr.strip()}")
            run_quiet(["systemctl", "stop", f"{self.RESTART_UNIT}.timer"])
        return faults


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

    # Strict (the boot check): the chip's loopback is required, so an SDK that cannot select it stops the test
    # here, before any pin is driven, rather than going on with a test that cannot pass.
    required = want_loopback and args.strict
    if args.sdk:
        try:
            fields = rp2.cmd("sdk init", timeout=15)
            log(f"SDK: {' '.join(fields[1:])}")
        except ProtocolError as e:
            if required:
                raise ProtocolError(f"the board's SDK could not be used: {e}") from None
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
            if required:
                raise ProtocolError(f"the chip's {args.asic_project} could not be selected: {e}") from None
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
    held_ui = {}
    for name, ok in ui_floating.items():
        if ok:
            continue
        # ui_in is an input of the chip, so what holds it is a DIP switch that is on (1 kOhm to 3.3 V), the chip's
        # own output on a line a wrong ribbon joins to it, or a wiring fault. It is never driven: against a chip
        # output that would be two drivers on one net. It fails the board, said.
        held_ui[name] = probe.held_level[name]
        notes.append(f"{name} is held {held_ui[name]} by something: not driven")
    if 0 not in ui_bits and project_selected:
        notes.append("ui_in[0] is held externally, so the factory-test loopback cannot be used")
        project_selected = False
    probe.hold_low("ui_in", ui_bits & {0})  # ui_in[0] stays low from here on; the rest are inputs

    # Reverse walk: Pi pulls, RP2 reads. ui_in[0] stays driven so the chip's
    # uio_oe cannot flip while its inputs float.
    log("\n== reverse walk: Pi pulls one line up, RP2 reads its inputs ==")
    reverse_names = [n for n, _g in probe.signals("ui_in", ui_bits - {0})] + [n for n, _g in probe.signals("uio")]
    reverse, held = probe.reverse_walk(reverse_names)
    probe.hold_low("ui_in", ui_bits & {0})
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
        for name, level in sorted(probe.uo_held.items()):
            notes.append(f"{name} reads {level} whatever its uio bit is set to: its line is held (a ribbon turned "
                         "round, or a short?)")  # fmt: skip
            log(f"  {notes[-1]}")
        if reason is None:
            asic_loopback = True
            log("  confirmed")
        else:
            notes.append(f"factory test not confirmed: {reason}; uo_out loopback disabled")
            log(f"WARNING: {notes[-1]}")
            if required:  # the chip's uio_oe is then not known: walking ui_in[0] could make it drive uio
                if "not uo_out = uio_in" in reason:  # a bridge between uio or uo_out wires reads like this too
                    raise Unclear(reason)
                raise ProtocolError(f"the chip's {args.asic_project} could not be confirmed: {reason}")

    # The heap after a collection just before the walks, to compare with the pin-id rounds' (collected too).
    log(f"MEM: {mem_free(rp2.cmd('mem'))} bytes of the RP2's heap free (collected) before the walks")
    log("\n== ui_in: RP2 drives, Pi reads ==")
    if asic_loopback or 0 not in ui_bits:
        observed, follows = probe.walk_twice("ui_in", ui_bits, partners=measured_partners)
    else:
        # No confirmed loopback: the chip's project may drive uio when ui_in[0] goes high, and uio[1:3] share
        # HAT lines with ui_in[1:3]. So ui_in[0] is walked alone, with every other ui_in bit an input.
        observed, follows = probe.walk_twice("ui_in", ui_bits - {0}, partners=measured_partners)
        probe.set_inputs("ui_in", ui_bits - {0})
        alone = probe.walk_twice("ui_in", {0}, partners=measured_partners)
        observed.update(alone[0])
        follows.update(alone[1])
        probe.hold_low("ui_in", ui_bits & {0})

    # Which cabling profile are we looking at?
    found, score = choose_cabling(observed, reverse)
    log(f"\nBest-fitting cabling profile: {found} (score {score}/{len(observed) + len(reverse)})")
    if score < 8:
        notes.append(f"no known cabling profile fits well (best: {found}, score {score})")
    cabling = found if args.cabling == "auto" else args.cabling
    partners = dict(measured_partners)
    for name, ps in shared_partners(cabling).items():
        partners[name] = sorted(set(partners.get(name, [])) | set(ps))

    if asic_loopback:
        # Confirmed uio_oe = 0: the chip does not drive uio. But a wrong ribbon can join a uio net to a line the
        # chip's uo_out drives, so a uio bit is driven only where nothing else can be driving its net: the reverse
        # walk found its line (a driven line does not follow the Pi's pull), it followed the RP2's weak pulls, or
        # the cabling puts it on the line of its own uo_out copy (which agrees with it). uio[6:7] sit on the Pi's
        # fixed I2C pull-ups, which neither test can see past: they are driven when the rest of the uio ribbon was
        # found in place, as only that ribbon reaches those HAT pins (and see `deferred`, below). The drive
        # strengths asked for are only honoured by firmware that has them: the deployed RP2040 boards' MicroPython
        # does not (it warns, and drives at its default), so no fight is ever relied on to be won.
        lines = profile_lines(cabling)
        # found on its own line, and the only uio bit found there: two on one line means one of them follows the
        # other through the chip (a uo_out copy landing on its net), so neither is known safe
        uio_at = {}
        for n, ps in reverse.items():
            if n.startswith("uio["):
                for g in ps:
                    uio_at.setdefault(g, set()).add(n)
        found = {k for k in range(8)
                 if set(reverse.get(signal_name("uio", k), ())) == {lines[signal_name("uio", k)]}
                 and uio_at.get(lines[signal_name("uio", k)]) == {signal_name("uio", k)}}  # fmt: skip
        floats = {signal_bit(n) for n, ok in uio_floating.items() if ok}
        latched = set(latch_bits(cabling))
        fixed = {k for k in range(8) if lines[signal_name("uio", k)] in PI_FIXED_PULLUP_GPIOS}
        judged = [set(reverse.get(signal_name("uio", k), ())) for k in range(8) if k not in fixed | latched]
        own = [lines[signal_name("uio", k)] for k in range(8) if k not in fixed | latched]
        # in place: no uio bit found on another line, and most found on their own (an open wire finds none)
        in_place = all(not ps or ps == {line} for ps, line in zip(judged, own)) and \
            2 * sum(ps == {line} for ps, line in zip(judged, own)) >= len(own)  # fmt: skip
        drivable = found | floats | latched | (fixed if in_place else set())
        # uio[6:7] are driven last, and only if neither followed another uio bit's walk: following one means a chip
        # output (that bit's uo_out copy) is on its line, through a short or a wrong ribbon.
        deferred = drivable - found - floats - latched
        # Their own lines have the Pi's fixed pull-up, which the reverse walk cannot move: a line it found for one of
        # them is reached through the chip, so that bit is not driven either.
        for k in sorted(deferred):
            if reverse.get(signal_name("uio", k)):
                deferred.discard(k)
                drivable.discard(k)
                notes.append(f"uio[{k}] is not driven: the reverse walk reached it through something (a short?)")
            elif probe.held_level.get(signal_name("uio", k)) != "high":
                # The Pi's pull-ups hold these lines high; held otherwise, something else (a short to ground, a
                # driven line) holds them, and driving them would meet it.
                deferred.discard(k)
                drivable.discard(k)
                notes.append(
                    f"uio[{k}] is not driven: its line is held "
                    f"{probe.held_level.get(signal_name('uio', k), 'by something')}, not by the Pi's pull-up"
                )
        for k in sorted(set(range(8)) - drivable):
            notes.append(f"uio[{k}] is not driven: its line may be driven by something else (a wrong ribbon?)")
        strength = 3
    else:
        if not uio_floating:
            log("\n== uio: probing which bits nothing else holds ==")
            uio_floating = probe.probe_floating("uio")
        drivable = {b for b, (n, _g) in enumerate(probe.signals("uio")) if uio_floating[n]}
        strength = 0  # asked for 2 mA where the firmware supports drive strengths (this board's does not)
        deferred = set()
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
        first = drivable - deferred
        uio_observed, uio_follows = probe.walk_twice("uio", first, strength, partners) if first else ({}, {})
        followed = {f for fs in uio_follows.values() for f in fs}
        for k in sorted(deferred):
            if signal_name("uio", k) in followed:
                drivable.discard(k)
                notes.append(f"uio[{k}] is not driven: it followed another uio bit's walk (a chip output on its line?)")
        later = deferred & drivable
        if later and later != deferred:  # one of the pair alone could meet the chip's copy of the other: neither
            for k in sorted(later):
                drivable.discard(k)
                notes.append(f"uio[{k}] is not driven: its partner on the Pi's I2C pull-ups could not be")
            later = set()
        if later:
            # Together, in phase (walk_together). Their lines cannot be told apart this way: each is given the lines
            # it should reach that were reached, and a line neither should reach goes to both, so the rows show it.
            # (Two wires of one ribbon cannot swap places.)
            names = [signal_name("uio", k) for k in sorted(later)]
            reached = probe.walk_together(names, strength)
            exp = expected_map(cabling, asic_loopback)
            stray = reached - set().union(*(exp[n] for n in names))
            uio_observed.update({n: (reached & exp[n]) | stray for n in names})
            notes.append(f"{' and '.join(names)} were walked together (the Pi's I2C pull-ups hide their lines)")
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
    # Pin-id sends a different frame on every signal at once: with a short between two of them, two RP2 outputs
    # would meet. It runs only when the walks found no line reached by a signal it should not be, and no RP2 pin
    # following one it should not.
    expect = expected_map(cabling, asic_loopback)
    strays = [n for n, ps in observed.items() if set(ps) - expect.get(n, set())]
    strays += [n for n, fs in follows.items() if set(fs) - expected_followers(cabling, asic_loopback, n)]
    if pin_scanner is not None and strays:
        notes.append(f"pin-id not run: the walks found a short or a stray line ({', '.join(sorted(set(strays)))})")
        pin_scanner = None
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
            alone = drivable - deferred  # uio[6:7] send no names: different frames on them could meet (above)
            if alone:
                rounds.append(("uio", {n: pin_id_label(n) for n, _g in probe.signals("uio", alone)}))
        hat.close()  # the decoder requests lines one at a time
        for round_name, transmitting in rounds:
            log(f"\n== pin-id: RP2 transmits {round_name} names, Pi decodes every HAT line ==")
            decoded = run_pin_id_round(rp2, probe, pin_scanner, transmitting, partners, log)
            pin_id[round_name] = {"transmitting": transmitting, "decoded": decoded}
        probe.set_inputs("uio")
        probe.hold_low("ui_in", ui_bits & {0})

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
        judged,
        expected,
        tested,
        required,
        direct=direct,
        reverse=reverse,
        follows=bad_follows,
        drive_failures=probe.drive_failures,
        latch=latch,
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
        "cabling_found": found if score >= 8 else None,
        "held_inputs": held_ui,
        "held_levels": dict(probe.held_level),
        "held_low_lines": list(probe.held_low),
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
    log(
        f"Cabling profile: {result['cabling']} "
        f"(ui_in <- HAT {CABLINGS[result['cabling']]['ui_in']}, uio <- {CABLINGS[result['cabling']]['uio']}, "
        f"uo_out <- {CABLINGS[result['cabling']]['uo_out']})"
    )
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
        log(
            f"pin-id {round_name} round: {'ok' if data['ok'] else 'FAIL'}"
            + (
                ": "
                + ", ".join(
                    f"GPIO{r['gpio']} {r['status']} (expected {r['expected']}, got {pin_id_display(r['decoded'])})"
                    for r in bad
                )
                if bad
                else ""
            )
        )
    if not result["asic_loopback"]:
        log("uo_out was NOT tested (no ASIC loopback).")


# -- The one line the boot check reads -------------------------------------------------------

SAYS = "WIRING:"
# A ribbon's faults named in the line before "and N more" (the report above it has them all).
NAMED_PER_RIBBON = 2
# Why a ui_in line is held, by how it was found held. A DIP switch that is on ties its line to 3.3 V.
HELD_WHY = {
    "high": "a DIP switch that is on? set all DIP switches off",
    "low": "something drives it low: a short to ground, or a chip output a wrong ribbon joins to it",
    "against the pulls": "something drives it",
}


def pmod_pin(name):
    """'ui_in[5]' -> 8: the Pmod pin (1-4, 7-10) a signal's bit is on, at the demo board and at the HAT alike."""
    return PMOD_PIN_NUMBERS[signal_bit(name)]


def hat_pin(gpio):
    """A Pi GPIO as the HAT's connectors name it: GPIO8 -> 'HAT JA pin 1', GPIO10 -> 'HAT JA/JB pin 2' (the HAT
    joins JA and JB pins 2 to 4)."""
    labels = HAT_GPIO_LABELS.get(gpio)
    if labels is None:
        return f"Pi GPIO{gpio}"
    parts = labels.split("/")
    return f"HAT {'/'.join(p[:2] for p in parts)} pin {parts[0][2:]}"


def hat_pins(gpios):
    return ", ".join(hat_pin(g) for g in sorted(gpios))


def ribbon(group, port):
    """'the ui_in ribbon (to HAT JA)': a ribbon named by the demo board's Pmod and the HAT port it goes to."""
    return f"the {group} ribbon (to HAT {port})"


def ribbon_reaches(result):
    """{group: {bit: Pi GPIOs}}: the lines each tested bit of each ribbon is on.

    ui_in[1..7] and uio: from the reverse walk (the Pi pulls a line, the RP2 reads: what the chip copies does not
    enter it). Where it found nothing: the forward walk's lines if one of them is a line the reverse walk cannot
    move (driven by the chip, or with the Pi's fixed I2C pull-up), else nothing. A uio bit that reached one line
    only is left out (with the loopback the chip's copy is always one), unless no uio bit has a line of its own,
    when none has. ui_in[0] (not in the reverse walk): from its forward walk. uo_out, with the chip's loopback:
    from what each uio bit reached through the chip."""
    rows = {r["signal"]: r for r in result["rows"]}
    reverse = {k: set(v) for k, v in result.get("reverse", {}).items()}
    seen = {g: {} for g in GROUPS}
    ambiguous = set()
    for name, r in rows.items():
        if r["status"] in ("untested", "contention"):
            continue
        if name == "ui_in[0]":
            seen["ui_in"][0] = set(r["observed"])
        elif reverse.get(name):
            seen[name.split("[")[0]][signal_bit(name)] = reverse[name]
        elif name.startswith("uio[") and result["asic_loopback"] and len(r["observed"]) < 2:
            ambiguous.add(signal_bit(name))  # one line, and the chip's copy is always one: not this ribbon's own
        else:
            unmovable = set(result.get("held", ())) | PI_FIXED_PULLUP_GPIOS
            seen[name.split("[")[0]][signal_bit(name)] = set(r["observed"]) if set(r["observed"]) & unmovable else set()
    if ambiguous and not any(seen["uio"].values()):  # no uio bit has a line of its own: the ribbon reaches nothing
        seen["uio"].update({k: set() for k in ambiguous})
    if result["asic_loopback"]:
        seen["uo_out"] = {signal_bit(n): set(r["observed"]) for n, r in rows.items()
                          if n.startswith("uio[") and r["status"] not in ("untested", "contention")}  # fmt: skip
    return seen


def ribbon_place(bits, port, offset=False):
    """How many of `bits` ({bit: GPIOs}) are on HAT `port` pin for pin; with offset, one position off (Pmod pin n on
    HAT pin 12 - n, which puts pins 1 and 7 on the HAT's ground)."""
    found = 0
    for k, gpios in bits.items():
        pin = PMOD_PIN_NUMBERS[k]
        if offset:
            if 12 - pin not in PMOD_PIN_NUMBERS:
                continue
            pin = 12 - pin
        if PMOD_HAT_PORTS[port][PMOD_PIN_NUMBERS.index(pin)] in gpios:
            found += 1
    return found


def ribbon_findings(result):
    """({group: (kind, what)}, {group: the port it is on}) for a ribbon that is wholly elsewhere: ("elsewhere", the
    port it is on), ("offset", the port it is seated one position off on), ("none", its signals: it reached
    nothing). A ribbon in place, or with only some wires wrong, is not in the first."""
    cabling = result["cabling"]
    seen = ribbon_reaches(result)
    place, found = {}, {}
    for group in GROUPS:  # uo_out last: it is on a port the uio ribbon is not on
        bits = seen[group]
        if not bits:
            continue
        expected = CABLINGS[cabling][group]
        ports = [p for p in PORTS if group != "uo_out" or p != place.get("uio")]
        best = max(ports, key=lambda p: (ribbon_place(bits, p), p == expected))
        place[group] = best
        n = len(bits)
        if expected in ports and ribbon_place(bits, expected) == n:  # uo_out is never where the uio ribbon is
            continue
        # What reached the Pi at all: for uo_out, beyond the uio bit's own line (which the uio walk reached itself).
        uio_port = place.get("uio", CABLINGS[cabling]["uio"])
        rest = bits if group != "uo_out" else {k: g - {PMOD_HAT_PORTS[uio_port][k]} for k, g in bits.items()}
        shifted = max(ports, key=lambda p: (ribbon_place(bits, p, offset=True), p == expected))
        movable = sum(1 for k in bits if 12 - PMOD_PIN_NUMBERS[k] in PMOD_PIN_NUMBERS)
        grounded = [rest[k] for k in rest if 12 - PMOD_PIN_NUMBERS[k] not in PMOD_PIN_NUMBERS]  # pins 1, 7
        if ribbon_place(bits, best) == n:
            found[group] = ("elsewhere", best)
        elif movable >= 3 and ribbon_place(bits, shifted, offset=True) == movable and not any(grounded):
            place[group] = shifted
            found[group] = ("offset", shifted)
        elif not any(rest.values()):
            found[group] = ("none", None)
    return found, place


def row_faults(row, cabling, held, levels=None, held_low_lines=()):
    """The faults of a required row that is not ok, each on the ribbon it is on: [{"group", "signal", "own",
    "via", "text"}]. own: the signal's own HAT line was not reached; via: for a uo_out line the chip drives from
    this row's signal, that signal."""
    name, lines = row["signal"], profile_lines(cabling)
    group = name.split("[")[0]
    own = lines[name]
    where = f"{name} (Pmod pin {pmod_pin(name)})"
    levels = levels or {}

    def fault(text, g=group, s=name, own_missing=False, via=None):
        return {"group": g, "signal": s, "own": own_missing, "via": via, "text": text}

    if row["status"] == "contention":
        return [fault(f"{where} could not be driven by the demo board: something else drives it")]
    if row["status"] == "untested":
        if name in held:
            return [fault(f"{where} is held {held[name]} on the demo board ({HELD_WHY[held[name]]})",
                          own_missing=True)]  # fmt: skip
        if levels.get(name) == "low" or (levels.get(name) == "high" and own not in PI_FIXED_PULLUP_GPIOS):
            return [fault(f"{where} could not be tested: something holds its line {levels[name]}", own_missing=True)]
        return [fault(f"{where} could not be tested", own_missing=True)]
    expected, observed = set(row["expected"]), set(row["observed"])
    missing, extra = expected - observed, observed - expected
    faults = []
    if own in missing:
        reached = f": it reached {hat_pins(extra)}" if extra else ""
        faults.append(fault(f"{where} did not reach {hat_pin(own)}{reached}", own_missing=True))
    elif extra:
        faults.append(fault(f"{where} also reached {hat_pins(extra)} (a short)"))
    for gpio in sorted(missing - {own}):  # the uo_out line the chip's factory test drives from this signal
        out = next(s for s, g in lines.items() if s.startswith("uo_out") and g == gpio)
        low = " (that line is held low: a short to ground?)" if gpio in held_low_lines else ""
        faults.append(fault(f"{out} (Pmod pin {pmod_pin(out)}) did not reach {hat_pin(gpio)}{low}", "uo_out", out,
                            via=name))  # fmt: skip
    if not faults:
        faults.append(fault(f"{where}: {row['detail'] or row['status']}"))
    return faults


def pin_id_faults(result):
    """The lines a pin-id round did not hear as expected, as row_faults gives them."""
    lines = profile_lines(result["cabling"])
    faults = []
    for data in result.get("pin_id", {}).values():
        sent = {pin_id_label(n): n for n in data["transmitting"]}
        for r in data["rows"]:
            if r["status"] in ("ok", "idle"):
                continue
            heard = "nothing" if r["decoded"] is None else pin_id_display(r["decoded"])
            if r["expected"] is None:
                faults.append({"group": "", "signal": None, "own": False, "via": None,
                               "text": f"{hat_pin(r['gpio'])} also heard {heard}"})  # fmt: skip
                continue
            name = sent[r["expected"]]
            if lines[name] == r["gpio"]:
                what, via = name, None
            else:  # a uo_out line, which the chip drives from `name`
                what = next(s for s, g in lines.items() if s.startswith("uo_out") and g == r["gpio"])
                via = name
            faults.append({"group": what.split("[")[0], "signal": what, "own": via is None, "via": via,
                           "text": f"{what} (Pmod pin {pmod_pin(what)}): its name was not read on "
                                   f"{hat_pin(r['gpio'])} (read: {heard})"})  # fmt: skip
    return faults


UNCLEAR = (
    "the readings fit no single open wire, swapped or turned ribbon: a short between neighbouring wires is "
    "likely; look at {ribbons} for bridged pins"
)


def ribbons_at(ports, cabling):
    """'the uio ribbon (to HAT JB) and the uo_out ribbon (to HAT JC)': the ribbons that go to `ports`."""
    by_port = {port: group for group, port in CABLINGS[cabling].items()}
    return " and ".join(ribbon(by_port[p], p) for p in PORTS if p in ports)


def ports_of(gpio):
    """{'JA', 'JB'} for GPIO10 (HAT JA2/JB2)."""
    return {label[:2] for label in HAT_GPIO_LABELS.get(gpio, "").split("/") if label}


def no_single_fault(result, bad, held, faults):
    """The WIRING: line when the readings fit no single fault (an open wire, two crossed wires, a whole ribbon
    elsewhere, one held bit): a signal reaching its own lines and others too (two wires bridged), a line two
    drivers meet on, or a held bit among other faults. It points at no one wrong place, only at the ribbons whose
    readings disagree and the HAT pins seen joined; the readings themselves go in result["readings"]. None when
    a single fault fits."""
    cabling = result["cabling"]
    bridged = [r for r in bad if r["status"] in ("short", "contention")
               or (set(r["expected"]) & set(r["observed"]) and set(r["observed"]) - set(r["expected"]))]  # fmt: skip
    # a held bit among faults that are readings (a bit that could not be tested is no reading of its own)
    held_among = bool(held) and any(f["signal"] not in held and "could not be tested" not in f["text"] for f in faults)
    if not bridged and not held_among:
        return None
    pairs = []
    for r in bridged:
        for extra in sorted(set(r["observed"]) - set(r["expected"])):
            mate = next((x for x in sorted(r["expected"]) if ports_of(x) & ports_of(extra)), None)
            pair = tuple(sorted((mate, extra))) if mate is not None else None
            if pair and pair not in pairs:
                pairs.append(pair)
    # A pair on the uo_out port can be only the chip copying a bridge between two wires of another ribbon: the
    # pairs on the wires' own ports, if there are any, are where to look.
    copies = CABLINGS[cabling]["uo_out"]
    own = [(a, b) for a, b in pairs if (ports_of(a) & ports_of(b)) - {copies}]
    pairs = own or pairs
    ports = set()
    for a, b in pairs:
        ports |= (ports_of(a) & ports_of(b)) - ({copies} if own else set())
    if not ports:
        ports = {CABLINGS[cabling][f["group"]] for f in faults if f["group"]} or set(PORTS)
    result["readings"] = [
        f"{r['signal']} (Pmod pin {pmod_pin(r['signal'])}) reached {hat_pins(r['observed']) or 'nothing'}; it "
        f"should reach {hat_pins(r['expected'])}" + (f"; held {held[r['signal']]}" if r["signal"] in held else "")
        for r in bad
    ][:8]  # fmt: skip
    together = any("were walked together" in n for n in result.get("notes", ()))
    pair_lines = {profile_lines(cabling)[signal_name("uio", k)] for k in (6, 7)}

    def named(gpio):  # uio[6:7] are walked as one, so which of their two lines it was is not known
        if together and gpio in pair_lines:
            return " or ".join(hat_pin(g) for g in sorted(pair_lines, reverse=True)).replace(" or HAT JB pin", " or")
        return hat_pin(gpio)

    shown = list(dict.fromkeys(f"{named(a)} and {named(b)} read as one" for a, b in pairs))
    joined = "; ".join(shown[:NAMED_PER_RIBBON])
    return UNCLEAR.format(ribbons=ribbons_at(ports, cabling)) + (f" ({joined})" if joined else "")


class Unclear(Exception):
    """The test stopped on readings that fit no single fault (the chip's copies did not follow its inputs, which a
    short between neighbouring uio or uo_out wires also does): exit 1, with what was read."""


def verdict(result, strict=True):
    """(exit code, the line after WIRING:) from a finished test: 0 every required signal reached the Pi where the
    cabling says, 1 a ribbon is not as it should be (named, with its pins), or uo_out could not be tested."""
    cabling = result["cabling"]
    where = ", ".join(f"{g} on HAT {CABLINGS[cabling][g]}" for g in GROUPS)
    if result["pass"]:
        if result["asic_loopback"]:
            return 0, f"all 24 Pmod signals reached the Pi where they should: {where} (uo_out through the chip)"
        return 0, f"the signals tested reached the Pi where they should ({where}); uo_out was not tested"
    held = result.get("held_inputs", {})
    bad = [r for r in result["rows"] if r["required"] and r["status"] != "ok"]
    untested_groups = [g for g in GROUPS if any(r["signal"].startswith(g + "[") and r["status"] == "untested"
                                                for r in bad)]  # fmt: skip
    if held.get("ui_in[0]") == "high":
        # With ui_in[0] high the factory test drives uio (its counter), which holds ui_in[1:3] through the HAT: that
        # follows from ui_in[0], which alone is said. Held low it explains no other held bit.
        bad = [r for r in bad if not (r["signal"] in {"ui_in[1]", "ui_in[2]", "ui_in[3]"} and r["signal"] in held)]
    if "ui_in[0]" in held:  # held at either level, the factory test cannot be used: uio is not tested
        bad = [r for r in bad if not (r["signal"].startswith("uio[") and r["status"] == "untested")]
    walk = [
        f
        for r in bad
        for f in row_faults(r, cabling, held, result.get("held_levels"), result.get("held_low_lines", ()))
    ]
    whole, _place = ribbon_findings(result)
    # A signal whose own wire is at fault explains what the chip copies from it, and what pin-id heard of it.
    at_fault = {f["signal"] for f in walk if f["own"]}
    # A uo_out line missed through ui_in[k] (on the line the HAT shares with uio[k]) reaches the chip by uio[k]'s
    # wire: a fault on that wire explains it too.
    shared = {n: f"uio[{j}]" for n in expected_direct(cabling) if n.startswith("ui_in[")
              for j in connected_uio(cabling, n)}  # fmt: skip
    at_fault |= {n for n, partner in shared.items() if partner in at_fault}
    faulted = {f["signal"] for f in walk}
    ids = [f for f in pin_id_faults(result) if f["signal"] not in faulted]
    faults = [
        f
        for f in walk + ids
        if f["group"] not in whole and not (f["via"] and (f["via"] in at_fault or f["via"].split("[")[0] in whole))
    ]
    unclear = None if whole else no_single_fault(result, bad, held, faults)
    if unclear:
        return 1, unclear
    parts = []
    if whole:  # a ribbon wholly elsewhere explains the single-wire faults around it: it alone is said
        faults = []
    swapped = [(a, b) for a in GROUPS for b in GROUPS if a < b
               and whole.get(a) == ("elsewhere", CABLINGS[cabling][b])
               and whole.get(b) == ("elsewhere", CABLINGS[cabling][a])]  # fmt: skip
    for a, b in swapped:
        parts.append(f"the {a} and {b} ribbons are on each other's HAT ports ({CABLINGS[cabling][b]} and "
                     f"{CABLINGS[cabling][a]}): swap them")  # fmt: skip
    offset = [g for g in GROUPS if whole.get(g, ("",))[0] == "offset"]
    if offset:
        which = ", ".join(f"{g} on HAT {whole[g][1]}"
                          + (f" (it goes on {CABLINGS[cabling][g]})" if whole[g][1] != CABLINGS[cabling][g] else "")
                          for g in offset)  # fmt: skip
        parts.append(f"{'the ' + offset[0] + ' ribbon is' if len(offset) == 1 else 'these ribbons are'} plugged in "
                     f"turned round and one position over ({which}): Pmod pin n arrives on HAT pin 12-n, and Pmod "
                     f"pins 1 and 7 are on the HAT's ground; plug {'it' if len(offset) == 1 else 'each'} in the right "
                     "way round, Pmod pin 1 to HAT pin 1")  # fmt: skip
    for group in GROUPS:
        port = CABLINGS[cabling][group]
        if group in whole:
            kind, what = whole[group]
            if kind == "elsewhere" and not any(group in pair for pair in swapped):
                parts.append(f"{ribbon(group, port)}: it is on HAT {what}, not {port}")
            elif kind == "none":
                parts.append(f"{ribbon(group, port)}: none of its signals reached the Pi (not plugged in, or broken)")
            continue
        texts, seen = [], set()
        for f in faults:  # one fault per signal: a uo_out line missed from two rows is one missing wire
            if f["group"] == group and f["signal"] not in seen:
                seen.add(f["signal"])
                texts.append(f["text"])
        if texts:
            more = f"; and {len(texts) - NAMED_PER_RIBBON} more" if len(texts) > NAMED_PER_RIBBON else ""
            parts.append(f"{ribbon(group, port)}: {'; '.join(texts[:NAMED_PER_RIBBON])}{more}")
    if whole:  # ribbons a misplaced one leaves untestable (not driven: a chip output may be on their lines)
        untested = [g for g in untested_groups if g not in whole]
        if strict and not result["asic_loopback"] and "uo_out" not in whole and "uo_out" not in untested:
            untested.append("uo_out")  # no loopback (ui_in[0] on the misplaced ribbon's ground, say): untested
        if untested:
            parts.append(f"and some {' and '.join(untested)} signals could not be tested until then")
    stray = list(dict.fromkeys(f["text"] for f in faults if f["group"] == ""))
    if stray and not parts:
        parts.append("; ".join(stray[:NAMED_PER_RIBBON]) + (f"; and {len(stray) - NAMED_PER_RIBBON} more"
                                                             if len(stray) > NAMED_PER_RIBBON else ""))  # fmt: skip
    if strict and not result["asic_loopback"] and not whole:  # a ribbon wholly elsewhere explains it
        which = "uio and uo_out were" if "uio" in untested_groups else "uo_out was"
        parts.append(
            f"{which} not tested: the chip's factory test could not be used (ui_in[0] is held)"
            if "ui_in[0]" in held
            else f"{which} not tested: the chip's factory test was not confirmed"
        )
    return 1, "; ".join(parts) or "the wiring did not pass (see the table above)"


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", default=None, help="serial port (default: /dev/ttboard, else /dev/ttyACM0)")
    parser.add_argument("--controller", choices=sorted(CONTROLLERS), default="rp2040")
    parser.add_argument(
        "--cabling",
        choices=["auto", *sorted(CABLINGS)],
        default="auto",
        help="expected cabling profile, or auto to pick the best fit (default)",
    )
    parser.add_argument(
        "--method",
        choices=["walk", "pin-id", "both"],
        default="both",
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
        "--fpga-reset",
        dest="fpga_reset",
        action="store_true",
        default=None,
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
    parser.add_argument(
        "--time-limit",
        type=int,
        default=None,
        help="seconds before the test stops itself and puts everything back (default TIME_LIMIT)",
    )
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
    if args.time_limit is None:
        args.time_limit = TIME_LIMIT
    return args


class Stopped(Exception):
    """SIGTERM, SIGINT or the test's own time limit (SIGALRM) during the test: the run is ended and everything put
    back."""


STOPS = (signal.SIGTERM, signal.SIGINT, signal.SIGALRM)
# The test's own limit, inside the boot check's (tt_fpga.WIRING_TIMEOUT), which kills it outright: at this limit it
# still stops cleanly and puts everything back (and has time left for the SDK fallback below). A passing run on the
# TT07 board took 22.7 s (8 Oct 2026): about four times that.
TIME_LIMIT = 90
# The most the teardown after the limit takes, every step bounded: a pin-id round's stop 10 s (if the limit came while
# it sent), resync 5 s, mem 5 s, sdk restore 30 s, leaving the command server 6 s; putting the Pi back: 22 pinctrl
# calls at PINCTRL_TIMEOUT (44 s) and 6 commands at COMMAND_TIMEOUT (30 s). Then, only if the board was not put
# back, the SDK fallback, at most FALLBACK_SECONDS.
TEARDOWN_SECONDS = 10 + 5 + 5 + 30 + 6 + 22 * 2 + 6 * 5
FALLBACK_SECONDS = 75
# Lines a reader of the boot report needs, which keeps only the end of the output: said again after the report.
KEPT = ("MEM:", "PULLS:", "FALLBACK:", "RESTORE:", "READINGS:")


def _stop(signum, frame):
    # The first stop ends the run; the restore that follows is not cut short by another.
    for sig in STOPS:
        signal.signal(sig, signal.SIG_IGN)
    signal.alarm(0)
    raise Stopped("its own time limit" if signum == signal.SIGALRM else f"signal {signum}")


def said(line):
    print(f"{SAYS} {line}")


def sdk_fallback(port):
    """Start the board's SDK again by a soft reset (tt_sdk_start.py, next to this script): only when the board could
    not be put back from RAM, so it is never left in the command server. None when it started, else why not."""
    script = pathlib.Path(__file__).resolve().parent / "tt_sdk_start.py"
    try:
        p = subprocess.run([sys.executable, str(script), port], capture_output=True, text=True,
                           timeout=FALLBACK_SECONDS)  # fmt: skip
    except (OSError, subprocess.TimeoutExpired) as e:
        return repr(e)
    said_lines = [ln for ln in p.stdout.splitlines() if ln.startswith("SDK_START:")]
    return None if p.returncode == 0 else " ".join(said_lines[-1:]) or f"tt_sdk_start.py exited {p.returncode}"


def main(argv=None):
    """Exit 0: the wiring is right. 1: it is not, or a reading was not steady (the WIRING: line says which
    ribbon and pin). 2: the test could not be made, and why; or what it changed was not put back."""
    args = parse_args(argv)
    kept = []

    def out(line=""):
        print(line)
        if str(line).startswith(KEPT):
            kept.append(line)

    print("=== TT PMOD wiring test ===")
    print(f"Port: {args.port}   Controller: {args.controller}   ASIC project: {args.asic_project}")
    env = PiEnvironment(manage_daemon=args.daemon, unload_modules=args.unload, log=out)
    if env.pins is None:
        said("the wiring was not tested: tt_dip_switches.py (its pinctrl helpers) is not next to this script")
        return 2
    pin_scanner = None
    if args.method in ("pin-id", "both"):
        pinid = load_sibling("identify_pmod_pins")
        if pinid is None:
            said("the wiring was not tested: identify_pmod_pins.py (the pin-id decoder) is not next to this script")
            return 2
        pin_scanner = make_pin_id_scanner(pinid)
    result, code, line, back = None, 2, None, []
    board_back = None  # why the board could not be put back from RAM, or None
    link, hat, served = None, None, False
    before = {sig: signal.signal(sig, _stop) for sig in STOPS}
    signal.alarm(args.time_limit)
    try:
        env.enter()
        # All 21 lines in one request: nothing is driven until every line,
        # the console UART's included, is a plain input.
        hat = HatGpio(ALL_HAT_GPIOS)
        hat.open("down")
        print(f"GPIO chip: {hat.chip_path}, {len(ALL_HAT_GPIOS)} HAT lines as inputs")
        fd = open_raw_serial(args.port)
        link = Rp2Link(fd, log=print)
        served = True  # from here the board may be in the command server
        ready = start_firmware(link, build_firmware(args.controller))
        print("RP2 command server running")
        try:
            free = mem_free(ready)
            out(f"MEM: {free} bytes of the RP2's heap free with the command server loaded")
            if free is None or free < MIN_HEAP_FREE:
                raise RuntimeError(f"RP2040 heap too low: {free} bytes free with the command server loaded (the "
                                   f"test needs {MIN_HEAP_FREE})")  # fmt: skip
            result = run_wiring_test(link, hat, args, log=out, pin_scanner=pin_scanner)
        finally:
            for sig in STOPS:  # the teardown is not cut short by a stop
                signal.signal(sig, signal.SIG_IGN)
            signal.alarm(0)
            try:
                link.resync()  # a command a stop cut short may still have its reply on the way
            except ProtocolError as e:  # nothing it answers now can be trusted: the fallback puts the board back
                board_back = f"the board's replies were out of step ({e})"
            if board_back is None:
                try:
                    out(f"MEM: {mem_free(link.cmd('mem', timeout=5))} bytes of the RP2's heap free after the test")
                except ProtocolError as e:
                    out(f"MEM: not read after the test: {e}")
                if args.fpga_reset:
                    try:
                        link.cmd("creset 1", timeout=5)
                    except ProtocolError as e:
                        board_back = f"the FPGA reset was not released: {e}"
            if args.sdk and board_back is None:
                try:
                    restored = " ".join(link.cmd("sdk restore", timeout=30)[1:])
                    out(f"RESTORE: {restored}")
                    if "not changed" in restored:  # the SDK was never used, but the server released its pins
                        board_back = "the board's SDK was not used, so its pins were left released"

                except ProtocolError as e:
                    board_back = f"the board's SDK state could not be put back from RAM: {e}"
            stop_firmware(link)
            served = board_back is not None
    except Unclear as e:
        code = 1
        line = UNCLEAR.format(
            ribbons=ribbons_at(
                {CABLINGS[args.cabling if args.cabling != "auto" else "asic"][g] for g in ("uio", "uo_out")},
                args.cabling if args.cabling != "auto" else "asic",
            )
        )
        out(f"READINGS: the chip's uo_out did not follow uio before the walks: {e}")
    except UnstableReading as e:
        code, line = 1, f"the readings were not steady, so the wiring is not known to be right: {e}"
    except Stopped as e:
        code, line = 2, f"the wiring test was stopped ({e}): the wiring was not tested"
    except (ProtocolError, RuntimeError, OSError) as e:
        code, line = 2, f"the wiring could not be tested: {e}"
    except Exception as e:
        code, line = 2, f"the wiring test failed unexpectedly: {type(e).__name__}: {e}"
    finally:
        for sig in STOPS:  # the restore is not cut short by a stop
            signal.signal(sig, signal.SIG_IGN)
        signal.alarm(0)
        try:
            if link is not None:
                if served:  # stopped part way: leave the command server and the raw REPL, as start-up errors do
                    with contextlib.suppress(OSError):
                        link.write(b"\r\x03\x03\x02")
                os.close(link.fd)
            if hat is not None:
                hat.close()
        finally:
            try:
                back = env.leave()
            except Exception as e:
                back = [f"putting the Pi back failed: {type(e).__name__}: {e}"]
            if link is not None and (served or board_back):
                why_not = sdk_fallback(args.port)
                started = "it was started again" if why_not is None else f"starting it again failed too ({why_not})"
                out(
                    f"FALLBACK: the board was not put back from RAM, so its SDK was started by a soft reset "
                    f"(tt_sdk_start.py): {started}; the board's own main.py rewrites /boot.log when it starts"
                )
                board_back = (board_back or "the board was left in the test's command server") + (
                    "; its SDK was started again by a soft reset" if why_not is None
                    else f"; its SDK did not start again ({why_not})")  # fmt: skip
            for sig, handler in before.items():
                signal.signal(sig, handler)

    if result is not None:
        try:
            report(result, args.discover, log=out)
            if args.json:
                pathlib.Path(args.json).write_text(json.dumps(result, indent=2))
            if args.discover:
                code, line = (0 if any(result["observed"].values()) else 1), "measured map only, no verdict"
            else:
                code, line = verdict(result, args.strict)
        except Exception as e:  # the report's own failure is the test's, never the wiring's
            code, line = 2, f"the wiring test failed unexpectedly while judging: {type(e).__name__}: {e}"
    if back:
        print("Not put back: " + "; ".join(back))
        code, line = 2, f"{line}; and the Pi was not put back as it was ({'; '.join(back)})"
    if board_back:
        code, line = 2, f"{line}; and {board_back}"
    print("")
    if result is not None and code == 1:
        for reading in result.get("readings", []):
            out(f"READINGS: {reading}")
    for kept_line in kept:  # again, where the boot report keeps them
        print(kept_line)
    said(line)
    print(f"RESULT: {'PASS' if code == 0 else 'FAIL'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
