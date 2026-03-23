# New Device Deployment Checklist

When deploying a new device of an **existing type** (e.g. adding another Arty A7 or LiteFury to a site), the following files need to be updated.

This checklist does NOT cover adding a new device type — that requires new gateware, CI jobs, test scripts, and documentation.

## Files to Update

### 1. Site dnsmasq configuration (on the gateway server)

**File**: `/etc/dnsmasq.d/pibs.conf` on the gateway (tweed for Welland, val2 for PS1)

Add a `dhcp-host` entry for the new RPi's MAC address with hostname, IP, and a comment describing the board type.

### 2. Site documentation

**File**: `docs/hardware/site-welland.md` or `docs/hardware/site-ps1.md`

- Add the new host to the appropriate inventory table (Arty, NeTV2, Fomu, TT FPGA, Acorn/LiteFury, etc.)
- Include: hostname, switch port, IP, RPi model, board type/serial, status

### 3. Hardware README deployment counts

**File**: `docs/hardware/README.md`

- Update the deployed/pending counts in the FPGA Boards table for the appropriate board type and site
- If a pending device is being deployed, decrement the pending count and increment the deployed count

### 4. Device-specific documentation

**File**: The board's own doc file (e.g. `acorn.md`, `fomu-evt.md`, etc.)

- If the device doc has a host inventory section, add the new host to the appropriate site table
- Update the deployment summary counts if present

### 5. Test infrastructure configuration

**File**: `verify_hardware.py`

- Add the new host to the `HOSTS` dict with the correct board type, gateway, target IP, and any variant info
- If the board type has a specific programming command, ensure `PROGRAM_COMMANDS` covers it

### 6. PoE switch configuration (physical)

On the PoE switch:
- Enable PoE on the new port if not already enabled
- Verify the RPi PXE boots and gets an IP from dnsmasq

## Verification Steps

After updating all files:

1. **PXE boot**: Verify the RPi boots via PXE/NFS from the gateway
2. **SSH access**: Confirm `ssh root@<gateway> 'ssh root@<new-host> hostname'` works
3. **FPGA detection**: Confirm the FPGA is detected (lsusb for USB devices, lspci for PCIe)
4. **Programming**: Run `openFPGALoader` (or appropriate tool) to program a test bitstream
5. **Test**: Run `verify_hardware.py --host <new-host>` to execute the full test suite
6. **Commit**: Commit all documentation changes with a message like "Add pi42 Arty A7 to Welland site"

## Example: Adding an Arty A7 at PS1

```
1. On val2: Add dhcp-host line to /etc/dnsmasq.d/pibs.conf
2. Edit docs/hardware/site-ps1.md: Add row to Arty A7 Hosts table
3. Edit docs/hardware/README.md: Increment PS1 (deployed) count for Arty A7
4. Edit verify_hardware.py: Add "ps1-piNN" to HOSTS dict
5. Power on the RPi, verify PXE boot, run verify_hardware.py
6. Commit and push
```
