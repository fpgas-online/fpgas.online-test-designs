"""The fpgas_online_verify package (verify/src) is importable from the tests without installing it."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "verify" / "src"))


@pytest.fixture(autouse=True)
def _no_device_tree(monkeypatch, tmp_path):
    """The machine running the tests is not the Pi under test: which HAT it has (boards/tt_fpga.pi_hat) is not
    known unless a test says, so the tests give the same results on a desktop and on a Pi."""
    from fpgas_online_verify.boards import tt_fpga

    monkeypatch.setattr(tt_fpga, "DEVICE_TREE", tmp_path / "no-device-tree")
