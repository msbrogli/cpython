"""Tests for sandbox recursion depth limiting.

This module tests the max_recursion_depth limit which prevents denial-of-service
attacks through deep recursion that can crash the interpreter.

Tests run in subprocesses to avoid sandbox scope conflicts between tests.
"""

import subprocess
import sys
import unittest


def run_sandbox_test(code: str, timeout: int = 10) -> tuple[int, str, str]:
    """Run a sandbox test in a subprocess.

    Returns (returncode, stdout, stderr).
    """
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        timeout=timeout
    )
    return result.returncode, result.stdout, result.stderr


class RecursionDepthPropertyTest(unittest.TestCase):
    """Test max_recursion_depth property access."""

    def test_property_exists(self):
        """max_recursion_depth property should exist and be readable."""
        code = '''
import sys
depth = sys.sandbox.max_recursion_depth
print(f"PASS: {depth}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS:", out, f"Output: {out}\nStderr: {err}")

    def test_property_settable(self):
        """max_recursion_depth should be settable."""
        code = '''
import sys
sys.sandbox.max_recursion_depth = 100
if sys.sandbox.max_recursion_depth == 100:
    print("PASS")
else:
    print("FAIL")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_default_is_zero(self):
        """Default max_recursion_depth should be 0 (no limit)."""
        code = '''
import sys
sys.sandbox.reset()
if sys.sandbox.max_recursion_depth == 0:
    print("PASS")
else:
    print(f"FAIL: {sys.sandbox.max_recursion_depth}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class SandboxRecursionErrorTest(unittest.TestCase):
    """Test SandboxRecursionError exception."""

    def test_exception_exists(self):
        """SandboxRecursionError should exist as a builtin."""
        code = '''
if SandboxRecursionError is not None:
    print("PASS")
else:
    print("FAIL")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_exception_inherits_sandbox_error(self):
        """SandboxRecursionError should inherit from SandboxError."""
        code = '''
if issubclass(SandboxRecursionError, SandboxError):
    print("PASS")
else:
    print("FAIL")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class BasicRecursionLimitTest(unittest.TestCase):
    """Test basic recursion depth limiting."""

    def test_recursion_limit_enforced(self):
        """Recursion beyond limit should raise SandboxRecursionError."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 10
sys.sandbox.add_filename('<test>')

code_str = """
def recurse(n):
    if n > 0:
        return recurse(n - 1) + 1
    return 0
try:
    recurse(100)
    print("FAIL: no exception")
except SandboxRecursionError:
    print("PASS")
"""
exec(compile(code_str, '<test>', 'exec'))
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_recursion_under_limit_allowed(self):
        """Recursion under limit should succeed."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 20
sys.sandbox.add_filename('<test>')

code_str = """
def recurse(n):
    if n > 0:
        return recurse(n - 1) + 1
    return 0
result = recurse(15)
if result == 15:
    print("PASS")
else:
    print(f"FAIL: {result}")
"""
exec(compile(code_str, '<test>', 'exec'))
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_no_limit_when_zero(self):
        """No recursion limit when max_recursion_depth is 0."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 0  # No limit
sys.sandbox.add_filename('<test>')

code_str = """
def recurse(n):
    if n > 0:
        return recurse(n - 1) + 1
    return 0
# Python's default limit is ~1000, but sandbox shouldn't block
result = recurse(100)
if result == 100:
    print("PASS")
else:
    print(f"FAIL: {result}")
"""
exec(compile(code_str, '<test>', 'exec'))
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class ScopeAwareRecursionTest(unittest.TestCase):
    """Test that recursion depth only counts sandbox-scoped frames."""

    def test_out_of_scope_not_counted(self):
        """Frames outside sandbox scope should not count toward depth."""
        code = '''
import sys

# Define a helper function OUTSIDE sandbox scope
def helper(callback, n):
    if n > 0:
        return helper(callback, n - 1)
    return callback()

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 5
sys.sandbox.add_filename('<test>')

code_str = """
def inner():
    return "done"

# helper() is not in scope, so its recursion doesn't count
# Only this frame (depth=1) should count
result = helper(inner, 100)  # helper recurses 100 times outside scope
if result == "done":
    print("PASS")
else:
    print(f"FAIL: {result}")
"""
exec(compile(code_str, '<test>', 'exec'), {'helper': helper})
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class CrossCodeBlockRecursionTest(unittest.TestCase):
    """Test recursion across multiple independently compiled code blocks."""

    def test_three_code_blocks_with_bridge(self):
        """Three sandbox code blocks calling each other via trusted bridge."""
        code = '''
import sys

# Trusted bridge function - OUTSIDE sandbox scope
def bridge(callback, *args):
    """Trusted intermediary that doesn't count toward sandbox depth."""
    return callback(*args)

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 10  # Low limit to verify only sandbox frames count
sys.sandbox.add_filename('<sandbox_a>')
sys.sandbox.add_filename('<sandbox_b>')
sys.sandbox.add_filename('<sandbox_c>')

# Three independent code blocks
code_a = """
def func_a():
    return bridge(func_b)
"""

code_b = """
def func_b():
    return bridge(func_c)
"""

code_c = """
def func_c():
    return "success"
"""

# Shared namespace for all blocks
shared_ns = {'bridge': bridge}

# Execute all three code blocks
exec(compile(code_a, '<sandbox_a>', 'exec'), shared_ns)
exec(compile(code_b, '<sandbox_b>', 'exec'), shared_ns)
exec(compile(code_c, '<sandbox_c>', 'exec'), shared_ns)

# Call func_a which calls bridge -> func_b -> bridge -> func_c
# Only func_a, func_b, func_c should count (depth 3), not bridge calls
result = shared_ns['func_a']()
if result == "success":
    print("PASS")
else:
    print(f"FAIL: {result}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_deep_bridge_recursion_not_counted(self):
        """Deep recursion in trusted bridge should not count toward sandbox limit."""
        code = '''
import sys

# Trusted bridge with deep internal recursion
def bridge_recurse(n, callback):
    """Recurses deeply in trusted code, then calls sandboxed callback."""
    if n > 0:
        return bridge_recurse(n - 1, callback)
    return callback()

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 5  # Very low limit
sys.sandbox.add_filename('<sandbox>')

code_str = """
def sandboxed_func():
    return "done"

# Bridge recurses 100 times (outside scope), then calls sandboxed_func (depth 1)
# Total sandbox depth is only 2 (this module + sandboxed_func), not 102
result = bridge_recurse(100, sandboxed_func)
if result == "done":
    print("PASS")
else:
    print(f"FAIL: {result}")
"""

exec(compile(code_str, '<sandbox>', 'exec'), {'bridge_recurse': bridge_recurse})
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_mixed_scope_chain_limit_enforced(self):
        """Sandbox limit should trigger when sandboxed frames exceed limit."""
        code = '''
import sys

# Trusted bridge
def bridge(callback, n):
    return callback(n)

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 5
sys.sandbox.add_filename('<sandbox_a>')
sys.sandbox.add_filename('<sandbox_b>')

# Two sandboxed code blocks that alternate calls via bridge
code_a = """
def func_a(n):
    if n <= 0:
        return 0
    return bridge(func_b, n - 1)  # depth +1 for func_a
"""

code_b = """
def func_b(n):
    if n <= 0:
        return 0
    return bridge(func_a, n - 1)  # depth +1 for func_b
"""

shared_ns = {'bridge': bridge}
exec(compile(code_a, '<sandbox_a>', 'exec'), shared_ns)
exec(compile(code_b, '<sandbox_b>', 'exec'), shared_ns)

# func_a(10) -> bridge -> func_b(9) -> bridge -> func_a(8) -> ...
# Each sandbox frame counts, so depth grows: 1, 2, 3, 4, 5, ERROR
try:
    shared_ns['func_a'](10)
    print("FAIL: no exception")
except SandboxRecursionError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_multiple_bridges_between_sandbox_calls(self):
        """Multiple trusted functions between sandbox calls shouldn't affect count."""
        code = '''
import sys

# Multiple trusted intermediaries
def bridge1(callback, arg):
    return bridge2(callback, arg)

def bridge2(callback, arg):
    return bridge3(callback, arg)

def bridge3(callback, arg):
    return callback(arg)

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 5
sys.sandbox.add_filename('<sandbox>')

code_str = """
call_count = 0

def sandboxed_recurse(n):
    global call_count
    call_count += 1
    if n <= 0:
        return call_count
    # Goes through 3 trusted bridges, but only sandboxed_recurse counts
    return bridge1(sandboxed_recurse, n - 1)

# With limit 5, we can make 5 sandboxed calls (depth 1,2,3,4,5 including module)
# Module frame + 4 recursive calls = depth 5
result = sandboxed_recurse(3)  # Module(1) + 4 sandboxed calls = 5, just under limit
if result == 4:  # 4 calls: recurse(3), recurse(2), recurse(1), recurse(0)
    print("PASS")
else:
    print(f"FAIL: call_count={result}")
"""

exec(compile(code_str, '<sandbox>', 'exec'), {
    'bridge1': bridge1, 'bridge2': bridge2, 'bridge3': bridge3
})
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class GeneratorRecursionTest(unittest.TestCase):
    """Test that generator yield/resume correctly adjusts depth."""

    def test_generator_yield_resume(self):
        """Generator yield should decrement depth, resume should increment."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 5
sys.sandbox.add_filename('<test>')

code_str = """
def gen():
    yield 1
    yield 2
    yield 3

g = gen()
results = []
for _ in range(3):
    results.append(next(g))
if results == [1, 2, 3]:
    print("PASS")
else:
    print(f"FAIL: {results}")
"""
exec(compile(code_str, '<test>', 'exec'))
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_recursive_generator(self):
        """Recursive generators should be limited by depth."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 5
sys.sandbox.add_filename('<test>')

code_str = """
def gen(n):
    if n > 0:
        yield n
        yield from gen(n - 1)

try:
    list(gen(100))  # Should fail - recursive generator
    print("FAIL: no exception")
except SandboxRecursionError:
    print("PASS")
"""
exec(compile(code_str, '<test>', 'exec'))
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class ExceptionHandlingTest(unittest.TestCase):
    """Test that depth is correctly tracked through exception handling."""

    def test_exception_unwinding(self):
        """Depth should be correctly decremented during exception unwinding."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 20
sys.sandbox.add_filename('<test>')

code_str = """
def recurse(n):
    if n == 0:
        raise ValueError("bottom")
    try:
        return recurse(n - 1)
    except ValueError:
        raise

try:
    recurse(10)
except ValueError as e:
    if str(e) == "bottom":
        print("PASS")
    else:
        print(f"FAIL: {e}")
"""
exec(compile(code_str, '<test>', 'exec'))
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_caught_recursion_error(self):
        """SandboxRecursionError should be catchable."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 5
sys.sandbox.add_filename('<test>')

code_str = """
def recurse(n):
    return recurse(n - 1)

try:
    recurse(100)
except SandboxRecursionError as e:
    if "depth" in str(e).lower() or "recursion" in str(e).lower():
        print("PASS")
    else:
        print(f"FAIL: {e}")
"""
exec(compile(code_str, '<test>', 'exec'))
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class RecursionDepthCounterTest(unittest.TestCase):
    """Test that sys.sandbox.recursion_depth accurately reflects current depth."""

    def test_recursion_depth_property_exists(self):
        """recursion_depth property should exist and be readable."""
        code = '''
import sys
depth = sys.sandbox.recursion_depth
if isinstance(depth, int) and depth >= 0:
    print("PASS")
else:
    print(f"FAIL: {depth}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_recursion_depth_read_only(self):
        """recursion_depth should be read-only."""
        code = '''
import sys
try:
    sys.sandbox.recursion_depth = 10
    print("FAIL: should be read-only")
except AttributeError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_recursion_depth_increments_in_scope(self):
        """recursion_depth should increment when entering sandbox-scoped frames."""
        code = '''
import sys

# Capture depth at various points
captured_depths = []

def capture_depth():
    """Trusted helper to capture current depth."""
    captured_depths.append(sys.sandbox.recursion_depth)
    return sys.sandbox.recursion_depth

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 20
sys.sandbox.add_filename('<test>')

code_str = """
# At module level: depth = 1
depth1 = capture_depth()

def func1():
    # Inside func1: depth = 2
    return capture_depth()

def func2():
    # Inside func2: depth = 2
    depth2 = capture_depth()
    def inner():
        # Inside inner called from func2: depth = 3
        return capture_depth()
    depth3 = inner()
    return (depth2, depth3)

d1 = func1()
d2, d3 = func2()

# Verify depths:
# - Module level: 1
# - func1: 2
# - func2: 2
# - inner: 3
if depth1 == 1 and d1 == 2 and d2 == 2 and d3 == 3:
    print("PASS")
else:
    print(f"FAIL: depth1={depth1}, d1={d1}, d2={d2}, d3={d3}")
"""
exec(compile(code_str, '<test>', 'exec'), {'capture_depth': capture_depth, 'captured_depths': captured_depths})
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_recursion_depth_only_counts_scoped_frames(self):
        """recursion_depth should only count sandbox-scoped frames, not trusted frames."""
        code = '''
import sys

# Trusted capture function that sandboxed code can call
def get_depth():
    """Trusted function to read sandbox recursion depth."""
    return sys.sandbox.recursion_depth

def trusted_recurse(n, callback):
    """Trusted function - NOT in sandbox scope."""
    if n > 0:
        return trusted_recurse(n - 1, callback)
    return callback()

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 20
sys.sandbox.add_filename('<test>')

code_str = """
def sandboxed_check():
    # Even after 50 levels of trusted_recurse, sandbox depth should still be 2
    # (module frame + this function)
    return get_depth()

# Call through 50 levels of trusted recursion
depth = trusted_recurse(50, sandboxed_check)

# Depth should be 2, not 52
if depth == 2:
    print("PASS")
else:
    print(f"FAIL: depth={depth}, expected 2")
"""
exec(compile(code_str, '<test>', 'exec'), {
    'trusted_recurse': trusted_recurse,
    'get_depth': get_depth
})
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_recursion_depth_three_code_blocks(self):
        """recursion_depth should correctly count across multiple compile() blocks."""
        code = '''
import sys

# Trusted bridge that captures depth before calling
captured = []

def get_depth():
    """Trusted function to read sandbox recursion depth."""
    return sys.sandbox.recursion_depth

def capture_depth(label):
    """Trusted function to capture depth with a label."""
    captured.append((label, sys.sandbox.recursion_depth))

def bridge_and_capture(callback, *args):
    """Trusted bridge - NOT in sandbox scope."""
    # Capture depth while inside trusted code
    captured.append(('bridge', sys.sandbox.recursion_depth))
    return callback(*args)

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 20
sys.sandbox.add_filename('<a>')
sys.sandbox.add_filename('<b>')
sys.sandbox.add_filename('<c>')

code_a = """
def func_a():
    capture_depth('func_a')
    return bridge_and_capture(func_b)
"""

code_b = """
def func_b():
    capture_depth('func_b')
    return bridge_and_capture(func_c)
"""

code_c = """
def func_c():
    capture_depth('func_c')
    return "done"
"""

shared = {
    'bridge_and_capture': bridge_and_capture,
    'capture_depth': capture_depth,
    'captured': captured
}

exec(compile(code_a, '<a>', 'exec'), shared)
exec(compile(code_b, '<b>', 'exec'), shared)
exec(compile(code_c, '<c>', 'exec'), shared)

result = shared['func_a']()

# Expected depths:
# - func_a: 1 (first sandbox frame)
# - bridge (after func_a): 1 (bridge not counted, func_a still active)
# - func_b: 2 (second sandbox frame)
# - bridge (after func_b): 2 (bridge not counted, func_a+func_b active)
# - func_c: 3 (third sandbox frame)

expected = [
    ('func_a', 1),
    ('bridge', 1),
    ('func_b', 2),
    ('bridge', 2),
    ('func_c', 3)
]

if captured == expected and result == "done":
    print("PASS")
else:
    print(f"FAIL: captured={captured}, expected={expected}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_recursion_depth_decrements_on_return(self):
        """recursion_depth should decrement when exiting sandbox-scoped frames."""
        code = '''
import sys

depths_before_after = []

def record_depth(label):
    depths_before_after.append((label, sys.sandbox.recursion_depth))

sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 20
sys.sandbox.add_filename('<test>')

code_str = """
record_depth('module_start')  # Should be 1

def outer():
    record_depth('outer_start')  # Should be 2
    inner()
    record_depth('outer_after_inner')  # Should be 2 (inner returned)
    return 'done'

def inner():
    record_depth('inner')  # Should be 3

result = outer()
record_depth('module_after_outer')  # Should be 1 (outer returned)

# Verify sequence
expected = [
    ('module_start', 1),
    ('outer_start', 2),
    ('inner', 3),
    ('outer_after_inner', 2),
    ('module_after_outer', 1)
]

if depths_before_after == expected:
    print("PASS")
else:
    print(f"FAIL: {depths_before_after}")
"""
exec(compile(code_str, '<test>', 'exec'), {
    'record_depth': record_depth,
    'depths_before_after': depths_before_after,
    'sys': sys
})
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class SecurityRegressionTest(unittest.TestCase):
    """Test that HYP-006 (deep recursion crash) is fixed."""

    def test_hyp006_deep_recursion_no_crash(self):
        """HYP-006: Deep recursion with exception re-raise should not crash."""
        code = '''
import sys
sys.sandbox.reset()
sys.sandbox.max_recursion_depth = 50
sys.sandbox.add_filename('<test>')

code_str = """
def recurse(n):
    if n <= 0:
        raise ValueError("Deep")
    try:
        recurse(n - 1)
    except:
        raise

try:
    recurse(500)
except SandboxRecursionError:
    print("PASS: Got SandboxRecursionError instead of crash")
except ValueError:
    print("FAIL: Got ValueError, limit not enforced")
"""
exec(compile(code_str, '<test>', 'exec'))
'''
        rc, out, err = run_sandbox_test(code, timeout=30)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")
        self.assertEqual(rc, 0, f"Process crashed or exited abnormally\nStderr: {err}")


if __name__ == '__main__':
    unittest.main()
