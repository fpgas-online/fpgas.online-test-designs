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


def test_rpi_hwid_takes_flash_sfdp_as_an_fpgaboard_field_when_it_is_installed():
    model = pytest.importorskip("rpi_hwid.model")
    board = {"kind": "acorn", **identity.flash_fields({**P48_FLASH, "sfdp": "none"}, "pcie")}
    fpga = model.FpgaBoard(**{k: v for k, v in board.items() if k in identity.FPGABOARD_FIELDS})
    assert fpga.flash_sfdp == "none"
