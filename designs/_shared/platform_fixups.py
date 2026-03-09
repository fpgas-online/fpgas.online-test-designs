"""Platform-level fixups for LiteX board targets.

Workarounds for inconsistencies between litex-boards platform definitions
and the openXC7 toolchain expectations.
"""

import os
import re


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
