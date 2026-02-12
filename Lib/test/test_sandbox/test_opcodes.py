"""Tests for sandbox opcode restriction mode.

When opcode restriction mode is active and an opcode not in allowed_opcodes
is executed within sandbox scope, SandboxRuntimeError is raised.
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

ALL_RESTRICTED_OPCODES = (
    YIELD_OPCODES | ASYNC_OPCODES | WITH_OPCODES |
    TRY_EXCEPT_OPCODES | GLOBAL_OPCODES | MATCH_OPCODES |
    IMPORT_STAR_OPCODES
)

# All opcodes 0..255
ALL_OPCODES = set(range(256))


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
        sys.sandbox.opcode_restrict_mode = False
        sys.sandbox.allowed_opcodes = None
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.set_config(**self.original_limits)

    def test_get_set_opcode_restrict_mode(self):
        """Setting and getting opcode restrict mode should work."""
        self.assertFalse(sys.sandbox.opcode_restrict_mode)
        sys.sandbox.opcode_restrict_mode = True
        self.assertTrue(sys.sandbox.opcode_restrict_mode)
        sys.sandbox.opcode_restrict_mode = False
        self.assertFalse(sys.sandbox.opcode_restrict_mode)

    def test_get_set_allowed_opcodes(self):
        """Setting and getting allowed opcodes should work."""
        opcodes = sys.sandbox.allowed_opcodes
        self.assertEqual(len(opcodes), 0)

        sys.sandbox.allowed_opcodes = YIELD_OPCODES
        result = sys.sandbox.allowed_opcodes
        self.assertIsInstance(result, frozenset)
        self.assertEqual(result, frozenset(YIELD_OPCODES))

    def test_clear_allowed_opcodes_with_none(self):
        """Passing None should clear all allowed opcodes."""
        sys.sandbox.allowed_opcodes = YIELD_OPCODES
        sys.sandbox.allowed_opcodes = None
        self.assertEqual(len(sys.sandbox.allowed_opcodes), 0)

    def test_allowed_opcodes_invalid_range(self):
        """Opcode out of range 0..255 should raise ValueError."""
        with self.assertRaises(ValueError):
            sys.sandbox.allowed_opcodes = {300}
        with self.assertRaises(ValueError):
            sys.sandbox.allowed_opcodes = {-1}


class OpcodeRestrictionEnforcementTests(unittest.TestCase):
    """Test that non-allowed opcodes are blocked in sandbox scope."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.sandbox.opcode_restrict_mode = False
        sys.sandbox.allowed_opcodes = None
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.set_config(**self.original_limits)

    # --- yield blocked ---

    def test_yield_blocked(self):
        """yield should be blocked when its opcodes are not allowed."""
        # Allow all opcodes EXCEPT yield-related ones
        allowed = _opcode_set_literal(ALL_OPCODES - YIELD_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.allow_specialized_opcodes = True  # Allow specialized so base opcode test works
sys.sandbox.add_filename("<sandbox>")

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
        """async def should be blocked when its opcodes are not allowed."""
        # RETURN_GENERATOR is shared with yield group and needed for async
        disallowed = ASYNC_OPCODES | {opcode.opmap['RETURN_GENERATOR']}
        allowed = _opcode_set_literal(ALL_OPCODES - disallowed)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.allow_specialized_opcodes = True  # Allow specialized so base opcode test works
sys.sandbox.add_filename("<sandbox>")

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
        """with statement should be blocked when its opcodes are not allowed."""
        allowed = _opcode_set_literal(ALL_OPCODES - WITH_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.allow_specialized_opcodes = True  # Allow specialized so base opcode test works
sys.sandbox.allow_dunder_access = True  # Required for class definitions
sys.sandbox.enable()
sys.sandbox.add_filename("<sandbox>")

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
        """try/except should be blocked when its opcodes are not allowed.

        Note: PUSH_EXC_INFO only executes when an exception is actually
        caught, so we must raise inside the try block to trigger the
        except handler where the disallowed opcodes live.
        """
        allowed = _opcode_set_literal(ALL_OPCODES - TRY_EXCEPT_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.add_filename("<sandbox>")

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
        """STORE_GLOBAL should be blocked when not allowed."""
        allowed = _opcode_set_literal(ALL_OPCODES - GLOBAL_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.add_filename("<sandbox>")

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
        """IMPORT_STAR should be blocked when not allowed."""
        allowed = _opcode_set_literal(ALL_OPCODES - IMPORT_STAR_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.add_filename("<sandbox>")

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
        """match/case should be blocked when its opcodes are not allowed."""
        allowed = _opcode_set_literal(ALL_OPCODES - MATCH_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.add_filename("<sandbox>")

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
        sys.sandbox.opcode_restrict_mode = False
        sys.sandbox.allowed_opcodes = None
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.set_config(**self.original_limits)

    def test_not_enforced_when_mode_off(self):
        """Opcode restrictions should NOT be enforced when mode is off."""
        # Allow nothing but mode is off
        allowed = _opcode_set_literal(set())  # Empty set
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
# Mode stays off
sys.sandbox.add_filename("<sandbox>")

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
        """Opcode restrictions should NOT be enforced outside sandbox scope."""
        # Allow only basic opcodes (not yield) but no scope registered
        allowed = _opcode_set_literal(ALL_OPCODES - YIELD_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
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

    def test_suspended_allows_disallowed_opcodes(self):
        """Suspended sandbox should allow disallowed opcodes."""
        # Allow nothing except basic ops, but suspend the sandbox
        allowed = _opcode_set_literal(ALL_OPCODES - YIELD_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.suspend()

exec(compile("""
def gen():
    yield 1
    yield 2

result = list(gen())
""", "<sandbox>", "exec"))
sys.sandbox.resume()
print("PASS")
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Not allowed when suspended: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_allowed_opcodes_still_work(self):
        """Allowed opcodes should continue to work in sandbox scope."""
        # Allow all opcodes except yield-related ones
        allowed = _opcode_set_literal(ALL_OPCODES - YIELD_OPCODES)
        code = f'''
import sys
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.opcode_restrict_mode = True
sys.sandbox.add_filename("<sandbox>")

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


class SpecializedOpcodeTests(unittest.TestCase):
    """Test that specialized opcodes are blocked when allow_specialized_opcodes=False."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.sandbox.opcode_restrict_mode = False
        sys.sandbox.allowed_opcodes = None
        sys.sandbox.allow_specialized_opcodes = False
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.set_config(**self.original_limits)

    def test_allow_specialized_opcodes_default(self):
        """allow_specialized_opcodes should default to False."""
        self.assertFalse(sys.sandbox.allow_specialized_opcodes)

    def test_get_set_allow_specialized_opcodes(self):
        """Setting and getting allow_specialized_opcodes should work."""
        self.assertFalse(sys.sandbox.allow_specialized_opcodes)
        sys.sandbox.allow_specialized_opcodes = True
        self.assertTrue(sys.sandbox.allow_specialized_opcodes)
        sys.sandbox.allow_specialized_opcodes = False
        self.assertFalse(sys.sandbox.allow_specialized_opcodes)

    def test_specialized_opcode_blocked_by_default(self):
        """Specialized opcodes should be blocked when flag is False.

        The function must be warmed up BEFORE sandbox is enabled (since enabling
        sandbox prevents specialization). Then we enable sandbox with
        opcode_restrict_mode and run the specialized code in scope.

        We use a separate filename for the sandbox scope to avoid blocking
        the test harness code.
        """
        import subprocess
        # ALL_OPCODES should allow all base opcodes
        allowed = _opcode_set_literal(ALL_OPCODES)
        code = f'''
import sys

# Compile the test function with a specific filename
func_code = compile("""
def hot_add(a, b):
    return a + b
""", "<sandbox-test>", "exec")
exec(func_code)

# Warm up to trigger specialization
for _ in range(100):
    hot_add(1, 2)

# Verify specialization happened
adaptive = hot_add.__code__._co_code_adaptive
if adaptive[6] == 122:
    print("FAIL: function not specialized")
    sys.exit(1)

# Enable sandbox with ALL configuration
sys.sandbox.enable()
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.allow_specialized_opcodes = False  # Block specialized opcodes
sys.sandbox.opcode_restrict_mode = True

# Add the function's filename to scope (not <string>)
sys.sandbox.add_filename("<sandbox-test>")

# Run the specialized function - should be blocked
try:
    result = hot_add(1, 2)
    # If we get here, no exception was raised - FAIL
    print("FAIL: no exception")
    sys.exit(1)
except SandboxRuntimeError:
    # We expect this error - specialized opcode blocked - PASS
    print("PASS")
    sys.exit(0)
'''
        # Run without preamble that enables sandbox
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Specialized opcode not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_specialized_opcode_allowed_when_flag_true(self):
        """Specialized opcodes should work when flag is True.

        We use a separate filename for the sandbox scope to be consistent
        with test_specialized_opcode_blocked_by_default.
        """
        import subprocess
        # ALL_OPCODES should allow all base opcodes
        allowed = _opcode_set_literal(ALL_OPCODES)
        code = f'''
import sys

# Compile the test function with a specific filename
func_code = compile("""
def hot_add(a, b):
    return a + b
""", "<sandbox-test>", "exec")
exec(func_code)

# Warm up to trigger specialization
for _ in range(100):
    hot_add(1, 2)

# Verify specialization happened
adaptive = hot_add.__code__._co_code_adaptive
if adaptive[6] == 122:
    print("FAIL: function not specialized")
    sys.exit(1)

# Enable sandbox with ALL configuration, allowing specialized opcodes
sys.sandbox.enable()
sys.sandbox.allowed_opcodes = {allowed}
sys.sandbox.allow_specialized_opcodes = True  # Allow specialized opcodes
sys.sandbox.opcode_restrict_mode = True

# Add the function's filename to scope
sys.sandbox.add_filename("<sandbox-test>")

# Run the specialized function - should work with flag=True
result = hot_add(1, 2)
assert result == 3, f"Expected 3, got {{result}}"
print("PASS")
sys.exit(0)
'''
        # Run without preamble that enables sandbox
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Specialized opcode should work when flag is True: stdout={result.stdout!r} stderr={result.stderr!r}")


if __name__ == '__main__':
    unittest.main()
