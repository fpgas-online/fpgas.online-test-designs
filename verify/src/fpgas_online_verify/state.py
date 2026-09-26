"""The board this host had last time, and what its flash held, so a change can be caught.

On a host with persistent storage the first verify records, for each board it found, the facts that should
not change by themselves: which board, its identity (serial numbers, IDCODE, PCI slot) and a fingerprint of
its flash. A later verify that sees different facts reports "changed", which is fatal, until
`fpgas-verify --update` records the new ones (after flashing a board on purpose, or swapping it). Loading a
design into SRAM, which every verify does, and upgrading packages change none of these facts.

A netboot root keeps /var/lib in tmpfs, so there every boot is a first run.
"""

import json
import pathlib

STATE = pathlib.Path("/var/lib/fpgas-online/verify-state.json")
SCHEMA_VERSION = 1


def load(path=STATE):
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        return {"unreadable": str(e)}
    return data.get("boards") if isinstance(data, dict) else {"unreadable": "not a JSON object"}


def save(boards, when, path=STATE):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "recorded_at": when, "boards": boards}, indent=2) + "\n"
    )
    tmp.replace(path)


def _walk(prefix, old, new, out):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            if key not in new:
                continue  # not read this time (a flash readback that failed): nothing to compare
            if key not in old:
                out.append(f"{prefix}{key}: not recorded before, now {new[key]!r}")
                continue
            _walk(f"{prefix}{key}.", old[key], new[key], out)
    elif old != new:
        out.append(f"{prefix.rstrip('.')}: was {old!r}, now {new!r}")


def differences(recorded, current):
    """What differs between the recorded boards and the current ones, as sentences; [] when nothing does."""
    if "unreadable" in (recorded or {}):
        return [f"the recorded state cannot be read ({recorded['unreadable']})"]
    out = []
    for board in sorted(set(recorded) - set(current)):
        out.append(f"{board}: recorded, not found now")
    for board in sorted(set(current) - set(recorded)):
        out.append(f"{board}: found now, not recorded before")
    for board in sorted(set(recorded) & set(current)):
        _walk(f"{board}.", recorded[board], current[board], out)
    return out
