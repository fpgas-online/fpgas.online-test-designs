# SPRAM test

A test of the 128 KB of SPRAM in the TinyTapeout FPGA Demo Board's iCE40UP5K: four `SB_SPRAM256KA` of 16K × 16 bits. As the SoC uses them (`designs/_shared/up5k_spram.py`, 32 bits wide: LiteX's `Up5kSPRAM` layout, with its bank select fixed), each 32-bit word is two of them side by side, bytes 0 and 1 in one and 2 and 3 in the other, and the byte address's bit 16 chooses one of two such pairs: two banks of 64 KB. The breakout has no
flash and no DRAM, so this is its memory test, `spram` in the boot check
([#343](https://github.com/fpgas-online/fpgas.online-test-designs/issues/343)).

| | |
|---|---|
| Board | TT FPGA Demo Board (iCE40UP5K) |
| SoC | the UART test's (`designs/uart/gateware/uart_soc_tt.py`): VexRiscv `minimal` at 12 MHz, a 1 KB boot ROM in block RAM, the UART on `ui_in[3]` (RX) and `uo_out[4]` (TX), and the SPRAM as one 128 KB bus region |
| Firmware | `generate_spram_firmware` in `designs/_shared/ice40_firmware.py`, in the ROM. It keeps every value in registers: no stack and no RAM, so nothing but the test touches the SPRAM |
| Pins driven | `uo_out[4]` (the UART's TX) only, as the UART test |
| Host script | `designs/spram/host/test_spram.py`, through the RP2350's UART bridge (`tt_test_wrapper.py`) |

## What it checks

The firmware prints its banner, its ident and `SPRAM_READY`, then waits. On each byte it receives it tests
the whole SPRAM:

1. **Each word's address.** It writes to every 32-bit word a pattern that holds the word's index (bits 0 to 14,
   again in bits 15 to 29, its two low bits in 30 and 31), then reads every word back. Two addresses that reach
   one cell, such as one bank answering for the other, leave a word holding another word's index.
2. **Every bit both ways.** The same with the inverse of that pattern. Across the two passes, every bit of
   every word has held a 0 and a 1.
3. **The byte lanes.** At the start of each 64 KB bank, for each of the word's four bytes: it writes
   `0xFFFFFFFF`, stores one `0x00` byte there (`sb`), and reads the word back. Only that byte may have changed.
   Each byte is half of one SPRAM's write mask (`MASKWREN`), which is the chip's, not a word's, so the two
   words reach every mask of all four SPRAMs.

It answers with one line: `SPRAM_TEST: PASS`, or at the first word that differs
`SPRAM_TEST: FAIL at 0x<address> read 0x<word> expected 0x<word>`. Then it waits for the next byte. The host
script says how long the answer took, as the bridge delivers it: `answered N s after the byte that asked`.

The host script sends a byte and reads the answer. It sends again if the design was still starting, at most
three times, 5 seconds apart. Its last line starts `SPRAM:`, and its exit code gives the result:

| Exit | Last line | Meaning |
|---|---|---|
| 0 | `SPRAM: all 128 KB written and read back twice, each byte lane's write mask checked` | pass |
| 1 | `SPRAM: FAIL at 0x… read 0x… expected 0x…` | the SPRAM failed: the board fails, with that line as the reason |
| 2 | `SPRAM: no answer from the SPRAM test design in 15 s: nothing was tested`, or `SPRAM: could not open <port>: …` | an error: the board's result is `error` |

`tests/test_spram.py` runs the firmware on a small RV32I interpreter, against a model of the UART and the SPRAM.
A good SPRAM passes. Each of these fails at the right word: a data bit stuck at 1 or at 0, the two banks on
one address (the bank select lost), a byte store that writes the whole word, and each byte lane's write mask
stuck off or on. It also runs the host script against a fake port.

## Build

```sh
uv sync --extra build
uv run python designs/spram/gateware/spram_soc_tt.py --build
```

The bitstream is `designs/spram/build/tt-fpga-yosys-nextpnr/gateware/tt_fpga_platform.bin`.
- CI builds it with `.github/workflows/build-spram-test.yml`, as artifact `spram-test-tt-fpga`.
- It ships in `fpgas-online-tt-fpga-bitstreams` beside the other TT FPGA designs.
- Like every TT FPGA load, the RP2350 streams it from the Pi. Nothing is written to the demo board.
