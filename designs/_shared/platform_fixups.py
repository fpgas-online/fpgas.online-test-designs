"""Platform-level fixups for LiteX board targets.

Workarounds for inconsistencies between litex-boards platform definitions
and the openXC7 toolchain expectations.
"""

import os
import re

from litex.build.generic_platform import IOStandard, Subsignal

# nextpnr-xilinx (openXC7 0.8.2, and its master as of 2026-09) only knows SSTL12/SSTL135/SSTL15.
# For any other SSTL name it writes no input-buffer, drive or VREF bits, so an input in, say,
# SSTL15_R has no receiver: the NeTV2's DDR3 data pins read back nothing at any IDELAY tap.
# The _R ("reduced drive") standards differ from their plain ones only in output drive strength,
# and prjxray has no bits for that difference, so the plain standard is all this flow can build.
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
