#!/usr/bin/env python3
"""Download and install FPGA toolchains into the project virtual environment.

Downloads pre-built binaries for:
  - openXC7 (Yosys + nextpnr-xilinx + Project X-Ray) for Xilinx 7-Series
  - OSS CAD Suite (Yosys + nextpnr-ice40 + nextpnr-ecp5 + icestorm + trellis)
  - RISC-V GCC (riscv64-unknown-elf-gcc) for LiteX VexRiscv CPU firmware/BIOS

All toolchains are extracted into .venv/toolchains/ so they live alongside
the Python packages managed by uv.

Usage:
    uv run python scripts/setup_toolchains.py
    uv run python scripts/setup_toolchains.py --toolchain openxc7
    uv run python scripts/setup_toolchains.py --toolchain oss-cad-suite
    uv run python scripts/setup_toolchains.py --toolchain riscv-gcc
    uv run python scripts/setup_toolchains.py --venv-dir .venv
"""

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Toolchain release URLs and metadata
# ---------------------------------------------------------------------------

# openXC7: nightly builds from the toolchain-nix repo
# Source: https://github.com/openXC7/toolchain-nix/releases
OPENXC7_RELEASES = {
    ("Linux", "x86_64"): "https://github.com/openXC7/toolchain-nix/releases/latest/download/openXC7-toolchain-linux-x64.tar.gz",
    ("Linux", "aarch64"): "https://github.com/openXC7/toolchain-nix/releases/latest/download/openXC7-toolchain-linux-arm64.tar.gz",
}

# OSS CAD Suite: nightly builds
# Source: https://github.com/YosysHQ/oss-cad-suite-build/releases
OSS_CAD_SUITE_RELEASES = {
    ("Linux", "x86_64"): "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/bucket-{date}/oss-cad-suite-linux-x64-{date}.tgz",
    ("Linux", "aarch64"): "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/bucket-{date}/oss-cad-suite-linux-arm64-{date}.tgz",
    ("Darwin", "x86_64"): "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/bucket-{date}/oss-cad-suite-darwin-x64-{date}.tgz",
    ("Darwin", "arm64"): "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/bucket-{date}/oss-cad-suite-darwin-arm64-{date}.tgz",
}

# Fallback: use GitHub API to find the latest OSS CAD Suite release date
OSS_CAD_SUITE_LATEST_API = "https://api.github.com/repos/YosysHQ/oss-cad-suite-build/releases/latest"

# RISC-V GCC: pre-built cross-compiler for VexRiscv firmware/BIOS
# LiteX requires riscv64-unknown-elf-gcc (or riscv-none-elf-gcc) to compile
# the BIOS and any custom C firmware that runs on the soft CPU.
# Source: https://github.com/sifive/freedom-tools/releases (SiFive)
# Alternative: https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases
RISCV_GCC_RELEASES = {
    ("Linux", "x86_64"): "https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v14.2.0-3/xpack-riscv-none-elf-gcc-14.2.0-3-linux-x64.tar.gz",
    ("Linux", "aarch64"): "https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v14.2.0-3/xpack-riscv-none-elf-gcc-14.2.0-3-linux-arm64.tar.gz",
    ("Darwin", "x86_64"): "https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v14.2.0-3/xpack-riscv-none-elf-gcc-14.2.0-3-darwin-x64.tar.gz",
    ("Darwin", "aarch64"): "https://github.com/xpack-dev-tools/riscv-none-elf-gcc-xpack/releases/download/v14.2.0-3/xpack-riscv-none-elf-gcc-14.2.0-3-darwin-arm64.tar.gz",
}

# The xpack RISC-V GCC uses "riscv-none-elf-" prefix. LiteX expects
# "riscv64-unknown-elf-" or "riscv-none-elf-" — both work since LiteX
# searches for multiple prefixes via its CrossCompiler class.


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def detect_platform() -> tuple[str, str]:
    """Return (system, machine) normalized for toolchain URLs."""
    system = platform.system()  # "Linux", "Darwin", "Windows"
    machine = platform.machine()  # "x86_64", "aarch64", "arm64", etc.

    # Normalize ARM variants
    if machine in ("arm64", "aarch64"):
        machine = "aarch64"

    return system, machine


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def download_file(url: str, dest: Path, description: str = "") -> Path:
    """Download a file from URL to dest with progress reporting."""
    desc = description or url.split("/")[-1]
    print(f"  Downloading {desc}...")
    print(f"    URL: {url}")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "fpgas-online-test-designs"})
        with urllib.request.urlopen(req) as response:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1 MB

            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total > 0:
                        pct = downloaded * 100 // total
                        mb_down = downloaded // (1024 * 1024)
                        mb_total = total // (1024 * 1024)
                        print(f"    {mb_down}/{mb_total} MB ({pct}%)", end="\r")

            if total > 0:
                print(f"    {total // (1024 * 1024)} MB downloaded")
            else:
                print(f"    {downloaded // (1024 * 1024)} MB downloaded")

    except urllib.error.HTTPError as e:
        print(f"    ERROR: HTTP {e.code} — {e.reason}")
        print(f"    URL: {url}")
        raise SystemExit(1)

    return dest


def extract_tarball(tarball: Path, dest_dir: Path) -> Path:
    """Extract a .tar.gz or .tgz file into dest_dir."""
    print(f"  Extracting {tarball.name} to {dest_dir}...")
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(dest_dir)
    return dest_dir


def extract_zip(zippath: Path, dest_dir: Path) -> Path:
    """Extract a .zip file into dest_dir."""
    print(f"  Extracting {zippath.name} to {dest_dir}...")
    dest_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zippath) as zf:
        zf.extractall(dest_dir)
    return dest_dir


# ---------------------------------------------------------------------------
# OSS CAD Suite: resolve latest release date
# ---------------------------------------------------------------------------

def get_oss_cad_suite_latest_date() -> str:
    """Query GitHub API for the latest OSS CAD Suite release tag.

    Returns the date string (e.g., '2025-03-01') from the tag 'bucket-YYYY-MM-DD'.
    """
    import json

    print("  Querying latest OSS CAD Suite release...")
    req = urllib.request.Request(
        OSS_CAD_SUITE_LATEST_API,
        headers={"User-Agent": "fpgas-online-test-designs"},
    )
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())

    tag = data["tag_name"]  # e.g. "bucket-2025-03-01"
    if not tag.startswith("bucket-"):
        print(f"    WARNING: Unexpected tag format: {tag}")
        return tag

    date = tag.removeprefix("bucket-")
    print(f"    Latest release: {date}")
    return date


# ---------------------------------------------------------------------------
# Toolchain installers
# ---------------------------------------------------------------------------

def install_openxc7(toolchains_dir: Path, cache_dir: Path) -> Path:
    """Download and extract the openXC7 toolchain."""
    print("\n=== Installing openXC7 toolchain ===")

    system, machine = detect_platform()
    key = (system, machine)
    if key not in OPENXC7_RELEASES:
        print(f"  ERROR: No openXC7 build available for {system}/{machine}")
        print(f"  Available platforms: {list(OPENXC7_RELEASES.keys())}")
        raise SystemExit(1)

    url = OPENXC7_RELEASES[key]
    install_dir = toolchains_dir / "openxc7"

    # Check if already installed
    marker = install_dir / ".installed"
    if marker.exists():
        print(f"  Already installed at {install_dir}")
        print(f"  (delete {marker} to force reinstall)")
        return install_dir

    # Download
    tarball_name = url.split("/")[-1]
    tarball = cache_dir / tarball_name
    if not tarball.exists():
        download_file(url, tarball, "openXC7 toolchain")
    else:
        print(f"  Using cached download: {tarball}")

    # Extract
    if install_dir.exists():
        shutil.rmtree(install_dir)
    extract_tarball(tarball, install_dir)

    # Mark as installed
    marker.write_text(url + "\n")

    # Verify key binaries exist
    _verify_openxc7(install_dir)

    return install_dir


def _verify_openxc7(install_dir: Path) -> None:
    """Check that key openXC7 binaries are present."""
    # The tarball may extract with a top-level directory; find the bin dir
    bin_candidates = list(install_dir.rglob("bin/yosys"))
    if bin_candidates:
        bin_dir = bin_candidates[0].parent
        print(f"  Binaries found in: {bin_dir}")
        for tool in ["yosys", "nextpnr-xilinx"]:
            tool_path = bin_dir / tool
            if tool_path.exists():
                print(f"    ✓ {tool}")
            else:
                print(f"    ✗ {tool} (not found)")
    else:
        print("  WARNING: Could not find yosys binary in extracted files")
        print("  Contents of install dir:")
        for p in sorted(install_dir.iterdir()):
            print(f"    {p.name}")


def install_oss_cad_suite(toolchains_dir: Path, cache_dir: Path) -> Path:
    """Download and extract the OSS CAD Suite toolchain."""
    print("\n=== Installing OSS CAD Suite ===")

    system, machine = detect_platform()
    key = (system, machine)
    if key not in OSS_CAD_SUITE_RELEASES:
        print(f"  ERROR: No OSS CAD Suite build available for {system}/{machine}")
        print(f"  Available platforms: {list(OSS_CAD_SUITE_RELEASES.keys())}")
        raise SystemExit(1)

    install_dir = toolchains_dir / "oss-cad-suite"

    # Check if already installed
    marker = install_dir / ".installed"
    if marker.exists():
        print(f"  Already installed at {install_dir}")
        print(f"  (delete {marker} to force reinstall)")
        return install_dir

    # Get latest release date
    date = get_oss_cad_suite_latest_date()
    url = OSS_CAD_SUITE_RELEASES[key].format(date=date)

    # Download
    tarball_name = url.split("/")[-1]
    tarball = cache_dir / tarball_name
    if not tarball.exists():
        download_file(url, tarball, "OSS CAD Suite")
    else:
        print(f"  Using cached download: {tarball}")

    # Extract
    if install_dir.exists():
        shutil.rmtree(install_dir)
    extract_tarball(tarball, install_dir)

    # Mark as installed
    marker.write_text(url + "\n")

    # Verify key binaries exist
    _verify_oss_cad_suite(install_dir)

    return install_dir


def _verify_oss_cad_suite(install_dir: Path) -> None:
    """Check that key OSS CAD Suite binaries are present."""
    bin_candidates = list(install_dir.rglob("bin/yosys"))
    if bin_candidates:
        bin_dir = bin_candidates[0].parent
        print(f"  Binaries found in: {bin_dir}")
        for tool in ["yosys", "nextpnr-ice40", "nextpnr-ecp5", "icepack", "ecppack",
                      "openFPGALoader"]:
            tool_path = bin_dir / tool
            if tool_path.exists():
                print(f"    ✓ {tool}")
            else:
                print(f"    ✗ {tool} (not found)")
    else:
        print("  WARNING: Could not find yosys binary in extracted files")
        print("  Contents of install dir:")
        for p in sorted(install_dir.iterdir()):
            print(f"    {p.name}")


# ---------------------------------------------------------------------------
# RISC-V GCC: cross-compiler for LiteX VexRiscv BIOS/firmware
# ---------------------------------------------------------------------------

def install_riscv_gcc(toolchains_dir: Path, cache_dir: Path) -> Path:
    """Download and extract the RISC-V GCC cross-compiler."""
    print("\n=== Installing RISC-V GCC cross-compiler ===")

    system, machine = detect_platform()
    key = (system, machine)
    if key not in RISCV_GCC_RELEASES:
        print(f"  ERROR: No RISC-V GCC build available for {system}/{machine}")
        print(f"  Available platforms: {list(RISCV_GCC_RELEASES.keys())}")
        raise SystemExit(1)

    url = RISCV_GCC_RELEASES[key]
    install_dir = toolchains_dir / "riscv-gcc"

    # Check if already installed
    marker = install_dir / ".installed"
    if marker.exists():
        print(f"  Already installed at {install_dir}")
        print(f"  (delete {marker} to force reinstall)")
        return install_dir

    # Download
    tarball_name = url.split("/")[-1]
    tarball = cache_dir / tarball_name
    if not tarball.exists():
        download_file(url, tarball, "RISC-V GCC cross-compiler")
    else:
        print(f"  Using cached download: {tarball}")

    # Extract
    if install_dir.exists():
        shutil.rmtree(install_dir)
    extract_tarball(tarball, install_dir)

    # Mark as installed
    marker.write_text(url + "\n")

    # Verify and create compatibility symlinks
    _verify_riscv_gcc(install_dir)

    return install_dir


def _verify_riscv_gcc(install_dir: Path) -> None:
    """Check that RISC-V GCC binaries are present and create symlinks if needed."""
    # Find the bin directory (xpack extracts with a version-named subdirectory)
    bin_candidates = list(install_dir.rglob("bin/riscv-none-elf-gcc"))
    if not bin_candidates:
        bin_candidates = list(install_dir.rglob("bin/riscv64-unknown-elf-gcc"))

    if bin_candidates:
        bin_dir = bin_candidates[0].parent
        print(f"  Binaries found in: {bin_dir}")

        # Check for key tools
        for tool_suffix in ["gcc", "ld", "objcopy", "objdump", "ar", "as"]:
            found = False
            for prefix in ["riscv-none-elf-", "riscv64-unknown-elf-"]:
                tool_path = bin_dir / f"{prefix}{tool_suffix}"
                if tool_path.exists():
                    print(f"    ok {prefix}{tool_suffix}")
                    found = True
                    break
            if not found:
                print(f"    MISSING {tool_suffix}")

        # Create riscv64-unknown-elf-* symlinks if only riscv-none-elf-* exists.
        # LiteX searches for both prefixes, but some older LiteX versions only
        # look for riscv64-unknown-elf-*. Symlinks ensure compatibility.
        _create_riscv_symlinks(bin_dir)

    else:
        print("  WARNING: Could not find RISC-V GCC binary in extracted files")
        print("  Contents of install dir:")
        for p in sorted(install_dir.iterdir()):
            print(f"    {p.name}")


def _create_riscv_symlinks(bin_dir: Path) -> None:
    """Create riscv64-unknown-elf-* symlinks pointing to riscv-none-elf-* if needed."""
    created = 0
    for src in bin_dir.glob("riscv-none-elf-*"):
        # Map riscv-none-elf-gcc -> riscv64-unknown-elf-gcc
        dest_name = src.name.replace("riscv-none-elf-", "riscv64-unknown-elf-")
        dest = bin_dir / dest_name
        if not dest.exists():
            dest.symlink_to(src.name)
            created += 1

    if created > 0:
        print(f"  Created {created} riscv64-unknown-elf-* compatibility symlinks")


def check_riscv_gcc_available() -> bool:
    """Check if a RISC-V GCC cross-compiler is already on PATH."""
    for prefix in ["riscv64-unknown-elf-gcc", "riscv-none-elf-gcc",
                    "riscv64-elf-gcc", "riscv32-unknown-elf-gcc"]:
        if shutil.which(prefix):
            return True
    return False


# ---------------------------------------------------------------------------
# Activation script generation
# ---------------------------------------------------------------------------

def write_activate_script(venv_dir: Path, toolchains_dir: Path) -> None:
    """Write a shell script that adds toolchain bins to PATH.

    Source this after activating the Python venv:
        source .venv/bin/activate
        source .venv/toolchains/activate-toolchains.sh
    Or use the combined activation:
        source .venv/activate-all.sh
    """
    # Find all bin directories in toolchains
    bin_dirs = []
    for toolchain in sorted(toolchains_dir.iterdir()):
        if not toolchain.is_dir():
            continue
        # Look for bin/ directory (may be nested one level)
        for candidate in [toolchain / "bin", *toolchain.glob("*/bin")]:
            if candidate.is_dir():
                bin_dirs.append(candidate)
                break

    # Write toolchain activation script
    activate_tc = toolchains_dir / "activate-toolchains.sh"
    lines = [
        "# Auto-generated by scripts/setup_toolchains.py",
        "# Source this to add FPGA toolchains to PATH",
        "",
    ]
    for bin_dir in bin_dirs:
        lines.append(f'export PATH="{bin_dir}:$PATH"')
    lines.append("")
    activate_tc.write_text("\n".join(lines))
    print(f"\n  Wrote {activate_tc}")

    # Write combined activation script
    activate_all = venv_dir / "activate-all.sh"
    lines = [
        "# Auto-generated by scripts/setup_toolchains.py",
        "# Source this to activate Python venv + FPGA toolchains",
        "",
        f'source "{venv_dir / "bin" / "activate"}"',
        f'source "{activate_tc}"',
        "",
    ]
    activate_all.write_text("\n".join(lines))
    print(f"  Wrote {activate_all}")


# ---------------------------------------------------------------------------
# Final verification
# ---------------------------------------------------------------------------

def _verify_all_tools(toolchains_dir: Path) -> None:
    """Verify all required tools are accessible after installation."""
    # Build a PATH that includes all toolchain bin directories
    extra_paths = []
    for toolchain in sorted(toolchains_dir.iterdir()):
        if not toolchain.is_dir():
            continue
        for candidate in [toolchain / "bin", *toolchain.glob("*/bin")]:
            if candidate.is_dir():
                extra_paths.append(str(candidate))
                break

    combined_path = os.pathsep.join(extra_paths + [os.environ.get("PATH", "")])

    required_tools = [
        # RISC-V GCC (needed for LiteX BIOS and firmware compilation)
        ("riscv64-unknown-elf-gcc", "RISC-V GCC", True),
        ("riscv64-unknown-elf-ld", "RISC-V linker", True),
        ("riscv64-unknown-elf-objcopy", "RISC-V objcopy", True),
        # FPGA synthesis (at least one yosys should be present)
        ("yosys", "Yosys synthesis", True),
        # Xilinx 7-Series (optional — only needed for Arty/NeTV2)
        ("nextpnr-xilinx", "nextpnr-xilinx (openXC7)", False),
        # iCE40 (optional — only needed for Fomu/TT FPGA)
        ("nextpnr-ice40", "nextpnr-ice40", False),
        # ECP5 (optional — only needed for ULX3S/ButterStick)
        ("nextpnr-ecp5", "nextpnr-ecp5", False),
        # Programming tools
        ("openFPGALoader", "openFPGALoader", False),
    ]

    all_ok = True
    for tool_name, description, required in required_tools:
        found = shutil.which(tool_name, path=combined_path)
        if found:
            print(f"  ok  {description}: {found}")
        elif required:
            print(f"  FAIL {description}: {tool_name} not found")
            all_ok = False
        else:
            print(f"  --  {description}: {tool_name} not found (optional)")

    if not all_ok:
        print("\n  WARNING: Some required tools are missing.")
        print("  LiteX builds may fail without a RISC-V cross-compiler.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and install FPGA toolchains into the project venv",
    )
    parser.add_argument(
        "--venv-dir",
        type=Path,
        default=Path(".venv"),
        help="Path to the virtual environment directory (default: .venv)",
    )
    parser.add_argument(
        "--toolchain",
        choices=["openxc7", "oss-cad-suite", "riscv-gcc", "all"],
        default="all",
        help="Which toolchain to install (default: all)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Directory for downloaded archives (default: <venv-dir>/toolchains/.cache)",
    )
    args = parser.parse_args()

    venv_dir = args.venv_dir.resolve()
    toolchains_dir = venv_dir / "toolchains"
    cache_dir = (args.cache_dir or toolchains_dir / ".cache").resolve()

    system, machine = detect_platform()
    print(f"Platform: {system}/{machine}")
    print(f"Venv:     {venv_dir}")
    print(f"Toolchains: {toolchains_dir}")
    print(f"Cache:    {cache_dir}")

    if not venv_dir.exists():
        print(f"\nERROR: Venv directory does not exist: {venv_dir}")
        print("Run 'uv venv' first, or specify --venv-dir")
        return 1

    cache_dir.mkdir(parents=True, exist_ok=True)

    if args.toolchain in ("riscv-gcc", "all"):
        install_riscv_gcc(toolchains_dir, cache_dir)

    if args.toolchain in ("openxc7", "all"):
        install_openxc7(toolchains_dir, cache_dir)

    if args.toolchain in ("oss-cad-suite", "all"):
        install_oss_cad_suite(toolchains_dir, cache_dir)

    write_activate_script(venv_dir, toolchains_dir)

    # Final verification: check RISC-V GCC is reachable
    print("\n=== Verification ===")
    _verify_all_tools(toolchains_dir)

    print("\n=== Setup complete ===")
    print(f"Activate with:  source {venv_dir / 'activate-all.sh'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
