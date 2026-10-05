"""Tests for designs/acorn-pcie/host/pcie_match_mps.py.

The Pi 5 firmware boots Linux with `pci=pcie_bus_safe`. In that mode the kernel matches Max_Payload_Size
across a link only once, at boot (pcie_bus_configure_settings); a device found later by a sysfs rescan keeps
its reset value of 128 bytes while the root port stays at 512. The root port then sends completions and
writes larger than the endpoint accepts, and a 7-series PCIe core flags them as malformed (FatalErr): on
pi-sw2-p48 (2026-09-26) LitePCIe's DMA never completed a descriptor until the endpoint's MPS was matched.

The helper is tested against a fake sysfs tree: one root port with one endpoint below it, each with a
256-byte config space holding a PCI Express capability.
"""

import importlib.util
import pathlib
import struct

import pytest

_HOST = pathlib.Path(__file__).resolve().parents[1] / "designs" / "acorn-pcie" / "host"
_spec = importlib.util.spec_from_file_location("pcie_match_mps", _HOST / "pcie_match_mps.py")
mm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mm)

RP, EP = "0001:00:00.0", "0001:01:00.0"
EXP_CAP = 0x70  # where the PCI Express capability sits in the fake config spaces (behind a PM capability)

# DevCtl as p48 read them: root port 0x2c50 (MRRS 512, MPS 512), endpoint after a rescan 0x2810 (MPS 128).
RP_DEVCTL, EP_DEVCTL_RESCANNED = 0x2C50, 0x2810


def encode(size):
    return {128: 0, 256: 1, 512: 2, 1024: 3, 2048: 4, 4096: 5}[size]


def config_space(devctl, mpss):
    cfg = bytearray(256)
    struct.pack_into("<HH", cfg, 0, 0x10EE, 0x7021)
    cfg[0x06] = 0x10  # Status: capabilities list present
    cfg[0x34] = 0x40
    cfg[0x40:0x42] = bytes([0x01, EXP_CAP])  # PM capability, next -> PCIe
    cfg[EXP_CAP : EXP_CAP + 2] = bytes([0x10, 0x00])  # PCI Express capability, end of list
    struct.pack_into("<I", cfg, EXP_CAP + 4, encode(mpss))  # DevCap: MPSS in bits 2:0
    struct.pack_into("<H", cfg, EXP_CAP + 8, devctl)
    return cfg


@pytest.fixture
def sysfs(tmp_path):
    """A root port with an endpoint below it, as /sys lays them out on a Pi 5 (pcie1)."""
    rp_dir = tmp_path / "devices" / "platform" / "axi" / "1000110000.pcie" / "pci0001:00" / RP
    ep_dir = rp_dir / EP
    ep_dir.mkdir(parents=True)
    bus = tmp_path / "bus" / "pci" / "devices"
    bus.mkdir(parents=True)
    (bus / RP).symlink_to(rp_dir)
    (bus / EP).symlink_to(ep_dir)

    def make(rp_devctl=RP_DEVCTL, rp_mpss=512, ep_devctl=EP_DEVCTL_RESCANNED, ep_mpss=512):
        (rp_dir / "config").write_bytes(config_space(rp_devctl, rp_mpss))
        (ep_dir / "config").write_bytes(config_space(ep_devctl, ep_mpss))
        return tmp_path

    return make


def devctl(root, bdf):
    cfg = (root / "bus" / "pci" / "devices" / bdf / "config").read_bytes()
    return struct.unpack_from("<H", cfg, EXP_CAP + 8)[0]


def test_rescanned_endpoint_gets_the_root_ports_mps(sysfs):
    root = sysfs()
    assert mm.match_mps(EP, sysfs_root=root) == "0001:01:00.0: MPS 128 -> 512 (root port 0001:00:00.0: 512)"
    # Only the MPS field moves: MRRS 512, relaxed ordering and no-snoop stay as the kernel left them.
    assert devctl(root, EP) == 0x2850
    assert devctl(root, RP) == RP_DEVCTL


def test_root_port_is_lowered_when_the_endpoint_cannot_reach_its_mps(sysfs):
    root = sysfs(ep_mpss=256)
    assert mm.match_mps(EP, sysfs_root=root) == ("0001:01:00.0: MPS 128 -> 256 (root port 0001:00:00.0: 512 -> 256)")
    assert (devctl(root, EP) >> 5) & 7 == encode(256)
    assert devctl(root, RP) == (RP_DEVCTL & ~0xE0) | (encode(256) << 5)


def test_nothing_is_raised_above_what_the_root_port_runs(sysfs):
    # A root port someone set to 256 stays at 256; the endpoint follows it rather than its own 512.
    root = sysfs(rp_devctl=(RP_DEVCTL & ~0xE0) | (encode(256) << 5))
    mm.match_mps(EP, sysfs_root=root)
    assert (devctl(root, EP) >> 5) & 7 == encode(256)
    assert (devctl(root, RP) >> 5) & 7 == encode(256)


def test_matched_link_is_left_alone(sysfs):
    root = sysfs(ep_devctl=0x2850)
    before = (root / "bus" / "pci" / "devices" / EP / "config").stat().st_mtime_ns
    assert mm.match_mps(EP, sysfs_root=root) == "0001:01:00.0: MPS 512 matches root port 0001:00:00.0"
    assert (root / "bus" / "pci" / "devices" / EP / "config").stat().st_mtime_ns == before


def test_absent_endpoint_is_not_an_error(sysfs):
    # Most bitstreams loaded over JTAG (pin-id, UART tests) have no PCIe endpoint at all.
    root = sysfs()
    assert mm.match_mps("0001:02:00.0", sysfs_root=root) == "0001:02:00.0: not present, nothing to match"


def test_main_exit_status(sysfs, capsys):
    root = sysfs()
    assert mm.main([EP, "--sysfs-root", str(root)]) == 0
    assert "MPS 128 -> 512" in capsys.readouterr().out


def test_main_fails_without_a_pcie_capability(sysfs, capsys):
    root = sysfs()
    ep_cfg = root / "bus" / "pci" / "devices" / EP / "config"
    cfg = bytearray(ep_cfg.read_bytes())
    cfg[0x06] = 0  # no capabilities list
    ep_cfg.write_bytes(bytes(cfg))
    assert mm.main([EP, "--sysfs-root", str(root)]) == 1
    assert "no PCI Express capability" in capsys.readouterr().out
