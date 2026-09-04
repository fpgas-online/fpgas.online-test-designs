\[[top](./README.md)\] \[[spec](./acorn.md)\] \[[pinmap](./acorn-pinmap.md)\] \[[wiring](./acorn-pinmap.md)\]

# Acorn PCIe Programming & Multiboot

How to program the Acorn CLE-215+ / LiteFury FPGA via PCIe, and how to use Xilinx 7-series multiboot for safe recovery from bad bitstreams.

## Programming Paths

The Acorn has two working programming paths:

| Method | Speed | Persistent? | Requires | Notes |
|--------|-------|-------------|----------|-------|
| GPIO JTAG → SRAM | ~16 s for a 1.6 MB XC7A200T bitstream (bit-banged libgpiod, measured 2026-08-31) | No (lost on power cycle) | RPi GPIO wiring | Works with any/no bitstream loaded. **Detach the PCIe endpoint first** (below) |
| PCIe → SPI Flash | Fast (~seconds) | Yes | Working LiteX PCIe bitstream | Requires PCIe-capable bitstream already running |

### Detach the PCIe endpoint before any JTAG reconfiguration

Reconfiguring the FPGA over JTAG while its endpoint is enumerated is a PCIe
surprise removal. The Pi 5's BCM2712 root complex does not survive it: on
2026-08-31 a JTAG load on pi-sw2-p47 killed the host outright ("Connection
closed by remote host", Pi rebooted). With the endpoint removed first, the same
load completed cleanly and the host was unaffected.

```bash
echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # before openFPGALoader
# ... load ...
echo 1 | sudo tee /sys/bus/pci/rescan                         # afterwards, or just reboot
```

Every `openFPGALoader … <bitstream>` invocation on this page assumes that
detach has been done. Read-only operations (`--detect`, and `--read-dna` /
`--read-xadc` on openFPGALoader ≥ 0.13) do not reconfigure the device and are
safe on a live endpoint.

### Prebuilt Vivado bitstreams

There is no need to build locally. GitHub release
[`vivado-bitstreams-v0.0-496-gf162f60`](https://github.com/fpgas-online/fpgas.online-test-designs/releases/tag/vivado-bitstreams-v0.0-496-gf162f60)
(Vivado 2025.2, published 2026-04-17) carries every test design × Acorn variant
(`cle-101`, `cle-215`, `cle-215p`), each as plain `.bit`/`.bin` plus the
`_fallback` and `_operational` multiboot variants described below, and a
`manifest.json` with a SHA-256 per file. For the Welland CLE-215+ boards use the
`*_acorn-cle-215p_*` files; their `.bit` header reads `7a200tfbg484`, matching
IDCODE `0x3636093`.

```bash
gh release download vivado-bitstreams-v0.0-496-gf162f60 \
    --repo fpgas-online/fpgas.online-test-designs \
    --pattern 'pmod-pin-id_acorn-cle-215p_vivado-vivado_sqrl_acorn.bit'
```

Note that the `pmod-pin-id` design in that release predates test-designs PR #10
(2026-08-31), which gave the Acorn pin-ID design a real clock; the release
build of *that one design* configures but never toggles a pin. The fixed
design must be rebuilt with Vivado until a newer release is cut.

**Flash-via-JTAG (`--write-flash`) is not currently working** with openFPGALoader on the Acorn. JTAG can only load bitstreams to volatile SRAM. This has important implications for the recovery strategy.

### Current Bitstream State

Five of the six Welland Acorn boards still have the **factory Sqrl
cryptocurrency mining firmware** in SPI flash (`lspci -nn` on each host,
2026-09-03):

| Host       | Flash contents (what enumerates at boot)                                   |
|------------|----------------------------------------------------------------------------|
| pi-sw2-p29 | Sqrl factory firmware `1e24:021f`                                          |
| pi-sw2-p43 | Sqrl factory firmware `1e24:021f`                                          |
| pi-sw2-p44 | `10ee:7011` — Xilinx 7-Series Hard PCIe block (a LiteX/Vivado design)      |
| pi-sw2-p46 | Sqrl factory firmware `1e24:021f`                                          |
| pi-sw2-p47 | Sqrl factory firmware `1e24:021f`                                          |
| pi-sw2-p48 | Sqrl factory firmware `1e24:021f`                                          |

Factory firmware characteristics:

- PCI vendor:device `1e24:021f` (Squirrels Research Labs)
- BAR0: 128 KB — repeating mining parameter pattern, no LiteX CSRs
- **Not a LiteX design** — `litepcie_util` cannot communicate with this firmware

To enable PCIe→Flash programming, the factory firmware must be replaced with a **LiteX Acorn PCIe SoC** bitstream (vendor `10ee`) that includes PCIe+DMA, SPI Flash controller, and ICAP. Building this bitstream requires **Vivado** (the XC7A200T is too large for the openXC7 open source toolchain); the prebuilt release above already contains `pcie-enumeration_acorn-cle-215p_*_{fallback,operational}.bin`.

The litepcie kernel module and `litepcie_util` were built on the host then
called pi2 (now pi-sw2-p48) — they just need a matching LiteX bitstream to bind
to. Because the Pi root is `overlayroot=tmpfs`, anything built on a Pi is lost
at reboot unless it is baked into the NFS root.

The longer-term intent (Tim, 2026-08-31) is to flash every board with a LiteX
design carrying PCIe + UART + GPIO that supports FPGA updates over PCIe, and to
add JTAG/PCIe/UART/GPIO self-verification to the Pi boot checks.

### What This Means

- JTAG can always load a bitstream into SRAM (volatile), but it is lost on power cycle
- The only way to write to SPI flash (persistent) is via PCIe using `litepcie_util`
- PCIe→Flash requires a LiteX bitstream (not the factory Sqrl firmware)
- The golden bitstream at flash address 0x0 is **irreplaceable without PCIe** — if it is corrupted, recovery requires the SRAM bootstrap procedure (see below)

## SPI Flash Layout

The Acorn has a Spansion S25FL256S (256 Mbit = 32 MB) quad-SPI NOR flash.

```
┌──────────────────────────────────────────────────┐
│ 0x00000000  Fallback bitstream (golden image)    │  ~4 MB
│             - Always boots first                 │
│             - Sets NEXT_CONFIG_ADDR = 0x400000   │
│             - Has PCIe + LiteX + SPI Flash       │
│             - PROTECTED — see safety rules        │
├──────────────────────────────────────────────────┤
│ 0x00400000  Operational bitstream (updatable)    │  ~4 MB
│             - Chain-loaded by fallback           │
│             - Has TIMER_CFG watchdog             │
│             - Updated via PCIe (litepcie_util)   │
│             - If broken, watchdog → fallback     │
├──────────────────────────────────────────────────┤
│ 0x00800000  Free space                           │  ~24 MB
│             (available for data/additional images)│
└──────────────────────────────────────────────────┘
```

## Multiboot Mechanism

### How It Works

1. **Power-on**: FPGA loads fallback bitstream from flash address 0x0
2. **Chain-load**: Fallback's `NEXT_CONFIG_ADDR` (0x400000) tells the FPGA to immediately load the operational bitstream
3. **Operational runs**: The operational bitstream runs the user's design with PCIe, UART, etc.
4. **If operational fails**: The `TIMER_CFG` watchdog detects configuration failure and triggers an automatic fallback to address 0x0
5. **Fallback recovers**: The golden image boots, PCIe comes up, and the host can reprogram the operational slot

### Watchdog Timer

The operational bitstream must include `CONFIGFALLBACK` and `TIMER_CFG` properties:

- `TIMER_CFG 0x0001fbd0` — watchdog timeout that triggers fallback if configuration stalls
- `CONFIGFALLBACK Enable` — enables the fallback mechanism

If the operational bitstream hangs during configuration (e.g. bad bitstream data), the watchdog fires and the FPGA ignores `WBSTAR`, rebooting from address 0x0 (the golden image).

### ICAPE2 Warm Reboot

The ICAPE2 (Internal Configuration Access Port) primitive allows software-triggered reconfiguration without a power cycle:

1. Write the target flash address to the `WBSTAR` (Warm Boot Start Address) register
2. Write the `IPROG` command to the ICAPE2 CMD register
3. The FPGA immediately begins reconfiguration from the specified address
4. PCIe link goes down momentarily and retrains after the new bitstream loads

LiteX exposes this via the `ICAP` core:
```python
from litex.soc.cores.icap import ICAP
self.icap = ICAP()
self.icap.add_reload()
```

## Programming via PCIe

### Prerequisites

- A working LiteX bitstream with PCIe support must already be running on the FPGA
- The `litepcie` kernel module must be loaded on the host
- `litepcie_util` must be built (auto-generated by LiteX build)

### Write Operational Bitstream

```bash
# Write new operational bitstream to flash at 0x400000
litepcie_util flash_write operational.bin 0x400000
```

### Reload from Flash

```bash
# Trigger ICAP warm reboot — FPGA reloads from flash
litepcie_util flash_reload
```

After reload, the PCIe link retrains. The host must rescan the PCIe bus:

```bash
echo 1 > /sys/bus/pci/rescan
```

### Full Update Sequence

```bash
# 1. Write new operational bitstream
litepcie_util flash_write new_design.bin 0x400000

# 2. Trigger warm reboot
litepcie_util flash_reload

# 3. Wait for PCIe link to retrain (~2-5 seconds)
sleep 5

# 4. Rescan PCIe bus
echo 1 > /sys/bus/pci/rescan

# 5. Verify new bitstream is running
lspci -d 10ee: -vvv
```

## Recovery from Bad Bitstream

### Automatic Recovery (Watchdog) — Operational Bitstream Bad

If the operational bitstream at 0x400000 is corrupted or fails to configure:

1. FPGA attempts to load operational bitstream
2. Configuration stalls or produces errors
3. `TIMER_CFG` watchdog fires
4. FPGA ignores `WBSTAR` and reloads from address 0x0 (fallback)
5. Golden image boots, PCIe comes up
6. Host can reprogram operational slot via `litepcie_util flash_write`

**No manual intervention required** — the system self-recovers.

### SRAM Bootstrap Recovery — Golden Bitstream Bad

If the golden bitstream at address 0x0 is corrupted, PCIe will not come up on boot and `litepcie_util` cannot be used. Since flash-via-JTAG is not currently working, recovery uses a **two-stage SRAM bootstrap**:

1. **Load a PCIe-capable bitstream to SRAM via JTAG** (volatile — lost on power cycle):
   ```bash
   echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # if anything is enumerated
   sudo rmmod spidev spi_bcm2835                                 # Pi 0-4 only
   openFPGALoader --cable libgpiod --pins 10:9:11:8 golden.bit
   ```

2. **PCIe comes up from the SRAM-loaded bitstream**. Load the litepcie kernel module:
   ```bash
   modprobe litepcie
   ```

3. **Write a new golden image to flash at address 0x0 via PCIe**:
   ```bash
   litepcie_util flash_write golden.bin 0x0
   ```

4. **Write the operational bitstream to 0x400000**:
   ```bash
   litepcie_util flash_write operational.bin 0x400000
   ```

5. **Power cycle** the board. The FPGA boots from the new golden image in flash, chain-loads operational, and PCIe comes up persistently.

**Critical**: Between steps 1 and 5, the board **must not lose power**. The SRAM-loaded bitstream is volatile — if power is lost before step 3 completes, the flash still has the corrupted golden image and you must restart from step 1.

### JTAG-only bootstrap via the `flash_writer` SoC (fallback)

`designs/pcie-enumeration/gateware/flash_writer_soc_acorn.py` is a minimal
LiteX SoC with **no PCIe**: JTAGBone as the host control channel plus the same
`S7SPIFlash` + `flash_cs_n` + `ICAP` cores the PCIe design uses. JTAG-loaded
into SRAM, it lets the host write a bitstream into flash through the
JTAGBone-exposed SPI CSRs and then trigger `icap.iprog`, so a board can be
moved from the factory firmware to a LiteX image without any PCIe involvement.

It was written in May 2026 when JTAG-loaded PCIe-capable designs appeared to
revert to the factory firmware within seconds, which was read as a
PERST→PROG_B circuit reacting to host-side link maintenance. The 2026-08-31
finding that reconfiguring an *enumerated* endpoint crashes and reboots the
Pi 5 (see the detach rule at the top of this page) is a simpler explanation
for the same observation, so the SRAM bootstrap above, with the endpoint
detached first, is the primary path and this SoC is the fallback if that
re-test fails. Notes for using it:

- LiteX 2025.12 (the pinned version) has an xc7 JTAGPHY bug that silently
  drops host→target JTAGBone writes. Apply
  `scripts/apply_litex_jtag_patch.py <venv>/lib/python3.12/site-packages/litex/soc/cores/jtag.py`
  before building; LiteX 2026.04 has the fix upstream.
- Build with `--toolchain openxc7` (it has been built and JTAG-loaded that
  way; a `--toolchain vivado` build is untested).
- The host side (a JTAGBone client that erases, page-programs and verifies
  the flash through the `flash`/`flash_cs_n` CSRs, then pulses `icap.iprog`)
  is not in the repo yet; `litex_server --jtag` plus `litex.tools.litex_client`
  is the starting point.
- The factory firmware at 0x0 does not chain-load 0x400000, so after writing
  the operational slot the *first* PROG_B still boots Sqrl; `icap.iprog`
  with `WBSTAR` = 0x400000 bypasses that until golden is installed at 0x0.

### Recovery Summary

| Scenario | Golden OK? | Operational OK? | Recovery Method | Automatic? |
|----------|-----------|----------------|-----------------|------------|
| Bad operational | Yes | No | Watchdog fallback to golden, reprogram via PCIe | Yes |
| Bad operational (PCIe broken) | Yes | No | Golden boots, reprogram via PCIe | Yes |
| Bad golden | No | — | SRAM bootstrap: JTAG→SRAM, then PCIe→Flash | No (manual) |
| Bad golden + no JTAG wiring | No | — | **Bricked** — requires physical JTAG reconnection | No |

## Initial Setup (New Board)

Since flash-via-JTAG is not working, initial multiboot setup uses the SRAM bootstrap method:

1. **Build a golden bitstream** with Vivado (LiteX SoC with PCIe + SPI Flash + ICAP + NEXT_CONFIG_ADDR)

2. **Load golden to SRAM via JTAG** (volatile):
   ```bash
   echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # detach the factory endpoint
   sudo rmmod spidev spi_bcm2835                                 # Pi 0-4 only
   openFPGALoader --cable libgpiod --pins 10:9:11:8 golden.bit
   ```

3. **PCIe comes up**. Load the kernel module and write golden to flash:
   ```bash
   modprobe litepcie
   litepcie_util flash_write golden.bin 0x0
   ```

4. **Write operational bitstream** to flash:
   ```bash
   litepcie_util flash_write operational.bin 0x400000
   ```

5. **Power cycle** — golden boots from flash, chain-loads operational, PCIe comes up persistently.

6. **Verify** multiboot works by intentionally writing a bad operational image, confirming watchdog fallback, then reprogramming:
   ```bash
   # Write garbage to operational slot
   dd if=/dev/urandom bs=1M count=4 of=/tmp/bad.bin
   litepcie_util flash_write /tmp/bad.bin 0x400000
   litepcie_util flash_reload
   # Wait — watchdog should fall back to golden
   sleep 10
   echo 1 > /sys/bus/pci/rescan
   # Verify golden is running (check ident string via UART)
   # Reprogram good operational
   litepcie_util flash_write operational.bin 0x400000
   litepcie_util flash_reload
   ```

From this point on, operational updates only need `litepcie_util flash_write` + `flash_reload`.

## Generating Multiboot Bitstreams

### Fallback (Golden) Bitstream

The fallback bitstream must set `NEXT_CONFIG_ADDR` to point to the operational slot:

**Vivado TCL:**
```tcl
set_property BITSTREAM.CONFIG.NEXT_CONFIG_ADDR 0x00400000 [current_design]
write_bitstream -force golden.bit
write_cfgmem -force -format bin -interface spix4 -size 16 \
    -loadbit "up 0x0 golden.bit" -file golden.bin
```

**LiteX (openXC7):**
The openXC7 toolchain does not currently support `NEXT_CONFIG_ADDR` bitstream properties. Multiboot golden bitstreams must be built with Vivado. This is acceptable since the golden image is written once and rarely updated.

### Operational Bitstream

The operational bitstream must enable the watchdog timer and fallback:

**Vivado TCL:**
```tcl
set_property BITSTREAM.CONFIG.TIMER_CFG 0x0001fbd0 [current_design]
set_property BITSTREAM.CONFIG.CONFIGFALLBACK Enable [current_design]
write_bitstream -force operational.bit
write_cfgmem -force -format bin -interface spix4 -size 16 \
    -loadbit "up 0x0 operational.bit" -file operational.bin
```

## Safety Rules

1. **NEVER write to flash address 0x0 via PCIe during normal operation.** The golden image is the recovery mechanism. Only write to 0x0 during initial setup or golden recovery. A wrapper script should validate the target address.

2. **Always use 0x400000 for operational updates:**
   ```bash
   # CORRECT — writes to operational slot
   litepcie_util flash_write design.bin 0x400000

   # DANGEROUS — overwrites golden image
   # litepcie_util flash_write design.bin 0x0   # DO NOT DO THIS
   ```

3. **Always test new bitstreams via JTAG SRAM load first** before writing to flash. This validates the design without touching flash:
   ```bash
   echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove
   openFPGALoader --cable libgpiod --pins 10:9:11:8 new_design.bit
   # Test it works, then write to flash via PCIe
   ```

4. **Keep JTAG wiring connected** on all deployed Acorn boards. Without JTAG, a corrupted golden image means the board is **permanently bricked** until JTAG is reconnected. As of 2026-08-31 pi-sw2-p43 and pi-sw2-p44 scan an empty JTAG chain and PS1's pi14/pi16 do not answer JTAG at all — those four are in exactly this state and must not be flashed over PCIe until JTAG is restored.

5. **Detach the PCIe endpoint before every JTAG load** (see the top of this page). A Pi 5 host crashes otherwise.

6. **The golden bitstream must be a minimal LiteX SoC** with only PCIe, SPI Flash, ICAP, and UART — no complex user logic that might fail.

## Future: Flash-via-JTAG Support

When openFPGALoader gains working `--write-flash` support for the Acorn (via GPIO JTAG), the recovery story simplifies significantly:

- Initial setup becomes a single JTAG flash write instead of the SRAM bootstrap
- Golden recovery no longer requires a volatile SRAM intermediate step
- The "bricked" scenario in the recovery table disappears — JTAG can always reflash

This is tracked as an openFPGALoader enhancement. The SRAM bootstrap procedure documented above works reliably in the meantime.

## References

- Xilinx XAPP1247 — MultiBoot with SPI: <https://docs.amd.com/v/u/en-US/xapp1247-multiboot-spi>
- LiteX Acorn CLE-215 wiki: <https://github.com/enjoy-digital/litex/wiki/Use-LiteX-on-the-Acorn-CLE-215>
- LitePCIe: <https://github.com/enjoy-digital/litepcie>
- LiteX ICAP core: <https://github.com/enjoy-digital/litex/blob/master/litex/soc/cores/icap.py>
- Acorn board spec: [acorn.md](acorn.md)
- Acorn pinmap: [acorn-pinmap.md](acorn-pinmap.md)
- GPIO JTAG wiring: [acorn-pinmap.md](acorn-pinmap.md)
