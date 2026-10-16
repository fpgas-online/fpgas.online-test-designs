"""Tests for identity.py: the per-board identity dict, its event form and its document.

rpi-hwid is never imported unless it is installed: fpgas-verify does not depend on it.
"""

import dataclasses
import json
import pathlib

import pytest
from fpgas_online_verify import idcode, identity

# rpi-hwid's src/rpi_hwid/model.py FpgaBoard fields, in order, at mithro/rpi-hwid origin/main 90f4a91
# (2026-10-02). A change on either side shows here first.
RPI_HWID_FPGABOARD_FIELDS = (
    "kind", "serial", "dna", "idcode", "flash", "flash_jedec", "gateware", "gateware_id", "hw_rev", "mode",
    "trace_id", "dna_sources", "dna_agree", "dna_conflict", "soc_model", "flash_uid", "flash_uid_bits",
    "flash_uid_state", "flash_uid_note", "flash_error", "flash_extended_id", "flash_sfdp", "flash_source",
)  # fmt: skip

# rpi-hwid's src/rpi_hwid/model.py TinyTapeoutBoard fields, in order, at mithro/rpi-hwid origin/main 310cd23
# (2026-10-03).
RPI_HWID_TINYTAPEOUTBOARD_FIELDS = (
    "usb_serial", "mcu", "shuttle", "chip", "repo", "commit", "demoboard", "demoboard_version", "sdk",
)  # fmt: skip

P48_FLASH = {
    "rdid": "0102194d0180", "part": "S25FL256S", "size_bytes": 32 << 20,
    "unique_id": "EDCBEECECB2B2A88B04F914D2E46AF90", "status": "00", "config": "02", "quad_enabled": True,
    "unique_id_opcode": 0x4B,
}  # fmt: skip


def test_the_fpgaboard_field_list_is_rpi_hwids():
    assert identity.FPGABOARD_FIELDS == RPI_HWID_FPGABOARD_FIELDS


def test_the_fields_used_are_fpgaboards_and_the_extras_never_clash_with_them():
    assert set(identity.FIELDS) <= set(identity.FPGABOARD_FIELDS)
    assert not set(identity.EXTRA_FIELDS) & set(identity.FPGABOARD_FIELDS)


def test_the_tiny_tapeout_field_list_is_rpi_hwids_and_clashes_with_no_other():
    assert identity.TINYTAPEOUT_FIELDS == RPI_HWID_TINYTAPEOUTBOARD_FIELDS
    assert not set(identity.TINYTAPEOUT_FIELDS) & (set(identity.FPGABOARD_FIELDS) | set(identity.EXTRA_FIELDS))


def test_the_dna_is_16_digits_as_rpi_hwid_normalises_it():
    assert identity.dna(0x54B48664B04854) == "0x0054b48664b04854"
    assert identity.dna("0x54B48664B04854") == identity.dna("54b48664b04854") == "0x0054b48664b04854"


def test_the_idcode_is_all_32_bits_and_its_fields():
    out = identity.idcode_fields({**idcode.decode(0x13636093), "result": "pass"})
    assert out == {"idcode": "0x13636093", "idcode_version": 1, "idcode_part_number": "0x3636",
                   "idcode_manufacturer_id": "0x049", "idcode_manufacturer": "Xilinx",
                   "idcode_device": "XC7A200T"}  # fmt: skip


def test_an_idcode_that_could_not_be_read_is_an_error_and_one_never_tried_is_absent():
    assert identity.idcode_fields({"result": "fail", "reason": "no device on the JTAG chain"}) == {
        "idcode_error": "no device on the JTAG chain"
    }
    two = {**idcode.decode(0x13636093), "idcode": "0x13636093, 0x0362d093", "result": "fail"}
    assert "more than one device" in identity.idcode_fields(two)["idcode_error"]
    assert identity.idcode_fields({}) == {}


NETV2_FOUND = {"variant": "a7-100", "idcode": "0x13631093", "idcodes": ["0x13631093"],
               "idcode_scan": {"tool": "openFPGALoader", "exit": 0, "output": []}}  # fmt: skip


def test_the_idcode_read_when_the_board_was_found_is_in_its_base():
    out = identity.base("netv2", "netv2", NETV2_FOUND)
    assert out == {"board": "netv2", "kind": "netv2", "variant": "a7-100", **idcode.decode(0x13631093)}
    # a found with only the IDCODE, as before the whole chain was kept
    assert identity.base("netv2", "netv2", {"variant": "a7-100", "idcode": "0x13631093"}) == out


def test_a_chain_of_more_than_one_device_found_is_an_idcode_error_in_the_base():
    found = {**NETV2_FOUND, "idcodes": ["0x13631093", "0x0362d093"]}
    out = identity.base("netv2", "netv2", found)
    assert "idcode" not in out
    assert out["idcode_error"] == "the JTAG chain has more than one device (0x13631093, 0x0362d093)"


def test_a_board_found_without_an_idcode_has_none_in_its_base():
    out = identity.base("acorn", "acorn", {"kind": "fpgas-online", "bdf": "0000:01:00.0", "variant": "cle-215+"})
    assert out == {"board": "acorn", "kind": "acorn", "variant": "cle-215+", "bdf": "0000:01:00.0"}


def test_the_flash_keeps_every_rdid_byte_and_register():
    out = identity.flash_fields(P48_FLASH, "pcie")
    assert out == {
        "flash": "S25FL256S", "flash_jedec": "0x010219", "flash_extended_id": "0x4d0180",
        "flash_size_bytes": 33554432, "flash_status": "0x00", "flash_config": "0x02", "flash_quad": True,
        "flash_uid": "edcbeececb2b2a88b04f914d2e46af90", "flash_uid_bits": 128, "flash_uid_state": "read",
        "flash_uid_opcode": "0x4b", "flash_source": "pcie",
    }  # fmt: skip


@pytest.mark.parametrize(("read", "fields"), [
    ({"sfdp": "1.6"}, {"flash_sfdp": "1.6"}),
    ({"sfdp": "none"}, {"flash_sfdp": "none"}),
    ({"sfdp_error": "Read SFDP (0x5a) failed: timed out"}, {"flash_sfdp_error": "Read SFDP (0x5a) failed: timed out"}),
    ({}, {}),  # not read: neither field
])  # fmt: skip
def test_the_sfdp_revision_is_rpi_hwids_flash_sfdp(read, fields):
    out = identity.flash_fields({**P48_FLASH, **read}, "pcie")
    assert {k: v for k, v in out.items() if k.startswith("flash_sfdp")} == fields
    assert all(identity.known(k) for k in out)


@pytest.mark.parametrize("uid", ["00" * 16, "ff" * 16])
def test_a_unique_id_of_all_zeros_or_all_ones_is_blank(uid):
    assert identity.flash_fields({**P48_FLASH, "unique_id": uid}, "pcie")["flash_uid_state"] == "blank"


def test_a_part_not_known_has_no_name_but_keeps_its_ids():
    out = identity.flash_fields({**P48_FLASH, "rdid": "ef4019000000", "part": "unknown"}, "pcie")
    assert "flash" not in out and out["flash_jedec"] == "0xef4019" and out["flash_extended_id"] == "0x000000"


def test_the_kind_is_rpi_hwids():
    assert identity.kind("acorn", {"kind": "fpgas-online"}) == identity.kind("acorn", {"kind": "sqrl-factory"})
    assert identity.kind("acorn", {"kind": "sqrl-factory"}) == "acorn"
    assert identity.kind("acorn", {"kind": "pcileech"}) == "pcileech"
    assert identity.kind("acorn", {"kind": "litex-other"}) == "unknown-fpga"
    assert [identity.kind(b, {}) for b in ("arty", "netv2", "tt", "fomu")] == ["arty", "netv2", "tt", "fomu"]


def test_the_event_form_is_flat_strings_with_its_schema():
    board = {"board": "acorn", "flash_quad": False, "flash_uid_bits": 128, "idcode_version": 1, "dna": "0x01"}
    assert identity.details(board) == {"board": "acorn", "flash_quad": "false", "flash_uid_bits": "128",
                                       "idcode_version": "1", "dna": "0x01", "schema": "fpga-identity/1"}  # fmt: skip


@pytest.mark.parametrize(
    ("value", "text"),
    [
        ("0x13636093", "0x13636093"),
        (None, "-"),  # read, and there is none
        (True, "true"),
        (False, "false"),
        (0, "0"),
        (33554432, "33554432"),
        (["b", "a"], '["b","a"]'),  # a list keeps its order
        (("x", 1), '["x",1]'),
        ({"z": 1, "a": [True, None]}, '{"a":[true,null],"z":1}'),  # compact, keys sorted
        ([], "[]"),
    ],
)
def test_each_type_has_one_event_form(value, text):
    assert identity.details({"field": value}) == {"field": text, "schema": "fpga-identity/1"}


def test_a_field_not_read_is_left_out_of_the_event_and_never_spelled_none():
    out = identity.details({"board": "arty", "kind": "arty"})
    assert out == {"board": "arty", "kind": "arty", "schema": "fpga-identity/1"}
    assert "None" not in identity.details({"dna": None}).values()


@pytest.mark.parametrize("value", [1.5, b"\x00", object()])
def test_a_value_of_any_other_type_is_a_bug_not_a_repr(value):
    with pytest.raises(TypeError, match=r"^identity field field: "):
        identity.details({"field": value})


@pytest.mark.parametrize(
    ("value", "where"),
    [
        ({"a": 1.5}, "a: "),
        ([1, 1.5], r"\[1\]: "),
        ({"a": [{"b": b"\x00"}]}, r"a\[0\]\.b: "),
        ({1: "x"}, ""),  # json.dumps would quietly make the key "1"
        ({"a": {None: 1}}, "a: "),
        ([object()], r"\[0\]: "),
    ],
)
def test_a_value_inside_a_list_or_dict_follows_the_same_rules(value, where):
    with pytest.raises(TypeError, match=rf"^identity field field: {where}an identity "):
        identity.details({"field": value})


def test_strings_integers_booleans_and_none_are_allowed_at_any_depth():
    value = {"a": [1, "x", True, None, ("y", {"b": [False]})]}
    assert identity.details({"field": value})["field"] == '{"a":[1,"x",true,null,["y",{"b":[false]}]]}'


def test_the_fields_refused_are_named_with_why():
    assert identity.refused({"board": "arty", "volts": 1.5, "raw": b"\x00"}).keys() == {"volts", "raw"}
    assert identity.refused({"board": "arty", "idcode_version": 1}) == {}


def test_a_field_name_that_is_not_a_string_is_refused_like_a_nested_one():
    with pytest.raises(TypeError, match="identity field 5: an identity's field names must be strings, not 5"):
        identity.details({"board": "arty", 5: "x"})
    assert identity.refused({"board": "arty", 5: "x"}) == {5: "an identity's field names must be strings, not 5"}


@pytest.mark.parametrize("board", ["arty", ["board", "arty"], None])
def test_an_identity_that_is_not_a_dict_is_refused(board):
    with pytest.raises(TypeError, match="an identity must be a dict, not "):
        identity.details(board)
    with pytest.raises(TypeError, match="an identity must be a dict, not "):
        identity.refused(board)


def test_the_document_is_versioned_and_holds_every_board():
    doc = identity.document([{"board": "arty", "kind": "arty"}], tool="fpgas-online-verify 0.0", read_at="now")
    assert doc == {"schema": "fpgas-verify/identity", "identity_version": 1, "tool": "fpgas-online-verify 0.0",
                   "read_at": "now", "source": "live", "boards": [{"board": "arty", "kind": "arty"}]}  # fmt: skip
    assert identity.document([])["tool"].startswith("fpgas-online-verify ")


def test_every_key_a_board_can_have_is_known():
    assert all(identity.known(k) for k in ("dna", "dna_error", "flash_error", "idcode_error", "board", "usb"))
    assert not identity.known("flash_part") and not identity.known("flash_unique_id")
    tt = ("usb_serial", "mcu", "sdk", "demoboard_version", "tinytapeout_error", "tinytapeout_note")
    assert all(identity.known(k) for k in tt)
    assert not identity.known("tinytapeout") and not identity.known("chip_url")


FIXTURE = pathlib.Path(__file__).parent / "data" / "identity-v1-acorn-p48.json"
# The golden fixture's board: every key, with its JSON type. A change here is a change to identity version 1.
FIXTURE_BOARD_TYPES = {
    "bdf": str, "board": str, "build": str, "dna": str, "flash": str, "flash_config": str, "flash_extended_id": str,
    "flash_jedec": str, "flash_quad": bool, "flash_size_bytes": int, "flash_source": str, "flash_status": str,
    "flash_uid": str, "flash_uid_bits": int, "flash_uid_opcode": str, "flash_uid_state": str, "idcode": str,
    "idcode_device": str, "idcode_manufacturer": str, "idcode_manufacturer_id": str, "idcode_part_number": str,
    "idcode_version": int, "identifier": str, "kind": str, "soc_model": str, "variant": str,
}  # fmt: skip


def test_the_golden_fixture_has_exactly_its_keys_types_and_version():
    doc = json.loads(FIXTURE.read_text())
    assert set(doc) == {"schema", "identity_version", "tool", "read_at", "source", "boards"}
    assert (doc["schema"], doc["identity_version"], doc["source"]) == ("fpgas-verify/identity", 1, "live")
    (board,) = doc["boards"]
    assert {k: type(v) for k, v in board.items()} == FIXTURE_BOARD_TYPES
    assert all(identity.known(k) for k in board)
    assert (board["dna"], board["idcode"], board["flash_jedec"], board["flash_extended_id"]) == (
        "0x0054b48664b04854", "0x13636093", "0x010219", "0x4d0180")  # fmt: skip
    assert (board["flash"], board["flash_uid"], board["flash_size_bytes"], board["kind"], board["variant"]) == (
        "S25FL256S", "edcbeececb2b2a88b04f914d2e46af90", 33554432, "acorn", "cle-215+")  # fmt: skip


def test_rpi_hwid_takes_the_golden_fixture_as_an_fpgaboard_when_it_is_installed():
    model = pytest.importorskip("rpi_hwid.model")
    (board,) = json.loads(FIXTURE.read_text())["boards"]
    fpga = model.FpgaBoard(**{k: v for k, v in board.items() if k in identity.FPGABOARD_FIELDS})
    assert fpga.kind == "acorn" and fpga.dna == "0x0054b48664b04854" and fpga.flash_uid_bits == 128


def test_rpi_hwid_takes_the_dict_as_an_fpgaboard_when_it_is_installed():
    model = pytest.importorskip("rpi_hwid.model")
    assert tuple(f.name for f in dataclasses.fields(model.FpgaBoard)) == RPI_HWID_FPGABOARD_FIELDS
    board = {"kind": "acorn", "dna": "0x0054b48664b04854", **identity.flash_fields(P48_FLASH, "pcie")}
    fpga = model.FpgaBoard(**{k: v for k, v in board.items() if k in identity.FPGABOARD_FIELDS})
    assert fpga.flash_extended_id == "0x4d0180" and fpga.identity == "0x0054b48664b04854"


def test_rpi_hwid_takes_a_tt_boards_fields_as_a_tinytapeoutboard_when_it_is_installed():
    model = pytest.importorskip("rpi_hwid.model")
    assert tuple(f.name for f in dataclasses.fields(model.TinyTapeoutBoard)) == RPI_HWID_TINYTAPEOUTBOARD_FIELDS
    board = {**identity.base("tt", "tt", {"variant": "tt-fpga", "usb": "1-2", "serial": "E661"}),
             "mcu": "RP2350", "chip": "fpga", "shuttle": None, "sdk": "v3.1.0"}  # fmt: skip
    tt = model.TinyTapeoutBoard(**{k: v for k, v in board.items() if k in identity.TINYTAPEOUT_FIELDS})
    assert tt.identity == "E661" and tt.mcu == "RP2350"


def test_rpi_hwid_takes_flash_sfdp_as_an_fpgaboard_field_when_it_is_installed():
    model = pytest.importorskip("rpi_hwid.model")
    board = {"kind": "acorn", **identity.flash_fields({**P48_FLASH, "sfdp": "none"}, "pcie")}
    fpga = model.FpgaBoard(**{k: v for k, v in board.items() if k in identity.FPGABOARD_FIELDS})
    assert fpga.flash_sfdp == "none"


# -- openFPGALoader --flash-info-json (the Arty's and NeTV2's flash, through the SPI-over-JTAG bridge) ----------

# A version 2 document as openFPGALoader's doc/guide/advanced.rst has it, with a field this reader does not know.
FLASH_INFO_FLASH = {
    "jedec_id": "0x010219", "manufacturer_id": "0x01", "memory_type": "0x02", "capacity": "0x19",
    "manufacturer": "Spansion", "manufacturer_jep106": "Spansion / Cypress / Infineon", "part": "S25FL256S",
    "extended_id": "0x4d0180", "size_bytes": 33554432, "size_source": "database",
    "unique_id": {"state": "read", "value": "E2789916A0809A22BBC76634C1BF53ED", "bits": 128, "opcode": "0x4b",
                  "note": None},
    "sfdp": {"revision": "1.6", "tables": [], "bfpt": {}}, "a_field_added_later": [1, 2],
}  # fmt: skip


def _flash_info(**changes):
    return {"format": "openFPGALoader-flash-info", "version": 2, "flashes": [{**FLASH_INFO_FLASH, **changes}]}


def test_a_flash_info_read_gives_the_same_fields_as_flash_fields_with_source_jtag():
    out = identity.flash_info_fields(_flash_info(), "jtag")
    assert out == {
        "flash_jedec": "0x010219", "flash_extended_id": "0x4d0180",
        "flash_uid": "e2789916a0809a22bbc76634c1bf53ed", "flash_uid_bits": 128,
        "flash_uid_state": "read", "flash_uid_opcode": "0x4b", "flash_sfdp": "1.6", "flash_source": "jtag",
    }  # fmt: skip
    assert all(identity.known(k) for k in out)
    # the same reading as the Acorn's spi_flash.Flash.identify() dict gives the same fields, part and size aside
    same = identity.flash_fields({"rdid": "0102194d0180", "unique_id": "E2789916A0809A22BBC76634C1BF53ED",
                                  "unique_id_opcode": 0x4B, "sfdp": "1.6"}, "jtag")  # fmt: skip
    assert out == same


def test_a_flash_info_part_and_size_from_openfpgaloaders_database_are_not_sent():
    """A JEDEC ID several parts share (the contract names 0xc22017, the NeTV2's Macronix, read 16 Oct 2026) must
    not put a part on a label that the chip never said: `flash` only from the chip, the size from its SFDP."""
    out = identity.flash_info_fields(_flash_info(), "jtag")
    assert "flash" not in out and "flash_size_bytes" not in out
    sfdp = {"revision": "1.0", "tables": [], "bfpt": {"density_bits": 67108864}}
    out = identity.flash_info_fields(_flash_info(sfdp=sfdp), "jtag")
    assert "flash" not in out and out["flash_size_bytes"] == 8388608
    out = identity.flash_info_fields(_flash_info(size_source="sfdp", sfdp=None), "jtag")
    assert out["flash_size_bytes"] == 33554432 and out["flash_sfdp"] == "none"


def test_a_flash_info_unique_id_read_blank_has_its_length_and_command_and_no_id():
    uid = {"state": "blank", "value": None, "bits": 64, "opcode": "0x4B", "note": None}
    out = identity.flash_info_fields(_flash_info(unique_id=uid), "jtag")
    assert (out["flash_uid_state"], out["flash_uid_bits"], out["flash_uid_opcode"]) == ("blank", 64, "0x4b")
    assert "flash_uid" not in out and "flash_uid_note" not in out and "flash_error" not in out


def test_a_flash_info_unique_id_the_chip_says_it_has_none_keeps_the_chips_note():
    note = "no factory ESN: security register 0x00"
    uid = {"state": "none", "value": None, "bits": None, "opcode": None, "note": note}
    out = identity.flash_info_fields(_flash_info(unique_id=uid), "jtag")
    assert (out["flash_uid_state"], out["flash_uid_note"]) == ("none", note)
    assert not {"flash_uid", "flash_uid_bits", "flash_uid_opcode", "flash_error"} & set(out)


def test_a_flash_info_unique_id_openfpgaloader_has_no_command_for_has_no_note():
    """`none` with a null note is openFPGALoader knowing no command for the part, not the chip saying it has no
    unique ID: rpi-hwid makes no label from it (label_input._fpga_needs), so no note is made up for it."""
    uid = {"state": "none", "value": None, "bits": None, "opcode": None, "note": None}
    out = identity.flash_info_fields(_flash_info(unique_id=uid), "jtag")
    assert out["flash_uid_state"] == "none"
    assert not {"flash_uid", "flash_uid_bits", "flash_uid_note", "flash_error"} & set(out)


def test_a_flash_info_part_without_sfdp_or_extended_id_or_known_part():
    out = identity.flash_info_fields(_flash_info(sfdp=None, extended_id=None, part=None, size_bytes=None), "jtag")
    assert out["flash_sfdp"] == "none" and out["flash_jedec"] == "0x010219"
    assert not {"flash_extended_id", "flash", "flash_size_bytes", "flash_error"} & set(out)


@pytest.mark.parametrize(
    ("doc", "why"),
    [
        ([], "the document is not a JSON object"),
        ({**_flash_info(), "format": "something-else"}, "its format is 'something-else'"),
        ({**_flash_info(), "version": 1}, "it is version 1; this reader takes only version 2"),
        ({**_flash_info(), "version": "2"}, "it is version '2'"),
        ({**_flash_info(), "version": True}, "it is version True"),
        ({**_flash_info(), "version": 3}, "it is version 3"),
        ({**_flash_info(), "flashes": []}, "it describes 0 flashes, not the board's one"),
        ({**_flash_info(), "flashes": [FLASH_INFO_FLASH, FLASH_INFO_FLASH]}, "it describes 2 flashes"),
        ({k: v for k, v in _flash_info().items() if k != "flashes"}, "it has no list of flashes"),
        (_flash_info(jedec_id="0xffffff"), "its JEDEC ID is 0xffffff: no flash answered"),
        (_flash_info(jedec_id="010219"), "its jedec_id is '010219'"),
        (_flash_info(jedec_id="0x010219\n"), "its jedec_id is"),
        (_flash_info(extended_id="0x4d01"), "its extended_id is '0x4d01'"),
        (_flash_info(unique_id={"state": "maybe"}), "its unique_id state is not one of read, blank, none"),
        (_flash_info(unique_id={**FLASH_INFO_FLASH["unique_id"], "value": "e278"}), "not 128 bits of hex"),
        (_flash_info(unique_id={**FLASH_INFO_FLASH["unique_id"], "value": "00" * 16}), "a blank read, not an ID"),
        (_flash_info(unique_id={**FLASH_INFO_FLASH["unique_id"], "opcode": None}), "with no opcode"),
        ({"format": "openFPGALoader-flash-info", "version": 2,
          "flashes": [{k: v for k, v in FLASH_INFO_FLASH.items() if k != "sfdp"}]}, "it has no sfdp"),
        (_flash_info(sfdp={"tables": []}), "its sfdp has no revision major.minor"),
    ],
)  # fmt: skip
def test_a_flash_info_document_this_does_not_take_is_a_flash_error_saying_why(doc, why):
    out = identity.flash_info_fields(doc, "jtag")
    assert list(out) == ["flash_error"]
    assert out["flash_error"].startswith("openFPGALoader's flash-info JSON is not one this reads: ")
    assert why in out["flash_error"]


def _netv2_identity(**uid):
    """A NeTV2's identity as its boot check builds it: found by its scan, its DNA, and its flash's identity."""
    found = {"variant": "a7-100", "idcode": "0x13631093", "idcodes": ["0x13631093"]}
    flash = _flash_info(unique_id={**FLASH_INFO_FLASH["unique_id"], **uid}) if uid else _flash_info()
    return {**identity.base("netv2", "netv2", found), "dna": "0x00589b1c2c34085c",
            **identity.flash_info_fields(flash, "jtag")}  # fmt: skip


def _label_needs(board):
    from rpi_hwid import label_input

    fpga = {k: v for k, v in board.items() if k in identity.FPGABOARD_FIELDS}
    return label_input.missing(label_input.build("netv2-host", {"fpga": [fpga]}))["fpga[0]"]


def test_rpi_hwid_can_label_a_netv2_from_its_flash_info_when_it_is_installed():
    model = pytest.importorskip("rpi_hwid.model")
    pytest.importorskip("rpi_hwid.label_input")
    board = _netv2_identity()
    fpga = model.FpgaBoard(**{k: v for k, v in board.items() if k in identity.FPGABOARD_FIELDS})
    assert (fpga.kind, fpga.identity, fpga.flash_source) == ("netv2", "0x00589b1c2c34085c", "jtag")
    assert _label_needs(board) == []
    # the chip saying it has no unique ID is a fact a label carries
    assert _label_needs(_netv2_identity(state="none", value=None, bits=None, opcode=None, note="no ESN: 0x00")) == []


def test_rpi_hwid_will_not_label_a_netv2_whose_unique_id_is_not_known_when_it_is_installed():
    """openFPGALoader knowing no unique ID command, or reading a blank one, leaves the label refused: rpi-hwid
    says what it still needs, and fpgas-verify --identify says the same (identify.missing)."""
    pytest.importorskip("rpi_hwid.label_input")
    from fpgas_online_verify import identify
    from fpgas_online_verify.boards.netv2 import BOARD as NETV2

    unknown = _netv2_identity(state="none", value=None, bits=None, opcode=None, note=None)
    assert _label_needs(unknown) == ["flash_uid_note"]
    assert identify.missing(NETV2, unknown) == [("flash_uid_note", identify.UID_NO_COMMAND)]
    blank = _netv2_identity(state="blank", value=None, bits=128)
    assert _label_needs(blank) == ["flash_uid_state"]
    assert identify.missing(NETV2, blank) == [("flash_uid_state", identify.UID_BLANK)]
    assert identify.missing(NETV2, _netv2_identity()) == []
