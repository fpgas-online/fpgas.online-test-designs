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

# openXC7: snap packages containing nextpnr-xilinx and Xilinx 7-Series tools.
# These are squashfs images that we extract with unsquashfs (no snap daemon needed).
# Source: https://github.com/openXC7/openXC7-snap/releases
# Note: Only x86_64 snaps are published; aarch64 must build from source.
OPENXC7_SNAP_VERSION = "0.8.2"
OPENXC7_RELEASES = {
    ("Linux", "x86_64"): f"https://github.com/openXC7/openXC7-snap/releases/download/{OPENXC7_SNAP_VERSION}/openxc7_{OPENXC7_SNAP_VERSION}_amd64.snap",
}

# OSS CAD Suite: nightly builds
# Source: https://github.com/YosysHQ/oss-cad-suite-build/releases
# URL pattern uses {tag} for the release tag (e.g. "2026-03-09") and
# {date_compact} for the filename date (e.g. "20260309", no hyphens).
OSS_CAD_SUITE_RELEASES = {
    ("Linux", "x86_64"): "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/{tag}/oss-cad-suite-linux-x64-{date_compact}.tgz",
    ("Linux", "aarch64"): "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/{tag}/oss-cad-suite-linux-arm64-{date_compact}.tgz",
    ("Darwin", "x86_64"): "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/{tag}/oss-cad-suite-darwin-x64-{date_compact}.tgz",
    ("Darwin", "arm64"): "https://github.com/YosysHQ/oss-cad-suite-build/releases/download/{tag}/oss-cad-suite-darwin-arm64-{date_compact}.tgz",
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
        raise SystemExit(1) from e

    return dest


def extract_tarball(tarball: Path, dest_dir: Path) -> Path:
    """Extract a .tar.gz or .tgz file into dest_dir."""
    print(f"  Extracting {tarball.name} to {dest_dir}...")
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(dest_dir, filter="data")
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

def get_oss_cad_suite_latest_tag() -> tuple[str, str]:
    """Query GitHub API for the latest OSS CAD Suite release tag.

    Returns (tag, date_compact) where tag is the release tag (e.g. "2026-03-09"
    or "bucket-2025-03-01") and date_compact is the date without hyphens
    (e.g. "20260309") used in filenames.
    """
    import json

    print("  Querying latest OSS CAD Suite release...")
    req = urllib.request.Request(
        OSS_CAD_SUITE_LATEST_API,
        headers={"User-Agent": "fpgas-online-test-designs"},
    )
    with urllib.request.urlopen(req) as response:
        data = json.loads(response.read())

    tag = data["tag_name"]  # e.g. "2026-03-09" or "bucket-2025-03-01"
    print(f"    Latest release tag: {tag}")

    # Extract the date portion (strip "bucket-" prefix if present)
    date_str = tag.removeprefix("bucket-")
    # Remove hyphens for the compact filename format
    date_compact = date_str.replace("-", "")

    print(f"    Date compact: {date_compact}")
    return tag, date_compact


# ---------------------------------------------------------------------------
# Toolchain installers
# ---------------------------------------------------------------------------

def install_openxc7(toolchains_dir: Path, cache_dir: Path) -> Path:
    """Download and extract the openXC7 toolchain from a snap package.

    The openXC7 project distributes nextpnr-xilinx and related tools as snap
    packages (squashfs images). We extract them with unsquashfs so no snap
    daemon is needed.
    """
    print("\n=== Installing openXC7 toolchain ===")

    system, machine = detect_platform()
    key = (system, machine)
    if key not in OPENXC7_RELEASES:
        print(f"  ERROR: No openXC7 build available for {system}/{machine}")
        if system == "Linux" and machine == "aarch64":
            print("  openXC7 snaps are only published for x86_64.")
            print("  For aarch64, build from source: https://github.com/openXC7")
        else:
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

    # Verify unsquashfs is available (needed to extract snap packages)
    if not shutil.which("unsquashfs"):
        print("  ERROR: 'unsquashfs' not found on PATH.")
        print("  Install squashfs-tools: sudo apt install squashfs-tools")
        raise SystemExit(1)

    # Download
    snap_name = url.split("/")[-1]
    snap_file = cache_dir / snap_name
    if not snap_file.exists():
        download_file(url, snap_file, "openXC7 snap package")
    else:
        print(f"  Using cached download: {snap_file}")

    # Extract snap (squashfs image) with unsquashfs
    if install_dir.exists():
        shutil.rmtree(install_dir)
    _extract_snap(snap_file, install_dir)

    # Mark as installed
    marker.write_text(url + "\n")

    # Create a flat bin/ directory with symlinks to the extracted binaries
    _create_openxc7_bin_links(install_dir)

    # Verify key binaries exist
    _verify_openxc7(install_dir)

    return install_dir


def _extract_snap(snap_file: Path, dest_dir: Path) -> None:
    """Extract a snap package (squashfs image) to a destination directory."""
    print(f"  Extracting {snap_file.name} with unsquashfs...")
    dest_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["unsquashfs", "-f", "-d", str(dest_dir / "squashfs-root"), str(snap_file)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  ERROR: unsquashfs failed (exit code {result.returncode})")
        print(f"  stderr: {result.stderr}")
        raise SystemExit(1)
    print(f"  Extracted to {dest_dir / 'squashfs-root'}")


def _create_openxc7_bin_links(install_dir: Path) -> None:
    """Create a top-level bin/ directory with symlinks to openXC7 tools.

    The snap extracts into squashfs-root/usr/bin/ (or similar). We create
    install_dir/bin/ with symlinks so the PATH setup in common.mk works.
    """
    bin_dir = install_dir / "bin"
    bin_dir.mkdir(exist_ok=True)

    # Tools we expect from the openXC7 snap
    openxc7_tools = [
        "nextpnr-xilinx", "fasm2frames", "xc7frames2bit", "bbasm", "bit2fasm",
    ]

    # Search for binaries in the extracted squashfs
    squashfs = install_dir / "squashfs-root"
    found = 0
    for tool in openxc7_tools:
        candidates = list(squashfs.rglob(tool))
        # Filter to actual executables (not directories or .d files)
        candidates = [c for c in candidates if c.is_file() and c.name == tool]
        if candidates:
            src = candidates[0]
            dest = bin_dir / tool
            if not dest.exists():
                dest.symlink_to(src.resolve())
                found += 1
                print(f"    Linked {tool} -> {src}")
        else:
            print(f"    WARNING: {tool} not found in snap")

    if found > 0:
        print(f"  Created {found} symlinks in {bin_dir}")


def _verify_openxc7(install_dir: Path) -> None:
    """Check that key openXC7 binaries are present."""
    bin_dir = install_dir / "bin"
    if bin_dir.is_dir():
        print(f"  Binaries in: {bin_dir}")
        for tool in ["nextpnr-xilinx", "fasm2frames", "xc7frames2bit"]:
            tool_path = bin_dir / tool
            if tool_path.exists():
                print(f"    ok {tool}")
            else:
                print(f"    MISSING {tool}")
    else:
        print("  WARNING: bin/ directory not created")
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
    tag, date_compact = get_oss_cad_suite_latest_tag()
    url = OSS_CAD_SUITE_RELEASES[key].format(tag=tag, date_compact=date_compact)

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

    combined_path = os.pathsep.join([*extra_paths, os.environ.get("PATH", "")])

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
