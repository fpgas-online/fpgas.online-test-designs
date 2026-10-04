"""Blocks between the Pi's RAM and the Acorn's DDR3 (fpgas_online_verify.boards.acorn.dma).

The driver and the SoC behind it are tests/acorn_fakes.py's FakeLitePCIe; the check's `dma` test runs on the
rig of tests/test_acorn_verify.py, whose FakePi has the kernel's side (lsmod, modprobe, rmmod, /dev/litepcie0).
"""

import json
import pathlib
import struct

import pytest
from fpgas_online_verify.boards.acorn import check, dma

from tests import acorn_fakes as fk
from tests.test_acorn_verify import Rig, images, small_slots  # noqa: F401  -- fixtures

CSRS = check.Csrs(fk.csr_json())
DRAM_WORDS = 1 << 20


def bridge(driver):
    return dma.Bridge(CSRS, opener=driver.open, ioctl=driver.ioctl, clock=driver.clock, sleep=driver.sleep,
                      read=driver.read, write=driver.write, close=driver.close)  # fmt: skip


def words(first, n):
    return b"".join(struct.pack("<Q", w) for w in range(first, first + n))


B = dma.BUFFER_WORDS
LENGTHS = [1, 2, B - 1, B, B + 1, 5 * B + 7, 32 * B, 32 * B + 1, 64 * B, 64 * B + 1, 150 * B + 3]


@pytest.mark.parametrize("irq_counts", ["next", "last"])
@pytest.mark.parametrize("nwords", LENGTHS)
def test_a_block_goes_to_the_dram_and_comes_back(nwords, irq_counts):
    driver = fk.FakeLitePCIe(irq_counts)
    data = words(0x1000, nwords)
    with bridge(driver) as b:
        b.to_dram(0x40, data)
        assert [driver.dram[0x40 + i] for i in (0, nwords - 1)] == [data[:8], data[-8:]]
        assert len(driver.dram) == nwords  # exactly the block: nothing before the base or past the end
        assert b.from_dram(0x40, nwords) == data
    assert driver.lost == 0


def test_a_read_starts_at_its_base():
    driver = fk.FakeLitePCIe()
    with bridge(driver) as b:
        b.to_dram(100, words(100, 3 * B))
        assert b.from_dram(100 + B + 5, 3) == words(100 + B + 5, 3)


def test_the_writer_is_enabled_before_the_bridge_sends():
    """While the DMA writer is off its FIFOs are in reset: a bridge started first would lose words in them."""
    driver = fk.FakeLitePCIe()
    with bridge(driver) as b:
        b.to_dram(0, words(7, 2 * B))
        b.from_dram(0, 2 * B)
    assert driver.lost == 0


def test_a_zero_length_transfer_moves_nothing():
    driver = fk.FakeLitePCIe()
    with bridge(driver) as b:
        b.to_dram(5, b"")
        assert b.from_dram(5, 0) == b""
    assert driver.dram == {} and not driver.reader_on and not driver.writer_on


def test_data_must_be_whole_words():
    with bridge(fk.FakeLitePCIe()) as b, pytest.raises(ValueError, match="whole number"):
        b.to_dram(0, b"\0" * 12)


def test_a_bridge_that_never_finishes_is_reported_with_its_count():
    driver = fk.FakeLitePCIe(stuck=True)
    with bridge(driver) as b, pytest.raises(dma.DMAError, match=r"not done after 10.0 s, 0 of 4 words moved"):
        b.to_dram(0, words(0, 4))
    assert not driver.reader_on  # the reader is switched off whatever happened


def test_both_directions_are_off_after_close():
    driver = fk.FakeLitePCIe()
    b = bridge(driver)
    b.lock()
    b.to_dram(0, words(0, B))
    b.close()
    assert driver.closed and not driver.reader_on and not driver.writer_on
    b.close()  # closing twice is harmless


def test_closing_a_device_that_was_only_looked_at_stops_nobodys_transfer():
    """The check opens every /dev/litepcie<n> to read its identifier. One that is another board's may have
    another process's DMA running, and the driver stops a direction for whoever asks."""
    driver = fk.FakeLitePCIe()
    driver.reader_on = driver.writer_on = True  # someone else's, on this device
    with bridge(driver) as b:
        check.read_identifier(b)
    assert driver.closed and driver.reader_on and driver.writer_on


def test_lock_refuses_a_channel_in_use_and_gives_back_what_it_took():
    driver = fk.FakeLitePCIe()
    driver.locks["writer"] = True  # another process has the writer
    with bridge(driver) as b, pytest.raises(dma.DMAError, match="another process"):
        b.lock()
    assert driver.locks == {"reader": False, "writer": True}  # the other process still has its writer


def test_dram_ready_reads_the_controller_select_bit():
    driver = fk.FakeLitePCIe()
    with bridge(driver) as b:
        assert b.dram_ready()
        driver.regs["sdram_dfii_control"] = 0xE  # the BIOS is driving the DRAM pins itself
        assert not b.dram_ready()


def test_padded_buffers_ends_on_an_interrupt():
    assert [dma.padded_buffers(n) for n in (1, B, B + 1, 32 * B, 32 * B + 1, 64 * B)] == [33, 33, 33, 33, 65, 65]
    for n in LENGTHS[:-1]:  # each from-DRAM chunk, with its padding, fits the half of the ring read() keeps
        assert dma.padded_buffers(min(n, dma.FROM_DRAM_CHUNK_BUFFERS * B)) <= dma.DMA_BUFFER_COUNT // 2 + 1


def test_a_missing_module_names_the_package():
    assert dma.module_missing(found=lambda: ["/dev/litepcie3"]) is None
    reason = dma.module_missing(found=list)
    assert "litepcie.ko is not loaded" in reason and dma.MODULE_PACKAGE in reason and "modprobe litepcie" in reason


def test_ioctl_numbers_are_litepcie_h():
    """_IOWR('S', 0, 12-byte reg), _IOW('S', 20, 1), _IOWR('S', 21/22, 24), _IOWR('S', 25, 6)."""
    assert (dma.IOCTL_REG, dma.IOCTL_DMA) == (0xC00C5300, 0x40015314)
    assert (dma.IOCTL_DMA_WRITER, dma.IOCTL_DMA_READER, dma.IOCTL_LOCK) == (0xC0185315, 0xC0185316, 0xC0065319)


def test_the_ring_constants_are_the_drivers():
    """dma.py's ring geometry against the litepcie the driver packages are built from (uv.lock)."""
    litepcie = pytest.importorskip("litepcie")
    config = (pathlib.Path(litepcie.__file__).parent / "software" / "kernel" / "config.h").read_text()

    def define(name):
        return int(next(line.split()[2] for line in config.splitlines() if line.startswith(f"#define {name} ")))

    ours = (dma.DMA_BUFFER_SIZE, dma.DMA_BUFFER_COUNT, dma.DMA_BUFFER_PER_IRQ)
    assert ours == tuple(define(name) for name in ("DMA_BUFFER_SIZE", "DMA_BUFFER_COUNT", "DMA_BUFFER_PER_IRQ"))


# -- the check's `dma` test (suite.py) ---------------------------------------------------------------------


def _dma(report):
    return next((t for t in report["tests"] if t["test"] == "dma"), None)


def _module_commands(rig):
    return [c for c in rig.pi.calls if c[0] in ("modprobe", "rmmod")]


def test_dma_is_the_last_of_the_acorns_tests():
    from fpgas_online_verify.boards.acorn import suite

    assert suite.TESTS[-1] == "dma" and "dma" in suite.NEEDS_BAR0


def test_the_check_loads_the_driver_for_the_dma_test_and_removes_it_again(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    report = rig.check()
    entry = _dma(report)
    assert report["result"] == "pass", report.get("reason")
    assert entry["result"] == "pass" and entry["driver"] == "loaded for the test" and entry["bytes"] == fk.DMA_BYTES
    assert "to_dram_MBps" in entry and "from_dram_MBps" in entry
    assert _module_commands(rig) == [["modprobe", "litepcie"], ["rmmod", "litepcie"], ["rmmod", "liteuart"]]
    assert rig.pi.modules == [] and rig.pi.litepcie.closed
    assert report["tests"][-1] is entry  # after every test that uses BAR0


def test_liteuart_loaded_by_udev_after_the_driver_is_removed_too(tmp_path, images):  # noqa: F811
    """Seen on pi-sw2-p48: liteuart.ko was not there yet when the driver had just been loaded, and stayed."""
    rig = Rig(tmp_path, images)
    rig.pi.liteuart_late = True
    report = rig.check(tests=["dma"])
    assert report["result"] == "pass" and rig.pi.modules == []
    assert _module_commands(rig) == [["modprobe", "litepcie"], ["rmmod", "litepcie"], ["rmmod", "liteuart"]]


def test_a_driver_that_was_already_loaded_is_used_and_left_loaded(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    rig.pi.modules = ["litepcie", "liteuart"]
    report = rig.check()
    assert _dma(report)["result"] == "pass" and _dma(report)["driver"] == "was loaded"
    assert _module_commands(rig) == [] and rig.pi.modules == ["litepcie", "liteuart"]


def test_a_host_without_the_module_is_told_which_package_has_it_and_the_board_still_passes(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    rig.pi.module_installed = False
    report = rig.check()
    assert report["result"] == "pass" and _dma(report) is None
    why = report["not_run"]["dma"]
    assert dma.MODULE_PACKAGE in why and "fpgas-online-acorn-litepcie-modules-<kernel>" in why and "not found" in why
    assert _module_commands(rig) == [["modprobe", "litepcie"]]  # nothing was loaded, so nothing is removed


def test_asking_for_the_dma_test_alone_without_the_module_is_a_fail(tmp_path, images):  # noqa: F811
    """A check that ran nothing has not shown the board works."""
    rig = Rig(tmp_path, images)
    rig.pi.module_installed = False
    report = rig.check(tests=["dma"])
    assert report["result"] == "fail" and "none of the tests asked for ran (dma)" in report["reason"]


def test_a_build_from_before_the_bridge_does_not_have_the_test_run(tmp_path, images):  # noqa: F811
    data = fk.csr_json()
    data["csr_registers"] = {n: r for n, r in data["csr_registers"].items() if not n.startswith("pcie_dram_")}
    fk.rewrite(images, "acorn-cle-215p-csr.json", json.dumps(data).encode())
    rig = Rig(tmp_path, images)
    report = rig.check()
    assert report["result"] == "pass" and _dma(report) is None
    assert "no DMA bridge" in report["not_run"]["dma"]
    assert _module_commands(rig) == []  # the driver is not even loaded


def test_the_golden_image_does_not_have_the_test_run(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images, identifier=fk.GOLDEN_IDENT_ON_CHIP, golden=True)
    report = rig.check()
    assert report["not_run"]["dma"] == "the golden image has no DRAM" and _module_commands(rig) == []


def test_a_word_that_reads_back_wrong_fails_the_board_and_the_driver_is_still_removed(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    rig.pi.litepcie.corrupt = fk.DRAM_BYTES // dma.WORD // 2 + 5  # in the timed block
    report = rig.check()
    entry = _dma(report)
    assert report["result"] == "fail" and entry["result"] == "fail"
    assert "read back wrong: word 5 is 0000000000000000" in entry["reason"]
    assert rig.pi.modules == []


def test_a_transfer_that_never_finishes_fails_with_what_was_moved(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    rig.pi.litepcie.stuck = True
    report = rig.check()
    assert _dma(report)["result"] == "fail" and "not done after" in _dma(report)["reason"]
    assert rig.pi.modules == [] and not rig.pi.litepcie.reader_on and not rig.pi.litepcie.writer_on


def test_a_driver_bound_to_another_design_is_not_used(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    rig.pi.litepcie.ident = "some other LitePCIe design"
    report = rig.check()
    assert _dma(report)["result"] == "fail"
    assert (
        "no device for the build BAR0 showed: /dev/litepcie0 runs 'some other LitePCIe design'"
        in _dma(report)["reason"]
    )
    assert rig.pi.litepcie.dram == {}  # nothing was written through it


def test_when_lsmod_fails_no_module_is_loaded_or_removed(tmp_path, images):  # noqa: F811
    """What was loaded before the test is how it knows what to remove after: without it, it loads nothing."""
    rig = Rig(tmp_path, images)
    rig.pi.lsmod_fails = True
    report = rig.check()
    assert "lsmod failed" in report["not_run"]["dma"] and _module_commands(rig) == []


def test_the_device_is_found_whatever_number_the_driver_gave_it(tmp_path, images):  # noqa: F811
    """pi-sw2-p48: the driver numbers its device again at every probe, so after the check has unbound and
    bound it for the BAR0 tests the board is /dev/litepcie1."""
    rig = Rig(tmp_path, images)
    rig.pi.modules = ["litepcie", "liteuart"]
    rig.pi.litepcie.node = "/dev/litepcie1"
    report = rig.check()
    assert _dma(report)["result"] == "pass" and _dma(report)["device"] == "/dev/litepcie1"


def test_of_two_litepcie_devices_the_one_running_the_boards_build_is_used(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    rig.pi.modules = ["litepcie", "liteuart"]
    rig.pi.litepcie.node = "/dev/litepcie2"
    other = fk.FakeLitePCIe(ident="another LitePCIe board", node="/dev/litepcie0")
    rig.pi.others = {"/dev/litepcie0": other}
    report = rig.check()
    assert _dma(report)["result"] == "pass" and _dma(report)["device"] == "/dev/litepcie2"
    assert other.dram == {} and other.closed  # read for its identifier, and nothing else


def test_a_module_that_loads_but_does_not_bind_is_reported(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    rig.pi.module_binds = False
    report = rig.check()
    assert "no /dev/litepcie<n> appeared" in report["not_run"]["dma"]
    assert rig.pi.modules == []  # what was loaded is removed all the same


def test_the_dma_test_alone_can_be_asked_for(tmp_path, images):  # noqa: F811
    rig = Rig(tmp_path, images)
    report = rig.check(tests=["dma"])
    assert [t["test"] for t in report["tests"]] == ["dma"] and report["result"] == "pass"
