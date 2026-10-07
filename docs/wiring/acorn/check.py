# SPDX-License-Identifier: Apache-2.0
"""Checking an Acorn's wiring with fpgas-verify: the "verifying" pages of each carrier, and their picture.

The pages of a carrier are for one reader: someone with an Acorn on that carrier who has built the cables
and wants to know whether they are right. Part 1 is running the check and reading its result, part 2 going
from a failing line to the wire, part 2b the messages that are not about a wire, and on a blade part 3 what
has been run on one. They are assembled from

* the words in check/*.md, which both pages share. A line starting `<!-- pi5 -->` or `<!-- blade -->` is
  for that carrier only, and so is a block between `<!-- pi5:begin -->` and `<!-- pi5:end -->`;
* wiring.toml, for which wire of which cable goes to which pin of this carrier (the picture, and what to
  swap when a pair is crossed);
* the tool's reference, docs/verify/: reading-the-result.md for the transcripts of real runs and
  common-failures.md for the Acorn rows of its "Common failures" table, so that each exists once;
* the cavity pictures steps.py draws, shown again where a failing line has to be taken to a wire.

gen.py's build() calls build() here, so the pages are part of generated/ and of `gen.py --check`.
"""

import math
import re

import steps
import tables
import wiring
from gen import pin_label
from sheetlib import INK, MUTED, RED, SIGNALS, Sheet, label_of
from steps import GREY, LINE, WIRE, T, W

FRAGMENTS = wiring.HERE / "check"
VERIFY = wiring.HERE.parent.parent / "verify"  # docs/verify/, the tool's reference
RESULTS = VERIFY / "reading-the-result.md"  # the transcripts of real runs
COMMON_FAILURES = VERIFY / "common-failures.md"  # the table of messages and what to do
SITE = "https://docs.fpgas.online/en/latest"
CONVERTING = f"{SITE}/boards/acorn/pcie-programming.html"
FAILURES = f"{SITE}/verify/common-failures.html#common-failures"

# Which test proves which wire. A ground wire is every test's return.
USES = {
    "TCK": "jtag",
    "TMS": "jtag",
    "TDO": "jtag",
    "TDI": "jtag, its device DNA read",
    "J2": "p2-uart, p2-serial",
    "K2": "p2-uart, p2-serial",
    "J5": "p2-gpio",
    "H5": "p2-gpio",
}
# The rows of verify/common-failures.md's "Common failures" that are about an Acorn: each named by the start of
# its first cell.
ACORN_FAILURES = [
    "`fail`: `unconverted: …`",
    "`fail`: `… is not a design we built`",
    "`fail`: `running the golden image`",
    "`fail`: `link is x2, expected x1`",
    "`fail`: `no device on the P1 JTAG chain`",
    "`fail`: `P1 JTAG could not be probed: GPIO14 (TMS) is held by",
    "`fail`: `… gpiod_line_request_set_values_subset: Assertion",
    "`fail`: `openFPGALoader printed no raw IDCODE scan",
    "`fail`: `… failed (exit N) before scanning the JTAG chain",
    "`fail`: `device DNA over P1 JTAG reads 0x…",
    "`fail`: `device DNA over JTAG … is not the one over BAR0`",
    "`fail`: `J5 -> GPIO3:",
    "`fail`: `K2 -> GPIO15:",
    "`fail`: `DRAM write",
    "`fail`: `power-cycle fail:",
    "`error`: `this host (…) is not an Acorn setup in wiring.toml`",
    "`error`: `… does not match its manifest`",
    "`changed`",
]
# A row that can only be met on one carrier: the marks are looked for in the row's start above.
ONLY = {
    "blade": ["GPIO14 (TMS) is held by", "gpiod_line_request_set_values_subset"],
    "pi5": ["`J5 -> GPIO3:", "power-cycle fail:"],  # the power-cycle check was measured on a Pi 5 only
}
if set(ONLY) - set(wiring.CARRIERS) or any(
    sum(m in s for s in ACORN_FAILURES) != 1 for ms in ONLY.values() for m in ms
):
    raise wiring.WiringError("check.py: ONLY names a carrier or a row that is not there")


def name(c, part):
    """The file of one page: part 1 run and read, 2 a failing line to its wire, 2b the other messages, 3 (a
    blade) what has been run."""
    return f"acorn-check-{c.key}-{part}.md"


def picture_name(c):
    return f"acorn-check-{c.key}-wires.svg"


# ----------------------------------------------------------------------------------------------
# The words
# ----------------------------------------------------------------------------------------------
def fragment(file, c):
    """check/<file> as it reads for carrier `c`: the other carrier's lines and blocks are left out."""
    out, open_block = [], None
    for line in (FRAGMENTS / file).read_text().splitlines():
        block = re.fullmatch(r"<!-- (\w+):(begin|end) -->", line.strip())
        if block:
            if block[1] not in wiring.CARRIERS:
                raise wiring.WiringError(f"check/{file}: no carrier {block[1]!r}")
            if (block[2] == "begin") == (open_block is not None) or (block[2] == "end" and block[1] != open_block):
                raise wiring.WiringError(
                    f"check/{file}: {line.strip()} does not pair with the block open ({open_block})"
                )
            open_block = block[1] if block[2] == "begin" else None
            continue
        if open_block not in (None, c.key):
            continue
        mark = re.match(r"<!-- (\w+) -->", line)
        if mark:
            if mark[1] not in wiring.CARRIERS:
                raise wiring.WiringError(f"check/{file}: no carrier {mark[1]!r}")
            if mark[1] != c.key:
                continue
            line = line[mark.end() :]
        out.append(line)
    if open_block:
        raise wiring.WiringError(f"check/{file}: the block {open_block} is not closed")
    text = "\n".join(out).strip() + "\n"
    if "<!--" in text:
        raise wiring.WiringError(f"check/{file}: a mark is not understood: {text[text.index('<!--') :][:40]!r}")
    return text


def transcript(marker, *said):
    """The ```text block of verify/reading-the-result.md under the paragraph starting with `marker`.

    said: words the caption here repeats (a host, a date): they must be in that paragraph, so that a caption
    cannot outlive a change of the transcript it stands over.
    """
    text = RESULTS.read_text()
    if text.count("\n" + marker) != 1:
        raise wiring.WiringError(
            f"docs/verify/reading-the-result.md: {marker!r} starts {text.count(chr(10) + marker)} lines, not one"
        )
    after = text[text.index("\n" + marker) :]
    block = re.search(r"```text\n.*?\n```\n", after, re.S)
    between = after[1 : block.start()] if block else ""
    if not block or any(mark in between for mark in ("\n**", "\n#", "```", "\n\n\n")) or between.count("\n\n") != 1:
        raise wiring.WiringError(
            f"docs/verify/reading-the-result.md: no transcript straight after the paragraph starting {marker!r}"
        )
    missing = [word for word in said if word not in between]
    if missing:
        raise wiring.WiringError(
            f"docs/verify/reading-the-result.md: the paragraph starting {marker!r} no longer says {missing}"
        )
    return block[0]


def without_advice(block):
    """A ```text transcript without its `What to do:` lines, marked as left out: the advice an older version printed
    there must not be printed on a page whose reader it does not apply to."""
    lines = block.strip().split("\n")
    at = [n for n, line in enumerate(lines) if line == "What to do:"]
    if len(at) != 1 or lines[-1] != "```":
        raise wiring.WiringError("a transcript without exactly one `What to do:` line, or not closed by ```")
    return "\n".join([*lines[: at[0]], "What to do: (left out here; see the text above)", "```"])


def failures(c):
    """The Acorn rows of verify/common-failures.md's "Common failures" table that can be met on carrier `c`, as a
    table."""
    text = COMMON_FAILURES.read_text()
    table = text[text.index("## Common failures\n") :].split("\n## ")[0]
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    out = ["| It says | Meaning, and what to do |", "|---|---|"]
    for start in ACORN_FAILURES:
        found = [r for r in rows if r.startswith("| " + start)]
        if len(found) != 1:
            raise wiring.WiringError(
                f"docs/verify/common-failures.md, Common failures: {len(found)} rows start {start!r}, not one"
            )
        other = [key for key, marks in ONLY.items() if key != c.key and any(m in start for m in marks)]
        if not other:
            out.append(site_links(for_carrier(found[0], c), "common-failures"))
    return "\n".join(out) + "\n"


def for_carrier(row, c):
    """A row whose advice differs by host, written as "On a <host>: … On a <other host>: …", keeps only the clause
    for carrier `c`: a reader of one carrier's page is not told what to do on the other."""
    names = [k.name for k in wiring.CARRIERS.values()]
    clause = re.compile(
        r" On a ("
        + "|".join(map(re.escape, names))
        + r"): (.*?)(?= On a (?:"
        + "|".join(map(re.escape, names))
        + r"):| \|$)"
    )
    found = clause.findall(row)
    if not found:
        return row
    if c.name not in [name for name, _ in found]:
        raise wiring.WiringError(f"docs/verify/common-failures.md: a row splits by host but has no clause for {c.name}")
    return clause.sub(
        lambda m: " " + re.sub(r"[a-z]", lambda ch: ch[0].upper(), m.group(2), count=1) if m.group(1) == c.name else "",
        row,
    )


def site_links(text, page=None):
    """Links written from docs/ (check/*.md) or from docs/verify/ (the reference's rows), as they have to read
    from a page of the site.

    A link to a heading of a page of the tool's reference goes to that heading on the site's copy of the page;
    one written as `#heading` is to a heading of `page`, the page of docs/verify/ the text is from."""
    for source in ("../hardware/acorn-pcie-programming.md", "hardware/acorn-pcie-programming.md"):
        text = text.replace(f"[acorn-pcie-programming.md]({source})", f"[converting a card]({CONVERTING})")
        text = text.replace(f"]({source})", f"]({CONVERTING})")
    unplaced = re.search(r"\]\(#[^)]*\)", text)
    if page is None and unplaced:
        raise wiring.WiringError(f"a link to a heading of no page: {unplaced[0]}")
    text = re.sub(r"\]\(#([a-z0-9-]+)\)", rf"]({page}.md#\1)", text)
    return re.sub(r"\]\(([a-z0-9-]+)\.md#([a-z0-9-]+)\)", rf"]({SITE}/verify/\1.html#\2)", text)


def wire_of(sig):
    """(connector, wire number) of a signal."""
    for connector, conn in wiring.CONNECTORS.items():
        if sig in conn["pins"]:
            return connector, conn["pins"].index(sig) + 1
    raise wiring.WiringError(f"{sig} is on no connector")


def swap(c, a, b):
    """What to do when the wires of signals a and b are in each other's cavity."""
    (connector, na), (other, nb) = wire_of(a), wire_of(b)
    if connector != other:
        raise wiring.WiringError(f"{a} and {b} are on different cables: they cannot be in each other's cavity")
    words = (
        f"wires {na} and {nb} of the {connector} cable are in each other's cavity. Take both terminals out of the "
        f"housing and put each in the other's cavity (the {connector} cavity picture below)"
    )
    for sig in (a, b):
        if sig in c.resistors:
            words += f". The {c.resistor_value} resistor stays in wire {wire_of(sig)[1]} ({label_of(sig)})"
    return words


def landing(c, sig):
    """Where a wire lands on the host: ("GPIO10", "header pin 19")."""
    hk, pin = c.wires[sig]
    hdr = c.headers[hk]
    return steps.host_pin(c, pin_label(hdr.pins[pin]["name"])), f"{hdr.short} pin {pin}"


# ----------------------------------------------------------------------------------------------
# The picture: which test uses which wire
# ----------------------------------------------------------------------------------------------
def picture(c):
    """Both cables as the builder flagged them: each wire with where it lands and the test that proves it."""
    sh = Sheet(W, 100)
    steps.title(sh, f"Which test uses which wire: Acorn on a {c.name}", "the wire numbers are the flags you put on")
    y = 104
    rows = 46
    for connector, conn in wiring.CONNECTORS.items():
        pins = conn["pins"]
        sh.text(30, y, f"{connector} cable ({conn['what']})", T + 3, "bold")
        out, body = steps.plug(sh, 76, y + 14, pins)
        for i, sig in enumerate(pins):
            x, y0 = out[sig]
            row = body[3] + 40 + (len(pins) - 1 - i) * rows
            n = i + 1
            if sig in c.wires:
                colour = SIGNALS[sig][0]
                sh.add(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{row}" stroke="{colour}" stroke-width="{WIRE}"/>')
                sh.wire_segments.append((x, y0, x, row - 16))
                steps.token(sh, x, row, n)
                pin, where = landing(c, sig)
                first = f"{label_of(sig)} to {pin}, {where}"
                second = "ground: every test's return" if label_of(sig) == "GND" else f"test: {USES[sig]}"
                sh.text(x + 24, row - 3, first, T, "bold", colour)
                sh.text(x + 24, row - 3 + LINE - 2, second, T, "regular", INK)
            else:
                colour = RED if sig == "VCC" else GREY
                sh.add(f'<line x1="{x}" y1="{y0}" x2="{x}" y2="{y0 + 12}" stroke="{colour}" stroke-width="{WIRE}"/>')
                sh.rect(x - 8, y0 + 8, 16, 22, fill=colour, stroke=INK, sw=1.5, rx=5)
                steps.token(sh, x, row, n)
                why = "3.3 V from the Acorn" if sig == "VCC" else label_of(sig)
                sh.text(x + 24, row - 3, f"{why}: cut back, in no cavity", T, "bold", colour if sig == "VCC" else MUTED)
                sh.text(x + 24, row - 3 + LINE - 2, "no test uses it", T, "regular", MUTED)
        y = body[3] + 40 + len(pins) * rows + 26
    y = steps.para(
        sh, 30, y, "pcie-link and pcie-bar0 go through the M.2 slot; rp1-pio, flash and ddr use no wire of the cables; "
        "scratch uses the serial pair as well.", W - 40, "bold",
    )  # fmt: skip
    if not any(s in c.wires for s in ("J5", "H5")):
        y = steps.para(sh, 30, y + 4, f"p2-gpio is never run on a {c.name}: J5 and H5 are not wired.", W - 40, "bold")
    y = steps.para(sh, 30, y + 4, steps.COLOURS, W - 40)
    y = steps.para(sh, 30, y + 4, "The plugs are sketched, not from a photograph.", W - 40, fill=MUTED)
    sh.h = math.ceil(y - LINE + 14)
    sh.check(f"check wires {c.key}")
    return sh.svg()


# ----------------------------------------------------------------------------------------------
# The page
# ----------------------------------------------------------------------------------------------
INSTALL = {
    "blade": (
        "The Compute Blades at ps1 boot from the network with their root file system in memory "
        "(`overlayroot=tmpfs`): what you install is gone at the next boot, and so is the check that would run at "
        "boot. So after each boot, install and run by hand.\n\n"
        "**Not on pi14 at ps1 or pi18 at ps1 yet.** Those two carry a Compute Module 4; the check has been "
        "run as written only on the two Compute Module 5 blades (pi16 and pi20 at ps1, 7 October 2026), and "
        "`vcgencmd` hung for good on both CM4 blades that day. Until the check has been tried on a CM4 blade, "
        "run it on pi16 at ps1 and pi20 at ps1 only."
    ),
    "pi5": (
        "**On a Raspberry Pi 5 of the fleet (welland) there is nothing to install.** The root it boots from "
        "carries the packages and runs the check once at each boot. Read that result, or run the check again "
        "by hand without telling the site:\n\n"
        "```bash\n"
        "journalctl -b -u fpgas-verify -o cat       # what the check at this boot said\n"
        "sudo fpgas-verify --no-publish             # run it again now; nothing is sent to the site\n"
        "```\n\n"
        "**On a Raspberry Pi 5 that is not booted from the fleet's root**, install and run by hand. If its root "
        "file system is in memory (`overlayroot=tmpfs`), what you install is gone at the next boot:"
    ),
}
# What a blade owner can expect, said once, on the first verifying page (the third does not repeat it).
TODAY = {
    "blade": [
        "",
        "**What to expect on a Compute Blade today.** `pcie-link` passes when the card is seated, on SQRL's "
        "factory image or on the vendor's XDMA sample image (version 0.0.post1220 or newer). On a Compute "
        "Module 5 `jtag` cannot run in a boot that has the header's serial port on (kernel 6.18): the serial "
        "port holds GPIO14, which is also the JTAG TMS wire, so `jtag` fails there whatever the wiring. With "
        'the port off at boot (a change to the gateway\'s boot files, on the page "verifying 3"), `jtag` '
        "passes (it reads the IDCODE and device DNA): run on pi20 at ps1 on 7 October 2026. On a Compute "
        "Module 4 it has not been run by us under this kernel (on pi14 at ps1 on 20 September 2026, under "
        "kernel 6.12, JTAG got no response, TCK floating). Every other test but `rp1-pio` is `not run` until the card "
        "is converted to the fpgas.online design, and converting a card on a blade is not in this guide yet: "
        'do not load a design into the card or convert it (the page "verifying 3" says why). So the result '
        "today is `fail` even with perfect cables: it shows that the card is seated "
        "and its PCIe link is up, and it cannot yet show that the two cables are right. The bench check with a "
        "meter, before fitting, is what the cables rest on until then.",
        "",
    ]
}
PASS = "**pass**: an Acorn on the Pi 5 setup"
BLADE_FAIL = "**fail, the docs' install steps run on a Compute Blade**"


def pages(c):
    """{part: page body} for one carrier, headings from level 2, each to be included under a page's title."""
    after_boot = fragment("after-a-boot.md", c)
    install = after_boot[after_boot.index("```bash") : after_boot.index("```\n", after_boot.index("```bash") + 7) + 4]
    wire_table, wire_examples = site_links(fragment("to-the-wire.md", c)).split("\n\n", 1)
    wire_table = wire_table.replace("{crossed_serial}", swap(c, "J2", "K2"))
    if "{crossed_spare}" in wire_table:  # only a carrier whose cable carries the two spare wires has that row
        wire_table = wire_table.replace("{crossed_spare}", swap(c, "J5", "H5"))
    cavity = {k: steps.png(steps.file_name(c, k)) for k in wiring.CONNECTORS}
    out = [
        tables.BANNER.strip(),
        "",
        "## What the check is",
        "",
        "`fpgas-verify` is the program that checks an FPGA board from the machine it is attached to. For an Acorn "
        "its check doubles as a wiring test: each of its tests uses a known set of wires between the card and the "
        f"{c.host}, so which tests pass, and what a failing one says, point at the wire. An Acorn is sold as a "
        "CLE-215+, a CLE-215 or a CLE-101, and the check's summary names the variant it found (`acorn cle-101`, "
        "for example); a CLE-215 has not been checked by us.",
        "",
        "The check never writes the card's flash and never loads a design into the FPGA. It drives the P1 and "
        "P2 wires, which is how it tests them, and puts the host's pins back as it found them.",
        *TODAY.get(c.key, []),
        "",
        "## Install it and run it",
        "",
        INSTALL[c.key],
        "",
        install.strip(),
        "",
        "`fpgas-verify` checks whichever board this host is set up for, as the check at boot does; "
        "`fpgas-acorn-verify` checks the Acorn whatever the host is set up for. On a host set up for an Acorn "
        "the two print the same.",
        "",
        "## Read the result",
        "",
        "There is one result, **pass** or **fail**, and only a pass exits 0. The summary on the terminal lists "
        "every test in the order it ran with its result; for a check that did not pass it ends with `RESULT:`, a "
        "`failed:` line for each failed test, a `not run:` line for the tests that did not run and why, and "
        "`What to do:`.",
        "",
    ]
    if c.key == "pi5":
        out += [
            "A pass, on the Acorn and Raspberry Pi 5 seen at welland's sw2 p47 on 2 October 2026 (on 6 October "
            "2026 that port had acorn-holly, device DNA `0x00200c8664b04854`, on the Pi 5 2 GB "
            "`285df3f84af242d0`). The run names the host by its port, `pi-sw2-p47`:",
            "",
            transcript(PASS, "pi-sw2-p47", "2026-10-02").strip(),
            "",
        ]
    else:
        out += [
            "**No Compute Blade has passed the whole check yet.** This is what one prints today: a Compute Blade "
            "with a Compute Module 5 and an Acorn CLE-101 still on the image it was sold with (pi16 at ps1, "
            "7 October 2026, installed by the steps above, version 0.0.post1216). Two things are wrong and neither "
            "is the wiring or the installation: the card has not been converted to the fpgas.online design, and in "
            "this boot the JTAG test cannot have its TMS pin, which the header's serial port holds. Its "
            "`What to do:` lines are left out here: that version's advice was for a Raspberry Pi 5. **On a Compute "
            "Blade, do not load a design into the card or convert it; that is not in this guide yet** (the page "
            '"verifying 3" says why). From version 0.0.post1284 the check says so itself, and says that changing '
            "the gateway's shared boot files or giving one blade its own copy is the gateway owner's choice.",
            "",
            without_advice(transcript(BLADE_FAIL, "pi16", "2026-10-07", "CLE-101", "0.0.post1216")),
            "",
            "On the blades at ps1 every `sudo` first prints `sudo: unable to resolve host pi16: Name or service "
            "not known` (with the blade's own name). It did no harm on the blades it was seen on (7 October 2026), "
            "and is left out above.",
            "",
            "**A card still on the vendor's XDMA sample image** (pi20 at ps1, 7 October 2026, version "
            "0.0.post1220) gets the same tests as one on SQRL's image: `pcie-link` and `rp1-pio` pass, `jtag` "
            "fails on GPIO14 as above, the rest are `not run`. Its summary line reads `acorn -: fail` (no variant "
            "is named), and the first `What to do:` line says the board runs Xilinx's XDMA sample design (on a "
            "Compute Blade, from version 0.0.post1284, not to convert it). That was on pi20 at ps1, "
            "installed by the steps above as version 0.0.post1216 and updated "
            "to 0.0.post1220 the same day; version 0.0.post1216 printed `acorn: fail (no test ran)` there "
            "([fpgas.online-test-designs issue 155, a card on the vendor XDMA sample image got no test at "
            "all](https://github.com/fpgas-online/fpgas.online-test-designs/issues/155)).",
            "",
            "A pass will list every test with `pass` and end there, with no `RESULT:` part; on a Compute Blade "
            "`p2-gpio` stays `not run`, because J5 and H5 are not wired.",
            "",
        ]
    out += [
        "## Which test uses which wire",
        "",
        steps.markdown_image(
            f"Both cables of an Acorn on a {c.name}: each wire, where it lands, and the test that proves it",
            steps.png(picture_name(c)),
        ),
        "",
        site_links(fragment("which-test.md", c)).strip(),
        "",
    ]
    fails = [
        tables.BANNER.strip(),
        "",
        "## From a failing line to the wire",
        "",
        "Find the failing line in the table, then the wire in the two cavity pictures under it: the number in a "
        "cavity is the number on the wire's flag.",
        "",
        f"**Before you touch a cable: {c.power_off}** **After moving a wire, the cable goes through the same checks "
        "as a new one before any boot:** take the card out and pull both plugs from its sockets, check that "
        "cable's plug contacts against its housing with the meter as step "
        f'{steps.meter_check_step(c)} of "JTAG connector 2" or "UART connector 2" does, run "the bench check" with '
        'the card out, and fit the cables as "Fitting" does. Then '
        "boot and run the check again"
        + (
            " (on a blade at ps1 the install is gone after the boot: install again, as on verifying 1; and "
            "not on pi14 or pi18 at ps1 yet, as verifying 1 says)"
            if c.key == "blade"
            else ""
        )
        + ". One "
        "test can be run on its own, `sudo fpgas-acorn-verify --test jtag` or `--test p2-serial`; it prints "
        "the usual summary, then the whole report as JSON.",
        "",
        wire_table.strip(),
        "",
        "The two cavity pictures are the ones the cables were built from, shown again to find a wire's "
        "cavity. Their notes about cutting, marking and the meter check belong to building the cables.",
        "",
    ]
    for connector in wiring.CONNECTORS:
        fails += [steps.markdown_image(f"Which wire goes in which cavity, {connector} cable", cavity[connector]), ""]
    fails += [
        wire_examples.strip(),
        "",
        'A failing line that is not in the table above is not about a wire of the cables: the page "verifying 2b" '
        "has every other message the check gives about an Acorn.",
        "",
    ]
    others = [
        tables.BANNER.strip(),
        "",
        "## Every other message about an Acorn",
        "",
        f"The check's own words, from the tool's list of [common failures]({FAILURES}), which has the other "
        "boards' too. A wire of the cables is behind the `jtag` and `p2-…` lines only; for those, the page "
        '"verifying 2" goes from the line to the wire.',
        "",
        failures(c).strip(),
        "",
    ]
    parts = {1: out, 2: fails, "2b": others}
    if c.key == "blade":
        parts[3] = [
            tables.BANNER.strip(),
            "",
            "## What has been run on a Compute Blade",
            "",
            site_links(fragment("compute-blade.md", c)).strip(),
            "",
        ]
    done = {}
    for part, lines in parts.items():
        page = site_links("\n".join(lines))
        stray = re.findall(r"(?<!!)\[[^\]]*\]\((?!https?://)[^)]*\)", page)
        unfilled = re.findall(r"\{[a-z_]+\}", page)
        if stray or unfilled or page.count("<!--") != 1:
            raise wiring.WiringError(
                f"{name(c, part)}: a relative link, an unfilled place or a mark left over: {stray} {unfilled}"
            )
        done[part] = page
    return done


def page(c):
    """Every page of one carrier, joined: what a reader meets, in order."""
    return "\n".join(pages(c).values())


def build():
    """{file name: contents} for each carrier's page and picture."""
    out = {}
    for c in wiring.CARRIERS.values():
        out[picture_name(c)] = picture(c)
        for part, body in pages(c).items():
            out[name(c, part)] = body
    return out
