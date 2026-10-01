"""Platform-level fixups for LiteX board targets.

Workarounds for inconsistencies between litex-boards platform definitions
and the openXC7 toolchain expectations.
"""

import os
import re
from pathlib import Path

from litex.build.generic_platform import IOStandard, Subsignal

# nextpnr-xilinx (openXC7 0.8.2, and its master as of 2026-09) only knows SSTL12/SSTL135/SSTL15.
# For any other SSTL name it writes no input-buffer, drive or VREF bits, so an input in, say,
# SSTL15_R has no receiver: the NeTV2's DDR3 data pins read back nothing at any IDELAY tap.
# The _R ("reduced drive") standards differ from their plain ones only in output drive strength, and
# nextpnr-xilinx has no _R standards, so they are built as the plain ones. For SSTL15_R the reduced drive is
# put back in the FASM (fasm_io_fixups.py: LVCMOS15.DRIVE.I8, as Vivado encodes it); for SSTL135_R no such
# feature has been decoded, so it builds at full drive (no board here uses it).
_REDUCED_DRIVE_IOSTANDARDS = {
    "SSTL15_R": "SSTL15",
    "DIFF_SSTL15_R": "DIFF_SSTL15",
    "SSTL135_R": "SSTL135",
    "DIFF_SSTL135_R": "DIFF_SSTL135",
}


def _plain_iostandard(item):
    if isinstance(item, IOStandard) and item.name in _REDUCED_DRIVE_IOSTANDARDS:
        return IOStandard(_REDUCED_DRIVE_IOSTANDARDS[item.name])
    if isinstance(item, Subsignal):
        return Subsignal(item.name, *[_plain_iostandard(c) for c in item.constraints])
    return item


def fix_openxc7_reduced_drive_iostandards(platform):
    """Replace SSTL*_R IO standards with the plain SSTL ones that nextpnr-xilinx can build.

    Call before any resource is requested. Only this platform instance's constraint list is
    rebuilt; the litex-boards definition (shared with Vivado builds) is left as it is.
    """
    cm = platform.constraint_manager
    cm.available = [(r[0], r[1], *[_plain_iostandard(item) for item in r[2:]]) for r in cm.available]


def constrain_openxc7_clocks(platform, domains):
    """Give nextpnr-xilinx the real period of each PLL output, and fail the build if one is not met.

    *domains* maps each ClockDomain to its frequency in Hz. Vivado derives PLL output clocks itself,
    so this does nothing unless the toolchain is openXC7. nextpnr-xilinx does not: LiteX constrains
    only the board's input clock and passes that frequency as `--freq`, so every PLL output was timed
    at the input frequency (the Arty's 100 MHz, the Acorn's 200 MHz), and LiteX also passes
    `--timing-allow-fail`. Arty DDR images that missed 100 MHz by up to a third were shipped, and
    whether one could read its DDR3 depended on where that build happened to place things.
    """
    if not getattr(platform.toolchain, "is_openxc7", False):
        return
    _add_period_constraints(platform, domains)

    toolchain = platform.toolchain
    # Wrap the toolchain once: a second call (two CRG helpers, say) only adds its periods. Wrapping again
    # would pass nextpnr --log twice, which it refuses, and nest the seed retries.
    if getattr(toolchain, "_fpgas_online_strict_timing", False):
        return
    toolchain._fpgas_online_strict_timing = True

    # build() resets timingstrict from its keyword argument, so force it there.
    build = toolchain.build

    def strict_build(*args, **kwargs):
        kwargs["timingstrict"] = True
        return build(*args, **kwargs)

    toolchain.build = strict_build

    # nextpnr-xilinx's result varies a lot with its seed (a 75 MHz Acorn SoC reached 74.0-92.5 MHz over three
    # seeds), and every build's BIOS timestamp changes the netlist, so a strict build would fail now and then.
    # Log nextpnr to a file, and when that shows a missed clock, place and route again with the next seed.
    finalize = toolchain.finalize

    def finalize_with_log(*args, **kwargs):
        result = finalize(*args, **kwargs)
        toolchain._nextpnr._pnr_opts += f"--log {toolchain._build_name}_nextpnr.log "
        return result

    toolchain.finalize = finalize_with_log
    toolchain.run_script = _retry_missed_timing(toolchain)


def _add_period_constraints(platform, domains):
    for domain, freq in domains.items():
        if freq <= 0:
            raise ValueError(f"clock domain {domain.name}: frequency {freq} is not positive")
        platform.add_period_constraint(domain.clk, 1e9 / freq)


def require_timing(platform, domains):
    """Fail the build if the design misses timing: every design calls this once, before building.

    *domains* maps each ClockDomain the design's CRG makes (a PLL output, or a board clock used as sys
    through a buffer) to its frequency in Hz; a design clocked straight from a board input passes {}, as the
    board's own constraint covers it. Every clock that drives logic must be named: nextpnr times any other at
    the fastest constrained frequency.

    openXC7: constrain_openxc7_clocks (real PLL periods, strict nextpnr, retries with other seeds).
    iCE40 (icestorm): the periods, and strict nextpnr, which LiteX otherwise runs with --timing-allow-fail.
    Vivado: nothing; it derives PLL clocks itself and reports timing in its own way.
    """
    toolchain = platform.toolchain
    if getattr(toolchain, "is_openxc7", False):
        constrain_openxc7_clocks(platform, domains)
    elif getattr(toolchain, "family", None) == "ice40":
        _add_period_constraints(platform, domains)
        if getattr(toolchain, "_fpgas_online_strict_timing", False):
            return
        toolchain._fpgas_online_strict_timing = True
        build = toolchain.build

        def strict_build(*args, **kwargs):
            kwargs["timingstrict"] = True
            return build(*args, **kwargs)

        toolchain.build = strict_build


OPENXC7_TIMING_SEEDS = 5
_MISSED_CLOCK = re.compile(r"^ERROR: Max frequency for clock .*FAIL at", re.MULTILINE)


def _retry_missed_timing(toolchain):
    run_script = toolchain.run_script

    def missed_timing(log):
        return log.exists() and _MISSED_CLOCK.search(log.read_text(errors="replace")) is not None

    def run_script_retrying(script):
        log = Path(f"{toolchain._build_name}_nextpnr.log")  # run_script runs in the build directory
        log.unlink(missing_ok=True)  # never judge this build by an older one's log
        try:
            return run_script(script)
        except OSError:
            if not missed_timing(log):
                raise
        text = Path(script).read_text()
        first = re.search(r"--seed (\d+)", text)
        if first is None:
            raise OSError(f"timing not met, and no --seed in {script} to vary")
        first = int(first.group(1))
        # Synthesis does not depend on the seed: rerun only nextpnr and what follows it.
        pnr = "".join(line for line in text.splitlines(keepends=True) if not line.startswith("yosys "))
        retry = Path(script).with_name(Path(script).stem + "_retry" + Path(script).suffix)
        for seed in range(first + 1, first + OPENXC7_TIMING_SEEDS):
            print(f"constrain_openxc7_clocks: timing not met with nextpnr seed {seed - 1}, trying seed {seed}")
            retry.write_text(re.sub(r"--seed \d+", f"--seed {seed}", pnr))
            log.unlink(missing_ok=True)
            try:
                return run_script(str(retry))
            except OSError:
                if not missed_timing(log):
                    raise
        raise OSError(f"timing not met with any nextpnr seed {first}..{first + OPENXC7_TIMING_SEEDS - 1}")

    return run_script_retrying


def fix_openxc7_device_name(platform):
    """Remove the dash between device family and package for openXC7.

    litex-boards defines NeTV2 (and some other boards) with a hyphenated
    device string like ``xc7a35t-fgg484-2`` for Vivado compatibility.
    The openXC7 toolchain's prjxray database and nextpnr-xilinx chipdb
    expect ``xc7a35tfgg484-2`` (no dash between part and package).

    Returns the original device name if it was changed, or None if no
    change was needed.
    """
    old_device = platform.device
    new_device = re.sub(r"^(xc7[aksz]\d+t)-(.*)", r"\1\2", old_device)
    if new_device != old_device:
        platform.device = new_device
        return old_device
    return None


def ensure_chipdb_symlink(platform):
    """Create a chipdb symlink for the un-dashed device name if needed.

    The openxc7 chipdb directory may only have a file for the dashed
    device name.  This creates a symlink so nextpnr can find the database
    under the un-dashed name.
    """
    chipdb_dir = os.environ.get("CHIPDB", "")
    if not chipdb_dir:
        return

    device = platform.device
    # Re-insert the dash to get the original form
    old_device_dashed = re.sub(r"^(xc7[aksz]\d+t)(.*)", r"\1-\2", device)
    old_dbpart = re.sub(r"-\d+$", "", old_device_dashed)
    new_dbpart = re.sub(r"-\d+$", "", device)

    if old_dbpart == new_dbpart:
        return

    old_chipdb = os.path.join(chipdb_dir, old_dbpart + ".bin")
    new_chipdb = os.path.join(chipdb_dir, new_dbpart + ".bin")

    if os.path.exists(old_chipdb) and not os.path.exists(new_chipdb):
        try:
            os.symlink(old_chipdb, new_chipdb)
        except FileExistsError:
            pass  # Another process may have created it concurrently.
