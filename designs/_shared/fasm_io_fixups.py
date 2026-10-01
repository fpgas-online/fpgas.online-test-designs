#!/usr/bin/env python3
"""Rewrite an openXC7 FASM so its SSTL IO banks get the VREF and drive that Vivado gives them.

nextpnr-xilinx (openXC7 0.8.2) ignores `set_property INTERNAL_VREF` and sets VREF.V_675_MV on every bank with
an SSTL input: right for SSTL135 (the Arty), 75 mV low for SSTL15 (the Acorn and the NeTV2), whose Vivado
builds use V_750_MV. It also has no SSTL15_R: that standard is built as SSTL15, whose outputs drive harder.
Vivado encodes an SSTL15_R output as LVCMOS15.DRIVE.I8 (seen in bit2fasm of the NeTV2 Vivado DDR image).

Only features nextpnr-xilinx already wrote are rewritten, and only to features prjxray-db has for the same
tiles, so the rewritten FASM still assembles with fasm2frames.

usage: fasm_io_fixups.py <file.fasm> [--vref-mv {600,675,750,900}] [--sstl15-reduced-drive]  (rewrites in place)
"""

import argparse
import re
import shlex
import sys
from pathlib import Path

VREF_MV = (600, 675, 750, 900)  # the HCLK_IOI3.VREF.V_<n>_MV features prjxray-db knows

_VREF = re.compile(r"^(HCLK_IOI3_X\d+Y\d+)\.VREF\.V_\d+_MV$")
_IOB = re.compile(r"^([LR]IOB33(?:_SING)?_X\d+Y\d+\.IOB_Y[01])\.(.+)$")
_SSTL15_DRIVE = "LVCMOS15_SSTL15.DRIVE.I16_I_FIXED"  # SSTL15, and also LVCMOS15 at 16 mA
_SSTL15_R_DRIVE = "LVCMOS15.DRIVE.I8"
# Only an SSTL output has this slew feature, so it marks the pins to rewrite. An SSTL output with SLEW=SLOW
# gets a slew feature it shares with LVCMOS and is left at full drive: the DDR3 resources all set SLEW=FAST.
_SSTL_OUTPUT = "SSTL135_SSTL15.SLEW.FAST"


def fix_lines(lines, vref_mv=None, sstl15_reduced_drive=False):
    """The FASM *lines* (each with its newline) with the fixes asked for applied."""
    if vref_mv is not None and vref_mv not in VREF_MV:
        raise ValueError(f"VREF {vref_mv} mV: prjxray can only set {', '.join(map(str, VREF_MV))} mV")

    sstl_sites = set()
    if sstl15_reduced_drive:
        for line in lines:
            m = _IOB.match(line.strip())
            if m and m.group(2) == _SSTL_OUTPUT:
                sstl_sites.add(m.group(1))

    out = []
    for line in lines:
        feature = line.strip()
        m = _VREF.match(feature)
        if m and vref_mv is not None:
            line = f"{m.group(1)}.VREF.V_{vref_mv}_MV\n"
        m = _IOB.match(feature)
        if m and m.group(1) in sstl_sites and m.group(2) == _SSTL15_DRIVE:
            line = f"{m.group(1)}.{_SSTL15_R_DRIVE}\n"
        out.append(line)
    return out


def add_openxc7_fasm_io_fixups(platform, vref_mv=None, sstl15_reduced_drive=False):
    """Run this script on the build's FASM between nextpnr-xilinx and fasm2frames (openXC7 builds only).

    LiteX sets fasm2frames' options on `_pre_packer_cmd[0]` in finalize(), so the step is put in front of it
    once finalize() has run.
    """
    toolchain = platform.toolchain
    if not getattr(toolchain, "is_openxc7", False):
        return
    if vref_mv is not None and vref_mv not in VREF_MV:
        raise ValueError(f"VREF {vref_mv} mV: prjxray can only set {', '.join(map(str, VREF_MV))} mV")
    finalize = toolchain.finalize

    def finalize_then_add_step(*args, **kwargs):
        result = finalize(*args, **kwargs)
        cmd = f"{shlex.quote(sys.executable)} {shlex.quote(str(Path(__file__).resolve()))}"
        opts = [shlex.quote(f"{toolchain._build_name}.fasm")]
        if vref_mv is not None:
            opts += ["--vref-mv", str(vref_mv)]
        if sstl15_reduced_drive:
            opts.append("--sstl15-reduced-drive")
        toolchain._pre_packer_cmd.insert(0, cmd)
        toolchain._pre_packer_opts[cmd] = " ".join(opts)
        return result

    toolchain.finalize = finalize_then_add_step


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fasm", type=Path)
    parser.add_argument("--vref-mv", type=int, choices=VREF_MV)
    parser.add_argument("--sstl15-reduced-drive", action="store_true")
    args = parser.parse_args(argv)
    lines = args.fasm.read_text().splitlines(keepends=True)
    fixed = fix_lines(lines, vref_mv=args.vref_mv, sstl15_reduced_drive=args.sstl15_reduced_drive)
    changed = sum(a != b for a, b in zip(lines, fixed))
    args.fasm.write_text("".join(fixed))
    print(f"fasm_io_fixups: {changed} feature(s) rewritten in {args.fasm}", file=sys.stderr)


if __name__ == "__main__":
    main()
