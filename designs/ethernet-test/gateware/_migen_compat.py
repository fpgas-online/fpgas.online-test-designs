"""Monkey-patch migen's bytecode tracer for Python >= 3.11 compatibility.

Migen 0.9.2's ``fhdl/tracer.py`` inspects CPython bytecode to discover
variable names (e.g. ``self.cd_sys = ClockDomain()`` -> name "cd_sys").
It only knows about opcodes up to Python 3.10.  Python 3.11 replaced
``CALL_FUNCTION`` / ``CALL_METHOD`` with ``CALL`` (and later ``CALL_KW``),
and widened all instruction words to 2 bytes (``CACHE`` / ``EXTENDED_ARG``
padding).  Without this patch every ``ClockDomain()`` without an explicit
name raises ``ValueError: Cannot extract clock domain name from code``.

Import this module *before* any migen / litex import to apply the fix.
"""

import sys

if sys.version_info >= (3, 11):
    import dis
    import inspect
    from opcode import opname

    # ---- patched helpers ------------------------------------------------

    def _patched_get_var_name(frame):
        """Walk bytecode instructions to find the STORE target after a CALL."""
        code = frame.f_code
        instructions = list(dis.get_instructions(code))

        # Find instruction at (or near) frame.f_lasti
        call_idx = None
        for i, instr in enumerate(instructions):
            if instr.offset == frame.f_lasti:
                call_idx = i
                break
            # f_lasti can point to a CACHE/PRECALL preceding the real CALL
            if instr.offset > frame.f_lasti:
                call_idx = i
                break

        if call_idx is None:
            return None

        # Walk forward from the call looking for a STORE_* instruction
        for instr in instructions[call_idx:]:
            if instr.opname in ("STORE_NAME", "STORE_ATTR"):
                return instr.argval
            if instr.opname == "STORE_FAST":
                return instr.argval
            if instr.opname == "STORE_DEREF":
                return instr.argval
            # Skip over CACHE, RESUME, PRECALL, POP_TOP, COPY,
            # CALL, CALL_KW, PUSH_NULL, LOAD_*, BUILD_*, NOP, etc.
            if instr.opname in (
                "CACHE", "RESUME", "PRECALL", "NOP",
                "CALL", "CALL_KW", "CALL_FUNCTION_EX",
                "PUSH_NULL", "COPY",
                "LOAD_GLOBAL", "LOAD_ATTR", "LOAD_FAST",
                "LOAD_DEREF", "LOAD_CONST",
                "DUP_TOP", "BUILD_LIST", "BUILD_TUPLE",
            ):
                continue
            # Any unexpected opcode means we can't determine the name
            return None

        return None

    def _patched_remove_underscore(s):
        if len(s) > 2 and s[0] == "_" and s[1] != "_":
            s = s[1:]
        return s

    def _patched_get_obj_var_name(override=None, default=None):
        if override:
            return override

        frame = inspect.currentframe().f_back
        ourclass = frame.f_locals["self"].__class__
        while "self" in frame.f_locals and isinstance(frame.f_locals["self"], ourclass):
            frame = frame.f_back

        vn = _patched_get_var_name(frame)
        if vn is None:
            vn = default
        else:
            vn = _patched_remove_underscore(vn)
        return vn

    # ---- apply the patch ------------------------------------------------

    import migen.fhdl.tracer as _tracer
    _tracer.get_var_name = _patched_get_var_name
    _tracer.get_obj_var_name = _patched_get_obj_var_name
