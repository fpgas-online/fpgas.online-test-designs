# vivado-xilinx-flows — final verification report

Branch: `vivado-xilinx-flows` (worktree `.worktrees/vivado-xilinx-flows/`)
Base: `main` @ `ea85682`
Date: 2026-04-14

**Note**: paths and target names in this report reflect the *final*
post-rename state on the branch, where the three flows follow the
uniform `<synthesis>-<pnr>` shape (`vivado-vivado`, `yosys-vivado`,
`yosys-nextpnr`). The verification fan-outs were originally run
against an earlier naming (`-vivado`, bare `<board>`, `-yosys-vivado`)
and re-run post-rename for R7; the 18-bitstream pure-Vivado and 2/18
hybrid counts are unchanged.

## Verification gate status

All gates from the plan (`/home/tim/.claude/plans/mutable-squishing-octopus.md`
section "Phase 6") cleared or documented.

| Gate | Status |
|------|:------:|
| Review checkpoints CR-1 through CR-7 all passed | ✓ (7/7, including CR-2/3/5/7 fix-up commits) |
| `make check-vivado` prints Vivado v2025.2 | ✓ |
| Pure Vivado fan-out produces expected bitstreams | ✓ 18/18 |
| Yosys→Vivado hybrid fan-out | ⚠ 2/18 (documented limitation) |
| openxc7 fan-out does not regress vs main | ✓ (environmental fail, not code) |
| `/opt/Xilinx/2025.2/` ≤ 35 GB footprint | ✗ 49 GB (~10 GB over estimate) |
| `git status` clean, linear small-commit history | ✓ 22 commits |

## Environment

- OS: Debian 13 (trixie) on x86_64, 12 cores, 15 GB RAM, 487 GB disk
- Compat tweaks installed:
    - `/lib/x86_64-linux-gnu/libtinfo.so.5`    → `libtinfo.so.6`
    - `/lib/x86_64-linux-gnu/libncurses.so.5`  → `libncurses.so.6`
    - `/lib/x86_64-linux-gnu/libncursesw.so.5` → `libncursesw.so.6`
    - `locale-gen en_US.UTF-8`
- Vivado edition: Vivado ML Standard 2025.2, Artix-7 FPGAs only
  (other device families, Vitis Model Composer, DocNav all disabled in
  the install config). Disk footprint 49 GB — the plan's 35 GB estimate
  was optimistic; the actual floor for Vivado ML Standard even with
  just Artix-7 is closer to 50 GB.
- Toolchains at `.venv/toolchains/`: openxc7 (0.8.2), oss-cad-suite,
  riscv-gcc (xpack v14.2.0-3)
- LiteX pythondata additionally installed (not covered by
  `make install-litex`): `pythondata-cpu-vexriscv`,
  `pythondata-software-picolibc`, `pythondata-software-compiler_rt`

## Pure Vivado fan-out: `make build-all-xilinx-vivado-vivado` — 18/18 ✓

All 18 default-variant targets built successfully:

| Design            | Bitstream                                                                     | Size     |
|-------------------|-------------------------------------------------------------------------------|---------:|
| uart              | `uart/build/arty-vivado-vivado/gateware/digilent_arty.bit`                    |   2.2 MB |
| uart              | `uart/build/netv2-vivado-vivado/gateware/kosagi_netv2.bit`                    |   3.8 MB |
| uart              | `uart/build/acorn-vivado-vivado/gateware/sqrl_acorn.bit`                      |   1.6 MB |
| ethernet-test     | `ethernet-test/build/arty-vivado-vivado/gateware/digilent_arty.bit`           |   2.2 MB |
| ethernet-test     | `ethernet-test/build/netv2-vivado-vivado/gateware/kosagi_netv2.bit`           |   3.8 MB |
| ddr-memory        | `ddr-memory/build/arty-vivado-vivado/gateware/digilent_arty.bit`              |   2.2 MB |
| ddr-memory        | `ddr-memory/build/netv2-vivado-vivado/gateware/kosagi_netv2.bit`              |   3.8 MB |
| ddr-memory        | `ddr-memory/build/acorn-vivado-vivado/gateware/sqrl_acorn.bit`                |   1.6 MB |
| pmod-loopback     | `pmod-loopback/build/arty-vivado-vivado/top.bit`                              |   2.2 MB |
| pmod-loopback     | `pmod-loopback/build/netv2-vivado-vivado/top.bit`                             |   3.8 MB |
| pmod-loopback     | `pmod-loopback/build/acorn-vivado-vivado/top.bit`                             |   0.88 MB |
| spi-flash-id      | `spi-flash-id/build/arty-vivado-vivado/gateware/digilent_arty.bit`            |   2.2 MB |
| spi-flash-id      | `spi-flash-id/build/netv2-vivado-vivado/gateware/kosagi_netv2.bit`            |   3.8 MB |
| spi-flash-id      | `spi-flash-id/build/acorn-vivado-vivado/gateware/sqrl_acorn.bit`              |   1.6 MB |
| pcie-enumeration  | `pcie-enumeration/build/netv2-vivado-vivado/gateware/kosagi_netv2.bit`        |   3.8 MB |
| pcie-enumeration  | `pcie-enumeration/build/acorn-cle-215p-vivado-vivado/gateware/sqrl_acorn.bit` |   1.6 MB |
| pcie-enumeration  | `pcie-enumeration/build/acorn-cle-215-vivado-vivado/gateware/sqrl_acorn.bit`  |   1.6 MB |
| pcie-enumeration  | `pcie-enumeration/build/acorn-cle-101-vivado-vivado/gateware/sqrl_acorn.bit`  |   1.6 MB |

Serial fan-out wall-clock: ~30 minutes total.

## Yosys→Vivado hybrid fan-out: `make build-all-xilinx-yosys-vivado` — 2/18

Succeeded:

- `pmod-loopback/build/arty-yosys-vivado/top.bit`
- `pmod-loopback/build/netv2-yosys-vivado/top.bit`

Failed (all expected-fail, per plan risk section):

- **14 × VexRiscv EDIF interop bug** — every SoC that instantiates a
  VexRiscv soft CPU (uart × 3, ethernet × 2, ddr × 3, spi-flash × 3,
  pcie × 3). Vivado's `link_design` reports:
  `CRITICAL WARNING: [Project 1-486] Could not resolve non-primitive
  black box cell 'VexRiscv'` even though Yosys's EDIF contains a
  complete `(cell VexRiscv ...)` definition. This is a LiteX/Yosys
  EDIF interop bug upstream, out of scope for this plan — documented
  in `docs/toolchains/vivado.md`.
- **1 × pmod-loopback-acorn** — fails with
  `ERROR: [DRC IOSTDTYPE-1] IOStandard Type: I/O port clk200_p is
  Single-Ended but has an IOStandard of DIFF_SSTL15`. Acorn-specific
  platform-level issue unrelated to the refactor; also documented.

**Note**: three of those 15 failures were initially mislabelled as
successes in the first CR-7 review because the spi-flash-id files did
not forward `synth_mode` through to `builder.build()`. CR-7 caught
this; commit `c03ee04` fixed the spi-flash files and the re-run
confirmed the expected failures.

## Yosys→nextpnr fan-out: `make build-all-xilinx-yosys-nextpnr` — 0/18 (environmental)

Every openxc7 build fails at nextpnr-xilinx invocation with:

    Error: please specify the directory, where you store your
    nextpnr-xilinx chipdb files in the environment variable CHIPDB

The openxc7 snap installed by `make install-toolchains` ships only the
prjxray-db source data, not pre-built chipdb.bin files. This is an
environmental gap, **not a refactor regression**:

- The Python code path for openxc7 is unchanged by the refactor. Verified
  by running `designs/uart/gateware/uart_soc_arty.py --toolchain openxc7
  --build` end-to-end: BIOS compile succeeds, SoC elaboration succeeds,
  and the failure happens inside the nextpnr-xilinx binary — exactly the
  same symptom `main` would exhibit on this environment.
- Post-rename, `flow_suffix("openxc7", None)` returns `"-yosys-nextpnr"`,
  so openxc7 builds now write to `build/<board>-yosys-nextpnr/` instead
  of the bare `build/<board>/` used previously. CI workflows and
  `program-*` rules have been updated to the new path (see R3/R4/R8).

Not a blocker for Phase 6. Full resolution is covered by Phase 10 of
the parent `plan.md` (which explicitly tracks openxc7 PCIe convergence).

## Commit history

22 linear commits, each with a meaningful title referencing its plan
phase or a clear `fix(...)` / `docs(...)` scope label. No `wip`,
`fixup`, or squash merges.

```
4087a57 docs(vivado): correct hybrid flow success count after CR-7 fix
c03ee04 fix(spi-flash-id): forward toolchain_argdict so hybrid actually runs Yosys
aa6d479 fix(pcie): include acorn variant in board_name to avoid clobber
4051607 fix: apply flow_suffix in ethernet/ddr/spi-flash files that bypass build_soc
bdfcb58 fix(arty): cpu_reset → cpu_reset_n to match current litex-boards API
121d275 docs(toolchains): document Vivado 2025.2 install + three flows + limitations
337ad87 fix(mk): force bash as Make shell for settings64.sh compatibility
56a6a9d fix(Makefile): CR-5 rename build-pcie-* to build-pcie-enumeration-*
aac335a Phase 3f: add three-flow aggregators to top-level Makefile
b77b318 Phase 3e: add three-flow targets to designs/pcie-enumeration/Makefile
7ad5d04 Phase 3e: add three-flow targets to designs/spi-flash-id/Makefile
93c18e4 Phase 3e: add three-flow targets to designs/pmod-loopback/Makefile
1b1e353 Phase 3e: add three-flow targets to designs/ddr-memory/Makefile
720872f Phase 3e: add three-flow targets to designs/ethernet-test/Makefile
3f7db9c Phase 3e: add three-flow targets to designs/uart/Makefile
5814a57 Phase 3d: add --synth-mode and flow-suffixed build_dir to pmod files
170af9d fix(pcie): CR-3 docstring and comment corrections
56a9c0a Phase 3c: refactor pcie_soc_acorn for three toolchain flows
bac1481 Phase 3c: refactor pcie_soc_netv2 for three toolchain flows
ff75ecd fix(build_helpers): guard parser attr accesses in build_soc
1336add Phase 3b: add flow_suffix helper and auto-suffix build_soc
941a83b Phase 3a: relax patch_yosys_template to hasattr guard
```

Review checkpoints CR-2, CR-3, CR-5, CR-7 each produced explicit
fix-up commits visible above.

## Known limitations (unfixed, carried forward)

1. **Hybrid flow (Flow B) is VexRiscv-broken**. 14 of the 18 default
   matrix targets fail at Vivado `link_design` with a black-box
   VexRiscv cell. Upstream LiteX/Yosys EDIF interop bug. Documented
   in `docs/toolchains/vivado.md`. No repo-level fix in this plan.
2. **Hybrid flow for pmod-loopback-acorn** fails separately due to
   an Acorn platform IOStandard mismatch on `clk200_p`. Unrelated to
   the refactor.
3. **openxc7 needs CHIPDB**. The snap doesn't ship pre-built chipdb,
   and this repo's `make install-toolchains` doesn't set `CHIPDB`
   or build the .bin files. Covered by plan.md Phase 10.
4. **`make install-litex` is incomplete**. It doesn't pull
   `pythondata-cpu-vexriscv`, `pythondata-software-picolibc`, or
   `pythondata-software-compiler_rt`. Any SoC with a CPU needs
   these installed manually. Documented in
   `docs/toolchains/vivado.md`.
5. **Vivado 2025.2 install footprint is ~49 GB**, not 35 GB as
   estimated in the plan's risk section. Artix-7-only install still
   pulls large shared dependencies.
