"""Tests for sandbox security fixes.

This module tests the following security fixes:
1. Statement limit enforcement via property setter
2. List multiplication size limit
3. Frozen mode auto-freeze of sys and builtins
4. eval()/exec() blocking with string arguments

Tests run in subprocesses to avoid sandbox scope conflicts between tests.
"""

import subprocess
import sys
import unittest


def run_sandbox_test(code: str) -> tuple[int, str, str]:
    """Run a sandbox test in a subprocess.

    Returns (returncode, stdout, stderr).
    """
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        timeout=10
    )
    return result.returncode, result.stdout, result.stderr


class StatementLimitPropertySetterTest(unittest.TestCase):
    """Test that setting max_statements via property enables tracing."""

    def test_statement_count_increments(self):
        """Statement count should increment when max_statements is set via property."""
        code = '''
import sys
# Store reference to sandbox before entering scope (sys access is blocked in scope)
sandbox = sys.sandbox
sandbox.max_statements = 1000
sandbox.add_filename('<string>')
initial = sandbox.statement_count
for i in range(10): pass
final = sandbox.statement_count
if final > initial:
    print("PASS")
else:
    print(f"FAIL: {initial} -> {final}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_statement_limit_enforced(self):
        """Statement limit should be enforced when set via property setter."""
        code = '''
import sys
sys.sandbox.max_statements = 20
sys.sandbox.add_filename('<string>')
# The loop should raise SandboxRuntimeError when limit is exceeded
for i in range(1000): pass
# If we get here, the limit was not enforced
print("FAIL: no exception")
'''
        rc, out, err = run_sandbox_test(code)
        # The test passes if SandboxRuntimeError was raised (non-zero exit, error in stderr)
        self.assertIn("SandboxRuntimeError", err, f"Output: {out}\nStderr: {err}")


class ListMultiplicationSizeLimitTest(unittest.TestCase):
    """Test that list multiplication respects size limits."""

    def test_list_multiply_blocked(self):
        """List multiplication should be blocked when result exceeds limit."""
        code = '''
import sys
sys.sandbox.max_list_size = 100
sys.sandbox.add_filename('<string>')
try:
    x = [1, 2, 3] * 1000
    print(f"FAIL: created {len(x)} items")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_list_multiply_allowed_under_limit(self):
        """List multiplication should work when result is under limit."""
        code = '''
import sys
sys.sandbox.max_list_size = 100
sys.sandbox.add_filename('<string>')
x = [1, 2, 3] * 10  # 30 items
if len(x) == 30:
    print("PASS")
else:
    print(f"FAIL: {len(x)}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_list_repeat_single_element(self):
        """Single element list multiplication should be blocked."""
        code = '''
import sys
sys.sandbox.max_list_size = 100
sys.sandbox.add_filename('<string>')
try:
    x = [1] * 1000
    print(f"FAIL: created {len(x)} items")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class FrozenModeTest(unittest.TestCase):
    """Test that frozen_mode blocks modifications to all objects in scope."""

    def test_sys_modification_blocked_in_scope(self):
        """Modifying sys should be blocked in scope when frozen_mode is enabled.

        Note: frozen_mode=1 makes ALL objects frozen by default (unless marked mutable).
        This is different from explicitly freezing objects with freeze().
        """
        code = '''
import sys
sys.sandbox.frozen_mode = 1
sys.sandbox.add_filename('<string>')
try:
    sys.test_attr = "test"
    print("FAIL: modification allowed")
except SandboxAttributeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_object_attribute_modification_blocked(self):
        """Modifying object attributes should be blocked in frozen_mode scope."""
        code = '''
import sys

class MyObj:
    def __init__(self):
        self.value = 1

obj = MyObj()
sys.sandbox.frozen_mode = 1
sys.sandbox.add_filename('<string>')
try:
    obj.value = 2
    print("FAIL: modification allowed")
except SandboxAttributeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_mutable_object_allowed_in_frozen_mode(self):
        """Objects marked as mutable should be modifiable even in frozen_mode."""
        code = '''
import sys
d = {"key": "value"}
sys.sandbox.set_mutable(d, True)
sys.sandbox.frozen_mode = 1
sys.sandbox.add_filename('<string>')
d["new_key"] = "new_value"
if d.get("new_key") == "new_value":
    print("PASS")
else:
    print(f"FAIL: {d}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class EvalExecBlockingTest(unittest.TestCase):
    """Test that eval/exec with strings are blocked in sandbox scope."""

    def test_eval_string_blocked(self):
        """eval() with string should be blocked in sandbox scope."""
        code = '''
import sys
sys.sandbox.add_filename('<string>')
try:
    eval('1+1')
    print("FAIL: eval allowed")
except SandboxSecurityError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_exec_string_blocked(self):
        """exec() with string should be blocked in sandbox scope."""
        code = '''
import sys
sys.sandbox.add_filename('<string>')
try:
    exec('x = 1')
    print("FAIL: exec allowed")
except SandboxSecurityError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_eval_code_object_blocked(self):
        """eval() with code object should be blocked (security fix)."""
        code = '''
import sys
# Compile BEFORE entering sandbox scope
code = compile('2+2', '<test>', 'eval')
sys.sandbox.add_filename('<string>')
try:
    result = eval(code)
    print(f"FAIL: eval returned {result}")
except SandboxSecurityError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_exec_code_object_blocked(self):
        """exec() with code object should be blocked (security fix)."""
        code = '''
import sys
# Compile BEFORE entering sandbox scope
code = compile('test_var = 42', '<test>', 'exec')
sys.sandbox.add_filename('<string>')
try:
    ns = {}
    exec(code, ns)
    print(f"FAIL: exec succeeded")
except SandboxSecurityError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_eval_allowed_with_allow_unsafe(self):
        """eval() with string should work when allow_unsafe=True."""
        code = '''
import sys
sys.sandbox.allow_unsafe = 1
sys.sandbox.add_filename('<string>')
result = eval('3+3')
if result == 6:
    print("PASS")
else:
    print(f"FAIL: {result}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_exec_allowed_with_allow_unsafe(self):
        """exec() with string should work when allow_unsafe=True."""
        code = '''
import sys
sys.sandbox.allow_unsafe = 1
sys.sandbox.add_filename('<string>')
ns = {}
exec('y = 99', ns)
if ns.get('y') == 99:
    print("PASS")
else:
    print(f"FAIL: {ns}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class CompileStillBlockedTest(unittest.TestCase):
    """Verify that compile() is still blocked (original behavior)."""

    def test_compile_blocked(self):
        """Direct compile() should still be blocked in sandbox scope."""
        code = '''
import sys
sys.sandbox.add_filename('<string>')
try:
    compile('x = 1', '<test>', 'exec')
    print("FAIL: compile allowed")
except SandboxSecurityError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class FloatTypeBlockingTest(unittest.TestCase):
    """Test that float creation is blocked when allow_float=0 (security fix)."""

    def test_float_arithmetic_blocked(self):
        """Float from runtime arithmetic should be blocked when allow_float=0.

        Note: `1 / 2` is constant-folded at compile time to 0.5, so we use
        variables to force runtime division which goes through PyFloat_FromDouble.
        """
        code = '''
import sys
sys.sandbox.allow_float = 0
sys.sandbox.add_filename('<string>')
# Use variables to prevent constant folding
a = 1
b = 2
try:
    x = a / b  # Runtime division, not constant-folded
    print(f"FAIL: created float {x}")
except SandboxTypeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_float_constructor_blocked(self):
        """float() constructor should be blocked when allow_float=0."""
        code = '''
import sys
sys.sandbox.allow_float = 0
sys.sandbox.add_filename('<string>')
try:
    x = float(5)
    print(f"FAIL: created float {x}")
except SandboxTypeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_float_constant_folded_blocked(self):
        """Constant-folded float literals are blocked by LOAD_CONST check.

        `1 / 2` is constant-folded at compile time to 0.5. The LOAD_CONST
        opcode check blocks loading this float constant when allow_float=0.
        """
        code = '''
import sys
sys.sandbox.allow_float = 0
sys.sandbox.add_filename('<string>')
try:
    # 1/2 is constant-folded to 0.5 at compile time
    x = 1 / 2
    print(f"FAIL: created float {x}")
except SandboxTypeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_float_allowed_by_default(self):
        """Float should be allowed by default."""
        code = '''
import sys
sys.sandbox.add_filename('<string>')
x = 1 / 2
if x == 0.5:
    print("PASS")
else:
    print(f"FAIL: {x}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class ComplexTypeBlockingTest(unittest.TestCase):
    """Test that complex creation is blocked when allow_complex=0 (security fix)."""

    def test_complex_constructor_blocked(self):
        """complex() constructor should be blocked when allow_complex=0."""
        code = '''
import sys
sys.sandbox.allow_complex = 0
sys.sandbox.add_filename('<string>')
try:
    x = complex(1, 2)
    print(f"FAIL: created complex {x}")
except SandboxTypeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_complex_arithmetic_blocked(self):
        """Complex from runtime arithmetic should be blocked when allow_complex=0.

        Note: `1j` is a literal that gets constant-folded, so we use
        complex() with variables to force runtime creation.
        """
        code = '''
import sys
sys.sandbox.allow_complex = 0
sys.sandbox.add_filename('<string>')
# Use variables to prevent constant folding
a = 1
b = 2
try:
    x = complex(a, b)  # Runtime complex creation
    print(f"FAIL: created complex {x}")
except SandboxTypeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_complex_literal_blocked(self):
        """Complex literals are blocked by LOAD_CONST check.

        `1+2j` is a complex literal that gets loaded via LOAD_CONST.
        The LOAD_CONST opcode check blocks loading this when allow_complex=0.
        """
        code = '''
import sys
sys.sandbox.allow_complex = 0
sys.sandbox.add_filename('<string>')
try:
    x = 1+2j  # Complex literal
    print(f"FAIL: created complex {x}")
except SandboxTypeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_complex_allowed_by_default(self):
        """Complex should be allowed by default."""
        code = '''
import sys
sys.sandbox.add_filename('<string>')
x = complex(1, 2)
if x == (1+2j):
    print("PASS")
else:
    print(f"FAIL: {x}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class LoadConstSizeCheckTest(unittest.TestCase):
    """Test that LOAD_CONST checks size limits on constant literals."""

    def test_large_string_literal_blocked(self):
        """Large string literal should be blocked when it exceeds max_str_length."""
        # Create code with a large string literal
        large_string = 'x' * 1000
        code = f'''
import sys
sys.sandbox.max_str_length = 100
sys.sandbox.add_filename('<string>')
try:
    s = "{large_string}"
    print(f"FAIL: created string of length {{len(s)}}")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_large_tuple_literal_blocked(self):
        """Large tuple literal should be blocked when it exceeds max_tuple_size."""
        # Create a tuple literal with many elements
        tuple_elements = ', '.join(['1'] * 200)
        code = f'''
import sys
sys.sandbox.max_tuple_size = 50
sys.sandbox.add_filename('<string>')
try:
    t = ({tuple_elements})
    print(f"FAIL: created tuple of size {{len(t)}}")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_small_constants_allowed(self):
        """Small constants should be allowed when under limits."""
        code = '''
import sys
sys.sandbox.max_str_length = 100
sys.sandbox.max_tuple_size = 50
sys.sandbox.add_filename('<string>')
s = "hello"
t = (1, 2, 3)
if len(s) == 5 and len(t) == 3:
    print("PASS")
else:
    print(f"FAIL: s={len(s)}, t={len(t)}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class DunderVariableAccessTest(unittest.TestCase):
    """Test that dunder variable names are blocked via LOAD_NAME/LOAD_GLOBAL."""

    def test_builtins_access_blocked(self):
        """__builtins__ should be blocked via LOAD_NAME when allow_dunder_access=0."""
        code = '''
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.add_filename('<string>')
try:
    x = __builtins__
    print(f"FAIL: accessed __builtins__")
except SandboxAttributeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_name_access_blocked(self):
        """__name__ should be blocked via LOAD_NAME when allow_dunder_access=0."""
        code = '''
import sys
sys.sandbox.allow_dunder_access = 0
sys.sandbox.add_filename('<string>')
try:
    x = __name__
    print(f"FAIL: accessed __name__")
except SandboxAttributeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_dunder_access_allowed_by_default(self):
        """Dunder variable access should be allowed by default."""
        code = '''
import sys
sys.sandbox.add_filename('<string>')
# allow_dunder_access defaults to 1 (allowed)
x = __name__
# __name__ is "__main__" when running with -c
if x is not None:
    print("PASS")
else:
    print("FAIL: __name__ is None")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class DictUpdateBypassTest(unittest.TestCase):
    """Test that dict.update() respects size limits (security fix)."""

    def test_dict_update_blocked(self):
        """dict.update() should be blocked when result exceeds limit."""
        code = '''
import sys
big_dict = {i: i for i in range(500)}
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
try:
    small_dict = {}
    small_dict.update(big_dict)
    print(f"FAIL: updated to {len(small_dict)} items")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_dict_ior_blocked(self):
        """dict |= other should be blocked when result exceeds limit."""
        code = '''
import sys
big_dict = {i: i for i in range(500)}
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
try:
    small_dict = {}
    small_dict |= big_dict
    print(f"FAIL: updated to {len(small_dict)} items")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_dict_update_allowed_under_limit(self):
        """dict.update() should work when result is under limit."""
        code = '''
import sys
small_update = {1: 'a', 2: 'b'}
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
d = {}
d.update(small_update)
if len(d) == 2:
    print("PASS")
else:
    print(f"FAIL: {len(d)}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class DictCopyBypassTest(unittest.TestCase):
    """Test that dict.copy() respects size limits (security fix)."""

    def test_dict_copy_blocked(self):
        """dict.copy() should be blocked when source exceeds limit."""
        code = '''
import sys
# Create large dict BEFORE sandbox
big_dict = {i: i for i in range(500)}
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
try:
    copy = big_dict.copy()
    print(f"FAIL: copied {len(copy)} items")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_dict_copy_allowed_under_limit(self):
        """dict.copy() should work when source is under limit."""
        code = '''
import sys
small_dict = {1: 'a', 2: 'b', 3: 'c'}
sys.sandbox.max_dict_size = 100
sys.sandbox.add_filename('<string>')
copy = small_dict.copy()
if len(copy) == 3:
    print("PASS")
else:
    print(f"FAIL: {len(copy)}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class SetCopyBypassTest(unittest.TestCase):
    """Test that set copy operations respect size limits (security fix)."""

    def test_set_copy_blocked(self):
        """set.copy() should be blocked when source exceeds limit."""
        code = '''
import sys
# Create large set BEFORE sandbox
big_set = {i for i in range(500)}
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<string>')
try:
    copy = big_set.copy()
    print(f"FAIL: copied {len(copy)} items")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_set_update_from_large_set_blocked(self):
        """set.update() from large set should be blocked."""
        code = '''
import sys
big_set = {i for i in range(500)}
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<string>')
try:
    small_set = set()
    small_set.update(big_set)
    print(f"FAIL: updated to {len(small_set)} items")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_set_union_blocked(self):
        """set.union() should be blocked when result exceeds limit."""
        code = '''
import sys
big_set = {i for i in range(500)}
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<string>')
try:
    result = set().union(big_set)
    print(f"FAIL: union created {len(result)} items")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_set_copy_allowed_under_limit(self):
        """set.copy() should work when source is under limit."""
        code = '''
import sys
small_set = {1, 2, 3, 4, 5}
sys.sandbox.max_set_size = 100
sys.sandbox.add_filename('<string>')
copy = small_set.copy()
if len(copy) == 5:
    print("PASS")
else:
    print(f"FAIL: {len(copy)}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


if __name__ == '__main__':
    unittest.main()
