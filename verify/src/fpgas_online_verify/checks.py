"""Which checks a board's boot check should run, in which group, and why a check cannot apply (#340, #339).

Tim, 15 Oct 2026, of the fleet page: "A huge number of boards are not getting the basic, memory and peripheral
checks. *Anything* which has an FPGA should be getting jtag, anything which has wires should be getting wiring,
etc." So every board type answers for each COMMON check: it is planned (a test of the board's check runs it), or
it is not applicable to that board's hardware, with the reason (Board.not_applicable). tests/test_verify_boards.py
holds every board type to that.

The report carries, per board (runner.plan):

  planned         every test the board's check should run, in running order, also when the check stopped first
  groups          {test: group} for each planned test: one of GROUPS (the site's check columns are grouped so)
  not_applicable  {common check: why the board cannot have it}
  not_run         {test: why} for each planned test that did not run (a test that is not written yet included)

A check is one name on every board: `wiring` is the Pmod cabling test on every board that has one (it was `pin-id`
on the Arty, NeTV2, Fomu and TT FPGA, and `wiring` on the board with a Tiny Tapeout chip), and `flash` the flash
test (it was `spiflash` on the Arty, NeTV2 and Fomu, and `flash` on the Acorn).
"""

GROUPS = ("basic", "memory", "peripherals", "board-specific")

# Every test name a board's check can report, and its group. A name missing here is a KeyError, never a guess:
# tests/test_verify_boards.py checks every board's tests are in it.
GROUP_OF = {
    "jtag": "basic",
    "header": "basic",
    "wiring": "basic",
    "flash": "memory",
    "ddr": "memory",
    "spram": "memory",
    "uart": "peripherals",
    "p2-uart": "peripherals",
    "p2-serial": "peripherals",
    "p2-gpio": "peripherals",
    "ethernet": "peripherals",
    "pcie-link": "board-specific",
    "pcie-bar0": "board-specific",
    "power-cycle": "board-specific",
    "rp1-pio": "board-specific",
    "scratch": "board-specific",
    "foboot": "board-specific",
    "foboot-after": "board-specific",
    "sdk": "board-specific",
    "dip-switches": "board-specific",
    "pmod": "board-specific",
}

# The checks every board type answers for: planned, or not applicable with the reason.
COMMON = ("jtag", "wiring", "flash", "ddr", "uart", "ethernet")

# A test a board's hardware calls for that its boot check does not run yet (Board.untested): it is planned, and
# not run with this reason. Whether that fails the board is Tim's call (coord-64, 15 Oct 2026); until he says,
# it does not: the board keeps its result and the site shows the test as should-have-run.
UNTESTED_FAILS = False
NO_TEST_YET = "no boot-check test yet: fpgas.online-test-designs #{issue}"

# The planned tests' reason when the check stopped before them, with the reason the board's check gave.
STOPPED = "the check stopped before it: {reason}"
STOPPED_NO_REASON = "the check stopped before it"
# The site keeps 300 characters of an event value. A per-test reason longer than that is cut here, saying so; the
# whole of it is in the board's reason (board<i>_reason) and the report.
FIT = 300
CUT = " … (the whole reason is the board's)"


def untested_reasons(untested):
    """{test: why} for Board.untested's {test: issue number}."""
    return {test: NO_TEST_YET.format(issue=issue) for test, issue in untested.items()}


def stopped(reason):
    """A planned test's not_run reason when the check stopped before it."""
    return STOPPED.format(reason=reason) if reason else STOPPED_NO_REASON


def fit(text):
    """`text` as an event value the site keeps whole: at most FIT characters, a cut said with CUT."""
    return text if len(text) <= FIT else text[: FIT - len(CUT)] + CUT


def groups(planned):
    """{test: group} for the planned tests."""
    return {test: GROUP_OF[test] for test in planned}
