# gateware/migen_compat.py
"""Monkey-patch migen's bytecode tracer for Python 3.12+ compatibility.

Migen 0.9.2 uses Python bytecode inspection to auto-detect variable names
(for CSR and ClockDomain naming). The opcodes it looks for (CALL_FUNCTION,
CALL_METHOD, etc.) were removed in Python 3.12, replaced by CALL / CALL_KW.

This module patches migen.fhdl.tracer.get_var_name with an implementation
derived from Amaranth (the migen successor) that handles modern opcodes.

Import this module *before* importing migen::

    import gateware.migen_compat  # noqa: F401  -- patches migen tracer
    from migen import *
"""

import sys
import platform
from opcode import opname

# Only patch if needed (Python 3.12+).
if sys.version_info >= (3, 12):
    import migen.fhdl.tracer as _tracer

    def _patched_get_var_name(frame):
        """Return the variable name that the call result is stored into.

        Walks bytecode forward from the call site to find a STORE_* opcode.
        Compatible with Python 3.6 through 3.13+.
        """
        code = frame.f_code
        call_index = frame.f_lasti

        # In Python 3.11+, CACHE pseudo-instructions follow real opcodes.
        # Walk backward past them to find the actual call opcode.
        while call_index > 0 and opname[code.co_code[call_index]] == "CACHE":
            call_index -= 2

        # Skip EXTENDED_ARG prefixes.
        while True:
            call_opc = opname[code.co_code[call_index]]
            if call_opc == "EXTENDED_ARG":
                call_index += 2
            else:
                break

        _call_opcodes = frozenset({
            "CALL_FUNCTION", "CALL_FUNCTION_KW", "CALL_FUNCTION_EX",
            "CALL_METHOD", "CALL_METHOD_KW", "CALL", "CALL_KW",
        })
        if call_opc not in _call_opcodes:
            return None

        _load_opcodes = frozenset({
            "LOAD_GLOBAL", "LOAD_NAME", "LOAD_ATTR", "LOAD_FAST",
            "LOAD_FAST_BORROW", "LOAD_DEREF", "DUP_TOP", "BUILD_LIST",
            "CACHE", "COPY",
        })

        index = call_index + 2
        imm = 0
        while True:
            opc = opname[code.co_code[index]]
            if opc == "EXTENDED_ARG":
                imm |= int(code.co_code[index + 1])
                imm <<= 8
                index += 2
            elif opc in ("STORE_NAME", "STORE_ATTR"):
                imm |= int(code.co_code[index + 1])
                return code.co_names[imm]
            elif opc == "STORE_FAST":
                imm |= int(code.co_code[index + 1])
                if sys.version_info >= (3, 11) and platform.python_implementation() == "CPython":
                    return code._varname_from_oparg(imm)
                else:
                    return code.co_varnames[imm]
            elif opc == "STORE_DEREF":
                imm |= int(code.co_code[index + 1])
                if sys.version_info >= (3, 11) and platform.python_implementation() == "CPython":
                    return code._varname_from_oparg(imm)
                else:
                    if imm < len(code.co_cellvars):
                        return code.co_cellvars[imm]
                    else:
                        return code.co_freevars[imm - len(code.co_cellvars)]
            elif opc in _load_opcodes:
                imm = 0
                index += 2
            else:
                return None

    # Apply the patch.
    _tracer.get_var_name = _patched_get_var_name
