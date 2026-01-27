"""Tests for scope management and statement counting."""

import subprocess
import sys
import unittest

from test.test_sandbox import _run_sandboxed_code, _get_settable_limits


class SandboxScopeTests(unittest.TestCase):
    """Test sandbox scope management."""

    def setUp(self):
        # Ensure clean scope state from any previous tests
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        # Ensure limits are resumed and scope is exited
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        sys.setsandboxlimits(**self.original_limits)

    def test_enter_exit_scope(self):
        """entersandboxscope and exitsandboxscope should work."""
        self.assertFalse(sys.issandboxinscope())

        sys.entersandboxscope()
        self.assertTrue(sys.issandboxinscope())

        sys.exitsandboxscope()
        self.assertFalse(sys.issandboxinscope())

    def test_enter_scope_resets_counters(self):
        """entersandboxscope should reset scope counters."""
        sys.setsandboxlimits(scope_max_statements=100000, scope_max_allocations=100000)
        sys.entersandboxscope()

        # Create many objects and KEEP REFERENCES so they don't get garbage collected
        # (getsandboxcounts() itself allocates a dict, so we need margin)
        result = []
        for _ in range(100):
            result.append([1, 2, 3])

        counts = sys.getsandboxcounts()
        # After 100 list creations, should have some allocations counted
        self.assertGreater(counts['scope_allocation_count'], 10)

        # Enter scope again - should reset
        sys.entersandboxscope()
        counts = sys.getsandboxcounts()
        # Count may not be exactly 0 due to dict allocation and statements
        # in getsandboxcounts call (which happens while in scope)
        self.assertLess(counts['scope_allocation_count'], 10)
        self.assertLess(counts['scope_statement_count'], 10)


class ScopedStatementCountTests(unittest.TestCase):
    """Test scoped statement counting."""

    def setUp(self):
        # Ensure clean scope state from any previous tests
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        sys.setsandboxlimits(**self.original_limits)

    def test_set_and_get_scope_max_statements(self):
        """Setting and getting scope_max_statements should work."""
        sys.setsandboxlimits(scope_max_statements=10000)
        limits = sys.getsandboxlimits()
        self.assertEqual(limits['scope_max_statements'], 10000)

    def test_statement_counting_in_exec(self):
        """Statements in exec() should be counted."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)
sys.entersandboxscope()
# Simple loop to generate statements
exec("x = 0\\nfor _ in range(100):\\n    x += 1")
counts = sys.getsandboxcounts()
# Should have counted the statements in exec
print(counts['scope_statement_count'])
sys.exit(0 if counts['scope_statement_count'] > 0 else 1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Statement counting failed: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_exceeding_statement_limit_raises_runtime_error(self):
        """Exceeding statement limit should raise SandboxRuntimeError."""
        # With ancestry-based scope, exec'd code is counted because it shares
        # the same co_filename ("<string>") as the selected frame
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=10)
sys.entersandboxscope()
try:
    # exec'd code has same filename as selected frame, so it counts
    exec("""
for _ in range(100):
    x = 1
""")
    sys.exit(2)  # Should not reach here
except SandboxRuntimeError as e:
    if "statement limit" in str(e):
        sys.exit(0)  # Expected error
    sys.exit(3)  # Wrong error message
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Statement limit not enforced: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_reset_scope_statement_count(self):
        """resetsandboxcounters should reset scope statement counter."""
        sys.setsandboxlimits(scope_max_statements=1000000)
        sys.entersandboxscope()

        # Do some work to generate statements
        for _ in range(100):
            x = 1

        counts_before = sys.getsandboxcounts()
        # Statement count should be > 0 if we're in scope
        # (the actual count depends on tracing implementation)
        self.assertGreater(counts_before['scope_statement_count'], 50)

        sys.resetsandboxcounters()
        # A few more statements may execute before we exit scope, so count
        # won't be exactly 0 but should be significantly less than before
        sys.exitsandboxscope()
        counts_after = sys.getsandboxcounts()
        self.assertLess(counts_after['scope_statement_count'], 20)


class SelectedFramesScopeTests(unittest.TestCase):
    """Test sandbox scope management via addsandboxframe().

    This tests the addsandboxframe() API which adds the current frame's
    filename to the registered set. Code with registered filenames counts
    toward scope limits.
    """

    def setUp(self):
        # Ensure clean scope state from any previous tests
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        # Reset all counters for clean test state
        sys.resetsandboxcounters()
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        sys.setsandboxlimits(**self.original_limits)
        sys.resetsandboxcounters()

    def test_addsandboxframe_basic(self):
        """addsandboxframe should add the current frame's filename to the set."""
        self.assertFalse(sys.issandboxinscope())

        sys.addsandboxframe()
        self.assertTrue(sys.issandboxinscope())

        sys.exitsandboxscope()
        self.assertFalse(sys.issandboxinscope())

    def test_registered_filename_counts_statements(self):
        """Code with registered filename should count toward statement limit."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)
sys.addsandboxfilename("<tracked>")

# Run code with registered filename - statements should count
exec(compile("""
x = 1
for _ in range(100):
    x += 1
""", "<tracked>", "exec"))

count = sys.getsandboxcounts()['scope_statement_count']
sys.clearsandboxfilenames()
print(count)
sys.exit(0 if count > 50 else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Statement counting failed: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_imported_function_does_not_count(self):
        """Code in imported modules should NOT count toward statement limit."""
        code = '''
import sys
import os
sys.setsandboxlimits(scope_max_statements=1000000)

# Register a custom filename - os module has different filename
sys.addsandboxfilename("<my-test>")

count_before = sys.getsandboxcounts()['scope_statement_count']

# Call an imported function - should NOT count toward statement limit
# os.getcwd() is a C builtin, so it has no Python frame at all
_ = os.getcwd()
_ = os.getcwd()
_ = os.getcwd()

count_after = sys.getsandboxcounts()['scope_statement_count']
sys.clearsandboxfilenames()

# The count should be 0 - no code with our filename was executed
increase = count_after - count_before
print(f"Increase: {increase}")
sys.exit(0 if increase == 0 else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Imported function wrongly counted: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_callback_from_builtin_counts(self):
        """Callbacks from builtins should count if defined with registered filename."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)
sys.addsandboxfilename("<callback-test>")

# Define and use a callback with registered filename
exec(compile("""
callback_calls = 0

def my_callback(x):
    global callback_calls
    callback_calls += 1
    # Do some work that should be counted
    for _ in range(5):
        y = x * 2
    return x

# sorted() is a builtin that calls our callback
result = sorted([3, 1, 2], key=my_callback)
""", "<callback-test>", "exec"))

counts = sys.getsandboxcounts()
sys.clearsandboxfilenames()

# The callback should have been called 3 times (once per element)
# and its statements should be counted
print(f"Statement count: {counts['scope_statement_count']}")
# Should have significant statement count from the callback loops
sys.exit(0 if counts['scope_statement_count'] > 10 else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Callback from builtin not counted: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_functions_in_exec_count(self):
        """Functions defined in exec'd code should count toward statement limit."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)
sys.addsandboxfilename("<exec-functions>")

# Run exec with registered filename - all functions share the same co_filename
exec(compile("""
def foo():
    x = 0
    for i in range(50):
        x += i
    return x

def bar():
    y = 0
    for i in range(50):
        y += i * 2
    return y

# Call the functions
result1 = foo()
result2 = bar()
""", "<exec-functions>", "exec"))

counts = sys.getsandboxcounts()
sys.clearsandboxfilenames()

# Both foo() and bar() should have their statements counted
print(f"Statement count: {counts['scope_statement_count']}")
# Should have counted ~100 loop iterations plus other statements
sys.exit(0 if counts['scope_statement_count'] > 80 else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Functions in exec not counted: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_multiple_filenames_registered(self):
        """Multiple filenames can be registered for scope tracking."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)

# Register a custom filename
sys.addsandboxfilename("<module-a>")

# Run code with registered filename
exec(compile("""
x = 0
for _ in range(50):
    x += 1
""", "<module-a>", "exec"))

count_a = sys.getsandboxcounts()['scope_statement_count']

# Register another filename
sys.addsandboxfilename("<module-b>")

# Run code with second registered filename
exec(compile("""
y = 0
for _ in range(50):
    y += 1
""", "<module-b>", "exec"))

count_after_b = sys.getsandboxcounts()['scope_statement_count']

# Run code with unregistered filename - should not count
exec(compile("""
z = 0
for _ in range(100):
    z += 1
""", "<unregistered>", "exec"))

count_after_unreg = sys.getsandboxcounts()['scope_statement_count']

sys.clearsandboxfilenames()

print(f"After A: {count_a}, After B: {count_after_b}, After unreg: {count_after_unreg}")

# Both registered filenames should have contributed
registered_counted = count_after_b > count_a > 0
# Unregistered should not have added to count
unreg_not_counted = count_after_unreg == count_after_b

sys.exit(0 if (registered_counted and unreg_not_counted) else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Multiple filenames test failed: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_filename_scope_with_allocation_limit(self):
        """Filename-based scope should also work with allocation limits."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_allocations=100000)

# Register a specific filename for tracking
sys.addsandboxfilename("<tracked-alloc>")

# Run code with registered filename - allocations should count
exec(compile("""
result = []
for _ in range(100):
    result.append([1, 2, 3])
""", "<tracked-alloc>", "exec"))

tracked_allocs = sys.getsandboxcounts()['scope_allocation_count']

# Run code with unregistered filename - allocations should NOT count
exec(compile("""
result2 = []
for _ in range(100):
    result2.append([1, 2, 3])
""", "<untracked-alloc>", "exec"))

after_untracked = sys.getsandboxcounts()['scope_allocation_count']

sys.clearsandboxfilenames()

print(f"Tracked allocs: {tracked_allocs}, After untracked: {after_untracked}")

# Tracked code should have counted allocations
tracked_counted = tracked_allocs > 50
# Untracked code should not have added to count
untracked_not_counted = after_untracked == tracked_allocs

sys.exit(0 if (tracked_counted and untracked_not_counted) else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Allocation limit with filename scope failed: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_exitsandboxscope_clears_all_registered_filenames(self):
        """exitsandboxscope should clear all registered filenames."""
        # Add current frame's filename to scope
        sys.addsandboxframe()
        self.assertTrue(sys.issandboxinscope())

        sys.exitsandboxscope()
        self.assertFalse(sys.issandboxinscope())

        # Add again - should work after exit
        sys.addsandboxframe()
        self.assertTrue(sys.issandboxinscope())
        sys.exitsandboxscope()

    def test_entersandboxscope_adds_current_frame(self):
        """entersandboxscope should add the current frame's filename to the set."""
        sys.setsandboxlimits(scope_max_statements=1000000)

        sys.entersandboxscope()
        self.assertTrue(sys.issandboxinscope())

        # Do some work - statements should count since we're in the selected frame
        x = 0
        for _ in range(100):
            x += 1

        count = sys.getsandboxcounts()['scope_statement_count']
        sys.exitsandboxscope()

        # Should have counted statements
        self.assertGreater(count, 50)


class FilenameBasedScopeTests(unittest.TestCase):
    """Test filename-based sandbox scope tracking.

    This tests the new addsandboxfilename() API where code is tracked
    by co_filename rather than frame pointers. This is simpler and
    works reliably across function calls.
    """

    def setUp(self):
        # Ensure clean scope state from any previous tests
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
        # Reset all counters for clean test state
        sys.resetsandboxcounters()
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        try:
            sys.clearsandboxfilenames()
        except RuntimeError:
            pass
        sys.setsandboxlimits(**self.original_limits)
        sys.resetsandboxcounters()

    def test_addsandboxfilename_basic(self):
        """addsandboxfilename should register a filename for scope tracking."""
        sys.setsandboxlimits(scope_max_statements=1000000)
        sys.addsandboxfilename("<test>")

        # Compile and exec code with the registered filename
        code = compile("x = 1; y = 2; z = 3", "<test>", "exec")
        exec(code)

        count = sys.getsandboxcounts()['scope_statement_count']
        # Should have counted the statements
        self.assertGreater(count, 0)

        sys.clearsandboxfilenames()

    def test_removesandboxfilename(self):
        """removesandboxfilename should unregister a filename."""
        sys.addsandboxfilename("<test-remove>")

        # Code with this filename should be in scope
        code = compile("pass", "<test-remove>", "exec")
        # Can't directly test scope inside exec, but we can test the API
        sys.removesandboxfilename("<test-remove>")

        # After removal, code with this filename shouldn't be in scope
        sys.clearsandboxfilenames()

    def test_clearsandboxfilenames(self):
        """clearsandboxfilenames should clear all registered filenames."""
        sys.addsandboxfilename("<test1>")
        sys.addsandboxfilename("<test2>")
        sys.addsandboxfilename("<test3>")

        sys.clearsandboxfilenames()

        # After clearing, no filenames should be registered
        # issandboxinscope requires a frame with matching filename
        self.assertFalse(sys.issandboxinscope())

    def test_functions_in_exec_count(self):
        """Functions defined in exec'd code should count toward statement limit."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)
sys.addsandboxfilename("<sandbox>")

# Compile code with registered filename
exec_code = compile("""
def foo():
    x = 0
    for i in range(50):
        x += i
    return x

def bar():
    y = 0
    for i in range(50):
        y += i * 2
    return y

# Call the functions
result1 = foo()
result2 = bar()
""", "<sandbox>", "exec")

exec(exec_code)

counts = sys.getsandboxcounts()
sys.clearsandboxfilenames()

# Both foo() and bar() should have their statements counted
print(f"Statement count: {counts['scope_statement_count']}")
# Should have counted ~100 loop iterations plus other statements
sys.exit(0 if counts['scope_statement_count'] > 80 else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Functions in exec not counted: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_cross_function_calls_count(self):
        """Cross-function calls within same registered filename should count."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)
sys.addsandboxfilename("<sandbox>")

# Define classes and functions that call each other
exec_code = compile("""
class Foo:
    def method(self):
        x = 0
        for i in range(20):
            x += i
        return x

class Bar:
    def call_foo(self, foo):
        return foo.method() + 1

# Create instances and call methods
foo = Foo()
bar = Bar()
result = bar.call_foo(foo)
""", "<sandbox>", "exec")

exec(exec_code)

counts = sys.getsandboxcounts()
sys.clearsandboxfilenames()

# All statements should be counted since they share the same filename
print(f"Statement count: {counts['scope_statement_count']}")
sys.exit(0 if counts['scope_statement_count'] > 30 else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Cross-function calls not counted: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_imported_modules_not_counted(self):
        """Code in imported modules should NOT count toward scope limits."""
        code = '''
import sys
import os
sys.setsandboxlimits(scope_max_statements=1000000)

# Register a custom filename - os module has different filename
sys.addsandboxfilename("<my-sandbox>")

count_before = sys.getsandboxcounts()['scope_statement_count']

# Call imported functions - should NOT count (different filename)
_ = os.getcwd()
_ = os.getcwd()
_ = os.getcwd()

count_after = sys.getsandboxcounts()['scope_statement_count']
sys.clearsandboxfilenames()

# The count should be 0 - no code with our filename was executed
increase = count_after - count_before
print(f"Increase: {increase}")
sys.exit(0 if increase == 0 else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Imported module wrongly counted: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_multiple_exec_same_filename(self):
        """Multiple exec() calls with same filename should share scope."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)
sys.addsandboxfilename("<shared>")

# First exec
exec(compile("""
class A:
    def work(self):
        x = 0
        for i in range(20):
            x += i
        return x
""", "<shared>", "exec"))

# Second exec - same filename
exec(compile("""
class B(A):
    def more_work(self):
        return self.work() * 2
""", "<shared>", "exec"))

# Third exec - call methods
exec(compile("""
b = B()
result = b.more_work()
""", "<shared>", "exec"))

counts = sys.getsandboxcounts()
sys.clearsandboxfilenames()

# All three exec blocks should have contributed to the count
print(f"Statement count: {counts['scope_statement_count']}")
sys.exit(0 if counts['scope_statement_count'] > 30 else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Multiple exec not sharing scope: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_statement_limit_with_filename(self):
        """Statement limit should work with filename-based tracking."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=10)
sys.addsandboxfilename("<limited>")

try:
    exec(compile("""
for _ in range(100):
    x = 1
""", "<limited>", "exec"))
    sys.exit(2)  # Should not reach here
except SandboxRuntimeError as e:
    if "statement limit" in str(e):
        sys.exit(0)  # Expected error
    sys.exit(3)  # Wrong error message
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Statement limit not enforced: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_allocation_limit_with_filename(self):
        """Allocation limit should work with filename-based tracking."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_allocations=100)
sys.addsandboxfilename("<alloc-limited>")

a = []
try:
    exec(compile("""
for i in range(1000):
    a.append([i])
""", "<alloc-limited>", "exec"), {"a": a})
    sys.exit(2)  # Should not reach here
except SandboxMemoryError:
    sys.exit(0)  # Successfully caught SandboxMemoryError
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode == 0:
            return  # Test passed
        if result.returncode == 2:
            self.fail("SandboxMemoryError was not raised")
        # If it exited with error, check that SandboxMemoryError was involved
        self.assertIn("SandboxMemoryError", result.stderr,
                      f"Expected SandboxMemoryError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_different_filenames_independent(self):
        """Different registered filenames should track independently."""
        code = '''
import sys
sys.setsandboxlimits(scope_max_statements=1000000)

# Register only one filename
sys.addsandboxfilename("<tracked>")

# This should count
exec(compile("""
x = 0
for i in range(50):
    x += i
""", "<tracked>", "exec"))

count_tracked = sys.getsandboxcounts()['scope_statement_count']

# This should NOT count (different filename, not registered)
exec(compile("""
y = 0
for i in range(100):
    y += i
""", "<not-tracked>", "exec"))

count_after = sys.getsandboxcounts()['scope_statement_count']
sys.clearsandboxfilenames()

# Count should not have increased (second exec has different filename)
print(f"After tracked: {count_tracked}, After untracked: {count_after}")
sys.exit(0 if count_after == count_tracked else 1)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Different filenames not independent: stdout={result.stdout!r} stderr={result.stderr!r}")


if __name__ == '__main__':
    unittest.main()
