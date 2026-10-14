On a host whose root file system is in memory (a netbooted Pi with `overlayroot=tmpfs`, as the Compute Blades
at ps1 are), what you install is gone at the next boot, and so is the boot check's unit. After each boot,
install and run by hand:

```bash
# 1. The two apt repositories the packages come from.
sudo install -d -m0755 /etc/apt/keyrings
sudo curl -fsSL --remove-on-error -o /etc/apt/keyrings/apt.gpg https://apt.fpgas.online/apt.gpg
echo "deb [signed-by=/etc/apt/keyrings/apt.gpg] https://apt.fpgas.online/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/apt.list
sudo curl -fsSL --remove-on-error -o /etc/apt/keyrings/fpgas.online-fpga-tools.gpg \
  https://fpgas.online/fpgas.online-fpga-tools/fpgas.online-fpga-tools.gpg
echo "deb [signed-by=/etc/apt/keyrings/fpgas.online-fpga-tools.gpg] https://fpgas.online/fpgas.online-fpga-tools/$(. /etc/os-release; echo $VERSION_CODENAME)/ ./" \
  | sudo tee /etc/apt/sources.list.d/fpgas.online-fpga-tools.list
ls -l /etc/apt/keyrings/apt.gpg /etc/apt/keyrings/fpgas.online-fpga-tools.gpg

# 2. The Acorn's packages.
sudo apt update
sudo apt install fpgas-online-acorn

# 3. What is installed, and which board this host is set up to check.
fpgas-verify --list

# 4. The check. Nothing is sent anywhere unless a file on the host says `publish = on`; --no-publish makes sure.
sudo fpgas-acorn-verify --no-publish
```
