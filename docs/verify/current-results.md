# fpgas-verify: current results

You want to see the check's last collected results on the Welland Pis.
Every fpgas-verify page is listed in [fpgas-verify](../verify.md).

## Current results

Collected 2026-10-02T03:50:20Z from the 24 Welland Pis that answered, all running `fpgas-online-verify`
`0.0.post771`, by:

```bash
uv run --no-project python scripts/collect_verify_status.py --ssh-config ../fpgas.online-infra/ansible/ssh.cfg
```

pi-sw2-p47's row is from a later check, at 2026-10-02T03:56:17Z, once its flash held the pinned release
(`vivado-bitstreams-acorn-pcie-20261001-ge568a408e7bd`). Rerun the collector to refresh this section.

| Board | Pis | Result | Tests (passed / run) |
|---|---|---|---|
| Acorn | 2 | pass 2 | pcie-link 2/2, pcie-bar0 2/2, jtag 2/2, flash 2/2, ddr 2/2, p2-uart 2/2, p2-serial 2/2, scratch 2/2, p2-gpio 2/2 |
| Arty A7 | 4 | fail 4 | uart 4/4, ddr 4/4, spiflash 4/4, ethernet 3/4, pin-id 0/4 |
| Fomu EVT | 1 | pass 1 | uart 1/1 |
| NeTV2 | 5 | fail 5 | uart 5/5, ddr 0/5, spiflash 5/5 |
| TT FPGA | 3 | fail 3 | pin-id 0/3, uart 3/3, spiflash 0/3 |
| Unrecognised PCIe FPGA | 2 | fail 2 | - |
| (no board) | 7 | missing 7 | - |

| Host | Pi | Board | Variant | Result | Tests | Reason | Checked (UTC) | fpgas-online-verify |
|---|---|---|---|---|---|---|---|---|
| pi-sw1-p10 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:14:54Z | 0.0.post771 |
| pi-sw1-p12 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:15:49Z | 0.0.post771 |
| pi-sw1-p14 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:16:07Z | 0.0.post771 |
| pi-sw1-p16 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:16:22Z | 0.0.post771 |
| pi-sw1-p17 | Pi 3B+ | Fomu EVT | evt | pass | uart=pass |  | 2026-10-02T03:16:39Z | 0.0.post771 |
| pi-sw1-p18 | Pi 3B+ | NeTV2 | a7-35 | fail | uart=pass ddr=**fail** spiflash=pass | ddr fail: the test exited 1 | 2026-10-02T03:17:44Z | 0.0.post771 |
| pi-sw1-p38 | Pi 5B | Unrecognised PCIe FPGA | - | fail | - | PCIe Screamer (PCILeech image): fpgas.online has no test design for this board yet | 2026-10-02T03:23:02Z | 0.0.post771 |
| pi-sw2-p9 | Pi 4B | Arty A7 | a7-35 | fail | uart=pass ddr=pass spiflash=pass ethernet=pass pin-id=**fail** | pin-id fail: the test exited 1 | 2026-10-02T03:29:45Z | 0.0.post771 |
| pi-sw2-p10 | Pi 4B | Arty A7 | a7-35 | fail | uart=pass ddr=pass spiflash=pass ethernet=**fail** pin-id=**fail** | ethernet fail: the test exited 1; pin-id fail: the test exited 1 | 2026-10-02T03:30:57Z | 0.0.post771 |
| pi-sw2-p12 | Pi 4B | Arty A7 | a7-35 | fail | uart=pass ddr=pass spiflash=pass ethernet=pass pin-id=**fail** | pin-id fail: the test exited 1 | 2026-10-02T03:31:05Z | 0.0.post771 |
| pi-sw2-p15 | Pi 4B | Arty A7 | a7-35 | fail | uart=pass ddr=pass spiflash=pass ethernet=pass pin-id=**fail** | pin-id fail: the test exited 1 | 2026-10-02T03:32:22Z | 0.0.post771 |
| pi-sw2-p18 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:33:35Z | 0.0.post771 |
| pi-sw2-p19 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:34:14Z | 0.0.post771 |
| pi-sw2-p20 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:34:27Z | 0.0.post771 |
| pi-sw2-p21 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:34:12Z | 0.0.post771 |
| pi-sw2-p22 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:34:16Z | 0.0.post771 |
| pi-sw2-p23 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:35:45Z | 0.0.post771 |
| pi-sw2-p24 | Orange Pi PC | - | - | missing | - | none of the installed boards (acorn, arty, fomu, netv2, tt) was found (auto: USB/PCI IDs, then probing) | 2026-10-02T03:35:05Z | 0.0.post771 |
| pi-sw2-p33 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-10-02T03:38:29Z | 0.0.post771 |
| pi-sw2-p35 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-10-02T03:38:51Z | 0.0.post771 |
| pi-sw2-p36 | Pi 4B | TT FPGA | tt-fpga | fail | pin-id=**fail** uart=pass spiflash=**fail** | pin-id fail: the test exited 1; spiflash fail: the test exited 1 | 2026-10-02T03:38:58Z | 0.0.post771 |
| pi-sw2-p37 | Pi 5B | Unrecognised PCIe FPGA | - | fail | - | Xilinx XDMA design (likely PicoEVB): fpgas.online has no test design for this board yet | 2026-10-02T03:38:50Z | 0.0.post771 |
| pi-sw2-p47 | Pi 5B | Acorn | cle-215+ | pass | pcie-link=pass pcie-bar0=pass jtag=pass flash=pass ddr=pass p2-uart=pass p2-serial=pass scratch=pass p2-gpio=pass | (a later check) | 2026-10-02T03:56:17Z | 0.0.post771 |
| pi-sw2-p48 | Pi 5B | Acorn | cle-215+ | pass | pcie-link=pass pcie-bar0=pass jtag=pass flash=pass ddr=pass p2-uart=pass p2-serial=pass scratch=pass p2-gpio=pass |  | 2026-10-02T03:42:34Z | 0.0.post771 |

No Pi answered on 63 ports: sw1 p1-9,p11,p13,p15,p19-37,p39-40; sw2 p1-8,p11,p13-14,p16-17,p25-29,p31-32,p34,p38-46.

What the results show:

| Board | Result |
|---|---|
| Acorn | both pass all 9 tests. `ddr` on each: 1 GiB, 2 passes, 0 errors, 1327.4 MB/s write, 1350.1 MB/s read |
| Arty A7 | `pin-id` fails on all 4; `ethernet` fails on pi-sw2-p10; `uart`, `ddr` and `spiflash` pass on all 4 |
| NeTV2 | `ddr` fails on all 5; `uart` and `spiflash` pass |
| TT FPGA | `pin-id` and `spiflash` fail on all 3; `uart` passes |
| Fomu EVT | pi-sw1-p17 passes |
| Unrecognised PCIe FPGA | pi-sw1-p38 (a PCIe Screamer) and pi-sw2-p37 (an XDMA design, likely a PicoEVB): fpgas.online has no test design for them |
| (no board) | pi-sw2-p18 … p24: Orange Pi PCs with no FPGA, so `missing`. pi-sw2-p30, their FEL host, is not on the fpgas root and is not read |
