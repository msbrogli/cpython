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
sys.sandbox.max_statements = 1000
sys.sandbox.add_filename('<string>')
initial = sys.sandbox.statement_count
for i in range(10): pass
final = sys.sandbox.statement_count
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

    def test_eval_code_object_allowed(self):
        """eval() with code object should still work."""
        code = '''
import sys
# Compile BEFORE entering sandbox scope
code = compile('2+2', '<test>', 'eval')
sys.sandbox.add_filename('<string>')
result = eval(code)
if result == 4:
    print("PASS")
else:
    print(f"FAIL: {result}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_exec_code_object_allowed(self):
        """exec() with code object should still work."""
        code = '''
import sys
# Compile BEFORE entering sandbox scope
code = compile('test_var = 42', '<test>', 'exec')
sys.sandbox.add_filename('<string>')
ns = {}
exec(code, ns)
if ns.get('test_var') == 42:
    print("PASS")
else:
    print(f"FAIL: {ns}")
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
