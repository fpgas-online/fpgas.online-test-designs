# One bitstream flow for every Xilinx board

Date: 2026-10-02. Status: **proposal, nothing here is implemented.** It needs Tim's answers to the
[decisions](#decisions-for-tim) before the packaging changes start.

## The rule

Tim, 2026-10-02: "All bitstreams should be built on CI using open source tooling and then vivado built
bitstreams can be added -- there shouldn't be a split based on board type, the same flow should be working for
acorn, netv2, arty, etc (all the xilinx based parts)."

## What happens today

| | Arty A7, NeTV2 | Acorn |
|---|---|---|
| Designs the boot check uses | the single-function designs (uart, ddr-memory, spi-flash-id, ...), loaded into SRAM | `designs/acorn-pcie`, the full test design, booted from flash |
| Built by | CI, openXC7, every commit | Vivado, by hand, off CI. No workflow builds `designs/acorn-pcie` |
| Published as | CI artifacts, bundled as `all-bitstreams` | a GitHub release of its own, `vivado-bitstreams-acorn-pcie-<date>-g<sha>` (`designs/acorn-pcie/tools/publish_release.py`) |
| `fpgas-online-<board>-bitstreams` holds | this commit's CI builds; version `X.Y.postN` | the release pinned in `packaging/acorn-pcie/release.toml`; version `<date>+g<sha>` |
| Vivado builds | none packaged | the only ones packaged |

Three more facts:

- CI already builds the single-function designs for all three Acorn variants with openXC7 (`build-uart-test.yml`,
  `build-ddr-test.yml`, `build-spiflash-test.yml`, `pmod-*.yml`, `pcie-enumeration-build.yml`, on the XC7A200T
  and the XC7A100T). They are in the `all-bitstreams` bundle (18 of its artifacts on `main` at b1218ee), and
  no package carries them.
- Building the Acorn's full test design with open tooling is Phase 5 of the approved
  [Acorn PCIe design](2026-09-03-acorn-pcie-design.md). It has not been started until now.
- PR #14 (`vivado-xilinx-flows`) is the uniform Vivado side: three flows for every Xilinx design
  (`vivado-vivado`, `yosys-vivado`, `yosys-nextpnr`), build directories named by board, variant and flow, and
  `scripts/publish_vivado_bitstreams.py`, which builds every design for every board with Vivado and publishes
  them with a manifest. It made the `vivado-bitstreams-v0.0-496-gf162f60` release in April. It is open, 266
  commits behind `main`, and conflicts with it.

`docs/hardware/acorn-pcie-programming.md` says the XC7A200T is too large for openXC7. That is out of date: CI
builds for it on every commit.

## Proposed flow

The words are [docs/verify-goals.md](../verify-goals.md)'s: a board has one *full test design* and several
*single-function test designs*, and the *golden bitstreams* are the set currently approved for every board.

1. **CI builds everything with open tooling, on every commit.** Every design, for every board and variant it
   supports, the Acorn's full test design included (operational and golden images). A build that fails or misses
   timing fails CI, as now.
2. **Each push to main publishes its bitstreams on that build's release**, `build-<version>` (PR #92), next to
   its debs: one file per (design, board, variant, flow), named `<design>_<board>-<variant>_<flow>.<ext>` as PR
   #14 names them, and a `manifest.json` (per file: design, board, variant, flow, sha256; for a full test
   design also its identifier, the flash slot it is for and its `csr.json`).
3. **Vivado builds are added to the same release.** One script checks out the release's commit, builds the
   Vivado flows of every Xilinx design for every Xilinx board, and uploads them to `build-<version>` with
   their manifest entries. It is `scripts/publish_vivado_bitstreams.py` from PR #14, pointed at the build's
   release. A release may have no Vivado builds: nothing waits for them.
   - With the self-hosted Vivado runners of PR #93, the script's builds are CI jobs of the same commit, and
     a job on `ubuntu-latest` uploads what they built (those runners have `contents: read` only).
   - Until those runners exist, it is run by hand on a machine with Vivado, as the Acorn's releases are now.
4. **One pin names the golden bitstreams, for every board.** `packaging/golden.toml`: the release, its
   manifest's sha256 and, per board, which flow is golden. Moving it is a reviewed pull request, after the
   candidates were checked on a board of each setup (verify-goals, fourth job). It is what
   `packaging/acorn-pcie/release.toml` is today, for every board instead of one.
5. **One package shape for every board.** `fpgas-online-<board>-bitstreams` is built from the pin, by one
   function, for the Acorn, the Arty and the NeTV2 alike (and the Fomu and the TT FPGA, which have no Vivado
   flow). Its version is the pinned build's `X.Y.postN`: no dates.
6. **The Acorn-only route goes away**: `packaging/acorn-pcie/release.toml`,
   `designs/acorn-pcie/tools/publish_release.py`, and new `vivado-bitstreams-acorn-pcie-*` releases. The
   existing releases stay: the fleet's flash holds the 20261001 images until a board is reflashed on purpose.

What must not change (from the sessions that run the fleet's Acorn check):

- The pin is the fleet's expectation. The boot check compares both flash slots and the running identifier with
  the pinned images. A new pin in the NFS root fails every board not yet reflashed, and nothing reflashes
  automatically.
- An image's identifier contains its build time, so a rebuild never matches a flashed image. The pinned files
  must be the files that were flashed.
- The installed package keeps, per build: the identifier, `csr.json`, and the golden-slot and operational-slot
  images, under `/usr/share/fpgas-online/acorn-pcie/images/`.

## Steps

| # | Pull request | State |
|---|---|---|
| 1 | `designs/acorn-pcie` builds with openXC7 in CI | being tried now; see [unknowns](#unknowns) |
| 2 | PR #14 brought up to `main`; `designs/acorn-pcie` joins its three flows | not started; needs Tim to say #14 is wanted as it is |
| 3 | `collect-bitstreams.yml` collects every board's builds and publishes them and the manifest on `build-<version>` | not started; after #92 |
| 4 | The Vivado script uploads to `build-<version>`, covering the full test design and the manifest fields the Acorn check reads | not started |
| 5 | `packaging/golden.toml` and one `-bitstreams` builder for every board; the verify code reads the same manifest for every board | not started; `verify/` and `packaging/debs/` belong to the verify session, to be agreed with it |
| 6 | Remove the Acorn-only route | last |

Until step 5 merges, the Acorn's pin and package stay exactly as they are.

## Unknowns

The Acorn PCIe design (§2.3 and Phase 5) names most of these.

- **Whether the Acorn's full test design builds with openXC7.** It has DDR3, PCIe with DMA, ICAP, XADC and DNA
  in one design; only the simpler `pcie-enumeration` design has been built for the Acorn with open tooling. Not
  known: whether it places, routes and meets timing.
- **Whether an openXC7 build of it works on a board.** Nobody has confirmed an openXC7 PCIe bitstream
  enumerating on hardware, and LiteDRAM built with openXC7 has never passed a memory test.
- **The golden (multiboot) image.** openXC7 cannot set `NEXT_CONFIG_ADDR`, `TIMER_CFG` or `CONFIGFALLBACK`.
  Phase 5 plans a script that patches those register writes into an openXC7 bitstream. Until it exists, the
  image in the golden flash slot can only come from Vivado.
- **What the open PCIe core lacks.** It hard-codes the device ID (`7011`, where the Vivado build has `7021`)
  and a 64 MiB BAR0 (128 KiB in the Vivado build). The Vivado IP is also configured for a 64-bit MSI address
  (a Pi 5 needs it), the subsystem IDs that name the board, and GT lane 0. Whether the open `pcie_7x` sources
  can do each is being checked in step 1.

## Decisions for Tim

1. **Is the golden set a pin for every board (step 4)?** Today only the Acorn has one; the Arty's and NeTV2's
   packages always carry the newest commit's builds. I recommend the pin for every board: it is the "golden
   bitstreams" of verify-goals, and it is the only way a Vivado build, which is made after the commit, can be
   the approved one.
2. **Which flow is golden?** I recommend: the open build wherever it has passed the check on a board; the
   Vivado build otherwise. For the Acorn that means Vivado until an openXC7 image has run on one.
3. **If the Acorn's full test design does not build or meet timing with openXC7**, should its CI job be
   allowed to fail without blocking merges (as the NeTV2 PCIe jobs are now, issue #30), or should the design
   be cut down until it does?
4. **Is PR #14 the Vivado side you want?** It needs bringing up to `main` before anything can build on it.
5. **A release holds at most 1000 files.** One Vivado flow of every design was 148 files in April's release
   (each Acorn build is six: `.bit` and `.bin`, plain, `_fallback` and `_operational`). Three flows and the
   debs would be about 500. Files as they are, or one archive per board?
