# verify_hardware.py — How the Hardware Verification Script Works

`verify_hardware.py` is the central test orchestrator. It uploads bitstreams and test scripts to remote Raspberry Pi boards, programs FPGAs, runs tests, and reports results. Every test follows the same sequence but with board-specific adaptations for how the FPGA connects to the RPi.

## Overview

```
Local machine                    RPi host                      FPGA board
─────────────                    ────────                      ──────────
verify_hardware.py
  │
  ├── ssh_upload(bitstream) ──────> ~/uart_arty.bit
  ├── ssh_upload(test_script) ───> ~/test_uart.py
  ├── ssh_run(pre_test) ─────────> stop serial-getty, kill interfering processes
  ├── ssh_run(program_cmd) ──────> openFPGALoader ─────────────> FPGA configured
  └── ssh_run(test_cmd) ─────────> python3 test_uart.py ──────> UART echo test
                                       │
                                       └── "RESULT: PASS" or "RESULT: FAIL"
```

## Network Topology

There are two types of SSH connections:

**Tweed-connected hosts** (pi3, pi5, pi9, pi17, pi21, pi27, pi29, pi31, pi33): These RPis are on a private 10.21.0.0/16 network behind a gateway called `tweed.welland.mithis.com`. Every SSH command is a double-hop:

```
local ──SSH──> tweed ──SSH──> root@10.21.0.NNN
```

The `_build_ssh_cmd()` function constructs this. The inner command is shell-escaped with `shlex.quote()` so it survives the tweed shell intact.

**Direct-SSH hosts** (rpi5-netv2, rpi3-netv2): These are reachable directly by hostname.

## Host and Board Definitions

The `HOSTS` dict maps host names to their properties:

```python
"pi33": {"ssh_type": "tweed", "target": "10.21.0.133", "board": "tt"}
"rpi5-netv2": {"ssh_type": "direct", "target": "tim@rpi5-netv2...", "board": "netv2",
               "variant": "a7-100", "serial_port": "/dev/ttyAMA0"}
```

- **`board`**: Which FPGA board is attached (arty, fomu, tt, netv2).
- **`variant`** (NeTV2 only): The FPGA variant (a7-35 or a7-100). The NeTV2 comes in two variants with different FPGAs, requiring different bitstreams.
- **`serial_port`** (NeTV2 only): Host-specific serial device override. On RPi 5, the GPIO UART is `/dev/ttyAMA0` (RP1 PL011). On RPi 3, it's `/dev/serial0` -> `/dev/ttyS0` (mini UART, because Bluetooth claims the PL011).

## Test Generation

`generate_tests()` creates the cross-product of DESIGNS x HOSTS. For each combination where the host's board type matches a board entry in the design, it creates a test case with:

1. **Artifact path**: The CI-built bitstream to upload. For NeTV2, variant-specific artifacts are preferred (e.g., `uart-test-netv2-a7-100t/kosagi_netv2.bit` over `uart-test-netv2/kosagi_netv2.bit`) so each host gets the bitstream matching its FPGA.

2. **Serial port override**: If the host defines `serial_port`, any `--port /dev/xxx` in the test_args is rewritten to match. This handles RPi 3 vs RPi 5 UART device differences for the same board type.

3. **Programming command**: Either from `PROGRAM_CMD[board]` or `HOST_PROGRAM_CMD[host_name]` for hosts that need special programming (NeTV2 uses different JTAG interfaces on each RPi model).

4. **Test command**: `python3 ~/test_<design>.py <test_args>`.

## File Upload

`ssh_upload()` pipes file contents through SSH stdin to `cat > <remote_path>`. This avoids `scp` shell-escaping issues with double-hop SSH. The file data is read locally and sent as raw bytes.

For TT FPGA boards, `EXTRA_UPLOADS` sends additional helper scripts (`tt_fpga_program.py`, `tt_test_wrapper.py`, `tt_pmod_wrapper.py`) that handle RP2350 communication.

## Pre-Test Commands

Each board config can define a `pre_test` shell command that runs on the RPi **before** FPGA programming. This is critical because the FPGA's BIOS/firmware starts executing immediately after programming, and any process holding the serial port would interfere with or corrupt the boot output.

Pre-test commands handle several board-specific issues:

**Arty PMOD**: `rmmod spidev spi_bcm2835` — The SPI kernel modules claim GPIO7-11 (which overlap with PMOD HAT port JB pins). Unloading them frees those GPIOs for the loopback test.

**Fomu UART**: `systemctl mask serial-getty@ttyAMA0; systemctl stop ...` — The `serial-getty` service runs a login console on the serial port. `stop` alone is insufficient because systemd can restart it; `mask` creates a symlink to `/dev/null` preventing restart entirely.

**NeTV2 UART**: Multiple interfering services must be killed:
- `serial-getty` — serial login console
- `netv2-status.js` — A Node.js monitoring app (managed by pm2) that continuously sends `json on` commands to the FPGA BIOS via the serial port
- `fuser -k` — Kills any remaining process holding the serial device
- `chmod 666` — After serial-getty releases the device, its permissions revert to root-only
- `pinctrl set 14 a4; pinctrl set 15 a4` — RPi 5 only: after serial-getty stops, GPIO14/15 revert from UART function to plain GPIO mode. This command sets them back to the UART alternate function (ALT4 = TXD0/RXD0). RPi 3 doesn't need this because its mini UART pins don't change function.

## FPGA Programming

Programming varies by board:

**Arty**: `openFPGALoader -b arty <bitstream>` — USB JTAG via the on-board FTDI chip.

**Fomu**: `openFPGALoader -b fomu <bitstream>` — USB DFU protocol. The Fomu EVT boots into a DFU bootloader from SPI flash. The bootloader has a ~3 minute timeout; after that it loads the user bitstream from SPI flash (which typically has no USB, making the Fomu disappear from USB). If DFU has timed out, the script triggers a **PoE power cycle** (see below) to reset the Fomu back into the bootloader.

**NeTV2 (rpi5)**: `sudo openFPGALoader -c rp1pio --pins 27:22:4:17 <bitstream>` — JTAG via RPi 5's RP1 GPIO bitbang. The pin numbers are TCK:TDO:TDI:TMS mapped to specific GPIO pins on the 40-pin header.

**NeTV2 (rpi3)**: `sudo openocd -f alphamax-rpi.cfg -c 'init; pld load 0 <bitstream>; exit'` — JTAG via OpenOCD with BCM2835 GPIO bitbang. Uses `pld load 0` (device index 0, OpenOCD 0.10.x syntax).

**TT FPGA**: `python3 ~/tt_fpga_program.py /dev/ttyACM0 <bitstream>` — Programming goes through the RP2350 microcontroller. The script uses `mpremote` to upload the bitstream to the RP2350's filesystem, then executes a MicroPython script that programs the iCE40 via PIO-accelerated SPI. The RP2350 connects to the RPi via USB CDC (`/dev/ttyACM0`), not GPIO.

### Programming Success Detection

The script checks multiple indicators because different tools report success differently:
- `rc == 0` — Standard exit code
- `"done 1" in output` — openFPGALoader prints the FPGA's DONE status bit
- `"dfuIDLE" in output` — dfu-util's success indicator (legacy, kept for compatibility)

### Fomu DFU Timeout Recovery

When the Fomu's DFU bootloader has timed out, programming fails. The script automatically recovers:

1. Detects the failure (`not programming_ok` for a Fomu board)
2. Calls `poe_reset()` to power-cycle the RPi (and the USB-powered Fomu) via SNMP-controlled PoE switch
3. Waits for the RPi to PXE-boot (~2 minutes), polling with `ssh_check_connectivity()`
4. Re-uploads all files (the PXE-booted tmpfs filesystem is empty after reboot)
5. Re-runs the pre_test (serial-getty mask is lost on reboot)
6. Retries programming (the Fomu is back in DFU mode after power cycle)

## PoE Reset

`poe_reset()` power-cycles a PoE-powered RPi via SNMP commands to a Netgear managed switch. The switch port numbers match the host naming convention: pi27 → switch port 27.

The sequence:
1. SSH to tweed, run `poe.sh <port> 2` (off)
2. Poll `ssh_check_connectivity()` until the host is unreachable (confirms power is off)
3. Run `poe.sh <port> 1` (on)
4. Poll `ssh_check_connectivity()` until the host responds (RPi 3 PXE boot takes ~2 minutes)

No fixed sleeps — all waits use polling with bounded timeouts.

## TT FPGA Special Handling

The TT FPGA Demo Board v3 has an RP2350 microcontroller between the RPi and the iCE40 FPGA. The RPi has no direct GPIO or UART connection to the FPGA — everything goes through the RP2350 via USB.

### UART Tests (tt_test_wrapper.py)

The wrapper creates a transparent UART bridge:

1. **Upload bitstream** to RP2350 filesystem via `mpremote`. Includes `reset_rp2350()` (Ctrl-C flood to break any stuck MicroPython script) and USB power cycle retry.
2. **Program FPGA** via MicroPython raw REPL: PIO SPI programming, UART1 setup on the correct TTDBv3 GPIO pins (GPIO20=RX, GPIO37=TX), 50 MHz PWM clock start.
3. **Bridge loop**: MicroPython relays bytes between USB CDC (stdin/stdout) and UART1 hardware.
4. **PTY relay**: The wrapper creates a PTY pair. A thread copies data bidirectionally between the USB serial fd and the PTY master. The test script connects to the PTY slave, thinking it's a real serial port. Ctrl-C (0x03) is stripped from RPi→RP2350 direction to prevent killing the bridge.
5. **Test execution**: `test_uart.py --port /dev/pts/N --board tt --skip-banner`

### PMOD Tests (tt_pmod_wrapper.py)

The PMOD headers on the TT board connect directly to the RPi's PMOD HAT — no RP2350 needed for the test itself. But the FPGA must still be programmed through the RP2350.

1. **Program FPGA** via the same MicroPython flow (SPI + clock).
2. **Release RP2350 GPIOs** to high-impedance (input mode) — the RP2350 shares the same pins as the PMOD headers. Without releasing them, the RP2350's output drivers would contend with the RPi's GPIO drivers.
3. **Run test on RPi**: `test_pmod_loopback.py --board tt` uses `gpiod` to drive/read GPIOs directly through the PMOD HAT.

The empirically confirmed TTDBv3 pin mapping through the PMOD HAT:

| Signal | PMOD HAT Pin | RPi GPIO | Direction |
|--------|-------------|----------|-----------|
| ui_in[0] | JA1 | 6 | RPi drives |
| ui_in[1] | JA7 | 12 | RPi drives |
| ui_in[2] | JA8 | 16 | RPi drives |
| ui_in[3] | JB1 | 5 | RPi drives |
| ui_in[4] | JC1 | 17 | RPi drives |
| ui_in[5] | JC3 | 4 | RPi drives |
| ui_in[6] | JC4 | 14 | RPi drives |
| ui_in[7] | JC9 | 15 | RPi drives |
| uo_out[0] | JC2 | 18 | RPi reads |
| uo_out[1] | JA10 | 21 | RPi reads |
| uo_out[2] | JB8 | 8 | RPi reads |
| uo_out[3] | JA9 | 20 | RPi reads |
| uo_out[4] | JB2 | 11 | RPi reads |
| uo_out[5] | JA3 | 19 | RPi reads |
| uo_out[6] | JB4 | 10 | RPi reads |
| uo_out[7] | JB3 | 9 | RPi reads |

## Test Execution and Result Detection

The test command runs on the remote RPi via `ssh_run()` with a 180-second timeout. Both stdout and stderr are captured.

`check_test_result()` determines pass/fail by searching the last 5 lines of combined output for `RESULT: PASS` or `RESULT: FAIL`. This marker-based approach is robust against wrapper output, error messages, and other noise appearing earlier in the output. All test scripts print exactly one `RESULT:` line at the end.

Fallback: if no `RESULT:` marker is found, the script checks for plain `PASS` in the tail combined with exit code 0.

## Summary and Exit Code

After all tests complete, the script prints a summary table and exits with code 0 if all tests passed, 1 if any failed. The `--list` flag shows all generated tests without running them. Filters (`--test`, `--host`, `--board`) narrow the test set.
