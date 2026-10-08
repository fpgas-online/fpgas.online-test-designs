#!/usr/bin/env python3
"""Read who a Fomu EVT is through the Raspberry Pi header it sits on (#200): hold its iCE40 in reset, read its
SPI flash's JEDEC ID and 64-bit unique ID over the shared SPI pins, and let the iCE40 boot from its flash again.

The EVT's header (im-tomu/fomu-hardware, branch evt, hardware/pcb/tomu-fpga.sch; the same pins as fomu-flash):

  BCM 27  CRESET  the iCE40's reset (low: in reset, its SPI pins released); also the board's reset button
  BCM 17  CDONE   high once the iCE40 has loaded a design
  BCM 8   SPI_CS  the flash's /CS, the iCE40's SPI_SS
  BCM 10  MOSI    the flash's DI, the iCE40's SPI_SO
  BCM 9   MISO    the flash's DO, the iCE40's SPI_SI
  BCM 11  CLK     the flash's CLK, the iCE40's SPI_SCK
  BCM 24  IO2     the flash's /WP
  BCM 25  IO3     the flash's /HOLD

The order is what keeps both sides safe:

 1. Every line is taken as an input, and CDONE is read. It must be high (an iCE40 has loaded a design), or
    nothing is driven at all: CDONE falling in step 2 would prove nothing.
 2. CRESET is driven low, and CDONE must fall. If it does not, no iCE40 is held on that reset and its flash
    bus may be in use, so the bus is never driven: CRESET is let go and the script says so.
 3. With the iCE40 in reset the Pi is the only master on the flash's bus. It sends read commands only: the
    opcodes in READ_ONLY, and nothing else can be sent. /WP is held low, so no status register can be
    written either.
 4. Every SPI line goes back to an input BEFORE CRESET is let go, so the iCE40 masters its flash alone when it
    boots. CRESET then goes back to an input too, and the board's pull-up takes it high. If an SPI line will
    not go back to an input, CRESET is not let go: the lines are given back to the kernel, CRESET last, and
    the Pi's pin controller makes each freed line an input.
 5. CDONE must rise again within BOOT_WAIT: the iCE40 has booted from its flash, as at power-up.

Nothing is written to the flash, and every line is given back an input whatever went wrong. A run stops whatever
design the iCE40 was running (the reset), so only the boot check runs it.

It prints one line, `fomu-header: {json}`, with what it read, and exits 0. It exits 2, with `fomu-header-error:
<why>`, when the GPIO lines could not be used. The board module (fpgas_online_verify.boards.fomu) judges the
reading. Requirements: python3-libgpiod (v1.6+ or v2.x).
"""

import json
import pathlib
import sys
import time

try:
    import gpiod
except ImportError:  # only on a Raspberry Pi
    gpiod = None

CRESET, CDONE = 27, 17
CS, MOSI, MISO, CLK, WP, HOLD = 8, 10, 9, 11, 24, 25
LINES = (CDONE, CS, MOSI, MISO, CLK, WP, HOLD, CRESET)  # CRESET last: lines are given back in this order
SPI_OUTPUTS = (CS, MOSI, CLK, WP, HOLD)

RELEASE_POWER_DOWN, READ_STATUS_1, READ_STATUS_2, READ_STATUS_3 = 0xAB, 0x05, 0x35, 0x15
READ_JEDEC_ID, READ_UNIQUE_ID = 0x9F, 0x4B
# Every opcode this script can send: reads, and the wake from deep power-down (which changes no stored bit).
READ_ONLY = frozenset((RELEASE_POWER_DOWN, READ_STATUS_1, READ_STATUS_2, READ_STATUS_3, READ_JEDEC_ID, READ_UNIQUE_ID))
UNIQUE_ID_DUMMIES, UNIQUE_ID_BYTES = 4, 8  # W25Q128JV: 4Bh, 4 dummy bytes, then UID63-0
BUSY = 0x01  # status register 1: an erase or program is under way

RESET_HOLD = 0.001  # s with CRESET low before CDONE is read (the iCE40 needs 200 ns)
WAKE = 0.001  # s after the wake from deep power-down (the W25Q128JV needs 3 us)
BUSY_WAIT = 5.0  # s to wait for an erase or program a design left going to end, before reading
BOOT_WAIT = 3.0  # s for CDONE to rise again once CRESET is let go

GPIO_CHIP_LABELS = {"pinctrl-rp1", "pinctrl-bcm2711", "pinctrl-bcm2835"}
CONSUMER = "fpgas-fomu-header"


class NotSent(Exception):
    """A command that is not in READ_ONLY: a bug, and nothing was sent."""


class Lines:
    """The header's lines through libgpiod (v2.x, or v1.6+): all requested as inputs; output(), set(), get(),
    input() per line; close() makes every line an input again and releases them."""

    def __init__(self, gpios, chip_path):
        self.gpios = list(gpios)
        self.v2 = hasattr(gpiod, "request_lines")
        self.outputs = {}  # gpio -> level, the lines driven now
        if self.v2:
            self.request = gpiod.request_lines(chip_path, consumer=CONSUMER, config=self._config())
        else:
            self.chip = gpiod.Chip(chip_path)
            self.lines = {g: self.chip.get_line(g) for g in self.gpios}
            for line in self.lines.values():
                line.request(consumer=CONSUMER, type=gpiod.LINE_REQ_DIR_IN)

    def _config(self):
        inp = gpiod.LineSettings(direction=gpiod.line.Direction.INPUT)
        config = {g: inp for g in self.gpios if g not in self.outputs}
        for g, level in self.outputs.items():
            value = gpiod.line.Value.ACTIVE if level else gpiod.line.Value.INACTIVE
            config[g] = gpiod.LineSettings(direction=gpiod.line.Direction.OUTPUT, output_value=value)
        return config

    def output(self, gpio, level):
        self.outputs[gpio] = level
        if self.v2:
            self.request.reconfigure_lines(self._config())
        else:
            self.lines[gpio].set_direction_output(level)

    def input(self, gpio):
        """`gpio` an input; it stays in `outputs`, as driven, unless that worked."""
        if self.v2:
            level = self.outputs.pop(gpio, None)
            try:
                self.request.reconfigure_lines(self._config())
            except OSError:
                if level is not None:
                    self.outputs[gpio] = level
                raise
        else:
            self.lines[gpio].set_direction_input()
            self.outputs.pop(gpio, None)

    def set(self, gpio, level):
        self.outputs[gpio] = level
        if self.v2:
            self.request.set_value(gpio, gpiod.line.Value.ACTIVE if level else gpiod.line.Value.INACTIVE)
        else:
            self.lines[gpio].set_value(level)

    def get(self, gpio):
        if self.v2:
            return 1 if self.request.get_value(gpio) == gpiod.line.Value.ACTIVE else 0
        return int(self.lines[gpio].get_value())

    def close(self):
        """Every line an input again, CRESET last, and the lines given back to the kernel, CRESET last. When a
        line will not go back to an input, CRESET is not let go while the Pi holds the lines: giving them back
        then leaves it to the kernel, whose Raspberry Pi pin controller makes each freed line an input, CRESET
        after the others. The script cannot hold CRESET low past its own exit."""
        stuck = release(self, [g for g in self.outputs if g != CRESET])
        if CRESET in self.outputs and not stuck:
            self.input(CRESET)
        if self.v2:
            self.request.release()
        else:
            for line in self.lines.values():
                line.release()
            self.chip.close()
        if stuck:
            raise OSError(f"{'; '.join(stuck)}: CRESET was not let go before the lines were given back (CRESET last)")


class Spi:
    """SPI mode 0, MSB first, bit-banged on `pins` (Lines, or a test's model). Only READ_ONLY opcodes."""

    def __init__(self, pins):
        self.pins = pins

    def command(self, opcode, dummies=0, read=0):
        if opcode not in READ_ONLY:
            raise NotSent(f"opcode {opcode:#04x} is not a read: not sent")
        self.pins.set(CS, 0)
        try:
            for byte in (opcode, *[0] * dummies):
                for bit in range(7, -1, -1):
                    self.pins.set(MOSI, byte >> bit & 1)
                    self.pins.set(CLK, 1)
                    self.pins.set(CLK, 0)
            self.pins.set(MOSI, 0)
            out = []
            for _ in range(read):
                byte = 0
                for _ in range(8):
                    self.pins.set(CLK, 1)
                    byte = byte << 1 | self.pins.get(MISO)
                    self.pins.set(CLK, 0)
                out.append(byte)
            return bytes(out)
        finally:
            self.pins.set(CS, 1)


def release(pins, gpios):
    """Each of `gpios` an input again, every one tried whatever the others do: what failed, in words."""
    stuck = []
    for gpio in gpios:
        try:
            pins.input(gpio)
        except OSError as e:
            stuck.append(f"GPIO{gpio} could not be set back to an input ({e})")
    return stuck


def read_flash(spi, sleep=time.sleep, clock=time.monotonic):
    """{"jedec", "uid", "status"} read from the flash, the iCE40 in reset."""
    spi.command(RELEASE_POWER_DOWN)
    sleep(WAKE)
    deadline = clock() + BUSY_WAIT
    status1 = spi.command(READ_STATUS_1, read=1)[0]
    busy_seen = bool(status1 & BUSY)
    while status1 & BUSY and clock() < deadline:  # a design was writing it when the reset came: let that end
        sleep(0.05)
        status1 = spi.command(READ_STATUS_1, read=1)[0]
    jedec = spi.command(READ_JEDEC_ID, read=3)
    uid = spi.command(READ_UNIQUE_ID, dummies=UNIQUE_ID_DUMMIES, read=UNIQUE_ID_BYTES)
    status = [status1, spi.command(READ_STATUS_2, read=1)[0], spi.command(READ_STATUS_3, read=1)[0]]
    return {"jedec": jedec.hex(), "uid": uid.hex(), "status": [f"{s:02x}" for s in status],
            "busy_at_reset": busy_seen, "busy_after_wait": bool(status1 & BUSY)}  # fmt: skip


def wait_for(pins, gpio, level, limit, sleep=time.sleep, clock=time.monotonic):
    """Seconds until `gpio` read `level`, or None if it did not within `limit`."""
    start = clock()
    while True:
        if pins.get(gpio) == level:
            return round(clock() - start, 3)
        if clock() - start >= limit:
            return None
        sleep(0.01)


def identify(pins, sleep=time.sleep, clock=time.monotonic):
    """The reading. `pins` has all LINES as inputs; every line is an input again when this returns or raises,
    except CRESET when an SPI line could not be set back to an input: it stays low (see Lines.close)."""
    out = {"cdone_before": pins.get(CDONE), "creset_before": pins.get(CRESET)}
    if out["cdone_before"] != 1:  # no design loaded, or nothing there: CDONE falling would prove nothing
        out["flash"] = None
        return out
    stuck = []
    try:
        pins.output(CRESET, 0)
        sleep(RESET_HOLD)
        out["cdone_in_reset"] = pins.get(CDONE)
        if out["cdone_in_reset"] != 0:
            out["flash"] = None  # no iCE40 held on that reset: its bus may be in use, so it is not driven
            return out
        try:
            pins.output(CS, 1)  # the flash deselected before any other line moves
            pins.output(WP, 0)  # status registers protected while the Pi has the bus
            pins.output(HOLD, 1)
            pins.output(CLK, 0)
            pins.output(MOSI, 0)
            out["flash"] = read_flash(Spi(pins), sleep, clock)
        finally:
            stuck = release(pins, SPI_OUTPUTS)  # the bus is the iCE40's again before it leaves reset
    finally:
        if not stuck:
            pins.input(CRESET)
    if stuck:
        raise OSError(f"{'; '.join(stuck)}: CRESET is still held low")
    out["boot_seconds"] = wait_for(pins, CDONE, 1, BOOT_WAIT, sleep, clock)
    out["cdone_after"] = pins.get(CDONE)
    return out


def header_chip():
    """The gpiochip of the 40-pin header, by its label."""
    for chip_path in sorted(pathlib.Path("/dev").glob("gpiochip*")):
        try:
            chip = gpiod.Chip(str(chip_path))
            label = chip.get_info().label if hasattr(gpiod, "request_lines") else chip.label()
            chip.close()
        except OSError:
            continue
        if label in GPIO_CHIP_LABELS:
            return str(chip_path)
    raise OSError("no GPIO chip with a Raspberry Pi header's label")


def main():
    if gpiod is None:
        print("fomu-header-error: python3-libgpiod (the gpiod module) is not installed")
        return 2
    try:
        pins = Lines(LINES, header_chip())
    except OSError as e:
        print(f"fomu-header-error: the header's GPIO lines could not be taken: {e}")
        return 2
    faults, reading = [], None
    try:
        reading = identify(pins)
    except Exception as e:  # whatever it was, the lines are still given back below, and it is said
        faults.append(f"the reading failed: {type(e).__name__}: {e}")
    try:
        pins.close()
    except OSError as e:
        faults.append(f"the lines could not all be given back: {e}")
    if faults:
        print("fomu-header-error: " + "; ".join(faults))
        return 2
    print("fomu-header: " + json.dumps(reading, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
