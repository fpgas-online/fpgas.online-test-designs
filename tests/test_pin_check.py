"""The post-build check that ports landed on the pins they were constrained to (designs/_shared/pin_check.py)."""

from designs._shared.pin_check import misplaced, placed_pins, requested_pins

XDC = """
# pcie_x1:0.rx_p
set_property LOC B10 [get_ports {pcie_x1_rx_p}]
# pcie_x1:0.tx_p
set_property LOC B6 [get_ports {pcie_x1_tx_p}]
set_property LOC J1 [get_ports {pcie_x1_rst_n}]
set_property IOSTANDARD LVCMOS33 [get_ports {pcie_x1_rst_n}]
set_property LOC G22 [get_ports {ddram_dm[1]}]
"""

# Trimmed from the real report of the build that never linked: the IP's cell LOC put lane 0 on D9/D7.
IO_BAD = """
| Pin Number | Signal Name    | Bank Type  | Pin Name                     | Use           |
| B6         |                |            | MGTPTXP2_216                 | Gigabit       |
| B10        |                |            | MGTPRXP2_216                 | Gigabit       |
| D7         | pcie_x1_tx_p   |            | MGTPTXP3_216                 | OUTPUT        |
| D9         | pcie_x1_rx_p   |            | MGTPRXP3_216                 | INPUT         |
| J1         | pcie_x1_rst_n  | High Range | IO_L3P_T0_DQS_AD5P_35        | INPUT         |
| G22        | ddram_dm[1]    | High Range | IO_L24N_T3_16                | OUTPUT        |
"""
IO_GOOD = (
    IO_BAD.replace("| B6         |                |", "| B6         | pcie_x1_tx_p   |")
    .replace("| B10        |                |", "| B10        | pcie_x1_rx_p   |")
    .replace("| D7         | pcie_x1_tx_p   |", "| D7         |                |")
    .replace("| D9         | pcie_x1_rx_p   |", "| D9         |                |")
)


def test_it_reads_the_constraints():
    want = {"pcie_x1_rx_p": "B10", "pcie_x1_tx_p": "B6", "pcie_x1_rst_n": "J1", "ddram_dm[1]": "G22"}
    assert requested_pins(XDC) == want


def test_it_reads_the_placement():
    assert placed_pins(IO_BAD)["pcie_x1_rx_p"] == "D9"
    assert "" not in placed_pins(IO_BAD)


def test_the_build_that_never_linked_is_caught():
    assert misplaced(XDC, IO_BAD) == [("pcie_x1_rx_p", "B10", "D9"), ("pcie_x1_tx_p", "B6", "D7")]


def test_a_correct_placement_passes():
    assert misplaced(XDC, IO_GOOD) == []


def test_an_unbraced_port_is_read_too():
    assert requested_pins("set_property LOC A1 [get_ports clk]") == {"clk": "A1"}


def test_a_port_missing_from_the_report_is_reported():
    assert misplaced("set_property LOC A1 [get_ports {ghost}]", IO_GOOD) == [("ghost", "A1", None)]
