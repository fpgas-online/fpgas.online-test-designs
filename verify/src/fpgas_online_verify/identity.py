"""Who each board is: one flat dict per board, the same in the boot report and the fpga-board-identified event.

The field names are rpi-hwid's FpgaBoard fields (FPGABOARD_FIELDS), verbatim, plus fields only fpgas-verify
has (EXTRA_FIELDS). docs/identity.md lists them all, with their types and when each is missing.

  * A key that is not there was not read.
  * A read that was tried and failed is `<field>_error`, the reason in words.
  * Identifiers are lower-case hex, 0x-prefixed, at a fixed width: the device DNA 16 digits (rpi-hwid's
    normalise_id), the IDCODE 8 (all 32 bits), the flash's RDID bytes 1-3 and 4-6 six each. The flash's
    unique ID is bare hex, as rpi-hwid has it.

The dict is the typed form: integers are numbers and booleans booleans. details() is the event form: flat
key=value strings, integers in decimal, booleans "true"/"false", lists and dicts compact JSON, "-" for read
and none, plus schema=fpga-identity/1. document() wraps the dicts of every board found in the versioned
document fpgas-verify --identify prints.

Stdlib only: the Pi hosts boot a tmpfs root with no LiteX.
"""

import datetime
import importlib.metadata
import json

from fpgas_online_verify import idcode

SCHEMA = "fpga-identity/1"  # the event's schema detail
DOCUMENT_SCHEMA = "fpgas-verify/identity"
IDENTITY_VERSION = 1

# rpi-hwid's src/rpi_hwid/model.py FpgaBoard, in its order. tests/test_identity.py pins this list.
FPGABOARD_FIELDS = (
    "kind", "serial", "dna", "idcode", "flash", "flash_jedec", "gateware", "gateware_id", "hw_rev", "mode",
    "trace_id", "dna_sources", "dna_agree", "dna_conflict", "soc_model", "flash_uid", "flash_uid_bits",
    "flash_uid_state", "flash_uid_note", "flash_error", "flash_extended_id", "flash_sfdp", "flash_source",
)  # fmt: skip
# The FpgaBoard fields fpgas-verify fills.
FIELDS = (
    "kind", "serial", "dna", "idcode", "flash", "flash_jedec", "flash_extended_id", "flash_sfdp", "flash_uid",
    "flash_uid_bits", "flash_uid_state", "flash_uid_note", "flash_error", "flash_source", "soc_model",
)  # fmt: skip
# fpgas-verify's own, whose names rpi-hwid does not use.
EXTRA_FIELDS = (
    "board", "variant", "bdf", "usb", "identifier", "build", "flash_size_bytes", "flash_status", "flash_config",
    "flash_quad", "flash_uid_opcode", "idcode_version", "idcode_part_number", "idcode_manufacturer_id",
    "idcode_manufacturer", "idcode_device",
)  # fmt: skip
ERROR_SUFFIX = "_error"
# idcode.decode()'s fields, in this order.
IDCODE_FIELDS = (
    "idcode", "idcode_version", "idcode_part_number", "idcode_manufacturer_id", "idcode_manufacturer",
    "idcode_device",
)  # fmt: skip

# A board module's name -> rpi-hwid's kind. The Acorn's own claims give theirs (kind()).
KINDS = {"acorn": "acorn", "arty": "arty", "netv2": "netv2", "tt": "tt", "fomu": "fomu"}
# What the Acorn module calls a PCIe design it finds -> rpi-hwid's kind.
ACORN_KINDS = {"fpgas-online": "acorn", "sqrl-factory": "acorn", "pcileech": "pcileech"}

DNA_DIGITS, IDCODE_DIGITS, RDID_DIGITS, REGISTER_DIGITS = 16, 8, 6, 2


def hex_id(value, digits):
    """An identifier as lower-case hex, 0x-prefixed, `digits` wide."""
    return f"0x{value:0{digits}x}"


def dna(value):
    """The device DNA (an int, or hex text however a tool spelled it), as rpi-hwid's normalise_id has it."""
    return hex_id(int(value, 16) if isinstance(value, str) else value, DNA_DIGITS)


def known(key):
    """True for a key the dict may have: a field, or a field's _error."""
    base = key[: -len(ERROR_SUFFIX)] if key.endswith(ERROR_SUFFIX) and key != "flash_error" else key
    return base in FIELDS or base in EXTRA_FIELDS


def kind(board_name, found):
    """rpi-hwid's kind for a board found by `board_name`'s module."""
    if board_name == "acorn":
        return ACORN_KINDS.get(found.get("kind"), "unknown-fpga")
    return KINDS.get(board_name, "unknown-fpga")


def base(board_key, board_name, found, variant=None):
    """What every board's dict starts with: board (the state key), kind, variant, and how it was found,
    including the IDCODE when finding the board read it (the NeTV2's scan)."""
    out = {"board": board_key, "kind": kind(board_name, found)}
    variant = variant or found.get("variant")
    if variant:
        out["variant"] = variant
    for key in ("serial", "usb", "bdf"):
        if found.get(key):
            out[key] = found[key]
    if found.get("idcode"):
        codes = found.get("idcodes") or [found["idcode"]]
        entry = idcode.decode(int(codes[0], 16)) if len(codes) == 1 else {"idcode": ", ".join(codes)}
        out.update(idcode_fields(entry))
    return out


def idcode_fields(entry):
    """The IDCODE fields from a JTAG entry: idcode.decode()'s fields, which are already identity fields (and
    maybe result/reason).

    One device on the chain gives the IDCODE and its decoded fields; anything else gives idcode_error."""
    code = entry.get("idcode")
    if code and "," not in code and "idcode_version" in entry:
        out = {key: entry[key] for key in IDCODE_FIELDS}
        out["idcode"] = hex_id(int(code, 16), IDCODE_DIGITS)
        return out
    if code:
        return {"idcode_error": f"the JTAG chain has more than one device ({code})"}
    if entry.get("result") not in (None, "pass"):
        return {"idcode_error": entry.get("reason") or entry["result"]}
    return {}


def flash_fields(ident, source):
    """The flash fields from what spi_flash.Flash.identify() read: all six RDID bytes, the part, its size, the
    status and configuration registers, and the factory unique ID with how it was read."""
    rdid = bytes.fromhex(ident["rdid"])
    out = {"flash_jedec": hex_id(int.from_bytes(rdid[:3], "big"), RDID_DIGITS)}
    if len(rdid) >= 6:
        out["flash_extended_id"] = hex_id(int.from_bytes(rdid[3:6], "big"), RDID_DIGITS)
    if ident.get("part") and ident["part"] != "unknown":
        out["flash"] = ident["part"]
    if ident.get("size_bytes"):
        out["flash_size_bytes"] = ident["size_bytes"]
    for key, name in (("status", "flash_status"), ("config", "flash_config")):
        if ident.get(key) is not None:
            out[name] = hex_id(int(ident[key], 16), REGISTER_DIGITS)
    if ident.get("quad_enabled") is not None:
        out["flash_quad"] = ident["quad_enabled"]
    uid = ident.get("unique_id")
    if uid:
        uid = uid.lower()
        out["flash_uid"] = uid
        out["flash_uid_bits"] = len(uid) * 4
        out["flash_uid_state"] = "blank" if set(uid) <= {"0"} or set(uid) <= {"f"} else "read"
        if ident.get("unique_id_opcode") is not None:
            out["flash_uid_opcode"] = hex_id(ident["unique_id_opcode"], REGISTER_DIGITS)
    out["flash_source"] = source
    return out


def _version():
    try:
        return importlib.metadata.version("fpgas-online-verify")
    except importlib.metadata.PackageNotFoundError:  # run from a checkout
        return "unknown"


def _check(value, where=""):
    """Raise TypeError unless `value` is a string, integer, boolean or None, or a list, tuple or dict of them
    (to any depth) whose dict keys are strings. The same rules hold at every depth: a float or a non-string
    key is refused inside a list or dict just as at the top."""
    at = f"{where}: " if where else ""
    if value is None or isinstance(value, (str, int)):  # bool is an int
        return
    if isinstance(value, (list, tuple)):
        for i, item in enumerate(value):
            _check(item, f"{where}[{i}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{at}an identity dict's keys must be strings, not {key!r}")
            _check(item, f"{where}.{key}" if where else key)
        return
    raise TypeError(f"{at}an identity value must be a string, integer, boolean, list, dict or None, not {value!r}")


def detail(value):
    """One value as an event detail (label contract §13, §17): a string as it is; None (read, and there is
    none) "-"; a boolean "true"/"false"; an integer in decimal; a list or dict compact JSON with sorted keys.
    Never a Python repr: any other type, at any depth, is a bug, and raises (_check)."""
    _check(value)
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (str, int)):
        return str(value)
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def details(board):
    """The fpga-board-identified event's details: the dict as flat strings, and its schema. A field not read
    is not in the dict, so not in the details either. A value detail() refuses raises TypeError naming its
    field."""
    out = {}
    for key, value in board.items():
        try:
            out[key] = detail(value)
        except TypeError as e:
            raise TypeError(f"identity field {key}: {e}") from None
    out["schema"] = SCHEMA
    return out


def refused(board):
    """The fields whose values details() refuses, each with why, so a caller can leave them out and say so."""
    out = {}
    for key, value in board.items():
        try:
            detail(value)
        except TypeError as e:
            out[key] = str(e)
    return out


KEEP = "keep_identity"  # the option the runner gives a board's check: called with the dict once it is built


def keep(options, board):
    """Hand the board's dict to the runner as soon as it is built, so a check that stops after sending
    fpga-board-identified still has it in its error report (and so in verify.json and fpga-verified)."""
    (options.get(KEEP) or (lambda board: None))(board)


def document(boards, source="live", tool=None, read_at=None):
    """The identity document: every board's dict, with what read them and when."""
    if tool is None:
        tool = f"fpgas-online-verify {_version()}"
    if read_at is None:
        read_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
    return {
        "schema": DOCUMENT_SCHEMA,
        "identity_version": IDENTITY_VERSION,
        "tool": tool,
        "read_at": read_at,
        "source": source,
        "boards": [dict(b) for b in boards],
    }
