On a host whose root file system is in memory (a netbooted Pi with `overlayroot=tmpfs`, as the Compute Blades
at ps1 are), what you install is gone at the next boot, and so is the boot check's unit. After each boot,
install and run by hand:

```bash
# 1. The two apt repositories the packages come from.
sudo install -d -m0755 /etc/apt/keyrings
curl -fsSL https://apt.fpgas.online/apt.gpg | sudo tee /etc/apt/keyrings/apt.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list
curl -fsSL https://fpgas.online/fpgas.online-fpga-tools/fpgas.online-fpga-tools.gpg \
  | sudo tee /etc/apt/keyrings/fpgas.online-fpga-tools.gpg > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/fpgas.online-fpga-tools.gpg] https://fpgas.online/fpgas.online-fpga-tools/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/fpgas.online-fpga-tools.list

# 2. The Acorn's packages.
sudo apt update
sudo apt install fpgas-online-acorn

# 3. What is installed, and which board this host is set up to check.
fpgas-verify --list

# 4. The check. Nothing is sent anywhere unless a file on the host says `publish = on`; --no-publish makes sure.
sudo fpgas-acorn-verify --no-publish
```

* The check never writes the card's flash and never loads a design into the FPGA. It does drive the P1 and P2
  wires, which is how it tests them, and puts the Pi's pins back as it found them; on a converted card it
  writes the design's scratch register and puts the old value back (with the opt-in power-cycle check on, it
  leaves a marker there); and it records what it found on this host
  (`/var/lib/fpgas-online/verify-state.json`).
* It exits 0 only for a pass. The summary is on the terminal; the same as JSON is in
  `/run/fpgas-online/verify.json`.
* To keep the packages across boots, they have to go into the image the host boots from; that is the host
  owner's root image, not something these packages do.
* The check needs no bitstream file of yours. The images it compares the card's flash with, and the design
  that converts a card, are installed with it by `fpgas-online-acorn-bitstreams`, in
  `/usr/share/fpgas-online/acorn-pcie/images/` (for a CLE-101: `acorn-cle-101-sqrl_acorn.bit` and the two
  flash images, [converting a card](hardware/acorn-pcie-programming.md)). No package installs a pin-id or
  loopback design for the Acorn; the check does not use one.

