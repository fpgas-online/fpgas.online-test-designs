# Plan: Make All Hardware Tests Pass Reliably

**Mission**: Every test passes first time, every time, automated, no interaction. Not done until 10 consecutive clean runs.

**Core principle**: Each phase is an iteration loop, not a checklist. New issues WILL surface. The cycle is: attempt → observe failure → diagnose → fix → rebuild → retest → repeat until green. Only move to the next phase when the current one is solid.

## Full Test Matrix

**Board hosts**: Arty A7 (pi3/5/9), NeTV2 (rpi5-netv2/rpi3-netv2), Fomu EVT (pi17/21), TT FPGA Demo Board (pi27/29/31/33). TT ASIC boards (pi19/23/25) are NOT in scope — they cannot run custom FPGA bitstreams.

**Standing principle**: The hardware works perfectly. All pins are correctly wired. Every test failure is a bug in our code or config.

| Test | Arty (×3) | NeTV2 (×2) | Fomu (×2) | TT (×4) | Total |
|------|-----------|------------|-----------|---------|-------|
| UART | 3 | 2 | 2 | 4 | **11** |
| PMOD | 3 | 2 | 2 | 4 | **11** |
| SPI Flash | 3 | 2 | 2 | 4 | **11** |
| Ethernet | 3 | 2 | — | — | **5** |
| DDR3 | 3 | 2 | — | — | **5** |
| PCIe | — | 2 | — | — | **2** |
| **Total** | **12** | **10** | **6** | **12** | **45** |

Every test must pass. If the current toolchain can't synthesize something, the work is to make it work — either by fixing the open-source toolchain support, adding Vivado CI builds, or finding an alternative approach. Nothing is out of scope.

---

## Iteration Protocol (applies to every phase)

Every phase follows this loop until its tests pass reliably:

```
1. IMPLEMENT the planned fix
2. BUILD locally (catch compile/synthesis errors before CI)
3. PUSH to CI and verify all workflows stay green
4. DEPLOY to hardware (upload bitstream + test script to RPi)
5. RUN test on ONE board first
6. If FAIL:
   a. Read full error output — don't skip details
   b. Diagnose root cause (wrong CSR? wrong pin? wrong baud? timing?)
   c. Fix the code
   d. Go to step 2
7. If PASS on one board:
   a. Run on ALL boards for this test type
   b. If any board fails, diagnose (board-specific issue? flaky USB? wrong variant?)
   c. Fix and retest ALL boards
8. Run 3× consecutive on all boards to confirm reliability
9. COMMIT with clear message, move to next phase
```

**When new issues surface mid-phase:**
- If the issue is within this phase's scope: fix it immediately (stay in the loop)
- If the issue affects a previous phase: go back and fix that phase first, re-verify, then resume
- If the issue is a new problem not in any phase: add it to the current phase or create a new sub-phase, fix it before moving on
- NEVER skip an issue. NEVER say "we'll fix it later."

---

## Phase 1: SPI Flash firmware for iCE40 (Fomu + TT)

**Problem**: `install_uart_firmware()` placeholder — no actual SPI Flash test firmware exists.

**Files to modify:**
- `designs/_shared/ice40_firmware.py` — add `generate_spiflash_firmware(uart_base, spiflash_base, ident)` using RV32I assembly (same pattern as UART firmware). Reads JEDEC ID via S7SPIFlash bitbang CSRs, prints `JEDEC_ID:` and `SPI_FLASH_TEST: PASS/FAIL`.
- `designs/spi-flash-id/gateware/spiflash_soc_fomu.py` — replace `self.add_spi_flash()` (LiteSPI) with `add_spi_flash()` from `common.py` (S7SPIFlash bitbang). Replace `install_uart_firmware` → `install_spiflash_firmware`.
- `designs/spi-flash-id/gateware/spiflash_soc_tt.py` — same changes.

**Likely issues to encounter during iteration:**
- S7SPIFlash may use tristate primitives that don't map to iCE40 — if so, write a minimal `Ice40SPIFlashBitbang` (~50 lines Migen)
- SPI bitbang CSR register layout may differ from what the RV32I firmware expects — verify offsets from generated `csr.h`
- SPI clock polarity/phase may need adjustment for AT25SF161 — check datasheet for mode 0/3
- Fomu hardware UART on `/dev/ttyAMA0` — if no output, debug pin mapping, baud rate, serial-getty conflict, GPIO overlay config (pins ARE wired, the bug is in the code)
- iCE40 EBR may be too small for combined UART+SPI firmware — check word count, optimize if >256 words (1KB)

**Verification gate**: `test_spiflash.py` shows JEDEC ID and PASS on at least one board. Then all applicable boards. Then 3× consecutive.

---

## Phase 2: SPI Flash CI build fix (Arty + NeTV2)

**Problem**: `SPIFLASH_PHY_FREQUENCY undeclared` — liblitespi compiled but SoC uses S7SPIFlash.

**Files to modify:**
- `designs/spi-flash-id/gateware/common.py` — add `soc.add_constant("SPIFLASH_PHY_FREQUENCY", int(sys_clk_freq) // 4)` to satisfy liblitespi compile.
- `verify_hardware.py` — use `--bios` mode for Arty/NeTV2 SPI Flash tests (BIOS prints flash info).

**Likely issues to encounter:**
- Adding the constant may fix compile but BIOS may not actually detect the S7SPIFlash — need to check BIOS boot output for flash init messages
- If BIOS doesn't detect flash: may need to add custom C firmware (`main.c`) that reads JEDEC ID via bitbang CSRs, or fix the BIOS detection path
- The `test_spiflash.py --bios` mode parsing may not match actual BIOS output format — compare actual output against expected patterns
- Other liblitespi constants may also be missing — fix each as they appear
- openXC7 timing may fail at 100MHz on Arty (seen before with UART) — may need to reduce sys_clk_freq

**Verification gate**: CI build green, `test_spiflash.py --bios` PASS on pi3 + rpi5-netv2, then all Arty/NeTV2 boards, then 3× consecutive.

---

## Phase 3: TT FPGA UART (fix RP2040 serial bridge)

**Problem**: RP2040 GPIOMap mismatch — UART bridge doesn't work after custom bitstream load.

**Boards**: TT FPGA Demo Boards only (pi27/29/31/33). TT ASIC boards (pi19/23/25) are NOT in scope.

**Steps:**
- Probe all 4 TT FPGA boards (pi27/29/31/33) to determine firmware version and GPIO config
- `designs/_shared/tt_fpga_program.py` — add UART bridge activation after FPGA programming

**Likely issues to encounter:**
- Different TT FPGA Demo Boards may have different RP2040 firmware versions with incompatible GPIO maps — may need per-board detection and configuration
- The RP2040 may not support UART bridging for custom bitstreams at all — may need to upload a MicroPython UART bridge script to the RP2040 after FPGA programming
- `mpremote` commands may fail or timeout over SSH — need robust error handling and retries
- After FPGA programming, the RP2040 may need a reset to enter bridge mode — discover the correct sequence
- The serial port `/dev/ttyACM0` may disappear during FPGA programming and reappear with a different name — need to wait for re-enumeration
- The custom firmware (from Phase 1) may output before the UART bridge is active — need to either delay firmware start or capture from the beginning

**Verification gate**: `test_uart.py --port /dev/ttyACM0 --board tt` PASS on all 4 TT hosts, then 3× consecutive.

---

## Phase 4: Ethernet without DDR3 (custom SoC)

**Problem**: Upstream `BaseSoC` hardcodes DDR3. LiteEth is pure synthesizable logic — can work with SRAM.

**Files to modify/create:**
- `designs/ethernet-test/gateware/ethernet_soc_arty.py` — rewrite as custom `SoCCore` subclass with LiteEth + 64KB SRAM, no DDR3
- `designs/ethernet-test/gateware/ethernet_soc_netv2.py` — same approach

**Likely issues to encounter:**
- LiteEth + BIOS networking stack may not fit in 64KB SRAM — if so, increase to 128KB or strip BIOS features with `bios_console="lite"`
- LiteEth MII PHY initialization may differ between Arty (MII, external PHY) and NeTV2 (RMII, on-board PHY) — need separate PHY configurations
- The Ethernet PHY may need a specific reference clock that the custom CRG doesn't provide — check Arty's 25MHz ETH_CLK and NeTV2's RMII clock requirements
- openXC7 may fail timing on the Ethernet clock domain (25MHz MII or 50MHz RMII) — check Fmax
- ARP responses from the FPGA may be too slow with SRAM-only (no burst capability) — verify with `test_ethernet.py` timeout settings
- The USB Ethernet adapter on each RPi may need driver loading or IP configuration — automate this in the test script
- DHCP vs static IP configuration may conflict — ensure test uses deterministic static IPs
- If the custom SoC builds but Ethernet doesn't respond: use UART to check BIOS boot output for LiteEth initialization messages

**Verification gate**: `test_ethernet.py` shows ARP + ping PASS on pi3 + rpi5-netv2, then all boards, then 3× consecutive.

---

## Phase 5: Fomu hardware UART (debug serial path)

**Problem**: Fomu hardware UART (`uart_name="serial"`, TX=pin13, RX=pin21) is correctly wired to RPi GPIO UART at `/dev/ttyAMA0` on pi17/pi21, but no output was received during earlier testing. The hardware is correct — the bug is in the code or RPi config.

**Debug approach (iterate until output appears):**
1. Check RPi UART config: Is GPIO UART enabled? Is `serial-getty@ttyAMA0` competing? Is the correct dtoverlay loaded?
2. Verify Fomu pin mapping: Check `fomu_evt.py` platform file — do pin13/pin21 match the actual physical wiring?
3. Check baud rate: Firmware generates 115200 at 12MHz sys_clk — verify divider math
4. Check firmware execution: Is VexRiscv actually running? Is the firmware writing to the UART CSR?
5. Probe from both ends: Send data FROM RPi to Fomu (check RX), check if Fomu TX line toggles

**Files to investigate/modify:**
- `designs/uart/gateware/uart_soc_fomu.py` — verify `uart_name="serial"` pin mapping matches physical wiring
- Fomu platform file (`fomu_evt.py` in litex-boards) — verify pin13/pin21 serial resource definition
- RPi pi17/pi21 config — check `/boot/config.txt` or PXE-served dtoverlay for UART enable, disable serial-getty

**Likely issues to encounter:**
- `serial-getty@ttyAMA0` on RPi may be holding the port open and consuming/corrupting data — stop or mask it
- RPi may need `enable_uart=1` in config.txt and/or `dtoverlay=miniuart-bt` to free up `/dev/ttyAMA0` for GPIO
- Pin numbering mismatch: Fomu "pin13"/"pin21" in the platform file may not map to the physical pads connected to the RPi — trace the actual netlist
- Baud rate mismatch: iCE40 at 12MHz with integer divider may not hit 115200 exactly — check if actual baud is close enough (within 3%)
- TX/RX swap: FPGA TX must connect to RPi RX (GPIO15) and vice versa — verify polarity
- Level shifting: Fomu runs at 1.8V, RPi GPIO is 3.3V — check if level shifters are present and working
- The firmware may crash before reaching the UART print loop — add a simple GPIO toggle or LED blink as a "firmware alive" indicator

**Verification gate**: `test_uart.py --port /dev/ttyAMA0 --board fomu` PASS on pi17 and pi21, then 3× consecutive.

---

## Phase 6: PMOD coverage expansion

**Problems**: Missing board configs, GPIO conflicts, unknown wiring.

**Files to modify:**
- `designs/pmod-loopback/host/test_pmod_loopback.py` — add `"tt"` board config, fix NeTV2 rpi3 config

**Likely issues to encounter:**
- TT FPGA PMOD pin mapping unknown — need to trace from iCE40 pins through RP2040 to RPi GPIO (may require reading RP2040 firmware source or probing with GPIO tools). All pins are wired — debug the mapping, don't assume it's missing.
- Fomu PMOD pin mapping — need to determine which Fomu EVT pads connect to RPi GPIO on pi17/pi21. The hardware IS wired; debug the exact pin mapping.
- rpi3-netv2 GPIO14/15 conflict — `serial-getty` or UART overlay may claim these pins. Fix: either use `dtoverlay=disable-bt` in PXE config on tweed, or modify NeTV2 loopback gateware to use different pins
- gpiod v1 vs v2 API differences across RPi models — the test script handles both but may hit edge cases on specific board/OS combinations
- GPIO chip label detection (`pinctrl-rp1` vs `pinctrl-bcm2711` vs `pinctrl-bcm2835`) may fail on some RPi firmware versions — add fallback detection

**Verification gate**: PMOD PASS on ALL boards (Arty ×3, NeTV2 ×2, Fomu ×2, TT FPGA ×4), then 3× consecutive.

---

## Phase 7: Open-source toolchain test matrix validation (10× clean runs)

**Goal**: Prove that ALL tests buildable with open-source tools pass reliably on all hardware before moving to Vivado-dependent tests. This covers: openXC7 (Arty/NeTV2 Xilinx 7-series), icestorm/nextpnr-ice40 (Fomu/TT iCE40).

**Open-source test matrix** (38 tests):

| Test | Arty (×3) | NeTV2 (×2) | Fomu (×2) | TT FPGA (×4) | Total |
|------|-----------|------------|-----------|---------------|-------|
| UART | 3 | 2 | 2 | 4 | **11** |
| PMOD | 3 | 2 | 2 | 4 | **11** |
| SPI Flash | 3 | 2 | 2 | 4 | **11** |
| Ethernet | 3 | 2 | — | — | **5** |
| **Total** | **12** | **8** | **6** | **12** | **38** |

**Process:**
- Build `verify_hardware.py` with `--repeat N` and `--download-artifacts`
- Run full openXC7 test matrix on all boards
- First run WILL surface intermittent failures — fix each one
- Re-run from scratch after every fix (partial runs don't count)
- Common intermittent issues:
  - USB device enumeration timing (DFU, RP2040) — fix with deterministic device polling
  - SSH connection drops — add retry with backoff
  - Serial port contention — exclusive open or kill competing processes
  - PoE-booted RPis rebooting during test — investigate and prevent
  - OpenOCD JTAG failures on consecutive programs — FPGA reset between programs

**Verification gate**: `uv run python verify_hardware.py --repeat 10 --download-artifacts` — all 38 open-source tests pass, 10 consecutive runs, zero failures, zero manual intervention. Not done until this passes. If run 9 of 10 fails, fix and start over from run 1.

**STOP HERE after Phase 7 passes.** Report results to user and wait for approval before proceeding to Vivado phases.

---

## Phase 8: Vivado local build setup

**Problem**: DDR3 and PCIe require Xilinx hard IP (ISERDES2/OSERDES2/IDELAYCTRL, GT transceivers) that openXC7 cannot synthesize. Vivado is proprietary and CANNOT be added to CI. Must set up local Vivado builds.

**Steps:**
1. Verify Vivado is installed locally (or install WebPack edition — free for 7-series)
2. Add `--toolchain vivado` support to the build scripts so designs can be built locally
3. Build DDR3 and PCIe bitstreams locally with Vivado
4. Create a workflow for manually-built bitstreams: local Vivado build → upload to test rigs → run tests

**Files to investigate/modify:**
- `designs/_shared/build_helpers.py` — verify Vivado toolchain support exists (may already work via LiteX `--toolchain`)
- `designs/ddr-test/gateware/ddr_soc_arty.py` — build with Vivado
- `designs/ddr-test/gateware/ddr_soc_netv2.py` — build with Vivado
- `designs/pcie-enumeration/gateware/pcie_soc_netv2.py` — build with Vivado (remove `if is_vivado:` guard or ensure it activates)

**Likely issues to encounter:**
- Vivado WebPack may need specific version for 7-series support — check compatibility
- LiteX Vivado toolchain may need additional Python packages (e.g., `vivado` in PATH)
- Build scripts may have openXC7-specific workarounds that break Vivado — conditionally apply them
- Vivado builds are slow (30-60 min per design) — need patience, not parallelism hacks
- Generated constraints may conflict with Vivado's timing engine — may need XDC adjustments

**Verification gate**: Successfully build DDR3 Arty, DDR3 NeTV2, PCIe NeTV2 bitstreams with Vivado. Bitstreams are valid (non-zero size, correct format).

---

## Phase 9: DDR3 (Arty + NeTV2)

**Problem**: DDR3 memtest failed on previous attempts — timing failures and read-leveling zeros with openXC7 bitstreams.

**Approach**: Use Vivado-built bitstreams from Phase 8. The hardware is correct — debug until memtest passes.

**Files to investigate/modify:**
- `designs/ddr-test/gateware/ddr_soc_arty.py` — DDR3 SoC for Arty
- `designs/ddr-test/gateware/ddr_soc_netv2.py` — DDR3 SoC for NeTV2
- `designs/ddr-test/host/test_ddr.py` — DDR3 test script

**Likely issues to encounter:**
- DDR3 timing is sensitive — even with Vivado, may need clock constraint tuning
- Read leveling calibration may fail on specific boards — debug with BIOS `mem_test` command
- A7DDRPHY has different configurations for Arty (DDR3) vs NeTV2 (DDR3L) — verify voltage and timing parameters
- BIOS may boot but memtest fails — check training sequence output for clues
- Different SDRAM modules on different boards may need different timing — check BIOS autodetection

**Verification gate**: DDR3 memtest PASS on all 5 boards (pi3/5/9 + rpi5-netv2/rpi3-netv2), then 3× consecutive.

---

## Phase 10: PCIe enumeration (NeTV2)

**Problem**: PCIe endpoint logic only built with Vivado (`if is_vivado:` guard). Uses GT transceivers (hard IP).

**Approach**: Use Vivado-built bitstreams from Phase 8.

**Files to investigate/modify:**
- `designs/pcie-enumeration/gateware/pcie_soc_netv2.py` — PCIe SoC
- `designs/pcie-enumeration/host/test_pcie_enumeration.py` — PCIe test script
- RPi5 PCIe configuration — unbind/rebind external PCIe controller after FPGA programming

**Likely issues to encounter:**
- RPi5 external PCIe controller (`1000110000.pcie`) needs unbind/rebind to retrain link after FPGA programming — automate this
- PCIe link training may fail intermittently — need proper FPGA reset + link retrain sequence
- rpi3-netv2 may not have PCIe connectivity to NeTV2 — debug the physical connection, don't assume it's missing
- Vivado synthesis for PCIe is complex (GT transceiver placement, clock routing) — may need specific constraints
- The NeTV2 PCIe connector may need specific initialization sequence before link comes up

**Verification gate**: PCIe device `10ee:7011` visible in lspci, config space readable, link Gen2 x1, on both NeTV2 boards, then 3× consecutive.

---

## Phase 11: Full test matrix validation (10× clean runs)

**Files to modify:**
**Goal**: Same as Phase 7, but now including DDR3 and PCIe (Vivado-built bitstreams).

**Full test matrix** (45 tests):

| Test | Arty (×3) | NeTV2 (×2) | Fomu (×2) | TT FPGA (×4) | Total |
|------|-----------|------------|-----------|---------------|-------|
| UART | 3 | 2 | 2 | 4 | **11** |
| PMOD | 3 | 2 | 2 | 4 | **11** |
| SPI Flash | 3 | 2 | 2 | 4 | **11** |
| Ethernet | 3 | 2 | — | — | **5** |
| DDR3 | 3 | 2 | — | — | **5** |
| PCIe | — | 2 | — | — | **2** |
| **Total** | **12** | **10** | **6** | **12** | **45** |

**Verification gate**:
```
uv run python verify_hardware.py --repeat 10
```
- All 45 tests pass
- 10 consecutive complete runs
- Zero failures, zero retries, zero manual intervention
- Clean, deterministic execution — same result every time

**Not done until this passes. If run 9 of 10 fails, fix the issue and start over from run 1.**
