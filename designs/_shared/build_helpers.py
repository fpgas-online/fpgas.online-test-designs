"""Common build helpers for LiteX test SoC targets.

Provides standardised SoC kwarg preparation and Builder invocation so
that each design target only needs to define its SoC class and call
these helpers.
"""

import os
from pathlib import Path

from litex.soc.integration.builder import Builder


def default_soc_kwargs(parser, ident):
    """Return common SoC keyword arguments with the given *ident* string.

    Sets reasonable defaults for the test designs:
    - ``ident``: design identification string (shown in BIOS banner)
    - ``ident_version``: True (include LiteX version in ident)
    - ``uart_baudrate``: 115200 (standard for all test designs)
    - ``integrated_main_ram_size``: 8192 (for openXC7 builds without DDR)
    """
    soc_kwargs = parser.soc_argdict
    soc_kwargs["ident"] = ident
    soc_kwargs["ident_version"] = True
    soc_kwargs["uart_baudrate"] = 115200
    soc_kwargs["integrated_main_ram_size"] = 8192
    return soc_kwargs


def default_build_dir(gateware_file, board_name):
    """Return the default build output directory for *board_name*.

    *gateware_file* should be ``__file__`` from the calling script.
    The build directory is placed at ``<design_dir>/build/<board_name>/``
    where ``<design_dir>`` is two levels up from the gateware script.
    """
    design_dir = Path(os.path.realpath(gateware_file)).parent.parent
    return str(design_dir / "build" / board_name)


def build_soc(soc, parser, board_name, gateware_file=None):
    """Configure the Builder and run the build if requested.

    *board_name* is the board-specific subdirectory name under ``build/``
    (e.g. ``"arty"`` or ``"netv2"``).

    If *gateware_file* is provided, the output directory is resolved
    relative to that file's design directory.  Otherwise falls back to
    the parser's builder_argdict output_dir (if set).
    """
    args = parser.parse_args()

    builder_kwargs = parser.builder_argdict
    if gateware_file is not None:
        builder_kwargs["output_dir"] = default_build_dir(gateware_file, board_name)

    builder = Builder(soc, **builder_kwargs)
    if args.build:
        builder.build(**parser.toolchain_argdict)
