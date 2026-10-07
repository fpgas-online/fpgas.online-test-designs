# SPDX-License-Identifier: Apache-2.0
"""Two rules that hold on every page printed for a carrier, read from generated/ as the reader gets it.

1. Power: every sentence that powers the host off, unplugs it, or presumes it off carries the carrier's own
   `power_off` sentence (wiring.toml). On a Compute Blade that sentence starts "Ask Tim": no blade page tells its
   reader to power off or unplug a blade, or presumes it off, without asking Tim first.
2. JTAG on a blade: every command on a blade page that runs the check has `--no-publish`, and a page that runs
   `jtag` (the whole check, `--update`, or `--test jtag`) names the conditions of the page "verifying 3".

gen.py --check keeps generated/ the same as what the generators print, so these read what is published.

Run: uv run --no-project --with pytest --with pillow==12.3.0 --with fonttools==4.65.0 pytest docs/wiring/acorn
"""

import re

import pytest
import steps
import wiring

OUT = wiring.HERE / "generated"

# Words that power a host off, unplug it, or say it is off. "serial port off" is not one: no host is off there.
POWER = re.compile(
    r"\bpower(?:ed|ing|s)?\s+(?:it\s+)?off\b"  # power off, powered off, power it off
    r"|\bunplug\w*"  # unplug, unplugged
    r"|\bunpowered\b"
    # "switch the blade off", "shut it down", "shutdown"; not "the FPGA's outputs are switched off"
    r"|\b(?:switch|turn|shut)(?:ed|s|ting)?\s+(?:it|the\s+(?:compute\s+)?(?:blade|host|pi(?:\s+5)?))\s+(?:off|down)\b"
    r"|\bshut\s*down\b|\bpoweroff\b"
    r"|\b(?:blade|host|pi(?:\s+5)?|power)\s+(?:is\s+|was\s+|stays\s+)?off\b",  # "the blade off", "the power off"
    re.I,
)


def carrier_files(c):
    """Every page and picture printed for carrier `c`: its file name names it (`blade`, `pi5`, or its wiring sheet).
    A dark picture carries the same words as its light one, so it is not read twice."""
    names = (c.key, steps.SHEETS[c.key])
    files = [
        p
        for p in sorted(OUT.iterdir())
        if p.suffix in (".md", ".svg") and not p.stem.endswith("-dark") and any(n in p.name for n in names)
    ]
    assert files, c.key
    return files


def units(path):
    """The text of a page or picture, as the pieces a sentence cannot run across: a paragraph, a list item, a
    table cell; in a picture, one line of text with the lines it wraps onto."""
    text = path.read_text()
    if path.suffix == ".svg":
        lines = re.findall(r'aria-label="([^"]*)"', text)
        out = []
        for line in lines:  # a line that starts in lower case continues the one before (steps.para wraps them)
            if out and line[:1].islower() and not re.search(r"[.!?]$", out[-1]):
                out[-1] += " " + line
            else:
                out.append(line)
        return out
    text = re.sub(r"```.*?```", "", text, flags=re.S)  # commands and transcripts: no instruction to the reader
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    pieces = []
    for block in re.split(r"\n\s*\n", text):
        # a list item or a table row starts a piece of its own; a hard-wrapped line continues the one before
        for item in re.split(r"\n(?=\s*(?:\d+\.|[*-]|\|)\s)", block):
            pieces += item.split("|")
    return [" ".join(p.replace("**", "").split()) for p in pieces if p.strip()]


def sentences(unit):
    return re.split(r"(?<=[.!?])\s+(?=[A-Z0-9`(\"'])", unit)


def strays(c, files):
    """(file, sentence) for each sentence with a power-off word that does not carry the carrier's power_off."""
    tail = c.power_off[1:]  # the first letter is lower case where the sentence goes on from another clause
    return [
        (path.name, s)
        for path in files
        for unit in units(path)
        for s in sentences(unit)
        if POWER.search(s) and tail not in s
    ]


@pytest.mark.parametrize("key", list(wiring.CARRIERS))
def test_every_power_off_on_a_carriers_pages_is_in_its_own_words(key):
    c = wiring.CARRIERS[key]
    files = carrier_files(c)
    assert strays(c, files) == []
    # not empty: the pages do power the host off, in the carrier's words, on the pages a builder meets it
    said = [p.name for p in files if c.power_off[1:] in " ".join(units(p))]
    for page in ("bench", "fit", "jtag-1", "uart-1"):
        assert steps.guide_name(c, page) in said, page
    assert f"acorn-check-{key}-2.md" in said and f"acorn-cable-{key}-shell-check.svg" in said
    if key == "blade":
        assert c.power_off.startswith("Ask Tim, then power off the Compute Blade")


def test_the_power_off_scan_finds_what_it_is_for(tmp_path):
    """The scan is not blind: wording that presumes the host off, without the carrier's sentence, is caught."""
    c = wiring.CARRIERS["blade"]
    bad = [
        "With the host powered off, lay the cable.",
        "Both cables, the Compute Blade unplugged from power, and a meter.",
        "Check the TDI wire with the blade off, the card out.",
        "Touch bare metal of the unplugged host.",
        "Power off the Compute Blade.",
    ]
    good = [
        f"If the Compute Blade is on, {c.power_off[0].lower()}{c.power_off[1:]}",
        f"**Before you touch a cable: {c.power_off}**",
        "In a boot with the header's serial port off, run it.",
        "Before powering on, look again. No power cycle was run by us.",
    ]
    page = tmp_path / "page.md"
    page.write_text("\n\n".join([*bad, *good]) + "\n")
    assert [s for _, s in strays(c, [page])] == bad
    svg = tmp_path / "picture.svg"  # a picture's wrapped lines are read as one sentence
    first, rest = c.power_off.split(": unplug ", 1)
    svg.write_text(f'<g aria-label="{first}:"/><g aria-label="unplug {rest}"/><g aria-label="host unplugged"/>')
    assert [s for _, s in strays(c, [svg])] == ["host unplugged"]


# Verifying 3's conditions for JTAG on a blade (check/compute-blade.md, its last list's steps 2 and 3), as words a
# page that runs `jtag` must carry.
JTAG_WORDS = ("serial port off", "gpio14 is free", "nothing on the card drives gpio14")


def test_a_blade_page_that_runs_jtag_has_no_publish_and_verifying_3s_conditions():
    pages = [p for p in carrier_files(wiring.CARRIERS["blade"]) if p.suffix == ".md"]
    runs = 0
    for path in pages:
        text = path.read_text()
        commands = re.findall(r"sudo fpgas-(?:acorn-)?verify\b[^`\n]*", text)
        for command in commands:
            assert "--no-publish" in command, (path.name, command)
        jtag = [cmd for cmd in commands if "--test jtag" in cmd or "--test" not in cmd]
        if jtag:
            runs += 1
            flat = " ".join(text.replace("**", "").split()).lower()
            for words in JTAG_WORDS:
                assert words in flat, (path.name, words)
    # verifying 1 (the whole check), 2 (--test jtag), 2b (--update, and the DNA row) and 3 (--test jtag)
    assert runs >= 4
