"""Add bracket-form port aliases to GTP site type JSON files.

nextpnr-xilinx uses Verilog bracket notation for bus ports (``RXDATA[0]``),
but nextpnr-xilinx-meta site type definitions use flat names (``RXDATA0``).
This mismatch causes "No wire found for port" errors during routing.

This script adds bracket aliases so chipdb generation includes both forms.

The site type JSON format nests pins under ``bels``::

    {
      "GTPE2_CHANNEL": {
        "bels": {
          "GTPE2_CHANNEL": {
            "pins": {
              "RXDATA0": {"dir": "OUTPUT", "wire": "RXDATA0"},
              ...
            }
          }
        }
      }
    }

Usage::

    python patch_gtp_sitetype.py site_type_GTPE2_CHANNEL.json [site_type_GTPE2_COMMON.json ...]
"""

import json
import re
import sys

# Match flat bus port names: UPPERCASE_PREFIX followed by DIGITS at end.
_BUS_PORT_RE = re.compile(r"^([A-Z][A-Z_]*)(\d+)$")


def _find_bus_aliases(names):
    """Identify bus ports and return flat->bracket name mapping.

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


def _patch_pins_dict(pins):
    """Add bracket aliases to a pins dict. Returns number of aliases added."""
    aliases = _find_bus_aliases(pins.keys())
    added = 0
    for flat, bracket in aliases.items():
        if bracket not in pins:
            # Clone the pin entry but keep the original wire name
            pins[bracket] = dict(pins[flat])
            added += 1
    return added


def patch_site_type(path):
    """Add bracket-form aliases to a site type JSON and rewrite in place.

    Handles the nextpnr-xilinx-meta format where pins are nested under
    ``bels.*.pins``, as well as top-level ``site_pins`` or ``pins`` keys.

    Returns the number of aliases added.
    """
    with open(path) as f:
        data = json.load(f)

    added = 0

    # Handle nested format: top-level key is site type name, pins under bels
    for _site_type_name, site_data in data.items():
        if not isinstance(site_data, dict):
            continue
        bels = site_data.get("bels", {})
        if isinstance(bels, dict):
            for _bel_name, bel_data in bels.items():
                if isinstance(bel_data, dict) and "pins" in bel_data:
                    pins = bel_data["pins"]
                    if isinstance(pins, dict):
                        added += _patch_pins_dict(pins)

        # Also check for site_pins at the site type level
        for key in ("site_pins", "pins"):
            if key in site_data and isinstance(site_data[key], dict):
                added += _patch_pins_dict(site_data[key])

    # Also check top-level site_pins/pins (alternative format)
    for key in ("site_pins", "pins"):
        if key in data and isinstance(data[key], dict):
            added += _patch_pins_dict(data[key])
        elif key in data and isinstance(data[key], list):
            existing = {p["name"] for p in data[key]}
            aliases = _find_bus_aliases(existing)
            for flat, bracket in aliases.items():
                if bracket not in existing:
                    orig = next(p for p in data[key] if p["name"] == flat)
                    data[key].append({**orig, "name": bracket})
                    added += 1

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
