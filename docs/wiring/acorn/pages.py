# SPDX-License-Identifier: Apache-2.0
"""The Acorn pages on docs.fpgas.online, as the generated text names them: one table of titles and addresses.

The generated fragments (`generated/acorn-*.md`) are shown on docs.fpgas.online under pages whose titles and
addresses are fpgas.online-docs'. A fragment that sends the reader to another page does it with a Markdown link
made here, by the page's published address (the docs sync turns it into a link inside the site), so no fragment
quotes a page's name in words, and a title that changes is changed in this table and nowhere else.

`PAGES` maps a page's key to (its path under the Acorn tree, its title). `{slug}` is the carrier's directory and
`{name}` its name. A key ending `-1`, `-2` and so on is the build-guide or check part of that number in
`steps.guide()` and `check.build()`.
"""

BASE = "https://docs.fpgas.online/en/latest/boards/acorn/"
# carrier key -> (its directory in the docs tree, its name in a title)
CARRIERS = {"pi5": ("rpi-5", "Raspberry Pi 5"), "blade": ("compute-blade", "Compute Blade")}
MAX_TITLE = 65  # the docs rule: a title is at most 65 characters

PAGES = {
    "overview": ("setup/{slug}/cables", "The two cables on a {name}"),
    "parts": ("setup/{slug}/parts", "Parts and tools for the {name} cables"),
    "jtag-1": ("setup/{slug}/jtag-wires", "How to prepare the JTAG cable's wires ({name})"),
    "jtag-2": ("setup/{slug}/jtag-housing", "How to fill the JTAG cable's housing ({name})"),
    "uart-1": ("setup/{slug}/uart-wires", "How to prepare the UART cable's wires ({name})"),
    "uart-2": ("setup/{slug}/uart-housing", "How to fill the UART cable's housing ({name})"),
    "bench": ("setup/{slug}/bench-check", "How to check the cables on the bench ({name})"),
    "fit": ("setup/{slug}/fitting", "How to fit the cables and the card ({name})"),
    "check-1": ("checks/{slug}", "How to run the Acorn check on a {name}"),
    "check-2": ("troubleshooting/{slug}-failing-test", "A failing Acorn test on a {name}"),
    "check-2b": ("troubleshooting/{slug}-other-messages", "Other Acorn check messages on a {name}"),
    "check-3": ("checks/{slug}-jtag", "How to make a {name} boot ready for JTAG"),
}
# The pages only one carrier has.
ONLY = {"check-3": ("blade",)}


class NoSuchPage(KeyError):
    """A page the carrier does not have, or a key that is no page."""


def _entry(key, page):
    if key not in CARRIERS or page not in PAGES or key not in ONLY.get(page, CARRIERS):
        raise NoSuchPage(f"the Acorn docs have no page {page!r} for carrier {key!r}")
    slug, name = CARRIERS[key]
    path, title = PAGES[page]
    return path.format(slug=slug), title.format(name=name)


def title(key, page):
    """The title of `page` for the carrier with key `key`, as docs.fpgas.online shows it."""
    return _entry(key, page)[1]


def url(key, page):
    """The published address of `page` for the carrier with key `key`."""
    return f"{BASE}{_entry(key, page)[0]}.html"


def link(key, page):
    """A Markdown link to `page` for the carrier with key `key`: its title, to its published address."""
    return f"[{title(key, page)}]({url(key, page)})"


def every():
    """[(carrier key, page key)] of every page there is."""
    return [(key, page) for key in CARRIERS for page in PAGES if key in ONLY.get(page, CARRIERS)]
