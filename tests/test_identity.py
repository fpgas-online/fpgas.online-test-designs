"""Tests for identity.py: the per-board identity dict, its event form and its document.

rpi-hwid is never imported unless it is installed: fpgas-verify does not depend on it.
"""

import dataclasses

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


def test_the_flash_keeps_every_rdid_byte_and_register():
    out = identity.flash_fields(P48_FLASH, "pcie")
    assert out == {
        "flash": "S25FL256S", "flash_jedec": "0x010219", "flash_extended_id": "0x4d0180",
        "flash_size_bytes": 33554432, "flash_status": "0x00", "flash_config": "0x02", "flash_quad": True,
        "flash_uid": "edcbeececb2b2a88b04f914d2e46af90", "flash_uid_bits": 128, "flash_uid_state": "read",
        "flash_uid_opcode": "0x4b", "flash_source": "pcie",
    }  # fmt: skip


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


def test_the_document_is_versioned_and_holds_every_board():
    doc = identity.document([{"board": "arty", "kind": "arty"}], tool="fpgas-online-verify 0.0", read_at="now")
    assert doc == {"schema": "fpgas-verify/identity", "identity_version": 1, "tool": "fpgas-online-verify 0.0",
                   "read_at": "now", "source": "live", "boards": [{"board": "arty", "kind": "arty"}]}  # fmt: skip
    assert identity.document([])["tool"].startswith("fpgas-online-verify ")


def test_every_key_a_board_can_have_is_known():
    assert all(identity.known(k) for k in ("dna", "dna_error", "flash_error", "idcode_error", "board", "usb"))
    assert not identity.known("flash_part") and not identity.known("flash_unique_id")


def test_rpi_hwid_takes_the_dict_as_an_fpgaboard_when_it_is_installed():
    model = pytest.importorskip("rpi_hwid.model")
    assert tuple(f.name for f in dataclasses.fields(model.FpgaBoard)) == RPI_HWID_FPGABOARD_FIELDS
    board = {"kind": "acorn", "dna": "0x0054b48664b04854", **identity.flash_fields(P48_FLASH, "pcie")}
    fpga = model.FpgaBoard(**{k: v for k, v in board.items() if k in identity.FPGABOARD_FIELDS})
    assert fpga.flash_extended_id == "0x4d0180" and fpga.identity == "0x0054b48664b04854"
