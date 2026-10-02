"""The board this host had last time, and what its flash held, so a change can be caught.

On a host with persistent storage the first verify records, for each board it found, the facts that should
not change by themselves: which board, its identity (serial numbers, IDCODE, PCI slot) and a fingerprint of
its flash. A later verify that sees different facts reports "changed", which is fatal, until
`fpgas-verify --update` records the new ones (after flashing a board on purpose, or swapping it). Loading a
design into SRAM, which every verify does, and upgrading packages change none of these facts.

A fact the record does not have is a change ("not recorded before"): it may be one that could not be read
last time, on a board that has since been swapped. The one exception is a fact a newer version of the
record introduced (NEW_FACTS): on a record of an older version it is added quietly, so an upgrade that reads
more does not make every stateful host report "changed" once. Likewise a fact a newer version reads more of,
or writes differently (WIDENED: the IDCODE, once read without its version; the device DNA, once written
without its leading zeros): on an older record, a recorded value that the new one only adds to, or only
respells, is replaced quietly.

A netboot root keeps /var/lib in tmpfs, so there every boot is a first run.
"""

import json
import pathlib

STATE = pathlib.Path("/var/lib/fpgas-online/verify-state.json")
SCHEMA_VERSION = 4
# The facts of a board's state that each version of the record introduced: {version: (key, ...)}.
NEW_FACTS = {2: ("dna",), 3: ("idcode",)}  # 2: the Acorn's device DNA; 3: the Arty's IDCODE


def _idcode_widened(old, new):
    """The recorded IDCODE is the new one without its version (openFPGALoader's --detect masked it)."""
    try:
        return int(old, 16) == int(new, 16) & 0x0FFFFFFF
    except (TypeError, ValueError):
        return False


def _same_number(old, new):
    """The recorded value is the new one spelled differently (the DNA, before identity.py gave it 16 digits)."""
    try:
        return int(old, 16) == int(new, 16)
    except (TypeError, ValueError):
        return False


# The facts each version of the record reads more of, or writes differently:
# {version: {key: old value is the new one, less or respelled}}.
WIDENED = {3: {"idcode": _idcode_widened}, 4: {"dna": _same_number}}


def load_record(path=STATE):
    """(boards, schema_version) of the recorded state; (None, None) when there is none."""
    try:
        data = json.loads(pathlib.Path(path).read_text())
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as e:
        return {"unreadable": str(e)}, None
    if not isinstance(data, dict):
        return {"unreadable": "not a JSON object"}, None
    return data.get("boards"), data.get("schema_version", 1)


def load(path=STATE):
    return load_record(path)[0]


def quiet_facts(version):
    """The board-level keys a record of `version` may lack without that being a change."""
    return {key for v, keys in NEW_FACTS.items() if (version or 1) < v for key in keys}


def widened(recorded, current, version):
    """The recorded boards with each fact that a newer version reads more of (WIDENED) replaced by the current
    value, where the recorded one is that value, less; the record itself when there is nothing to replace."""
    rules = {key: same for v, keys in WIDENED.items() if (version or 1) < v for key, same in keys.items()}
    if not rules or not isinstance(recorded, dict) or "unreadable" in recorded:
        return recorded
    out = dict(recorded)
    for board, facts in recorded.items():
        now = current.get(board)
        if not (isinstance(facts, dict) and isinstance(now, dict)):
            continue
        for key, same in rules.items():
            if key in facts and key in now and facts[key] != now[key] and same(facts[key], now[key]):
                out[board] = {**out[board], key: now[key]}
    return out


def save(boards, when, path=STATE):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION, "recorded_at": when, "boards": boards}, indent=2) + "\n"
    )
    tmp.replace(path)


def _walk(prefix, old, new, out, quiet=()):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            if key not in new:
                continue  # not read this time (a flash readback that failed): nothing to compare
            if key not in old:
                if key not in quiet:  # quiet: a fact the record's version did not have yet
                    out.append(f"{prefix}{key}: not recorded before, now {new[key]!r}")
                continue
            _walk(f"{prefix}{key}.", old[key], new[key], out)
    elif old != new:
        out.append(f"{prefix.rstrip('.')}: was {old!r}, now {new!r}")


def merged(recorded, current):
    """The recorded state with what is new in `current` added, and nothing recorded dropped."""
    if not (isinstance(recorded, dict) and isinstance(current, dict)):
        return current
    out = dict(recorded)
    for key, value in current.items():
        out[key] = merged(recorded[key], value) if key in recorded else value
    return out


def differences(recorded, current, quiet=()):
    """What differs between the recorded boards and the current ones, as sentences; [] when nothing does.
    `quiet`: board-level keys the record may lack (quiet_facts())."""
    if "unreadable" in (recorded or {}):
        return [f"the recorded state cannot be read ({recorded['unreadable']})"]
    out = []
    for board in sorted(set(recorded) - set(current)):
        out.append(f"{board}: recorded, not found now")
    for board in sorted(set(current) - set(recorded)):
        out.append(f"{board}: found now, not recorded before")
    for board in sorted(set(recorded) & set(current)):
        _walk(f"{board}.", recorded[board], current[board], out, quiet)
    return out
