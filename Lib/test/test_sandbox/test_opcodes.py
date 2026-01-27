"""Tests for sandbox opcode restriction mode.

When opcode restriction mode is active and a banned opcode is executed
within sandbox scope, SandboxRuntimeError is raised.
"""

import opcode
import sys
import unittest

from test.test_sandbox import _run_sandboxed_code, _get_settable_limits


# ---------------------------------------------------------------------------
# Named opcode sets by keyword group
# ---------------------------------------------------------------------------

YIELD_OPCODES = {
    opcode.opmap['YIELD_VALUE'],
    opcode.opmap['GET_YIELD_FROM_ITER'],
    opcode.opmap['RETURN_GENERATOR'],
}

ASYNC_OPCODES = {
    opcode.opmap['GET_AWAITABLE'],
    opcode.opmap['SEND'],
    opcode.opmap['GET_AITER'],
    opcode.opmap['GET_ANEXT'],
    opcode.opmap['BEFORE_ASYNC_WITH'],
    opcode.opmap['END_ASYNC_FOR'],
    opcode.opmap['ASYNC_GEN_WRAP'],
}

WITH_OPCODES = {
    opcode.opmap['BEFORE_WITH'],
    opcode.opmap['WITH_EXCEPT_START'],
}

TRY_EXCEPT_OPCODES = {
    opcode.opmap['PUSH_EXC_INFO'],
    opcode.opmap['CHECK_EXC_MATCH'],
    opcode.opmap['CHECK_EG_MATCH'],
    opcode.opmap['POP_EXCEPT'],
    opcode.opmap['RERAISE'],
    opcode.opmap['PREP_RERAISE_STAR'],
}

GLOBAL_OPCODES = {
    opcode.opmap['STORE_GLOBAL'],
    opcode.opmap['DELETE_GLOBAL'],
}

MATCH_OPCODES = {
    opcode.opmap['MATCH_MAPPING'],
    opcode.opmap['MATCH_SEQUENCE'],
    opcode.opmap['MATCH_KEYS'],
    opcode.opmap['MATCH_CLASS'],
}

IMPORT_STAR_OPCODES = {
    opcode.opmap['IMPORT_STAR'],
}

ALL_BANNED_OPCODES = (
    YIELD_OPCODES | ASYNC_OPCODES | WITH_OPCODES |
    TRY_EXCEPT_OPCODES | GLOBAL_OPCODES | MATCH_OPCODES |
    IMPORT_STAR_OPCODES
)


def _opcode_set_literal(opcodes):
    """Return a Python source literal for a set of opcode ints.

    Used to embed opcode values in subprocess code strings, since the
    subprocess cannot reference our module-level constants directly.
    """
    return '{' + ', '.join(str(op) for op in sorted(opcodes)) + '}'


class OpcodeRestrictionAPITests(unittest.TestCase):
    """Test the sys API for opcode restriction mode."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxopcoderestrictmode(False)
        sys.setsandboxbannedopcodes(None)
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        sys.setsandboxlimits(**self.original_limits)

    def test_get_set_opcode_restrict_mode(self):
        """Setting and getting opcode restrict mode should work."""
        self.assertFalse(sys.getsandboxopcoderestrictmode())
        sys.setsandboxopcoderestrictmode(True)
        self.assertTrue(sys.getsandboxopcoderestrictmode())
        sys.setsandboxopcoderestrictmode(False)
        self.assertFalse(sys.getsandboxopcoderestrictmode())

    def test_get_set_banned_opcodes(self):
        """Setting and getting banned opcodes should work."""
        opcodes = sys.getsandboxbannedopcodes()
        self.assertEqual(len(opcodes), 0)

        sys.setsandboxbannedopcodes(YIELD_OPCODES)
        result = sys.getsandboxbannedopcodes()
        self.assertIsInstance(result, frozenset)
        self.assertEqual(result, frozenset(YIELD_OPCODES))

    def test_clear_banned_opcodes_with_none(self):
        """Passing None should clear all banned opcodes."""
        sys.setsandboxbannedopcodes(YIELD_OPCODES)
        sys.setsandboxbannedopcodes(None)
        self.assertEqual(len(sys.getsandboxbannedopcodes()), 0)

    def test_banned_opcodes_invalid_range(self):
        """Opcode out of range 0..255 should raise ValueError."""
        with self.assertRaises(ValueError):
            sys.setsandboxbannedopcodes({300})
        with self.assertRaises(ValueError):
            sys.setsandboxbannedopcodes({-1})

    def test_set_all_banned_opcodes(self):
        """Setting all banned opcodes should work."""
        sys.setsandboxbannedopcodes(ALL_BANNED_OPCODES)
        result = sys.getsandboxbannedopcodes()
        self.assertEqual(result, frozenset(ALL_BANNED_OPCODES))
        self.assertEqual(len(result), 25)


class OpcodeRestrictionEnforcementTests(unittest.TestCase):
    """Test that banned opcodes are blocked in sandbox scope."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxopcoderestrictmode(False)
        sys.setsandboxbannedopcodes(None)
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        sys.setsandboxlimits(**self.original_limits)

    # --- yield blocked ---

    def test_yield_blocked(self):
        """yield should be blocked when its opcodes are banned."""
        banned = _opcode_set_literal(YIELD_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

try:
    exec(compile("""
def gen():
    yield 1

list(gen())
""", "<sandbox>", "exec"))
    print("FAIL: no exception")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "Opcode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {{e}}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"yield not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    # --- async/await blocked ---

    def test_async_blocked(self):
        """async def should be blocked when its opcodes are banned."""
        # RETURN_GENERATOR is shared with yield group and needed for async
        banned = _opcode_set_literal(
            ASYNC_OPCODES | {opcode.opmap['RETURN_GENERATOR']}
        )
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

try:
    exec(compile("""
import asyncio

async def coro():
    return 42

asyncio.run(coro())
""", "<sandbox>", "exec"))
    print("FAIL: no exception")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "Opcode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {{e}}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"async not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    # --- with statement blocked ---

    def test_with_statement_blocked(self):
        """with statement should be blocked when its opcodes are banned."""
        banned = _opcode_set_literal(WITH_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

try:
    exec(compile("""
class CM:
    def __enter__(self): return self
    def __exit__(self, *a): return False

with CM() as c:
    x = 1
""", "<sandbox>", "exec"))
    print("FAIL: no exception")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "Opcode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {{e}}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"with not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    # --- try/except blocked ---

    def test_try_except_blocked(self):
        """try/except should be blocked when its opcodes are banned.

        Note: PUSH_EXC_INFO only executes when an exception is actually
        caught, so we must raise inside the try block to trigger the
        except handler where the banned opcodes live.
        """
        banned = _opcode_set_literal(TRY_EXCEPT_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

try:
    exec(compile("""
try:
    raise ValueError("test")
except Exception:
    pass
""", "<sandbox>", "exec"))
    print("FAIL: no exception")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "Opcode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {{e}}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"try/except not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    # --- global/nonlocal blocked ---

    def test_store_global_blocked(self):
        """STORE_GLOBAL should be blocked when banned."""
        banned = _opcode_set_literal(GLOBAL_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

try:
    exec(compile("""
def foo():
    global x
    x = 42

foo()
""", "<sandbox>", "exec"))
    print("FAIL: no exception")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "Opcode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {{e}}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"STORE_GLOBAL not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    # --- import star blocked ---

    def test_import_star_blocked(self):
        """IMPORT_STAR should be blocked when banned."""
        banned = _opcode_set_literal(IMPORT_STAR_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

try:
    exec(compile("""
from sys import *
""", "<sandbox>", "exec"))
    print("FAIL: no exception")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "Opcode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {{e}}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"IMPORT_STAR not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    # --- match/case blocked ---

    def test_match_case_blocked(self):
        """match/case should be blocked when its opcodes are banned."""
        banned = _opcode_set_literal(MATCH_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

try:
    exec(compile("""
x = [1, 2, 3]
match x:
    case [a, b, c]:
        result = a + b + c
""", "<sandbox>", "exec"))
    print("FAIL: no exception")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "Opcode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {{e}}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"match/case not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")


class OpcodeRestrictionBypassTests(unittest.TestCase):
    """Test that opcode restrictions are NOT enforced in expected cases."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxopcoderestrictmode(False)
        sys.setsandboxbannedopcodes(None)
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        sys.setsandboxlimits(**self.original_limits)

    def test_not_enforced_when_mode_off(self):
        """Banned opcodes should NOT be enforced when mode is off."""
        banned = _opcode_set_literal(YIELD_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
# Mode stays off
sys.addsandboxfilename("<sandbox>")

exec(compile("""
def gen():
    yield 1
    yield 2

result = list(gen())
""", "<sandbox>", "exec"))
print("PASS")
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Enforced when mode off: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_not_enforced_outside_scope(self):
        """Banned opcodes should NOT be enforced outside sandbox scope."""
        banned = _opcode_set_literal(YIELD_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
# No scope registered

def gen():
    yield 1
    yield 2

result = list(gen())
print("PASS")
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Enforced outside scope: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_suspended_allows_banned_opcodes(self):
        """Suspended sandbox should allow banned opcodes."""
        banned = _opcode_set_literal(YIELD_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")
sys.suspendsandboxlimits()

exec(compile("""
def gen():
    yield 1
    yield 2

result = list(gen())
""", "<sandbox>", "exec"))
sys.resumesandboxlimits()
print("PASS")
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Not allowed when suspended: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_allowed_opcodes_still_work(self):
        """Non-banned opcodes should continue to work in sandbox scope."""
        banned = _opcode_set_literal(YIELD_OPCODES)
        code = f'''
import sys
sys.setsandboxbannedopcodes({banned})
sys.setsandboxopcoderestrictmode(True)
sys.addsandboxfilename("<sandbox>")

exec(compile("""
# Normal code should work fine
x = 1 + 2
y = [1, 2, 3]
z = {{k: v for k, v in enumerate(y)}}
result = sum(y)
""", "<sandbox>", "exec"))
print("PASS")
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Allowed opcodes broken: stdout={result.stdout!r} stderr={result.stderr!r}")


if __name__ == '__main__':
    unittest.main()
