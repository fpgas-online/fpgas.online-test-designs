"""Pure-function tests for verify_hardware.py (no network)."""

import importlib.util
import pathlib

_MOD_PATH = pathlib.Path(__file__).resolve().parents[1] / "verify_hardware.py"
_spec = importlib.util.spec_from_file_location("verify_hardware", _MOD_PATH)
vh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vh)


def test_gateway_host_uses_proxyjump_and_login_user():
    cmd = vh._build_ssh_cmd("welland-sw2-p29", "echo ok", as_root=False)
    assert cmd == [
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
        "-o", "ProxyJump=tim@10.21.0.1",
        "pi@10.21.2.29", "echo ok",
    ]


def test_gateway_host_wraps_root_commands_in_sudo():
    cmd = vh._build_ssh_cmd("welland-sw2-p29", "rmmod spidev; echo done", as_root=True)
    assert cmd[-2] == "pi@10.21.2.29"
    assert cmd[-1] == "sudo -n sh -c 'rmmod spidev; echo done'"


def test_root_login_host_is_not_wrapped():
    cmd = vh._build_ssh_cmd("welland-pi3", "echo ok", as_root=True)
    assert cmd[-2] == "root@10.21.0.103"
    assert cmd[-1] == "echo ok"


def test_direct_host_has_no_proxyjump():
    cmd = vh._build_ssh_cmd("rpi5-netv2", "echo ok", as_root=False)
    assert "-o" in cmd and not any(a.startswith("ProxyJump=") for a in cmd)
    assert cmd[-2:] == ["tim@rpi5-netv2.iot.welland.mithis.com", "echo ok"]


def test_remote_home_follows_login_user():
    assert vh.remote_home("welland-sw2-p29") == "/home/pi"
    assert vh.remote_home("welland-pi3") == "/root"
    assert vh.remote_home("rpi5-netv2") == "/home/tim"
