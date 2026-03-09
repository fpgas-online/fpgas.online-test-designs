# Resources

Curated links for the fpgas-online-test-designs project, organized by topic.

## LiteX Ecosystem

- **LiteX** -- SoC builder framework for creating FPGA-based systems on chip.
  <https://github.com/enjoy-digital/litex>
- **LiteX Boards** -- Board definition files and target scripts for many FPGA
  development boards.
  <https://github.com/litex-hub/litex-boards>
- **LiteDRAM** -- DRAM controller core (DDR, DDR2, DDR3, DDR4, LPDDR4, SDRAM).
  <https://github.com/enjoy-digital/litedram>
- **LiteEth** -- Ethernet core (MAC, PHY, UDP/IP stack).
  <https://github.com/enjoy-digital/liteeth>
- **LitePCIe** -- PCIe core (DMA, MSI, configuration).
  <https://github.com/enjoy-digital/litepcie>
- **LiteSPI** -- SPI and SPI Flash core (XIP support, various flash chips).
  <https://github.com/litex-hub/litespi>
- **LiteX Wiki** -- Documentation, tutorials, and build instructions.
  <https://github.com/enjoy-digital/litex/wiki>
- **Wishbone Utils** -- Host-side bridge tools (`litex_server`, `litex_cli`,
  `wishbone-tool`) for communicating with LiteX SoCs.
  <https://github.com/litex-hub/wishbone-utils>

## Board Vendor Repos

### Digilent Arty A7

- **Arty A7 Reference Manual** -- Pinout, schematic, and peripheral documentation.
  <https://digilent.com/reference/programmable-logic/arty-a7/reference-manual>

### NeTV2

- **NeTV2 FPGA** -- Gateware for the NeTV2 open video platform (Artix-7 based).
  <https://github.com/AlphamaxMedia/netv2-fpga>
- **NeTV2 MVP Scripts** -- OpenOCD configuration scripts for JTAG programming.
  <https://github.com/alphamaxmedia/netv2mvp-scripts>
- **NeTV2 Test HAT** -- Raspberry Pi HAT for NeTV2 testing infrastructure.
  <https://github.com/AlphamaxMedia/netv2-testhat>
- **NeTV2 on Crowd Supply** -- Product page with hardware specifications.
  <https://www.crowdsupply.com/alphamax/netv2>
- **bunnie's NeTV2 blog post** -- Design background and architecture overview.
  <https://www.bunniestudios.com/blog/?p=4842>

### Fomu

- **Fomu Hardware** -- PCB design files for the Fomu FPGA-in-a-USB-port (iCE40UP5K).
  <https://github.com/im-tomu/fomu-hardware>
- **Fomu Workshop** -- Interactive tutorial covering toolchain setup, Verilog, and
  RISC-V on Fomu.
  <https://workshop.fomu.im>

### TinyTapeout

- **TinyTapeout PCB** -- PCB design for the TinyTapeout demo board.
  <https://github.com/TinyTapeout/tt-demo-pcb>
- **TinyTapeout FPGA Demo** -- FPGA-based demo and test platform for TinyTapeout.
  <https://github.com/efabless/tt-fpga-demo>

### ULX3S

- **ULX3S** -- Open source ECP5 development board with SDRAM, HDMI, WiFi, and
  extensive I/O.
  <https://radiona.org/ulx3s/>

### ButterStick

- **ButterStick** -- ECP5 development board with PCIe edge connector and Gigabit
  Ethernet.
  <https://butterstick.io>

### Raspberry Pi FPGA Hats

- **RPi5 Artix-7 FPGA Hat** -- Raspberry Pi 5 HAT with an Artix-7 FPGA connected
  via the PCIe/FPC connector.
  <https://github.com/m1geo/Pi5-Artix-FPGA-Hat>

## Toolchains

- **openXC7** -- Fully open source toolchain for Xilinx 7-Series FPGAs.
  <https://github.com/openXC7>
- **openXC7 Toolchain Installer** -- Build script that installs the complete
  openXC7 toolchain to `/opt/openxc7`.
  <https://github.com/openXC7/toolchain-installer>
- **OpenXC7-LiteX Docker** -- Docker container with openXC7 and LiteX
  pre-installed.
  <https://github.com/tiiuae/OpenXC7-LiteX>
- **Yosys** -- Open source RTL synthesis framework supporting Verilog,
  SystemVerilog, and VHDL (via GHDL plugin).
  <https://github.com/YosysHQ/yosys>
- **nextpnr** -- Portable FPGA place-and-route tool with backends for iCE40,
  ECP5, Xilinx, Nexus, and others.
  <https://github.com/YosysHQ/nextpnr>
- **Project X-Ray** -- Reverse-engineered Xilinx 7-Series bitstream database.
  <https://github.com/chipsalliance/prjxray>
- **Project IceStorm** -- Reverse-engineered Lattice iCE40 bitstream database and
  tools (icepack, iceprog).
  <https://github.com/YosysHQ/icestorm>
- **Project Trellis** -- Reverse-engineered Lattice ECP5 bitstream database and
  tools (ecppack).
  <https://github.com/YosysHQ/prjtrellis>
- **openFPGALoader** -- Universal open source FPGA programming utility supporting
  Xilinx, Lattice, Intel, Gowin, and more.
  <https://github.com/trabucayre/openFPGALoader>

## PMOD

- **PMOD Specification** -- Digilent's standard for peripheral modules, defining
  6-pin and 12-pin connector pinouts and electrical characteristics.
  <https://digilent.com/reference/pmod/specification>
- **Digilent PMOD HAT** -- Raspberry Pi HAT adapter for connecting PMOD peripherals.
  <https://digilent.com/reference/add-ons/pmod-hat/reference-manual>

## Testing & CI

- **Pepijn de Vos HIL CI blog post** -- Architecture and implementation of
  hardware-in-the-loop continuous integration for FPGA tools.
  <http://pepijndevos.nl/2026/02/17/hardware-in-the-loop-continuous-integration-for-fpga-tools.html>
- **Baremetal CI Docker** -- Docker containers for managing self-hosted GitHub
  Actions runners with physical hardware access.
  <https://github.com/BareMetalTestLab/baremetal-ci-docker>
- **Ferrous Systems HIL Testing** -- Guide to hardware-in-the-loop testing with
  GitHub Actions self-hosted runners.
  <https://ferrous-systems.com/blog/gha-hil-tests/>

## Related Projects

- **timvideos LiteX Build Environment** -- Automated build system for LiteX-based
  FPGA SoCs, predecessor to current LiteX workflows.
  <https://github.com/timvideos/litex-buildenv>
- **Linux on LiteX-VexRiscv** -- Run Linux on LiteX SoCs using the VexRiscv
  RISC-V CPU, with support for many FPGA boards.
  <https://github.com/litex-hub/linux-on-litex-vexriscv>
- **LiteX M2SDR** -- M.2 SDR project using LiteX with PCIe on Raspberry Pi 5,
  serving as a reference for RPi5 PCIe FPGA integration.
  <https://github.com/enjoy-digital/litex_m2sdr>
