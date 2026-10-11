#!/usr/bin/env python3
"""Install each board's packages as the how-tos say, from the published repositories, with no Pi (#307).

The install how-tos (docs/verify/installing.md, and each "Installing the <Board> Packages" section in
docs/hardware/) are tested elsewhere only in x86 Debian containers against a repository built in the job. This
runs their own commands, taken from the pages, against the published indexes, as each of 64-bit and 32-bit
Raspberry Pi OS sees them:

  rpios64  Debian arm64 (deb.debian.org) with archive.raspberrypi.com: 64-bit Raspberry Pi OS.
  rpios32  Raspbian armhf (raspbian.raspberrypi.com) with archive.raspberrypi.com: 32-bit Raspberry Pi OS.
           It trusts no Debian archive key, as the image does not (raspbian-archive-keyring holds only
           Raspbian's), so a Debian source the pages add must name its own key.

It runs inside a throwaway Debian container of the same release, as root, with apt set to the target's
architecture and an empty package status. Every `apt install` is a simulation (APT::Get::Simulate): nothing is
installed, and the packages it would install are read from apt's `Inst` lines. It fails on:

  - a page command that fails (a key that does not download, a source line that does not write);
  - an `apt update` that reports any error or warning (a source that is not signed by the key the page names,
    a suite that does not exist);
  - an `apt install` that does not resolve (an unmet dependency);
  - a package from a repository a page adds that does not download, or does not match its index;
  - a board's install that pulls in another board's packages or tools, or its own debug package unasked;
  - a board that gets Debian's openFPGALoader where the page has added fpgas.online's;
  - a page command this check does not know, a second install section, or a command that names a release in a
    step not limited to that release.

Not covered, and why: the status is empty, so a conflict with a package already on a Pi is not seen (the
virtual run of #266 modelled a base system; install_test.sh installs the built packages in a real container);
which packages each board's tools must bring is install_test.sh's (it reads the packages this commit builds).

The commands are the pages' own, run as written (with `sudo` as a no-op, since the container runs as root). The
pages' setup steps (installing.md's steps up to its first install) run once; installing.md's own install steps
and each board's install steps then run from that state. A step whose lead says "On <release> only" runs on that
release only. Every command must be one this check knows; a board's install steps end at its first command that
needs the board (`sudo fpgas-...`), and only such commands may follow it.

  docker run --rm -v "$PWD:/src:ro" debian:bookworm sh /src/packaging/debs/howto_install_container.sh rpios32

It refuses to run outside a container: it replaces /etc/apt's sources and /etc/os-release.
"""

import argparse
import dataclasses
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.parse

REPO = pathlib.Path(__file__).resolve().parents[2]
INSTALLING = "docs/verify/installing.md"
HARDWARE = "docs/hardware"

# The base archives of each system, as the images have them. Each is signed by the key its image's keyring
# package holds: the key is taken from that package, for the release (trixie's apt refuses a key whose binding
# signatures are SHA-1, and the keyring packages carry the keys re-signed), and its fingerprint is checked. The
# pages' own sources are what is tested, not these.
DEBIAN_KEYRING = "/usr/share/keyrings/debian-archive-keyring.gpg"  # from the container's debian-archive-keyring


@dataclasses.dataclass(frozen=True)
class Keyring:
    archive: str  # the archive's base URL
    package: str  # the keyring package the image installs
    path: str  # the keyring file in it
    fingerprint: str  # the primary key it must hold


RPI_KEYRING = Keyring(
    "http://archive.raspberrypi.com/debian",
    "raspberrypi-archive-keyring",
    "usr/share/keyrings/raspberrypi-archive-keyring.gpg",
    "CF8A1AF502A2AA2D763BAE7E82B129927FA3303E",
)
RASPBIAN_KEYRING = Keyring(
    "http://raspbian.raspberrypi.com/raspbian",
    "raspbian-archive-keyring",
    "usr/share/keyrings/raspbian-archive-keyring.gpg",
    "A0DA38D0D76E8B5D638872819165938D90FDDD2E",
)
BASE_KEYS = "/etc/apt/base-keys"


@dataclasses.dataclass(frozen=True)
class System:
    name: str
    arch: str
    os_id: str  # /etc/os-release ID: debian on 64-bit Raspberry Pi OS, raspbian on 32-bit
    sources: tuple  # (line with {suite}, ...)
    trusts_debian: bool  # whether apt's own trust store holds Debian's archive keys


SYSTEMS = {
    "rpios64": System(
        "rpios64",
        "arm64",
        "debian",
        (
            f"deb [signed-by={DEBIAN_KEYRING}] http://deb.debian.org/debian {{suite}} main contrib non-free "
            "non-free-firmware",
            f"deb [signed-by={DEBIAN_KEYRING}] http://deb.debian.org/debian {{suite}}-updates main contrib non-free "
            "non-free-firmware",
            f"deb [signed-by={DEBIAN_KEYRING}] http://deb.debian.org/debian-security {{suite}}-security main contrib "
            "non-free non-free-firmware",
            f"deb [signed-by={BASE_KEYS}/raspberrypi.gpg] http://archive.raspberrypi.com/debian {{suite}} main",
        ),
        True,
    ),
    "rpios32": System(
        "rpios32",
        "armhf",
        "raspbian",
        (
            f"deb [signed-by={BASE_KEYS}/raspbian.gpg] http://raspbian.raspberrypi.com/raspbian {{suite}} main "
            "contrib non-free rpi",
            f"deb [signed-by={BASE_KEYS}/raspberrypi.gpg] http://archive.raspberrypi.com/debian {{suite}} main",
        ),
        False,
    ),
}

# Tools only one board's package brings: another board's install must not pull them in.
TOOL_OF = {"openocd": "netv2", "micropython-mpremote": "tt-fpga"}
# Tools a board must not pull in although other boards use them (packaging/debs/install_test.sh says the same).
NOT_FOR = {"acorn": {"python3-libgpiod"}}
# Packages no board's install may pull in unless its page names them (install_test.sh says the same).
NEVER = {"sudo"}
# The releases a page might name in a command; such a command must sit in a step limited to that release.
RELEASES = ("bookworm", "trixie", "forky")
# The boards that load the FPGA with openFPGALoader: their install must bring one.
OPENFPGALOADER = {"openfpgaloader-fpgasonline", "openfpgaloader-fpgasonline-git", "openfpgaloader"}


# -- reading the pages --------------------------------------------------------------------------------------------


@dataclasses.dataclass
class Step:
    page: str
    number: int | None
    lead: str  # the paragraph that introduces the code block
    code: str


def section(text, heading):
    """The lines of the `## ...` section whose heading starts with `heading`, up to the next `## ` heading."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("## ") and line[3:].startswith(heading)]
    if len(starts) != 1:
        raise ValueError(f"expected one section '## {heading}...', found {len(starts)}")
    out = []
    for line in lines[starts[0] + 1 :]:
        if line.startswith("## "):
            break
        out.append(line)
    return out


def steps(page, lines):
    """The bash blocks of a section, each with the numbered step (`**N.**`) and paragraph it follows."""
    out, lead, number, block = [], [], None, None
    for line in lines:
        if block is not None:
            if line.startswith("```"):
                out.append(Step(page, number, " ".join(lead), "\n".join(block)))
                block = None  # the step's lead stays: a second block in the same step is under it too
            else:
                block.append(line)
            continue
        if line.startswith("~~~"):
            raise ValueError(f"{page}: a ~~~ code block, which this check does not read: {line!r}")
        if line.startswith("```"):
            if line.strip() != "```bash":
                raise ValueError(f"{page}: a code block that is not bash: {line!r}")
            block = []
            continue
        m = re.match(r"\*\*(\d+)\.\*\*\s*(.*)", line)
        if m:
            number, lead = int(m.group(1)), [m.group(2)]
        elif line.startswith("#"):
            number, lead = None, []
        elif line.strip():
            lead.append(line.strip())
    if block is not None:
        raise ValueError(f"{page}: a code block that is not closed")
    return out


def commands(code):
    """The block's commands: continuation lines joined, comments and blank lines dropped, and a trailing comment
    after a command removed only where it is plainly one (`  # ...` after the command)."""
    out, current = [], ""
    for line in code.splitlines():
        stripped = line.strip()
        if not current and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            current += stripped[:-1].rstrip() + " "
            continue
        current += stripped
        out.append(re.sub(r"\s{2,}#.*$", "", current))
        current = ""
    if current:
        raise ValueError(f"a command ends in a continuation: {current!r}")
    return out


KINDS = (
    ("mkdir", re.compile(r"^sudo install -d -m0755 /etc/apt/keyrings$")),
    ("key", re.compile(r"^curl -fsSL \S+ \| sudo tee /etc/apt/keyrings/[\w.-]+ > /dev/null$")),
    (
        "source",
        re.compile(
            r'^echo "deb \[signed-by=/etc/apt/keyrings/[\w.-]+\] .*"'
            r" \| sudo tee /etc/apt/sources\.list\.d/[\w.-]+\.list$"
        ),
    ),
    ("update", re.compile(r"^sudo apt update$")),
    ("install", re.compile(r"^sudo apt install( -t [\w-]+)? [\w.+-]+( [\w.+-]+)*$")),
    ("board", re.compile(r"^(sudo )?fpgas-[\w-]+( .*)?$")),  # needs the board: the install steps end here
)


def kind(command):
    """What a page command does, or None for one this check does not know."""
    for name, pattern in KINDS:
        if pattern.match(command):
            return name
    return None


def only_on(lead):
    """The release a step is limited to ("On bookworm only, ..."), or None."""
    m = re.match(r"On (\w+) only\b", lead)
    return m.group(1) if m else None


def install_plan(page, step_list, suite):
    """The commands of the install steps that apply on `suite`, in order, up to the first command that needs the
    board. Refuses, so that no step is passed over unseen: a command this check does not know (a source line with
    no signed-by=, an apt-get, anything new); anything but a board command after a board command; and a command
    that names a release in a step not limited to it."""
    plan, board = [], None
    for step in step_list:
        release = only_on(step.lead)
        for command in commands(step.code):
            k = kind(command)
            if k is None:
                raise ValueError(f"{page} step {step.number}: {command!r} is a command this check does not know")
            if board:
                if k != "board":
                    raise ValueError(f"{page} step {step.number}: {command!r} after {board!r}, which needs the board")
                continue
            if k == "board":
                board = command
                continue
            named = set(re.findall(r"\b(" + "|".join(RELEASES) + r")\b", command))
            if named and named != {release}:
                raise ValueError(
                    f"{page} step {step.number}: {command!r} names {sorted(named)}, but the step is not limited "
                    "to that release (its lead does not start 'On <release> only')"
                )
            if release is None or release == suite:
                plan.append((step.number, k, command))
    return plan


def installing_plan(suite):
    """installing.md's commands, split at its first install: the setup (the repositories every board needs, and
    apt update), and its own install steps (one board's package, then its debug package)."""
    text = (REPO / INSTALLING).read_text()
    plan = install_plan(INSTALLING, steps(INSTALLING, section(text, "Installing")), suite)
    first = next((i for i, (_n, k, _c) in enumerate(plan) if k == "install"), len(plan))
    return plan[:first], plan[first:]


def setup_plan(suite):
    return installing_plan(suite)[0]


INSTALL_SECTION = re.compile(r"^## (Installing the .+)$", re.M)  # any such heading counts: two are refused


def install_section(page):
    """The page's one install section, as lines; a second one is refused, since only one would be read."""
    text = (REPO / page).read_text()
    headings = INSTALL_SECTION.findall(text)
    if len(headings) != 1:
        raise ValueError(f"{page}: expected one '## Installing the ... Packages' section, found {headings}")
    return section(text, headings[0])


def boards():
    """board -> (page, the board's metapackage), for every hardware page with an install section."""
    out = {}
    for path in sorted((REPO / HARDWARE).glob("*.md")):
        if not INSTALL_SECTION.search(path.read_text()):
            continue
        page = str(path.relative_to(REPO))
        installs = re.findall(r"^sudo apt install (fpgas-online-[\w-]+)$", "\n".join(install_section(page)), re.M)
        if len(installs) != 1:
            raise ValueError(f"{page}: expected one 'sudo apt install fpgas-online-<board>' line, found {installs}")
        out[installs[0].removeprefix("fpgas-online-")] = (page, installs[0])
    return out


def board_plan(page, suite):
    return install_plan(page, steps(page, install_section(page)), suite)


def named(plan):
    """The packages a plan's install commands name (`-t <release>` aside): what its page asks for."""
    out = set()
    for _n, k, command in plan:
        if k == "install":
            out |= set(re.sub(r" -t [\w-]+", "", command).split()[3:])
    return out


# -- judging what apt says ----------------------------------------------------------------------------------------


def update_problems(output):
    """The lines of `apt update` output that are an error or a warning, each with the indented lines that follow it
    (apt gives the reason there: "  Sub-process /usr/bin/sqv returned an error code ...")."""
    out = []
    for line in output.splitlines():
        if re.match(r"^(W|E|Err|Warning|Error):", line):  # apt 2 and apt 3 (trixie) wording
            out.append(line)
        elif out and line.startswith(" ") and out[-1] is not None:
            out[-1] += " " + line.strip()
        else:
            out.append(None)  # a line that is neither: what follows it is not a reason
    return [line for line in out if line is not None]


def install_problems(output):
    """What apt says is wrong with an install: its errors (`E:`, apt 3's `Error:`) and the unmet dependencies."""
    return [line.strip() for line in output.splitlines() if line.startswith(("E:", "Error:")) or " : Depends: " in line]


def installed(output):
    """The packages an `apt install` simulation would install (its `Inst` lines)."""
    return [m.group(1) for m in re.finditer(r"^Inst (\S+) ", output, re.M)]


def foreign(board, packages, all_boards, asked=()):
    """The packages of `packages` that belong to another board, or that `board` must not pull in. A page may ask
    (`asked`) for its board's own debug package, or for one of `NEVER`; not for another board's package or tool."""
    out = []
    for p in packages:
        own = p == f"fpgas-online-{board}" or p.startswith(f"fpgas-online-{board}-")
        if p in asked and ((own and p.endswith("-debug")) or p in NEVER):
            continue
        ours = p.startswith("fpgas-online-") and p != "fpgas-online-verify"
        not_this_board = ours and (not own or p.endswith("-debug"))
        tool = TOOL_OF.get(p, board) != board or p in NOT_FOR.get(board, ()) or p in NEVER
        if not_this_board or tool:
            out.append(p)
    return out


# -- running ------------------------------------------------------------------------------------------------------


def run(command):
    r = subprocess.run(["bash", "-euo", "pipefail", "-c", command], capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr


def in_container():
    # docker's marker (the job runs the check with docker), as root: it rewrites /etc/apt
    return pathlib.Path("/.dockerenv").exists() and os.geteuid() == 0


def primary_fingerprints(colons):
    """The primary keys' fingerprints in `gpg --with-colons` output (an fpr line right after a pub line)."""
    out, after_pub = [], False
    for line in colons.splitlines():
        if line.startswith("pub:"):
            after_pub = True
        elif line.startswith("fpr:") and after_pub:
            out.append(line.split(":")[9])
            after_pub = False
        elif line.startswith(("sub:", "uid:")):
            after_pub = False
    return out


def stanza(packages_text, name):
    """The newest stanza of package `name` in a Packages index, as a dict."""
    found = []
    for block in packages_text.split("\n\n"):
        fields = dict(re.findall(r"^([\w-]+): (.*)$", block, re.M))
        if fields.get("Package") == name:
            found.append(fields)
    if not found:
        raise SystemExit(f"FAIL: no {name} in the index")
    newest = found[0]
    for fields in found[1:]:
        if run(f"dpkg --compare-versions {fields['Version']} gt {newest['Version']}")[0] == 0:
            newest = fields
    return newest


def fetch_keyring(keyring, suite, arch, dest):
    """The key the image trusts for `keyring.archive`: from the keyring package of `suite`, checked against the
    index's SHA256 and against the fingerprint pinned here (the trust anchor; the index is not yet verifiable)."""
    work = pathlib.Path("/var/lib/target/keyring") / keyring.package
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rc, out = run(f"curl -fsSL {keyring.archive}/dists/{suite}/main/binary-{arch}/Packages.gz | gzip -dc > {work}/P")
    if rc:
        raise SystemExit(f"FAIL: cannot read {keyring.archive} {suite} {arch} Packages.gz:\n{out}")
    fields = stanza((work / "P").read_text(), keyring.package)
    deb = work / "keyring.deb"
    rc, out = run(f"curl -fsSL -o {deb} {keyring.archive}/{fields['Filename']}")
    if rc:
        raise SystemExit(f"FAIL: cannot fetch {keyring.archive}/{fields['Filename']}:\n{out}")
    rc, out = run(f"sha256sum {deb}")
    if out.split()[0] != fields["SHA256"]:
        raise SystemExit(f"FAIL: {fields['Filename']} is not the index's: {out.split()[0]} != {fields['SHA256']}")
    rc, out = run(f"dpkg-deb -x {deb} {work}/x && cp {work}/x/{keyring.path} {dest}")
    if rc:
        raise SystemExit(f"FAIL: {fields['Filename']} has no {keyring.path}:\n{out}")
    rc, out = run(f"gpg --show-keys --with-colons {dest}")
    if primary_fingerprints(out) != [keyring.fingerprint]:  # that key and no other
        raise SystemExit(
            f"FAIL: {keyring.package} {fields['Version']} holds {primary_fingerprints(out)}, "
            f"not just {keyring.fingerprint}"
        )
    print(f"    {keyring.package} {fields['Version']}: {keyring.fingerprint}")


def prepare(system, suite):
    """The container as the target system: its os-release, its base archives and trust, apt set to simulate."""
    for path in ("/etc/apt/sources.list", "/etc/os-release"):
        pathlib.Path(path).unlink(missing_ok=True)
    for d in ("/etc/apt/sources.list.d", "/var/lib/apt/lists"):
        shutil.rmtree(d)
        pathlib.Path(d).mkdir()
    pathlib.Path("/etc/os-release").write_text(f"ID={system.os_id}\nVERSION_CODENAME={suite}\n")
    if not system.trusts_debian:
        for key in pathlib.Path("/etc/apt/trusted.gpg.d").glob("*"):
            key.unlink()
    pathlib.Path(BASE_KEYS).mkdir(parents=True, exist_ok=True)
    fetch_keyring(RPI_KEYRING, suite, system.arch, f"{BASE_KEYS}/raspberrypi.gpg")
    if system.os_id == "raspbian":
        fetch_keyring(RASPBIAN_KEYRING, suite, system.arch, f"{BASE_KEYS}/raspbian.gpg")
    pathlib.Path("/etc/apt/sources.list.d/base.list").write_text(
        "".join(line.format(suite=suite) + "\n" for line in system.sources)
    )
    pathlib.Path("/var/lib/target").mkdir(exist_ok=True)
    pathlib.Path("/var/lib/target/status").write_text("")
    pathlib.Path("/etc/apt/apt.conf.d/99howto-target").write_text(
        f'APT::Architecture "{system.arch}";\n'
        f'APT::Architectures {{ "{system.arch}"; }};\n'
        'Dir::State::status "/var/lib/target/status";\n'
        'APT::Get::Simulate "true";\n'
        'APT::Get::Assume-Yes "true";\n'
    )
    sudo = pathlib.Path("/usr/local/bin/sudo")
    sudo.write_text('#!/bin/sh\nexec "$@"\n')
    sudo.chmod(0o755)


def execute(plan, label, failures):
    """Run a plan's commands; return the packages its installs would install. Failures are collected, not raised:
    the run reports every one, then fails."""
    packages = []
    for number, k, command in plan:
        rc, out = run(command)
        where = f"{label} step {number}: {command}"
        print(f"--- {where}")
        if k == "update":
            problems = update_problems(out)
            if rc or problems:
                failures.append(f"{where}: exit {rc}; " + "; ".join(problems or [out.strip()[-500:]]))
        elif k == "install":
            if rc:
                failures.append(f"{where}: exit {rc}; " + "; ".join(install_problems(out) or [out.strip()[-500:]]))
            got = installed(out)
            print("    " + " ".join(sorted(got)))
            packages += got
        elif rc:
            failures.append(f"{where}: exit {rc}: {out.strip()[-500:]}")
    return packages


def source_urls(path):
    """The repository URLs of a sources file's `deb` lines, each ending in a slash."""
    urls = []
    for line in path.read_text().splitlines():
        m = re.match(r"^deb (?:\[[^\]]*\] )?(\S+)", line)
        if m:
            urls.append(m.group(1).rstrip("/") + "/")
    return urls


def page_sources():
    """The repository URLs the pages added (every source file but the base one), less any that is also a base
    archive's: on 64-bit the TT page's bookworm-backports is deb.debian.org/debian, whose pool is the base's, so its
    files are not told apart by URL and are the base's to serve."""
    d = pathlib.Path("/etc/apt/sources.list.d")
    base = set(source_urls(d / "base.list"))
    return [u for f in sorted(d.glob("*.list")) if f.name != "base.list" for u in source_urls(f) if u not in base]


def page_uris(print_uris, sources):
    """From `apt-get --print-uris` output, the (URI, package, version) of each file that comes from a repository a
    page added. The lines are `'URI' file size [hash]`: apt prints MD5Sum, or for a bookworm-backports file no
    hash at all; the hash is apt's to check, when it downloads."""
    out = []
    for uri, name in re.findall(r"^'(\S+)' (\S+) \d+(?: \S+)?$", print_uris, re.M):
        if any(uri.startswith(s) for s in sources):
            package, version, _arch = name.removesuffix(".deb").split("_")
            out.append((uri, package, urllib.parse.unquote(version)))  # an epoch is written %3a in the file name
    return out


def downloads(plan, done, failures, label):
    """Download every package the plan's installs would take from a repository a page added, with apt, which checks
    each file against the index's hashes: a simulation alone never fetches a .deb, so a published index naming a
    missing or broken file would pass. `done` holds the URIs already checked on this system."""
    sources = page_sources()
    debs = pathlib.Path("/var/lib/target/debs")
    debs.mkdir(parents=True, exist_ok=True)
    for _n, k, command in plan:
        if k != "install":
            continue
        rc, out = run(
            command.replace("sudo apt install", "apt-get -o APT::Get::Simulate=false --print-uris -qq install", 1)
        )
        if rc:
            continue  # the install itself failed; that is reported already
        ours = page_uris(out, sources)
        if not ours and any(p.startswith("fpgas-online-") for p in named([(0, k, command)])):
            failures.append(f"{label}: {command}: no file from a page's repository found; the download check read none")
        for uri, package, version in ours:
            if uri in done:
                continue
            done.add(uri)
            rc, out = run(f"cd {debs} && apt-get -o APT::Get::Simulate=false -qq download '{package}={version}'")
            if rc:
                failures.append(f"{label}: {uri} does not download as its index says: {out.strip()[-500:]}")
            else:
                print(f"    downloaded and checked: {uri}")


def snapshot(to):
    shutil.rmtree(to, ignore_errors=True)
    for d in ("/etc/apt", "/var/lib/apt/lists"):
        shutil.copytree(d, f"{to}{d}", symlinks=True)


def restore(frm):
    for d in ("/etc/apt", "/var/lib/apt/lists"):
        shutil.rmtree(d)
        shutil.copytree(f"{frm}{d}", d, symlinks=True)


def judge(board, package, page, got, asked, all_boards, failures):
    """The verdicts on what one board's install would install."""
    if f"fpgas-online-{board}-tools" not in got:
        failures.append(f"{page}: installing {package} does not install fpgas-online-{board}-tools")
    if board != "tt-fpga":
        if not OPENFPGALOADER & set(got):
            failures.append(f"{page}: installing {package} brings no openFPGALoader")
        elif any("fpgas.online-fpga-tools" in s for s in page_sources()) and "openfpgaloader-fpgasonline" not in got:
            failures.append(f"{page}: fpgas.online's openFPGALoader repository is added, but {package} gets another")
    for p in foreign(board, got, all_boards, asked):
        failures.append(f"{page}: installing {package} pulls in {p}, which is not this board's")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("system", choices=sorted(SYSTEMS))
    args = parser.parse_args()
    if not in_container():
        raise SystemExit(
            "refusing to run outside a container, or not as root: this replaces /etc/apt's sources and /etc/os-release"
        )
    m = re.search(r"^VERSION_CODENAME=(\w+)$", pathlib.Path("/usr/lib/os-release").read_text(), re.M)
    if not m:
        raise SystemExit("FAIL: the container's /usr/lib/os-release has no VERSION_CODENAME")
    suite = m.group(1)  # the container's own release: the target's
    system = SYSTEMS[args.system]
    print(f"=== {system.name} ({system.arch}, ID={system.os_id}) {suite}")
    failures = []
    try:  # every page is read before anything runs: a page the check cannot follow fails the run at once
        setup, own = installing_plan(suite)
        all_boards = boards()
        plans = {board: board_plan(page, suite) for board, (page, _package) in all_boards.items()}
    except ValueError as e:
        print(f"\nFAILED:\n{e}")
        return 1
    prepare(system, suite)
    if [k for _n, k, _c in setup].count("update") != 1:
        failures.append(f"{INSTALLING}: the setup steps do not end in one apt update: {setup}")
    execute(setup, INSTALLING, failures)
    if failures:  # without the repositories no board can be judged
        print("\n".join(["", "FAILED:", *failures]))
        return 1
    snapshot("/var/lib/target/after-setup")
    done = set()
    # installing.md's own install steps: its example board's package, then that board's debug package
    own_installs = [c for _n, k, c in own if k == "install"]
    examples = {w.removeprefix("fpgas-online-") for c in own_installs for w in c.split()[3:]} & set(all_boards)
    if len(examples) != 1:
        failures.append(f"{INSTALLING}: its install steps name {sorted(examples)}, not one board")
    else:
        (board,) = examples
        got = execute(own, INSTALLING, failures)
        downloads(own, done, failures, INSTALLING)
        judge(board, f"fpgas-online-{board}", INSTALLING, got, named(own), all_boards, failures)
    for board, (page, package) in all_boards.items():
        restore("/var/lib/target/after-setup")
        plan = plans[board]
        if not any(k == "install" and package in c.split() for _n, k, c in plan):
            failures.append(f"{page}: no install step for {package} on {suite}")
        got = execute(plan, page, failures)
        downloads(plan, done, failures, page)
        judge(board, package, page, got, named(plan), all_boards, failures)
    print("\n".join(["", "FAILED:", *failures]) if failures else "\nall boards install as the pages say")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
