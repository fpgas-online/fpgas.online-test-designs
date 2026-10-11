# Acorn PCIe Programming & Multiboot

How to program the Acorn CLE-215+ / LiteFury FPGA via PCIe, and how to use Xilinx 7-series multiboot for safe recovery from bad bitstreams.

## Programming Paths

The Acorn has two working programming paths:

| Method | Speed | Persistent? | Requires | Notes |
|--------|-------|-------------|----------|-------|
| GPIO JTAG → SRAM | ~16 s for a 1.6 MB XC7A200T bitstream (bit-banged libgpiod) | No (lost on power cycle) | RPi GPIO wiring | Works with any/no bitstream loaded. **Detach the PCIe endpoint first** (below) |
| PCIe → SPI Flash | Fast (~seconds) | Yes | Working LiteX PCIe bitstream | Requires PCIe-capable bitstream already running |

### Detach the PCIe endpoint before any JTAG reconfiguration

Reconfiguring the FPGA over JTAG while its endpoint is enumerated is a PCIe
surprise removal. The Pi 5's BCM2712 root complex does not survive it: the
host dies outright ("Connection closed by remote host", the Pi reboots). With
the endpoint removed first, the load completes cleanly and the host is
unaffected.

```bash
echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # before openFPGALoader
# ... load ...
echo 1 | sudo tee /sys/bus/pci/rescan                         # afterwards, or just reboot
sudo python3 designs/acorn-pcie/host/pcie_match_mps.py        # after every rescan (next section)
```

### Match the Max Payload Size after every rescan

The Pi 5 firmware boots Linux with `pci=pcie_bus_safe`. In that mode the
kernel matches Max_Payload_Size (MPS) across the link once, at boot; a sysfs
rescan does not. An endpoint found by a rescan keeps its reset MPS of 128
bytes while the root port `0001:00:00.0` stays at 512. The root port then
returns read completions of up to 512 bytes, the 7-series PCIe core rejects
them as malformed TLPs and sets FatalErr, and LitePCIe's DMA waits forever for
its read data. With the mismatch, `litepcie_util dma_test` moves nothing
(TX 128, RX 0, no MSI); with the endpoint's MPS set to 512 it moves data
(3.6 Gb/s on a CLE-215+ on a Raspberry Pi 5).

```bash
sudo lspci -vv -s 0001:00:00.0 | grep MaxPayload   # root port: 512
sudo lspci -vv -s 0001:01:00.0 | grep MaxPayload   # after a rescan: 128 - mismatch
sudo python3 designs/acorn-pcie/host/pcie_match_mps.py
# 0001:01:00.0: MPS 128 -> 512 (root port 0001:00:00.0: 512)
```

`pcie_match_mps.py` writes only the MPS field of Device Control. It sets both
ends to the smaller of the root port's current MPS and the endpoint's
supported maximum, as `pcie_bus_safe` does at boot. It does nothing when the
loaded design has no PCIe endpoint. Run it before `insmod litepcie.ko`, or at
least before any DMA. The PCI core rewrites Device Control on every
remove/rescan, so run it again after each one. `verify_hardware.py` runs it
after its Acorn JTAG load. A boot-time enumeration is already matched (p48 with
its flash image: 512 on both ends).

Every `openFPGALoader … <bitstream>` invocation on this page assumes that
detach has been done. Read-only operations (`--detect`, and `--read-dna` /
`--read-xadc` on openFPGALoader ≥ 0.13) do not reconfigure the device and are
safe on a live endpoint.

### Prebuilt Vivado bitstreams

There is no need to build locally. GitHub release
[`vivado-bitstreams-v0.0-496-gf162f60`](https://github.com/fpgas-online/fpgas.online-test-designs/releases/tag/vivado-bitstreams-v0.0-496-gf162f60)
(Vivado 2025.2) carries every test design × Acorn variant
(`cle-101`, `cle-215`, `cle-215p`), each as plain `.bit`/`.bin` plus the
`_fallback` and `_operational` multiboot variants described below, and a
`manifest.json` with a SHA-256 per file. For a CLE-215+ use the
`*_acorn-cle-215p_*` files; their `.bit` header reads `7a200tfbg484`, matching
IDCODE `0x3636093`.

```bash
gh release download vivado-bitstreams-v0.0-496-gf162f60 \
    --repo fpgas-online/fpgas.online-test-designs \
    --pattern 'pmod-pin-id_acorn-cle-215p_vivado-vivado_sqrl_acorn.bit'
```

The `pmod-pin-id` build in that release has no working clock: it configures
but never toggles a pin. Rebuild *that one design* with Vivado from this
repository.

**Flash-via-JTAG (`--write-flash`) does not work** with openFPGALoader on the Acorn. JTAG can only load bitstreams to volatile SRAM. This has important implications for the recovery strategy.

### Sqrl's factory firmware

A board still on Sqrl's factory
(cryptocurrency mining) firmware cannot be programmed over PCIe.

Factory firmware characteristics:

- PCI vendor:device `1e24:021f` (Squirrels Research Labs)
- BAR0: 128 KB — repeating mining parameter pattern, no LiteX CSRs
- **Not a LiteX design** — `litepcie_util` cannot communicate with this firmware

To enable PCIe→Flash programming, the factory firmware must be replaced with a **LiteX Acorn PCIe SoC** bitstream (vendor `10ee`) that includes PCIe+DMA, SPI Flash controller, and ICAP. This design (`designs/acorn-pcie`) is built with **Vivado** today. The part is not the reason: CI builds the single-function designs for the XC7A200T with openXC7 on every push to main and every PR. The prebuilt release above already contains `pcie-enumeration_acorn-cle-215p_*_{fallback,operational}.bin`.

Because the Pi root is `overlayroot=tmpfs`, anything built on a Pi is lost
at reboot unless it is baked into the NFS root.

The aim is to flash every board with a LiteX design carrying PCIe + UART +
GPIO that supports FPGA updates over PCIe.

### What This Means

- JTAG can always load a bitstream into SRAM (volatile), but it is lost on power cycle
- SPI flash (persistent) can only be written through our running SoC: `fpgas-acorn-flash` over PCIe (no kernel module; what the fleet uses) or over the P2 UART bridge (`--uart`, slow), or `litepcie_util` with `litepcie.ko` loaded
- `fpgas-acorn-flash` refuses a card that a kernel driver (`litepcie.ko`) is bound to: the driver owns BAR0 then. Over the P2 UART it refuses while `litepcie.ko` is bound to any device. Unbind the driver first. (`fpgas-verify` instead unbinds the driver for its check and binds it again.)
- PCIe→Flash requires our LiteX bitstream running (not the factory Sqrl firmware)
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

The two flash images use Xilinx 7-series multiboot ([XAPP1247, MultiBoot with SPI](https://docs.amd.com/v/u/en-US/xapp1247-multiboot-spi)), with LiteX's ICAP core ([`icap.py`](https://github.com/enjoy-digital/litex/blob/master/litex/soc/cores/icap.py)) for the warm reboot.

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

After reload, the PCIe link retrains. The host must rescan the PCIe bus, then
match the endpoint's Max_Payload_Size (see
[above](#match-the-max-payload-size-after-every-rescan)):

```bash
echo 1 > /sys/bus/pci/rescan
python3 designs/acorn-pcie/host/pcie_match_mps.py
```

### Full Update Sequence

```bash
# 1. Write new operational bitstream
litepcie_util flash_write new_design.bin 0x400000

# 2. Trigger warm reboot
litepcie_util flash_reload

# 3. Wait for PCIe link to retrain (~2-5 seconds)
sleep 5

# 4. Rescan PCIe bus, then match Max_Payload_Size
echo 1 > /sys/bus/pci/rescan
python3 designs/acorn-pcie/host/pcie_match_mps.py

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

If the golden bitstream at address 0x0 is corrupted, PCIe will not come up on boot and `litepcie_util` cannot be used. Since flash-via-JTAG does not work, recovery uses a **two-stage SRAM bootstrap**:

1. **Load a PCIe-capable bitstream to SRAM via JTAG** (volatile — lost on power cycle):
   ```bash
   echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # if anything is enumerated
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

### Recovery Summary

| Scenario | Golden OK? | Operational OK? | Recovery Method | Automatic? |
|----------|-----------|----------------|-----------------|------------|
| Bad operational | Yes | No | Watchdog fallback to golden, reprogram via PCIe | Yes |
| Bad operational (PCIe broken) | Yes | No | Golden boots, reprogram via PCIe | Yes |
| Bad golden | No | — | SRAM bootstrap: JTAG→SRAM, then PCIe→Flash | No (manual) |
| Bad golden + no JTAG wiring | No | — | **Bricked** — requires physical JTAG reconnection | No |

## Converting a factory board on a Pi 5 with the Waveshare HAT

These steps replace Sqrl's factory firmware (or an older release of ours) with
the images of the release pinned in
[`packaging/acorn-pcie/release.toml`](../../packaging/acorn-pcie/release.toml).
Everything runs on the Acorn's own Pi, using what the fleet installs: the
images and `manifest.json` from `fpgas-online-acorn-bitstreams` in
`/usr/share/fpgas-online/acorn-pcie/images/`, and `fpgas-acorn-flash`. Nothing
needs `litepcie.ko`. Writing the flash, the fallback slot at `0x0` especially,
needs the owner's go-ahead for that board.

Each step is one block. Paste it into a shell on the Pi as the `pi` user:
every block runs its commands as root through `sudo … bash -s` itself, so an
`exit` inside a block ends only that block, and every block sets the variables
it uses. The JTAG steps (1 and 4) hold `/run/lock/fpgas-acorn.lock`, the lock
`fpgas-verify` and `fpgas-acorn-flash` use, for their whole block. Steps 2
and 3 must not: `fpgas-acorn-flash` takes that lock itself for each command,
and waits for it, so wrapping it in the same lock would hang.

**0. Pick the images.** The board's PCIe ID, before conversion, gives the
variant:

| Variant | Factory `lspci -nn` ID | `--idcode` | File for `0x000000` (fallback slot) | File for `0x400000` (operational slot) |
|---|---|---|---|---|
| CLE-215+ | `1e24:021f` | `0x03636093` | `acorn-cle-215p-golden-sqrl_acorn_fallback.bin` | `acorn-cle-215p-sqrl_acorn_operational.bin` |
| CLE-101 | `1e24:0101` | `0x03631093` | `acorn-cle-101-golden-sqrl_acorn_fallback.bin` | `acorn-cle-101-sqrl_acorn_operational.bin` |

The same names are in `manifest.json` under `flash_layout`. The blocks below
use the CLE-215+ names. Check that the installed files are the ones the
manifest describes. Every file the release puts in the package must say
`ok`; `MISSING` is expected only for assets the package doesn't install:

```bash
cd /usr/share/fpgas-online/acorn-pcie/images
python3 -c '
import hashlib, json, os
for f in json.load(open("manifest.json"))["files"]:
    if not os.path.exists(f["asset"]):
        print("MISSING", f["asset"])
        continue
    ok = hashlib.sha256(open(f["asset"], "rb").read()).hexdigest() == f["sha256"]
    print("ok     " if ok else "BAD    ", f["asset"])
'
```

**1. Load our SoC into the FPGA's SRAM over JTAG.** The factory design can't
write its own flash, so first load ours into the FPGA's configuration memory.
This is temporary: it lasts until the FPGA is reset or loses power, and it
touches nothing in flash. The file is the operational design as a plain
`.bit` (`acorn-cle-215p-sqrl_acorn.bit`), not one of the `.bin` slot images.
PCIe is detached first, because reconfiguring an enumerated endpoint crashes
a Pi 5 (see [above](#detach-the-pcie-endpoint-before-any-jtag-reconfiguration)).

```bash
sudo flock -n /run/lock/fpgas-acorn.lock bash -s <<'JTAG' || echo "Acorn busy, or openFPGALoader failed"
set -u
D=0001:01:00.0
I=/usr/share/fpgas-online/acorn-pcie/images
ls -l /dev/gpiochip0      # must point at the RP1's chip (see below)
echo 1 > /sys/bus/pci/devices/$D/remove
openFPGALoader --cable libgpiod --pins 10:9:11:8 $I/acorn-cle-215p-sqrl_acorn.bit
rc=$?
for p in 8 9 10 11; do pinctrl set $p ip pd; done   # openFPGALoader leaves the JTAG pins driven
echo 1 > /sys/bus/pci/rescan
lspci -nn -s $D           # expect 10ee:7021, subsystem 1e24:021f
exit $rc
JTAG
```

openFPGALoader's `libgpiod` cable opens `/dev/gpiochip0`, which must be the
40-pin header's chip. On a Pi 5 that is the RP1's GPIO chip, whose number
varies (11 to 15). The boot check makes `/dev/gpiochip0` a symlink to it
(`verify/src/fpgas_online_verify/boards/acorn/links.py` finds it by its
`raspberrypi,rp1-gpio` compatible). If `ls -l /dev/gpiochip0` shows nothing,
or another chip, run `fpgas-acorn-verify` once, or link it by hand to the
chip `gpiodetect` lists as `pinctrl-rp1`.

From here until step 4, **the board must not lose power**. The SoC is only in
SRAM, and step 3 changes the flash.

**2. Back up the whole flash, and copy it off the Pi.**

```bash
sudo bash -s <<'FLASH'
set -u
D=0001:01:00.0
# Our SoC must be the one answering, or the tool would poke the factory design's registers.
[ "$(cat /sys/bus/pci/devices/$D/vendor):$(cat /sys/bus/pci/devices/$D/device)" = "0x10ee:0x7021" ] || { echo "our SoC is not running: redo step 1"; exit 1; }
orig=$(setpci -s $D COMMAND)
setpci -s $D COMMAND=0002:0002     # memory decode on: fpgas-acorn-flash doesn't do this, and reads all 0xff without it
fpgas-acorn-flash id               # part, size, unique_id, quad_enabled
fpgas-acorn-flash dump /home/pi/factory.bin
sha256sum /home/pi/factory.bin
setpci -s $D COMMAND=$orig
FLASH
```

`/home/pi` lives in the Pi's RAM: the fleet's root filesystem is a RAM
overlay on top of the shared network root. So the 32 MiB dump never reaches
the network root, and it is gone at reboot. (`/tmp` is on the same overlay;
`/home/pi` just keeps the copy easy to find.) From another machine, copy it
off and check its sha256 matches the one printed above. Name the backup by
board identity, filling in the values `fpgas-acorn-flash id` and the board's
DNA give:

```bash
HOST=the-pi        # the Pi the card is on
OUT=acorn-cle-215p_dna-DNA_flashuid-UNIQUEID_${HOST}_factory_YYYY-MM-DD.bin
ssh "pi@$HOST" cat /home/pi/factory.bin > "$OUT"
sha256sum "$OUT"
```

**3. Write and check both slots, operational first.** Set `BACKUP_SHA256` to
the off-Pi copy's sha256, so the block stops unless the dump on the Pi is the
one you saved:

```bash
sudo bash -s <<'FLASH'
set -u
D=0001:01:00.0
I=/usr/share/fpgas-online/acorn-pcie/images
BACKUP_SHA256=paste-the-off-Pi-copy-sha256-here
echo "$BACKUP_SHA256  /home/pi/factory.bin" | sha256sum -c || exit 1
[ "$(cat /sys/bus/pci/devices/$D/vendor):$(cat /sys/bus/pci/devices/$D/device)" = "0x10ee:0x7021" ] || exit 1
orig=$(setpci -s $D COMMAND)
setpci -s $D COMMAND=0002:0002
fpgas-acorn-flash write --idcode 0x03636093 $I/acorn-cle-215p-sqrl_acorn_operational.bin 0x400000 &&
fpgas-acorn-flash write --idcode 0x03636093 --i-know-this-writes-golden $I/acorn-cle-215p-golden-sqrl_acorn_fallback.bin 0x0 &&
fpgas-acorn-flash verify $I/acorn-cle-215p-sqrl_acorn_operational.bin 0x400000 &&
fpgas-acorn-flash verify $I/acorn-cle-215p-golden-sqrl_acorn_fallback.bin 0x0
rc=$?
setpci -s $D COMMAND=$orig
exit $rc
FLASH
```

Each `write` reads back what it wrote (`wrote and verified … RESULT: PASS`),
and the two `verify` commands check both slots again at the end.

If `write` refuses with "the flash's QUAD bit is clear", stop and ask. The
images load from flash in x4 mode, and this tool cannot set that bit. Nothing
has been written, and the board keeps the SRAM-loaded SoC until it loses power.

**4. Make the FPGA load from flash, then reboot the Pi.** Rebooting the Pi
alone is not enough, because the FPGA keeps running the SRAM-loaded SoC. A
JTAG reset makes it reload from flash (a PoE cycle of the port does the same):

```bash
sudo flock -n /run/lock/fpgas-acorn.lock bash -s <<'JTAG' && sudo systemctl reboot || echo "Acorn busy, or openFPGALoader failed: not rebooting"
D=0001:01:00.0
echo 1 > /sys/bus/pci/devices/$D/remove
openFPGALoader --cable libgpiod --pins 10:9:11:8 --reset
rc=$?
for p in 8 9 10 11; do pinctrl set $p ip pd; done
exit $rc
JTAG
```

**5. Check.** `fpgas-verify` runs at boot (`journalctl -b -u fpgas-verify`),
and `fpgas-acorn-verify` runs the same checks on demand. A converted board
enumerates as `10ee:7021`, subsystem `1e24:021f`, and passes with
`flash 0x000000 match` and `flash 0x400000 match`; its identifier is the
release's operational build. On the fleet there is nothing to record: the root
keeps no verify state across the reboot. On a host with a persistent
`/var/lib`, run `sudo fpgas-verify --update` to accept a change made on
purpose.

A board already running one of our releases skips step 1.

### On a Compute Blade

**Do not convert a card on a Compute Blade.** What differs on a blade, for reading a card there by hand (pins from
[`docs/wiring/acorn/wiring.toml`](../wiring/acorn/wiring.toml), `[carriers.blade]`):

| | Pi 5 + Waveshare HAT | Compute Blade |
|---|---|---|
| JTAG `--pins` | `10:9:11:8` | `2:3:4:14` |
| `/dev/gpiochip0` | a symlink to the RP1 chip | CM4: already the header chip. CM5: the RP1 chip. Under kernel 6.18 it was already `gpiochip0`; check with `gpiodetect` |
| PCIe address (`D=`, and `--bdf` for `fpgas-acorn-flash`) | `0001:01:00.0` | the one `lspci -D` shows (`0000:01:00.0` on a CM4, `0001:01:00.0` on a CM5) |
| Pins after openFPGALoader | `8 9 10 11` to `ip pd` | `2 3 4` to `ip pd`. `14` is shared with the P2 UART (J2, through 470 Ω), so put it back to its UART function: `pinctrl set 14 a0` on a CM4, `a4` on a CM5 |

[The Acorn check](https://docs.fpgas.online/en/latest/boards/acorn/checks/about.html) says why not to convert there. On a Compute Module 5 with kernel 6.18, JTAG cannot have its TMS pin (GPIO14) while the header's serial port is on ([How to make a Compute Blade boot ready for JTAG](https://docs.fpgas.online/en/latest/boards/acorn/checks/compute-blade-jtag.html)).

`fpgas-acorn-flash --uart PORT` reaches the flash over the P2 UART bridge
instead of PCIe. It works, but slowly.

## Initial Setup (New Board), with `litepcie_util`

The same SRAM bootstrap with LiteX's own tools, for a host that has
`litepcie.ko` and `litepcie_util` built:

1. **Build a golden bitstream** with Vivado (LiteX SoC with PCIe + SPI Flash + ICAP + NEXT_CONFIG_ADDR)

2. **Load golden to SRAM via JTAG** (volatile):
   ```bash
   echo 1 | sudo tee /sys/bus/pci/devices/0001:01:00.0/remove   # detach the factory endpoint
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

4. **Keep JTAG wiring connected** on all deployed Acorn boards. Without JTAG, a corrupted golden image means the board is **permanently bricked** until JTAG is reconnected. Check that `fpgas-verify`'s `jtag` test passes on a board before flashing it over PCIe.

5. **Detach the PCIe endpoint before every JTAG load** (see the top of this page). A Pi 5 host crashes otherwise.

6. **The golden bitstream must be a minimal LiteX SoC** with only PCIe, SPI Flash, ICAP, and UART — no complex user logic that might fail.
