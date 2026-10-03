#!/usr/bin/env python3
"""Judge an openXC7 build that is expected to fail (issue #105), and say so in the CI log.

The Acorn PCIe SoC does not build with openXC7 yet: nextpnr-xilinx cannot place the XADC, and without the XADC
the design misses timing. Its CI build keeps running so that the day it builds is noticed, but it must not
block anything, and its bitstreams are not shipped (.github/workflows/collect-bitstreams.yml leaves them out).

  build failed, for a reason #105 records   expected: a warning, exit 0
  build failed, for any other reason        a new problem: an error, exit 1
  build passed                              unexpected: an error, exit 1, so that someone updates #105 and
                                            decides whether the bitstreams ship (they have never run on a board)

    python3 scripts/openxc7_expected_failure.py --outcome failure --log build.log
"""

import argparse
import pathlib
import sys

ISSUE = "https://github.com/fpgas-online/fpgas.online-test-designs/issues/105"
# What the known failures print, from nextpnr-xilinx and from designs/_shared/platform_fixups.py require_timing.
KNOWN = (
    "Unable to place cell 'XADC'",
    "timing not met with any nextpnr seed",
)


def judge(outcome, log_text):
    """(exit status, GitHub Actions annotation) for a build's outcome and log."""
    if outcome == "success":
        return 1, (
            f"::error::Unexpected pass: the openXC7 build now succeeds. Update {ISSUE} and decide whether these "
            "bitstreams ship; they have never run on a board, and collect-bitstreams.yml still leaves them out."
        )
    if outcome != "failure":
        return 1, f"::error::The build step's outcome is {outcome!r}, neither success nor failure"
    for line in log_text.splitlines():
        for known in KNOWN:
            if known in line:
                return 0, f"::warning::Expected failure ({ISSUE}): {line.strip()}"
    return 1, f"::error::The openXC7 build failed for a reason {ISSUE} does not record: read the build log"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--outcome", required=True, help="the build step's outcome: success, failure, ...")
    parser.add_argument("--log", required=True, type=pathlib.Path, help="the build step's output")
    args = parser.parse_args(argv)
    text = args.log.read_text(errors="replace") if args.log.exists() else ""
    status, annotation = judge(args.outcome, text)
    print(annotation)
    return status


if __name__ == "__main__":
    sys.exit(main())
