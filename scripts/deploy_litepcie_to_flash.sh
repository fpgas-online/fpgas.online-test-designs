#!/bin/bash
# End-to-end deployment of the LiteX LitePCIe gateware into the Acorn's
# QSPI flash via the JTAG-loaded flash_writer SoC. Run once SSH access
# to root@tweed.welland.mithis.com is restored (need the 4096-bit RSA
# key in the agent).
#
# Steps:
#   1. Upload patched flash_writer bitstream to welland-pi4
#   2. JTAG-load it into SRAM (stays loaded — no PCIe to auto-revert)
#   3. Run native_jtagbone.py on pi4 to:
#      a. Verify the JTAGBone bridge by reading the SoC identifier CSR
#      b. Read flash JEDEC ID (should be 0x010219 for Spansion S25FL256S)
#      c. Erase sectors at flash 0x400000 (operational slot, ~2 MB)
#      d. Page-program operational.bit bytes
#      e. Read back to verify
#      f. Trigger ICAP IPROG via the icap CSR
#   4. Remove the cached PCI device on pi4, rescan, lspci
#   5. Expect: 0001:01:00.0 with vendor 0x10ee (Xilinx) — LitePCIe!
#
# Safety: this writes to flash 0x400000 (operational slot) only. The
# Sqrl factory firmware at flash 0x0 is preserved as the recovery
# golden image. If anything goes wrong, JTAG --reset reloads the
# factory image and PCIe enumerates as 1e24:021f again.

set -euo pipefail

PI4=10.21.0.104
GATEWAY=root@tweed.welland.mithis.com
BITSTREAM="${1:-/home/tim/github/fpgas-online/fpgas.online-test-designs/.worktrees/acorn-pcie-update/designs/pcie-enumeration/build/acorn-flash-writer/gateware/sqrl_acorn.bit}"
OPERATIONAL_BIT="${2:-/home/tim/github/fpgas-online/fpgas.online-test-designs/.worktrees/vivado-xilinx-flows/designs/pcie-enumeration/build/acorn-cle-215p-vivado-vivado/gateware/sqrl_acorn_operational.bit}"

if [ ! -f "$BITSTREAM" ]; then
    echo "ERROR: flash_writer bitstream not found at: $BITSTREAM" >&2
    exit 1
fi

if [ ! -f "$OPERATIONAL_BIT" ]; then
    echo "ERROR: operational LitePCIe bitstream not found at: $OPERATIONAL_BIT" >&2
    exit 1
fi

echo "=== Step 1/5: Upload patched flash_writer to welland-pi4 ==="
scp -o ConnectTimeout=10 "$BITSTREAM" "$GATEWAY:/tmp/flash_writer.bit"
ssh -o ConnectTimeout=10 "$GATEWAY" "scp -o ConnectTimeout=10 /tmp/flash_writer.bit root@$PI4:/root/flash_writer.bit"

echo "=== Step 1.5/5: Upload operational LitePCIe to welland-pi4 ==="
scp -o ConnectTimeout=10 "$OPERATIONAL_BIT" "$GATEWAY:/tmp/operational.bit"
ssh -o ConnectTimeout=10 "$GATEWAY" "scp -o ConnectTimeout=10 /tmp/operational.bit root@$PI4:/root/operational.bit"

echo "=== Step 2/5: JTAG-load flash_writer into SRAM ==="
ssh -o ConnectTimeout=10 "$GATEWAY" "ssh -o ConnectTimeout=30 root@$PI4 '
    rmmod spidev 2>&1 || true
    rmmod spi_bcm2835 2>&1 || true
    /usr/local/bin/openFPGALoader --cable libgpiod --pins 10:9:11:8 /root/flash_writer.bit 2>&1 | tail -3
'"

echo "=== Step 3/5: Write operational.bit to flash 0x400000 via JTAGBone ==="
ssh -o ConnectTimeout=10 "$GATEWAY" "ssh -o ConnectTimeout=600 root@$PI4 '
    cd /root/flash_writer_work
    python3 native_jtagbone.py --bitstream /root/operational.bit --offset 0x400000 --verify --iprog 2>&1 | tail -50
'"

echo "=== Step 4/5: Linux PCI rescan ==="
ssh -o ConnectTimeout=10 "$GATEWAY" "ssh -o ConnectTimeout=30 root@$PI4 '
    if [ -e /sys/bus/pci/devices/0001:01:00.0/remove ]; then
        echo 1 > /sys/bus/pci/devices/0001:01:00.0/remove
    fi
    sleep 2
    echo 1 > /sys/bus/pci/devices/0001:00:00.0/rescan
    sleep 3
'"

echo "=== Step 5/5: Verify LitePCIe (vendor 0x10ee) on lspci ==="
ssh -o ConnectTimeout=10 "$GATEWAY" "ssh -o ConnectTimeout=15 root@$PI4 '
    echo === lspci -Dnn ===
    lspci -Dnn | grep -iE \"0001|10ee|xilinx|sqrl|1e24\" || echo \"(no devices on 0001)\"
    echo === Vendor ID ===
    v=\$(setpci -s 0001:01:00.0 VENDOR_ID 2>/dev/null || echo MISSING)
    d=\$(setpci -s 0001:01:00.0 DEVICE_ID 2>/dev/null || echo MISSING)
    echo VENDOR=\$v DEVICE=\$d
    case \"\$v\" in
        \"10ee\") echo \"GOAL-4-SUCCESS: Xilinx LitePCIe is running. Try the BAR0 loopback next.\" ;;
        \"1e24\") echo \"FAIL: Still Sqrl factory firmware — flash write did not take effect.\" ;;
        \"ffff\"|\"FFFF\") echo \"FAIL: No device responding on PCIe.\" ;;
        \"MISSING\") echo \"FAIL: No 0001:01:00.0 device enumerated.\" ;;
        *) echo \"UNKNOWN VENDOR \$v — investigate.\" ;;
    esac
'"
