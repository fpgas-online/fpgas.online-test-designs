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


def test_poe_snmp_cmd_builds_admin_enable_write():
    off = vh.poe_snmp_cmd("welland-sw2-p29", enable=False, community="secret")
    assert off == [
        "snmpset", "-v2c", "-c", "secret", "10.1.5.11",
        "1.3.6.1.2.1.105.1.1.1.3.1.29", "i", "2",
    ]
    on = vh.poe_snmp_cmd("welland-sw2-p29", enable=True, community="secret")
    assert on[-1] == "1"


def test_poe_snmp_cmd_rejects_host_without_poe_info():
    import pytest
    with pytest.raises(KeyError):
        vh.poe_snmp_cmd("welland-pi3", enable=False, community="secret")


def _pin_id_test_for(host):
    tests = [t for t in vh.generate_tests() if t["host"] == host and t["test_type"] == "pin-id"]
    assert len(tests) == 1
    return tests[0]


def test_acorn_pin_id_test_uses_absolute_paths_in_login_home():
    t = _pin_id_test_for("welland-sw2-p46")
    assert t["remote_bitstream"] == "/home/pi/pin-id_acorn.bit"
    assert t["remote_script"] == "/home/pi/test_pin-id.py"
    assert t["test_cmd"] == "python3 /home/pi/test_pin-id.py --board acorn"


def test_acorn_program_cmd_detaches_pcie_and_uses_libgpiod():
    t = _pin_id_test_for("welland-sw2-p46")
    cmd = t["program_cmd"]
    assert cmd.index("0001:01:00.0/remove") < cmd.index("openFPGALoader")
    assert "ln -sfn /dev/gpiochip15 /dev/gpiochip0" in cmd
    assert "--cable libgpiod --pins 10:9:11:8 /home/pi/pin-id_acorn.bit" in cmd
    assert cmd.rstrip().endswith("/sys/bus/pci/rescan")
    assert "rp1pio" not in cmd


def test_acorn_pin_id_artifact_matches_ci_upload_name():
    # pmod_pin_id_acorn.py calls platform.build() directly, so LiteX names the
    # output build/acorn/top.bit, and the CI job uploads build/acorn/*.bit.
    t = _pin_id_test_for("welland-sw2-p46")
    assert t["artifact"] == "pmod-pin-id-acorn-cle-215plus/top.bit"


def test_cli_repeat_and_dry_run_flags_exist():
    import argparse
    parser = vh.build_arg_parser()
    assert isinstance(parser, argparse.ArgumentParser)
    args = parser.parse_args(["--repeat", "3", "--dry-run", "--host", "welland-sw2-p46"])
    assert args.repeat == 3 and args.dry_run is True


def test_direct_host_is_never_sudo_wrapped():
    # rpi3-netv2 logs in as pi and puts its own `sudo` in HOST_PROGRAM_CMD;
    # an outer `sudo -n sh -c` would make its `~/netv2/...` config path resolve
    # to /root.
    cmd = vh._build_ssh_cmd("rpi3-netv2", "sudo openocd -f ~/netv2/x.cfg", as_root=True)
    assert cmd[-1] == "sudo openocd -f ~/netv2/x.cfg"


def test_poe_reset_failure_message_never_contains_community(monkeypatch, capsys):
    import subprocess

    monkeypatch.setenv(vh.POE_COMMUNITY_ENV, "s3cret-community")

    def fake_run(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs.get("timeout", 0))

    monkeypatch.setattr(vh.subprocess, "run", fake_run)
    assert vh.poe_reset("welland-sw2-p29") is False
    out = capsys.readouterr().out
    assert "s3cret-community" not in out
    assert "PoE reset failed" in out
