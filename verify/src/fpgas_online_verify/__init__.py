"""fpgas.online boot-time FPGA board verification: find the board a Raspberry Pi has, check it with the
fpgas.online test bitstreams, and catch a board or flash that changed since last time.

The core is here; each board is a module in fpgas_online_verify.boards (a namespace package, so each board's
module can ship in its own package). docs/plans/2026-09-26-fpgas-online-verify-design.md has the design.
"""
