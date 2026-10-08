"""designs/_host/fomu_header_id.py against a model of a Fomu EVT on a Pi's header (#200).

The model is the EVT's wiring: CRESET resets an iCE40 whose CDONE falls in reset and rises when it has booted
from its flash; the flash (a W25Q128JV) answers bit-banged SPI mode 0 on the shared pins. It records every
moment the Pi drives a flash line while the iCE40 is out of reset (contention: the iCE40 owns that bus then),
and every opcode the flash was sent, so the tests prove the script never fights the iCE40 and never sends a
write."""

import importlib.util
import pathlib

import pytest

_PATH = pathlib.Path(__file__).parents[1] / "designs" / "_host" / "fomu_header_id.py"
_spec = importlib.util.spec_from_file_location("fomu_header_id", _PATH)
fhi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fhi)

JEDEC = bytes.fromhex("ef7018")
UID = bytes.fromhex("e4613c4813475c2a")
BUS = (fhi.CS, fhi.MOSI, fhi.CLK, fhi.WP, fhi.HOLD, fhi.MISO)


class Clock:
    def __init__(self):
        self.now = 0.0

    def sleep(self, s):
        self.now += s

    def __call__(self):
        return self.now


class Evt:
    """The Pi's side of the header lines (fhi.Lines' interface) and the board behind them."""

    def __init__(self, clock, ice40=True, busy_reads=0, boots=True, fail_at=None):
        self.clock = clock
        self.ice40 = ice40  # False: nothing on CRESET/CDONE (a header with no Fomu, CDONE held high by something)
        self.boots = boots
        self.driven = {}  # gpio -> level the Pi drives
        self.cdone = 1
        self.events = []  # what happened, in order
        self.contention = []
        self.opcodes = []
        self.busy_reads = busy_reads
        self.fail_at = fail_at  # raise OSError on this set() call number
        self.sets = 0
        self.closed = False
        self._bits, self._out, self._edges = [], [], 0

    # -- the iCE40 ------------------------------------------------------------------------------------------
    def in_reset(self):
        return self.ice40 and self.driven.get(fhi.CRESET) == 0

    def _check_bus(self):
        if not self.in_reset() and any(g in self.driven for g in BUS):
            self.contention.append(dict(self.driven))

    # -- fhi.Lines --------------------------------------------------------------------------------------------
    def output(self, gpio, level):
        self.driven[gpio] = level
        self.events.append(("output", gpio, level))
        if gpio == fhi.CRESET and level == 0 and self.ice40:
            self.cdone = 0
        self._check_bus()

    def input(self, gpio):
        was_reset = self.in_reset()
        self.driven.pop(gpio, None)
        self.events.append(("input", gpio))
        if gpio == fhi.CRESET and was_reset and self.boots:
            self.boot_at = self.clock.now + 0.2  # the iCE40 boots from its flash
        self._check_bus()

    def set(self, gpio, level):
        self.sets += 1
        if self.fail_at is not None and self.sets == self.fail_at:
            raise OSError("line went away")
        if gpio not in self.driven:
            raise AssertionError(f"set() on GPIO{gpio}, which is not an output")
        old = self.driven[gpio]
        self.driven[gpio] = level
        self._check_bus()
        if gpio == fhi.CS and level == 0:
            self._bits, self._out, self._edges = [], [], 0
        if gpio == fhi.CS and level == 1 and old == 0:
            self.events.append(("cs-high",))
        if gpio == fhi.CLK and level == 1 and old == 0 and self.driven.get(fhi.CS) == 0 and self.in_reset():
            if len(self._bits) < 8:  # the opcode, MSB first
                self._bits.append(self.driven[fhi.MOSI])
                if len(self._bits) == 8:
                    op = int("".join(map(str, self._bits)), 2)
                    self.opcodes.append(op)
                    self._out = self._answer(op)
            else:  # each edge after it: the flash's next bit is on MISO until the next one
                self._edges += 1

    def _answer(self, op):
        if op == fhi.READ_JEDEC_ID:
            data = JEDEC
        elif op == fhi.READ_UNIQUE_ID:
            data = bytes(4) + UID  # the 4 dummy bytes clock out nothing useful
        elif op == fhi.READ_STATUS_1:
            if self.busy_reads:
                self.busy_reads -= 1
                data = b"\x01"
            else:
                data = b"\x00"
        elif op in (fhi.READ_STATUS_2, fhi.READ_STATUS_3):
            data = b"\x02"
        else:
            data = b""
        return [b >> (7 - i) & 1 for b in data for i in range(8)]

    def get(self, gpio):
        if gpio == fhi.CDONE:
            if not self.ice40:
                return 1
            if getattr(self, "boot_at", None) is not None and self.clock.now >= self.boot_at:
                self.cdone = 1
            return self.cdone
        if gpio == fhi.MISO:
            if self.driven.get(fhi.CS) != 0 or not 1 <= self._edges <= len(self._out):
                return 1  # released, pulled high
            return self._out[self._edges - 1]
        if gpio == fhi.CRESET:
            return self.driven.get(fhi.CRESET, 1)
        return 1


def run(evt, clock):
    return fhi.identify(evt, clock.sleep, clock)


def test_reads_the_flash_ids_with_the_ice40_in_reset_and_lets_it_boot():
    clock = Clock()
    evt = Evt(clock)
    out = run(evt, clock)
    assert out["cdone_before"] == 1 and out["cdone_in_reset"] == 0 and out["cdone_after"] == 1
    assert out["flash"]["jedec"] == "ef7018" and out["flash"]["uid"] == UID.hex()
    assert out["flash"]["status"] == ["00", "02", "02"] and out["flash"]["busy_at_reset"] is False
    assert out["boot_seconds"] is not None and out["boot_seconds"] <= fhi.BOOT_WAIT
    assert evt.driven == {}, "every line is an input at the end"
    assert evt.contention == []


def test_only_read_opcodes_reach_the_flash():
    clock = Clock()
    evt = Evt(clock)
    run(evt, clock)
    assert set(evt.opcodes) <= fhi.READ_ONLY
    assert evt.opcodes[0] == fhi.RELEASE_POWER_DOWN
    assert fhi.READ_JEDEC_ID in evt.opcodes and fhi.READ_UNIQUE_ID in evt.opcodes


def test_the_allow_list_holds_no_write_opcode():
    writes = {0x06, 0x04, 0x02, 0x32, 0x20, 0x52, 0xD8, 0xC7, 0x60, 0x01, 0x31, 0x11, 0x42, 0x44, 0x66, 0x99, 0x50,
              0xB9, 0x38, 0xE8, 0x36, 0x39, 0x7E, 0x98}  # fmt: skip
    assert not writes & fhi.READ_ONLY


@pytest.mark.parametrize("op", [0x06, 0x02, 0x20, 0xC7, 0x01])
def test_a_write_opcode_is_refused_before_anything_is_driven(op):
    clock = Clock()
    evt = Evt(clock)
    evt.output(fhi.CRESET, 0)
    evt.output(fhi.CS, 1)
    evt.events.clear()
    with pytest.raises(fhi.NotSent):
        fhi.Spi(evt).command(op)
    assert evt.events == [] and evt.opcodes == []


def test_the_spi_lines_are_inputs_before_creset_is_let_go():
    clock = Clock()
    evt = Evt(clock)
    run(evt, clock)
    release = evt.events.index(("input", fhi.CRESET))
    for gpio in fhi.SPI_OUTPUTS:
        assert ("input", gpio) in evt.events[:release], f"GPIO{gpio} still driven when CRESET was let go"
    assert evt.events[0] == ("output", fhi.CRESET, 0), "nothing is driven before the reset"


def test_wp_is_low_while_the_pi_has_the_bus():
    clock = Clock()
    evt = Evt(clock)
    run(evt, clock)
    first_cs = next(i for i, e in enumerate(evt.events) if e == ("output", fhi.CS, 1))
    assert ("output", fhi.WP, 0) in evt.events[:first_cs]


def test_no_ice40_on_the_reset_means_the_bus_is_never_driven():
    clock = Clock()
    evt = Evt(clock, ice40=False)
    out = run(evt, clock)
    assert out["cdone_in_reset"] == 1 and out["flash"] is None
    assert [e for e in evt.events if e[1:2] and e[1] in BUS] == []
    assert evt.opcodes == [] and evt.driven == {}


def test_a_flash_left_busy_by_a_design_is_waited_for():
    clock = Clock()
    evt = Evt(clock, busy_reads=3)
    out = run(evt, clock)
    assert out["flash"]["busy_at_reset"] is True and out["flash"]["busy_after_wait"] is False
    assert out["flash"]["jedec"] == "ef7018"


def test_an_ice40_that_does_not_boot_again_is_said():
    clock = Clock()
    evt = Evt(clock, boots=False)
    out = run(evt, clock)
    assert out["boot_seconds"] is None and out["cdone_after"] == 0
    assert evt.driven == {}


@pytest.mark.parametrize("fail_at", [1, 5, 40, 200])
def test_a_line_that_fails_mid_read_leaves_every_line_an_input(fail_at):
    clock = Clock()
    evt = Evt(clock, fail_at=fail_at)
    with pytest.raises(OSError):
        run(evt, clock)
    assert evt.driven == {}
    assert evt.contention == []
