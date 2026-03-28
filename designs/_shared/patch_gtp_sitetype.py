"""Add bracket-form port aliases to GTP site type JSON files.

nextpnr-xilinx uses Verilog bracket notation for bus ports (``RXDATA[0]``),
but nextpnr-xilinx-meta site type definitions use flat names (``RXDATA0``).
This mismatch causes "No wire found for port" errors during routing.

This script adds bracket aliases so chipdb generation includes both forms.

Usage::

    python patch_gtp_sitetype.py site_type_GTPE2_CHANNEL.json [site_type_GTPE2_COMMON.json ...]
"""

import json
import re
import sys

# Match flat bus port names: UPPERCASE_PREFIX followed by DIGITS at end.
_BUS_PORT_RE = re.compile(r"^([A-Z][A-Z_]*)(\d+)$")


def _find_bus_aliases(names):
    """Identify bus ports and return flat→bracket name mapping.

    Groups port names by alphabetic prefix.  Only prefixes with 2+
    numeric suffixes are treated as buses (avoids aliasing scalar ports
    like ``GTREFCLK0``).

    Returns e.g. ``{"RXDATA0": "RXDATA[0]", "RXDATA1": "RXDATA[1]", ...}``
    """
    groups = {}
    for name in names:
        m = _BUS_PORT_RE.match(name)
        if m:
            groups.setdefault(m.group(1), []).append((name, m.group(2)))

    return {
        flat: f"{prefix}[{idx}]"
        for prefix, members in groups.items()
        if len(members) >= 2
        for flat, idx in members
    }


def patch_site_type(path):
    """Add bracket-form aliases to a site type JSON and rewrite in place.

    Handles both dict-keyed and list-of-dicts pin formats used across
    different nextpnr-xilinx-meta versions.

    Returns the number of aliases added.
    """
    with open(path) as f:
        data = json.load(f)

    added = 0

    for key in ("site_pins", "pins"):
        if key not in data:
            continue
        pins = data[key]

        if isinstance(pins, dict):
            aliases = _find_bus_aliases(pins.keys())
            for flat, bracket in aliases.items():
                if bracket not in pins:
                    pins[bracket] = dict(pins[flat])
                    added += 1

        elif isinstance(pins, list):
            existing = {p["name"] for p in pins}
            aliases = _find_bus_aliases(existing)
            for flat, bracket in aliases.items():
                if bracket not in existing:
                    orig = next(p for p in pins if p["name"] == flat)
                    pins.append({**orig, "name": bracket})
                    added += 1

        break  # Only process the first matching key

    if not added:
        print(f"patch_gtp_sitetype: no bus ports to alias in {path}", file=sys.stderr)
        return 0

    with open(path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    print(f"patch_gtp_sitetype: added {added} alias(es) to {path}", file=sys.stderr)
    return added


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <site_type.json> [...]", file=sys.stderr)
        sys.exit(1)
    total = sum(patch_site_type(p) for p in sys.argv[1:])
    print(f"patch_gtp_sitetype: {total} total alias(es) added", file=sys.stderr)
