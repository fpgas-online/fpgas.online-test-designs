"""Reading and decoding whole JTAG IDCODEs (verify/src/fpgas_online_verify/idcode.py).

The openFPGALoader output is what pi-sw2-p48 printed on 2026-10-02 for
`openFPGALoader --cable libgpiod --pins 10:9:11:8 --detect --verbose-level 2`; its Acorn CLE-215+ (XC7A200T)
answers 0x13636093, silicon version 1, which plain `--detect` prints as "idcode 0x3636093".
"""

from fpgas_online_verify import idcode

P48 = """libgpiod jtag bitbang driver, dev=/dev/gpiochip0, tck_pin=11, tms_pin=8, tdi_pin=10, tdo_pin=9
Raw IDCODE:
- 0 -> 0x13636093
- 1 -> 0xffffffff
Fetched TDI, end-of-chain
found 1 devices
index 0:
	idcode 0x3636093
	manufacturer xilinx
	family artix a7 200t
	model  xc7a200
	irlength 6
"""
OPENOCD = "Info : JTAG tap: xc7.tap tap/device found: 0x0362d093 (mfg: 0x049 (Xilinx), part: 0x362d, ver: 0x0)\n"


def test_the_raw_scan_gives_the_whole_idcode_not_the_masked_one():
    assert idcode.parse(P48) == [0x13636093]


def test_the_report_keeps_the_raw_scan_lines_not_the_masked_part_table():
    assert idcode.scan_lines(P48) == ["- 0 -> 0x13636093", "- 1 -> 0xffffffff"]
    assert idcode.scan_lines(OPENOCD) == [OPENOCD.strip()]


def test_plain_detect_output_has_no_whole_idcode():
    """Without the raw scan there is only the part table's masked value, which is not read as the IDCODE."""
    assert idcode.parse(P48.split("index 0:")[1]) == []


def test_openocd_output_is_the_whole_idcode():
    assert idcode.parse(OPENOCD) == [0x0362D093]


def test_an_empty_or_stuck_chain_has_no_devices():
    assert idcode.parse("Raw IDCODE:\n- 0 -> 0xffffffff\nFetched TDI, end-of-chain\n") == []
    assert idcode.parse("Raw IDCODE:\n- 0 -> 0x00000000\nJTAG init failed with: TDO is stuck at 0\n") == []


def test_p48s_idcode_decodes_to_an_xc7a200t_version_1():
    assert idcode.decode(0x13636093) == {
        "idcode": "0x13636093",
        "idcode_version": 1,
        "idcode_part_number": "0x3636",
        "idcode_manufacturer_id": "0x049",
        "idcode_manufacturer": "Xilinx",
        "idcode_device": "XC7A200T",
    }


def test_a_version_0_idcode_keeps_its_leading_zero():
    assert idcode.decode(0x0362D093) == {
        "idcode": "0x0362d093",
        "idcode_version": 0,
        "idcode_part_number": "0x362d",
        "idcode_manufacturer_id": "0x049",
        "idcode_manufacturer": "Xilinx",
        "idcode_device": "XC7A35T",
    }


def test_an_altera_idcode_names_altera():
    d = idcode.decode(0x020F30DD)
    assert (d["idcode_manufacturer_id"], d["idcode_manufacturer"], d["idcode_part_number"], d["idcode_device"]) == (
        "0x06e",
        "Altera",
        "0x20f3",
        "unknown",
    )


def test_an_ecp5_idcode_names_lattice():
    d = idcode.decode(0x41111043)
    assert (
        d["idcode_version"],
        d["idcode_manufacturer_id"],
        d["idcode_manufacturer"],
        d["idcode_part_number"],
        d["idcode_device"],
    ) == (
        4,
        "0x021",
        "Lattice",
        "0x1111",
        "unknown",
    )


def test_the_parts_on_the_boards_have_names():
    names = {code: idcode.device(code) for code in (0x13631093, 0x0362C093, 0x2362D093, 0x03636093)}
    assert names == {0x13631093: "XC7A100T", 0x0362C093: "XC7A50T", 0x2362D093: "XC7A35T", 0x03636093: "XC7A200T"}


def test_an_unknown_part_and_manufacturer_say_so():
    d = idcode.decode(0x41234567)
    assert (d["idcode_device"], d["idcode_manufacturer"], d["idcode_manufacturer_id"], d["idcode_part_number"]) == (
        "unknown",
        "unknown",
        "0x2b3",
        "0x1234",
    )


def test_the_part_is_compared_without_the_version():
    assert idcode.same_part(0x13636093, 0x03636093)
    assert idcode.same_part(0xF3636093, 0x03636093)
    assert not idcode.same_part(0x13631093, 0x03636093)


def test_bit_0_must_be_set():
    assert idcode.faults(0x13636093) == []
    assert idcode.faults(0x13636092) == ["IDCODE 0x13636092 has bit 0 clear, which no IDCODE has"]
