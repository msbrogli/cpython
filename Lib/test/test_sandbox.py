"""Tests for the sandbox functionality in sys module."""

import subprocess
import sys
import unittest


# Default timeout for subprocess tests (seconds)
SUBPROCESS_TIMEOUT = 10

# Test limit values - chosen to be large enough for normal test operations
# but small enough to trigger limit checks quickly
TEST_LIST_LIMIT = 500
TEST_DICT_LIMIT = 500
TEST_SET_LIMIT = 500
TEST_TUPLE_LIMIT = 500
TEST_STR_LIMIT = 100
TEST_INT_DIGITS_LIMIT = 5  # ~45 decimal digits (each internal digit ~9 decimals)


def _run_sandboxed_code(code, timeout=SUBPROCESS_TIMEOUT):
    """Run code in a subprocess with sandbox limits.

    Args:
        code: Python code to execute as a string
        timeout: Maximum time to wait for the subprocess (seconds)

    Returns:
        subprocess.CompletedProcess with returncode, stdout, and stderr
    """
    return subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        timeout=timeout
    )


def _get_settable_limits():
    """Get current limits for restoring in tearDown."""
    return sys.getsandboxlimits()


class SandboxLimitsTests(unittest.TestCase):
    """Test sandbox limits functionality."""

    def setUp(self):
        # Save original limits (excluding read-only fields)
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        # Restore original limits
        sys.setsandboxlimits(**self.original_limits)
        # Exit scope if entered
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass

    def test_getsandboxlimits_returns_dict(self):
        """getsandboxlimits should return a dictionary with all limit keys."""
        limits = sys.getsandboxlimits()
        self.assertIsInstance(limits, dict)
        expected_keys = {
            'max_int_digits', 'max_str_length', 'max_bytes_length',
            'max_list_size', 'max_dict_size', 'max_set_size', 'max_tuple_size',
            'global_max_allocations', 'scope_max_statements', 'scope_max_allocations',
            'scope_max_iterations', 'allow_float', 'allow_complex', 'allow_dunder_access'
        }
        self.assertEqual(set(limits.keys()), expected_keys)

    def test_getsandboxcounts_returns_dict(self):
        """getsandboxcounts should return a dictionary with count keys."""
        counts = sys.getsandboxcounts()
        self.assertIsInstance(counts, dict)
        expected_keys = {'global_allocation_count', 'scope_allocation_count', 'scope_statement_count', 'scope_iteration_count'}
        self.assertEqual(set(counts.keys()), expected_keys)

    def test_default_limits_are_zero(self):
        """Default limits should be 0 (no limit) and types allowed."""
        limits = sys.getsandboxlimits()
        self.assertEqual(limits['max_int_digits'], 0)
        self.assertEqual(limits['max_str_length'], 0)
        self.assertEqual(limits['max_bytes_length'], 0)
        self.assertEqual(limits['max_list_size'], 0)
        self.assertEqual(limits['max_dict_size'], 0)
        self.assertEqual(limits['max_set_size'], 0)
        self.assertEqual(limits['max_tuple_size'], 0)
        self.assertEqual(limits['global_max_allocations'], 0)
        self.assertEqual(limits['scope_max_statements'], 0)
        self.assertEqual(limits['scope_max_allocations'], 0)
        self.assertTrue(limits['allow_float'])
        self.assertTrue(limits['allow_complex'])
        self.assertTrue(limits['allow_dunder_access'])

    def test_setsandboxlimits_updates_limits(self):
        """setsandboxlimits should update the limits."""
        sys.setsandboxlimits(max_int_digits=100, max_str_length=1000)
        limits = sys.getsandboxlimits()
        self.assertEqual(limits['max_int_digits'], 100)
        self.assertEqual(limits['max_str_length'], 1000)


class IntegerLimitsTests(unittest.TestCase):
    """Test integer size limits.

    Note: max_int_digits is in internal digits (each ~30 bits = ~9 decimal digits),
    not decimal digits.
    """

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)

    def test_small_integers_allowed(self):
        """Small integers should always be allowed."""
        sys.setsandboxlimits(max_int_digits=TEST_INT_DIGITS_LIMIT)
        x = 12345
        self.assertEqual(x, 12345)

    def test_large_integers_blocked(self):
        """Large integers exceeding limit should raise SandboxOverflowError."""
        sys.setsandboxlimits(max_int_digits=TEST_INT_DIGITS_LIMIT)
        # 10^50 requires about 6 internal digits
        with self.assertRaises(SandboxOverflowError) as cm:
            x = 10 ** 50
        self.assertIn("sandbox limit", str(cm.exception))

    def test_no_limit_allows_large_integers(self):
        """With no limit (0), large integers should be allowed."""
        sys.setsandboxlimits(max_int_digits=0)
        x = 10 ** 100  # Should work
        self.assertIsInstance(x, int)


class StringLimitsTests(unittest.TestCase):
    """Test string length limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)

    def test_small_strings_allowed(self):
        """Small strings should always be allowed."""
        sys.setsandboxlimits(max_str_length=TEST_STR_LIMIT)
        s = "hello world"
        self.assertEqual(s, "hello world")

    def test_large_strings_blocked(self):
        """Large strings exceeding limit should raise SandboxOverflowError."""
        sys.setsandboxlimits(max_str_length=TEST_STR_LIMIT)
        with self.assertRaises(SandboxOverflowError) as cm:
            # Use join to trigger PyUnicode_New
            s = ''.join(['x' for _ in range(200)])
        self.assertIn("sandbox limit", str(cm.exception))


class ListLimitsTests(unittest.TestCase):
    """Test list size limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)

    def test_small_lists_allowed(self):
        """Small lists should always be allowed."""
        sys.setsandboxlimits(max_list_size=100)
        lst = [1, 2, 3, 4, 5]
        self.assertEqual(len(lst), 5)

    def test_large_lists_blocked(self):
        """Large lists exceeding limit via append should raise SandboxOverflowError."""
        sys.setsandboxlimits(max_list_size=100)
        lst = []
        with self.assertRaises(SandboxOverflowError) as cm:
            for i in range(150):
                lst.append(i)
        self.assertIn("sandbox limit", str(cm.exception))


class DictLimitsTests(unittest.TestCase):
    """Test dict size limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)

    def test_small_dicts_allowed(self):
        """Small dicts should always be allowed."""
        sys.setsandboxlimits(max_dict_size=TEST_DICT_LIMIT)
        d = {'a': 1, 'b': 2}
        self.assertEqual(len(d), 2)

    def test_large_dicts_blocked(self):
        """Large dicts exceeding limit should raise SandboxOverflowError."""
        sys.setsandboxlimits(max_dict_size=TEST_DICT_LIMIT)
        d = {}
        with self.assertRaises(SandboxOverflowError) as cm:
            for i in range(600):
                d[i] = i
        self.assertIn("sandbox limit", str(cm.exception))


class SetLimitsTests(unittest.TestCase):
    """Test set size limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)

    def test_small_sets_allowed(self):
        """Small sets should always be allowed."""
        sys.setsandboxlimits(max_set_size=TEST_SET_LIMIT)
        s = {1, 2, 3}
        self.assertEqual(len(s), 3)

    def test_large_sets_blocked(self):
        """Large sets exceeding limit should raise SandboxOverflowError."""
        sys.setsandboxlimits(max_set_size=TEST_SET_LIMIT)
        s = set()
        with self.assertRaises(SandboxOverflowError) as cm:
            for i in range(600):
                s.add(i)
        self.assertIn("sandbox limit", str(cm.exception))


class TupleLimitsTests(unittest.TestCase):
    """Test tuple size limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)

    def test_small_tuples_allowed(self):
        """Small tuples should always be allowed."""
        sys.setsandboxlimits(max_tuple_size=TEST_TUPLE_LIMIT)
        t = (1, 2, 3, 4, 5)
        self.assertEqual(len(t), 5)

    def test_large_tuples_blocked(self):
        """Large tuples exceeding limit should raise SandboxOverflowError."""
        sys.setsandboxlimits(max_tuple_size=TEST_TUPLE_LIMIT)
        with self.assertRaises(SandboxOverflowError) as cm:
            t = tuple(range(600))
        self.assertIn("sandbox limit", str(cm.exception))


class TypeRestrictionTests(unittest.TestCase):
    """Test type restriction (float, complex)."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)

    def test_float_allowed_by_default(self):
        """Float creation should be allowed by default."""
        f = float(1)
        self.assertEqual(f, 1.0)

    def test_float_blocked_when_disabled(self):
        """Float creation should raise SandboxTypeError when disabled."""
        sys.setsandboxlimits(allow_float=False)
        with self.assertRaises(SandboxTypeError) as cm:
            f = float(1)
        self.assertIn("forbidden", str(cm.exception))

    def test_complex_allowed_by_default(self):
        """Complex creation should be allowed by default."""
        c = complex(1, 2)
        self.assertEqual(c, 1+2j)

    def test_complex_blocked_when_disabled(self):
        """Complex creation should raise SandboxTypeError when disabled."""
        sys.setsandboxlimits(allow_complex=False)
        with self.assertRaises(SandboxTypeError) as cm:
            c = complex(1, 2)
        self.assertIn("forbidden", str(cm.exception))


class ObjectCreationHookTests(unittest.TestCase):
    """Test object creation hook functionality."""

    def setUp(self):
        self.original_hook = sys.getobjectcreationhook()

    def tearDown(self):
        sys.setobjectcreationhook(self.original_hook)

    def test_getobjectcreationhook_default_none(self):
        """Default hook should be None."""
        sys.setobjectcreationhook(None)
        self.assertIsNone(sys.getobjectcreationhook())

    def test_setobjectcreationhook_requires_callable(self):
        """setobjectcreationhook should require a callable."""
        with self.assertRaises(TypeError):
            sys.setobjectcreationhook("not callable")

    def test_setobjectcreationhook_accepts_none(self):
        """setobjectcreationhook should accept None."""
        sys.setobjectcreationhook(None)
        self.assertIsNone(sys.getobjectcreationhook())

    def test_hook_called_on_object_creation(self):
        """Hook should be called when creating objects."""
        created_objects = []

        def hook(obj, type_, frame, context):
            created_objects.append((type_.__name__, context))
            return obj

        sys.setobjectcreationhook(hook)

        class MyClass:
            pass

        instance = MyClass()

        # Check that our class creation was captured
        found = any(name == 'MyClass' for name, _ in created_objects)
        self.assertTrue(found, f"Expected MyClass in {created_objects}")

    def test_hook_can_block_creation(self):
        """Hook can raise exception to block object creation."""
        def blocking_hook(obj, type_, frame, context):
            if type_.__name__ == 'BlockedClass':
                raise ValueError("Creation blocked by hook")
            return obj

        sys.setobjectcreationhook(blocking_hook)

        class BlockedClass:
            pass

        with self.assertRaises(ValueError) as cm:
            instance = BlockedClass()
        self.assertIn("blocked by hook", str(cm.exception))


class MinimalSafeLimitsTests(unittest.TestCase):
    """Test that minimal safe limits don't interfere with Python internals."""

    # Recommended minimal limits
    MINIMAL_LIMITS = {
        'max_int_digits': 100,       # ~10^900
        'max_str_length': 100000,    # 100KB
        'max_bytes_length': 100000,  # 100KB
        'max_list_size': 10000,
        'max_dict_size': 10000,
        'max_set_size': 10000,
        'max_tuple_size': 10000,
    }

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)

    def test_minimal_limits_allow_imports(self):
        """Minimal limits should allow standard library imports."""
        sys.setsandboxlimits(**self.MINIMAL_LIMITS)

        # These imports use internal strings, dicts, lists
        import json
        import re
        import collections
        import functools
        import urllib.parse

    def test_minimal_limits_allow_basic_operations(self):
        """Minimal limits should allow basic Python operations."""
        sys.setsandboxlimits(**self.MINIMAL_LIMITS)

        # Create containers within limits
        d = {str(i): i for i in range(1000)}
        l = list(range(1000))
        s = set(range(1000))
        t = tuple(range(1000))

        self.assertEqual(len(d), 1000)
        self.assertEqual(len(l), 1000)
        self.assertEqual(len(s), 1000)
        self.assertEqual(len(t), 1000)

    def test_minimal_limits_block_excessive_resources(self):
        """Minimal limits should block excessive resource usage."""
        sys.setsandboxlimits(**self.MINIMAL_LIMITS)

        # Should block very large integers
        with self.assertRaises(SandboxOverflowError):
            x = 10 ** 1000  # Requires ~110 internal digits

        # Should block very long strings
        with self.assertRaises(SandboxOverflowError):
            s = ''.join(['x' for _ in range(200000)])


class SuspendResumeLimitsTests(unittest.TestCase):
    """Test suspend/resume functionality for syscalls."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        # Ensure limits are resumed
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        sys.setsandboxlimits(**self.original_limits)

    def test_suspend_bypasses_limits(self):
        """Suspended limits should allow exceeding normal limits."""
        sys.setsandboxlimits(max_list_size=10)

        # Should fail with limits active
        with self.assertRaises(SandboxOverflowError):
            list(range(20))

        # Suspend and try again
        sys.suspendsandboxlimits()
        self.assertTrue(sys.issandboxsuspended())

        # Should succeed while suspended
        lst = list(range(20))
        self.assertEqual(len(lst), 20)

    def test_resume_reactivates_limits(self):
        """Resumed limits should block operations again."""
        sys.setsandboxlimits(max_list_size=10)
        sys.suspendsandboxlimits()

        # Works while suspended
        lst = list(range(20))
        self.assertEqual(len(lst), 20)

        # Resume limits
        sys.resumesandboxlimits()
        self.assertFalse(sys.issandboxsuspended())

        # Should fail again
        with self.assertRaises(SandboxOverflowError):
            list(range(20))

    def test_nested_suspend_resume(self):
        """Nested suspend/resume should work correctly."""
        sys.setsandboxlimits(max_list_size=10)

        # First suspend
        count1 = sys.suspendsandboxlimits()
        self.assertEqual(count1, 1)
        self.assertTrue(sys.issandboxsuspended())

        # Nested suspend
        count2 = sys.suspendsandboxlimits()
        self.assertEqual(count2, 2)

        # First resume - still suspended
        count3 = sys.resumesandboxlimits()
        self.assertEqual(count3, 1)
        self.assertTrue(sys.issandboxsuspended())

        # Should still work
        lst = list(range(20))
        self.assertEqual(len(lst), 20)

        # Second resume - now active
        count4 = sys.resumesandboxlimits()
        self.assertEqual(count4, 0)
        self.assertFalse(sys.issandboxsuspended())

        # Should fail now
        with self.assertRaises(SandboxOverflowError):
            list(range(20))


class GlobalAllocationCountLimitsTests(unittest.TestCase):
    """Test global allocation counting limits for GC-tracked objects."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        # Ensure limits are resumed
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        sys.setsandboxlimits(**self.original_limits)
        sys.resetsandboxcounters()

    def test_set_and_get_global_max_allocations(self):
        """Setting and getting global_max_allocations should work."""
        sys.setsandboxlimits(global_max_allocations=10000)
        limits = sys.getsandboxlimits()
        self.assertEqual(limits['global_max_allocations'], 10000)

    def test_global_allocation_count_tracked(self):
        """Global allocation count should be tracked."""
        sys.resetsandboxcounters()
        initial = sys.getsandboxcounts()['global_allocation_count']
        self.assertEqual(initial, 0)

        # Create some objects
        _ = [1, 2, 3]
        _ = {'a': 1}
        _ = (1, 2)

        count = sys.getsandboxcounts()['global_allocation_count']
        self.assertGreater(count, 0)

    def test_exceeding_global_allocation_limit_raises_memory_error(self):
        """Exceeding global allocation limit should raise SandboxMemoryError."""
        # Use a higher limit to allow for error handling allocations
        code = '''
import sys
sys.setsandboxlimits(global_max_allocations=1000)
sys.resetsandboxcounters()
a = []
try:
    for i in range(2000):
        a = [a]
    sys.exit(2)  # Should not reach here
except SandboxMemoryError:
    sys.exit(0)  # Successfully caught SandboxMemoryError
'''
        result = _run_sandboxed_code(code)
        # The process should complete (not hang) and either:
        # - Return 0 (caught SandboxMemoryError successfully)
        # - Return non-zero with SandboxMemoryError indication (error handling failed)
        if result.returncode == 0:
            return  # Test passed
        if result.returncode == 2:
            self.fail("SandboxMemoryError was not raised")
        # If it exited with error, check that SandboxMemoryError was involved
        self.assertIn("SandboxMemoryError", result.stderr,
                      f"Expected SandboxMemoryError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_reset_global_allocation_count(self):
        """resetsandboxcounters should reset global allocation counter to 0."""
        sys.setsandboxlimits(global_max_allocations=1000)

        # Create some objects
        for _ in range(10):
            _ = [1, 2, 3]

        count_before = sys.getsandboxcounts()['global_allocation_count']
        self.assertGreater(count_before, 0)

        sys.resetsandboxcounters()
        count_after = sys.getsandboxcounts()['global_allocation_count']
        self.assertEqual(count_after, 0)

    def test_allocations_while_suspended_dont_count(self):
        """Allocations while suspended should not count toward limit."""
        sys.setsandboxlimits(global_max_allocations=100)
        sys.resetsandboxcounters()

        # Suspend and create lots of objects
        sys.suspendsandboxlimits()
        for _ in range(200):
            _ = [1, 2, 3]
        count_suspended = sys.getsandboxcounts()['global_allocation_count']

        sys.resumesandboxlimits()

        # Should still be at a low count (suspended allocations didn't count)
        self.assertLess(count_suspended, 100)

    def test_no_limit_allows_many_allocations(self):
        """With no limit (0), many allocations should be allowed."""
        sys.setsandboxlimits(global_max_allocations=0)
        sys.resetsandboxcounters()

        # Create many objects - should not raise
        for _ in range(1000):
            _ = [1, 2, 3]


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


class ScopedAllocationCountTests(unittest.TestCase):
    """Test scoped allocation counting."""

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

    def test_set_and_get_scope_max_allocations(self):
        """Setting and getting scope_max_allocations should work."""
        sys.setsandboxlimits(scope_max_allocations=5000)
        limits = sys.getsandboxlimits()
        self.assertEqual(limits['scope_max_allocations'], 5000)

    def test_scoped_allocation_count_tracked(self):
        """Scoped allocation count should be tracked when in scope."""
        sys.setsandboxlimits(scope_max_allocations=10000)
        sys.entersandboxscope()

        # Create many objects and KEEP REFERENCES so they don't get garbage collected
        # (getsandboxcounts() itself allocates, so we need significant margin)
        result = []
        for _ in range(100):
            result.append([1, 2, 3])
            result.append({'a': 1})

        count = sys.getsandboxcounts()['scope_allocation_count']
        # After 200 object creations, should have significant allocations
        self.assertGreater(count, 50)

    def test_exceeding_scoped_allocation_limit_raises_memory_error(self):
        """Exceeding scoped allocation limit should raise SandboxMemoryError."""
        import subprocess
        code = '''
import sys
sys.setsandboxlimits(scope_max_allocations=100)
sys.entersandboxscope()
a = []
try:
    for i in range(1200):
        a = [a]
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

    def test_reset_scope_allocation_count(self):
        """resetsandboxcounters should reset scope allocation counter."""
        sys.setsandboxlimits(scope_max_allocations=10000)
        sys.entersandboxscope()

        # Create many objects and KEEP REFERENCES so they don't get garbage collected
        result = []
        for _ in range(100):
            result.append([1, 2, 3])

        counts_before = sys.getsandboxcounts()
        self.assertGreater(counts_before['scope_allocation_count'], 20)

        sys.resetsandboxcounters()
        counts_after = sys.getsandboxcounts()
        # Count may not be exactly 0 due to dict allocation in getsandboxcounts
        self.assertLess(counts_after['scope_allocation_count'], 10)

    def test_allocations_outside_scope_dont_count_scoped(self):
        """Allocations outside scope should not count toward scoped limit."""
        sys.setsandboxlimits(scope_max_allocations=10000)
        sys.resetsandboxcounters()

        # Not in scope - create many objects and KEEP REFERENCES
        result = []
        for _ in range(100):
            result.append([1, 2, 3])

        counts = sys.getsandboxcounts()
        # Global should count (some allocations for the loops and lists)
        self.assertGreater(counts['global_allocation_count'], 10)
        # Scoped should not count (not in scope)
        self.assertEqual(counts['scope_allocation_count'], 0)

    def test_global_and_scoped_counts_independent(self):
        """Global and scoped allocation counts should be tracked independently."""
        sys.setsandboxlimits(global_max_allocations=100000, scope_max_allocations=10000)
        sys.resetsandboxcounters()

        # Create many objects outside scope and KEEP REFERENCES
        result = []
        for _ in range(100):
            result.append([1, 2, 3])

        global_before = sys.getsandboxcounts()['global_allocation_count']
        self.assertGreater(global_before, 10)
        self.assertEqual(sys.getsandboxcounts()['scope_allocation_count'], 0)

        # Enter scope and create more objects
        sys.entersandboxscope()
        result2 = []
        for _ in range(100):
            result2.append([1, 2, 3])

        counts = sys.getsandboxcounts()
        # Both should have increased
        self.assertGreater(counts['global_allocation_count'], global_before)
        self.assertGreater(counts['scope_allocation_count'], 10)


class IntegrationTests(unittest.TestCase):
    """Integration tests for sandbox functionality."""

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

    def test_sandbox_exec_with_all_limits(self):
        """Test running sandboxed code with all limit types."""
        import subprocess
        code = '''
import sys
sys.setsandboxlimits(
    max_int_digits=100,
    max_str_length=10000,
    max_list_size=1000,
    global_max_allocations=100000,
    scope_max_statements=10000,
    scope_max_allocations=5000,
)
sys.resetsandboxcounters()
sys.entersandboxscope()
try:
    exec("""
result = []
for i in range(100):
    result.append(i * 2)
total = sum(result)
""")
    sys.exit(0)  # Success
except Exception as e:
    print(f"Unexpected error: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=10
        )
        self.assertEqual(result.returncode, 0,
                        f"Sandboxed exec failed: stdout={result.stdout!r} stderr={result.stderr!r}")


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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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
        import subprocess
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


class ScopedIterationCountTests(unittest.TestCase):
    """Tests for scoped iteration counting and limits.

    The iteration limit counts calls to PyIter_Next(), which is used by
    many C builtins like sum(), min(), max() when consuming iterators.
    This protects against infinite loops in C code that would otherwise
    bypass the statement limit.
    """

    def setUp(self):
        # Ensure clean scope state from any previous tests
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass
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

    def test_set_and_get_scope_max_iterations(self):
        """Setting and getting scope_max_iterations should work."""
        sys.setsandboxlimits(scope_max_iterations=50000)
        limits = sys.getsandboxlimits()
        self.assertEqual(limits['scope_max_iterations'], 50000)

    def test_iteration_count_tracked_with_sum(self):
        """Iteration count should be tracked when using sum()."""
        from itertools import islice, cycle
        sys.setsandboxlimits(scope_max_iterations=1000000)
        sys.resetsandboxcounters()
        sys.entersandboxscope()

        # Use sum() which calls PyIter_Next
        _ = sum(islice(cycle([1, 2, 3]), 100))

        counts = sys.getsandboxcounts()
        self.assertGreater(counts['scope_iteration_count'], 0)
        sys.exitsandboxscope()

    def test_exceeding_iteration_limit_raises_runtime_error(self):
        """Exceeding iteration limit should raise SandboxRuntimeError."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=1000)
sys.resetsandboxcounters()
sys.entersandboxscope()
try:
    # This should raise SandboxRuntimeError when iteration limit is exceeded
    sum(cycle([0, 1]))
    sys.exit(2)  # Should not reach here
except SandboxRuntimeError as e:
    if "iteration limit" in str(e).lower():
        sys.exit(0)  # Success
    else:
        print(f"Wrong error: {e}", file=sys.stderr)
        sys.exit(1)
except Exception as e:
    print(f"Wrong exception type: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected SandboxRuntimeError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_normal_iteration_within_limit_works(self):
        """Normal iteration within limits should work fine."""
        from itertools import islice, cycle
        sys.setsandboxlimits(scope_max_iterations=1000000)
        sys.resetsandboxcounters()
        sys.entersandboxscope()

        # This should work fine
        # cycle([1, 2, 3]) for 999 items: 333 complete cycles of (1+2+3=6) = 1998
        result = sum(islice(cycle([1, 2, 3]), 999))
        self.assertEqual(result, 1998)

        sys.exitsandboxscope()

    def test_iteration_limit_protects_sum_with_infinite_iterator(self):
        """Iteration limit should protect against sum() with infinite iterator."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=500)
sys.entersandboxscope()
try:
    sum(cycle([0]))  # Infinite iterator
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError:
    print("PASS: SandboxRuntimeError raised")
    sys.exit(0)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Iteration limit didn't protect sum(): {result.stdout!r} {result.stderr!r}")

    def test_reset_scope_iteration_count(self):
        """resetsandboxcounters should reset scope iteration counter."""
        from itertools import islice, cycle
        sys.setsandboxlimits(scope_max_iterations=1000000)

        sys.entersandboxscope()
        _ = sum(islice(cycle([1]), 100))
        sys.exitsandboxscope()

        count_before = sys.getsandboxcounts()['scope_iteration_count']
        self.assertGreater(count_before, 0)

        sys.resetsandboxcounters()
        count_after = sys.getsandboxcounts()['scope_iteration_count']
        self.assertEqual(count_after, 0)

    def test_no_iteration_limit_allows_many_iterations(self):
        """With no iteration limit (0), many iterations should be allowed."""
        from itertools import islice, cycle
        sys.setsandboxlimits(scope_max_iterations=0)
        sys.resetsandboxcounters()
        sys.entersandboxscope()

        # This should work with no limit
        result = sum(islice(cycle([1]), 10000))
        self.assertEqual(result, 10000)

        sys.exitsandboxscope()

    def test_enter_scope_resets_iteration_count(self):
        """entersandboxscope should reset iteration counters."""
        from itertools import islice, cycle
        sys.setsandboxlimits(scope_max_iterations=1000000)

        # First scope with some iterations
        sys.entersandboxscope()
        _ = sum(islice(cycle([1]), 100))
        count1 = sys.getsandboxcounts()['scope_iteration_count']
        sys.exitsandboxscope()

        # Second scope should start fresh
        sys.entersandboxscope()
        count2 = sys.getsandboxcounts()['scope_iteration_count']
        sys.exitsandboxscope()

        self.assertGreater(count1, 0)
        self.assertEqual(count2, 0)


class IteratorWrapperProtectionTests(unittest.TestCase):
    """Test iterator wrapper protection for direct tp_iternext callers.

    These tests verify that builtins like list(), tuple(), set() that
    call tp_iternext directly are now protected by the iterator wrapper
    approach. The wrapper is applied in PyObject_GetIter() and checks
    iteration limits on each step.
    """

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass

    def test_list_iteration_protected(self):
        """list() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = list(cycle([0, 1]))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"list() not protected: {result.stdout!r} {result.stderr!r}")

    def test_tuple_iteration_protected(self):
        """tuple() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = tuple(cycle([0, 1]))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"tuple() not protected: {result.stdout!r} {result.stderr!r}")

    def test_set_iteration_protected(self):
        """set() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import count

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = set(count())  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"set() not protected: {result.stdout!r} {result.stderr!r}")

    def test_frozenset_iteration_protected(self):
        """frozenset() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import count

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = frozenset(count())  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"frozenset() not protected: {result.stdout!r} {result.stderr!r}")

    def test_all_iteration_protected(self):
        """all() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = all(cycle([True]))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"all() not protected: {result.stdout!r} {result.stderr!r}")

    def test_any_with_all_false_iteration_protected(self):
        """any() of infinite iterator (all False) is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = any(cycle([False]))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"any() not protected: {result.stdout!r} {result.stderr!r}")

    def test_for_loop_iteration_protected(self):
        """for loop over infinite iterator is protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    for x in cycle([0]):  # Should hit iteration limit
        pass
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"for loop not protected: {result.stdout!r} {result.stderr!r}")

    def test_enumerate_iteration_protected(self):
        """enumerate() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = list(enumerate(cycle([0])))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"enumerate() not protected: {result.stdout!r} {result.stderr!r}")

    def test_zip_iteration_protected(self):
        """zip() of infinite iterators is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = list(zip(cycle([0]), cycle([1])))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"zip() not protected: {result.stdout!r} {result.stderr!r}")

    def test_map_iteration_protected(self):
        """map() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = list(map(lambda x: x, cycle([0])))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"map() not protected: {result.stdout!r} {result.stderr!r}")

    def test_filter_iteration_protected(self):
        """filter() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = list(filter(lambda x: True, cycle([0])))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"filter() not protected: {result.stdout!r} {result.stderr!r}")

    def test_sorted_iteration_protected(self):
        """sorted() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import count

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = sorted(count())  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"sorted() not protected: {result.stdout!r} {result.stderr!r}")

    def test_min_iteration_protected(self):
        """min() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = min(cycle([1, 2, 3]))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"min() not protected: {result.stdout!r} {result.stderr!r}")

    def test_max_iteration_protected(self):
        """max() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=100)
sys.entersandboxscope()
try:
    result = max(cycle([1, 2, 3]))  # Should hit iteration limit
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        print("PASS: SandboxRuntimeError raised")
        sys.exit(0)
    else:
        print(f"FAIL: Wrong error: {e}")
        sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"max() not protected: {result.stdout!r} {result.stderr!r}")

    def test_normal_iteration_still_works(self):
        """Normal iteration with finite iterables should still work."""
        code = '''
import sys

sys.setsandboxlimits(scope_max_iterations=1000)
sys.entersandboxscope()
try:
    # These should all work fine
    result1 = list(range(50))
    result2 = tuple(range(50))
    result3 = set(range(50))
    result4 = sum(range(50))
    result5 = [x for x in range(50)]
    if len(result1) == 50 and len(result2) == 50 and len(result3) == 50:
        print("PASS: Normal iteration works")
        sys.exit(0)
    else:
        print("FAIL: Wrong results")
        sys.exit(1)
except Exception as e:
    print(f"FAIL: Unexpected error: {e}")
    sys.exit(1)
finally:
    sys.exitsandboxscope()
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Normal iteration broken: {result.stdout!r} {result.stderr!r}")

    def test_wrapper_not_applied_outside_scope(self):
        """Iterator wrapper should not be applied outside sandbox scope."""
        from itertools import islice, cycle

        # Outside sandbox scope, iteration should work without limit check
        sys.setsandboxlimits(scope_max_iterations=10)
        # NOT entering scope

        # This should work even though limit is 10, because we're not in scope
        result = list(islice(cycle([1]), 100))
        self.assertEqual(len(result), 100)


class DunderAccessBlockingTests(unittest.TestCase):
    """Test dunder attribute blocking."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.setsandboxlimits(**self.original_limits)
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass

    def test_default_allows_dunder(self):
        """Default should allow dunder access."""
        limits = sys.getsandboxlimits()
        self.assertTrue(limits['allow_dunder_access'])

    def test_dunder_read_blocked(self):
        """Reading dunder attributes blocked when configured."""
        code = '''
import sys
sys.setsandboxlimits(allow_dunder_access=False)
sys.entersandboxscope()
x = {}
try:
    d = x.__class__
    print("ERROR: should have raised")
except SandboxAttributeError as e:
    print("OK:", e)
'''
        result = _run_sandboxed_code(code)
        self.assertIn("OK:", result.stdout)

    def test_dunder_write_blocked(self):
        """Writing dunder attributes blocked when configured."""
        code = '''
import sys
sys.setsandboxlimits(allow_dunder_access=False)
sys.entersandboxscope()
class Foo:
    pass
try:
    Foo.__doc__ = "hacked"
    print("ERROR: should have raised")
except SandboxAttributeError as e:
    print("OK:", e)
'''
        result = _run_sandboxed_code(code)
        self.assertIn("OK:", result.stdout)

    def test_dunder_delete_blocked(self):
        """Deleting dunder attributes blocked when configured."""
        code = '''
import sys
sys.setsandboxlimits(allow_dunder_access=False)
sys.entersandboxscope()
class Foo:
    __doc__ = "test"
try:
    del Foo.__doc__
    print("ERROR: should have raised")
except SandboxAttributeError as e:
    print("OK:", e)
'''
        result = _run_sandboxed_code(code)
        self.assertIn("OK:", result.stdout)

    def test_normal_attr_allowed(self):
        """Normal attributes still allowed when dunder blocked."""
        code = '''
import sys
sys.setsandboxlimits(allow_dunder_access=False)
sys.entersandboxscope()
class Foo:
    pass
Foo.bar = 42
print("OK:", Foo.bar)
'''
        result = _run_sandboxed_code(code)
        self.assertIn("OK: 42", result.stdout)

    def test_outside_scope_allowed(self):
        """Dunder access allowed outside sandbox scope."""
        code = '''
import sys
sys.setsandboxlimits(allow_dunder_access=False)
# NOT entering sandbox scope
x = {}
print("OK:", x.__class__.__name__)
'''
        result = _run_sandboxed_code(code)
        self.assertIn("OK: dict", result.stdout)

    def test_dunder_blocked_with_filename_scope(self):
        """Dunder blocking should work with filename-based scope tracking."""
        code = '''
import sys
sys.setsandboxlimits(allow_dunder_access=False)
sys.addsandboxfilename("<sandbox>")

try:
    exec(compile("""
x = {}
d = x.__class__
""", "<sandbox>", "exec"))
    print("ERROR: should have raised")
except SandboxAttributeError as e:
    print("OK:", e)
'''
        result = _run_sandboxed_code(code)
        self.assertIn("OK:", result.stdout)

    def test_dunder_allowed_when_enabled(self):
        """Dunder access allowed when allow_dunder_access is True."""
        code = '''
import sys
sys.setsandboxlimits(allow_dunder_access=True)
sys.entersandboxscope()
x = {}
print("OK:", x.__class__.__name__)
'''
        result = _run_sandboxed_code(code)
        self.assertIn("OK: dict", result.stdout)

    def test_single_underscore_allowed(self):
        """Single underscore attributes should still be allowed."""
        code = '''
import sys
sys.setsandboxlimits(allow_dunder_access=False)
sys.entersandboxscope()
class Foo:
    pass
Foo._private = 42
print("OK:", Foo._private)
'''
        result = _run_sandboxed_code(code)
        self.assertIn("OK: 42", result.stdout)


class FrozenModeTests(unittest.TestCase):
    """Test sandbox frozen mode functionality.

    Frozen mode prevents attribute addition, modification, and deletion
    on objects. It supports both a global freeze flag (in _PySandboxState)
    and per-instance freeze/mutable flags (in ob_flags).

    Frozen mode is scope-aware: restrictions are only enforced when the
    current executing frame's filename is in the registered sandbox scope.
    This means unittest framework code (running from unittest/case.py) is
    not affected, so self.assertRaises() works correctly.
    """

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.entersandboxscope()

    def tearDown(self):
        # Ensure frozen mode is disabled
        sys.setsandboxfrozenmode(False)
        # Ensure limits are resumed
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        sys.setsandboxlimits(**self.original_limits)
        # Exit sandbox scope
        try:
            sys.exitsandboxscope()
        except RuntimeError:
            pass

    # --- Global frozen mode: get/set ---

    def test_getsandboxfrozenmode_default_false(self):
        """Global frozen mode should be disabled by default."""
        self.assertFalse(sys.getsandboxfrozenmode())

    def test_setsandboxfrozenmode_enables(self):
        """setsandboxfrozenmode(True) should enable frozen mode."""
        sys.setsandboxfrozenmode(True)
        is_frozen = sys.getsandboxfrozenmode()
        sys.setsandboxfrozenmode(False)
        self.assertTrue(is_frozen)

    def test_setsandboxfrozenmode_disables(self):
        """setsandboxfrozenmode(False) should disable frozen mode."""
        sys.setsandboxfrozenmode(True)
        sys.setsandboxfrozenmode(False)
        self.assertFalse(sys.getsandboxfrozenmode())

    # --- Global frozen mode: blocks attribute set ---

    def test_frozen_mode_blocks_instance_setattr(self):
        """Frozen mode should block setting attributes on instances."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1  # Before freeze

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError) as cm:
            obj.y = 2
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_blocks_instance_delattr(self):
        """Frozen mode should block deleting attributes on instances."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError) as cm:
            del obj.x
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_blocks_type_setattr(self):
        """Frozen mode should block setting attributes on types."""
        class Foo:
            pass

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError) as cm:
            Foo.class_var = 42
        self.assertIn("frozen mode", str(cm.exception))

    def test_frozen_mode_allows_after_disable(self):
        """Disabling frozen mode should allow modifications again."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            obj.x = 1

        sys.setsandboxfrozenmode(False)
        obj.x = 1  # Should succeed now
        self.assertEqual(obj.x, 1)

    def test_frozen_mode_blocks_setattr_builtin(self):
        """Frozen mode should block setattr() builtin."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            setattr(obj, 'x', 1)

    def test_frozen_mode_blocks_delattr_builtin(self):
        """Frozen mode should block delattr() builtin."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            delattr(obj, 'x')

    # --- Per-instance freeze ---

    def test_sandboxfreezeobject_freezes_object(self):
        """sandboxfreezeobject should freeze a specific object."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 10

        sys.sandboxfreezeobject(obj)
        self.assertTrue(sys.sandboxisobjectfrozen(obj))

        with self.assertRaises(SandboxAttributeError) as cm:
            obj.b = 20
        self.assertIn("frozen object", str(cm.exception))

    def test_sandboxisobjectfrozen_default_false(self):
        """New objects should not be frozen by default."""
        class Foo:
            pass
        obj = Foo()
        self.assertFalse(sys.sandboxisobjectfrozen(obj))

    def test_per_instance_freeze_without_global_mode(self):
        """Per-instance freeze should work without global frozen mode."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        self.assertFalse(sys.getsandboxfrozenmode())
        sys.sandboxfreezeobject(obj)

        with self.assertRaises(SandboxAttributeError):
            obj.b = 2

    def test_per_instance_freeze_blocks_delete(self):
        """Per-instance freeze should block attribute deletion."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        sys.sandboxfreezeobject(obj)
        with self.assertRaises(SandboxAttributeError):
            del obj.a

    def test_frozen_does_not_affect_other_objects(self):
        """Freezing one object should not affect other objects."""
        class Foo:
            pass
        obj1 = Foo()
        obj2 = Foo()

        sys.sandboxfreezeobject(obj1)

        # obj1 is frozen
        with self.assertRaises(SandboxAttributeError):
            obj1.x = 1

        # obj2 is not frozen
        obj2.x = 1
        self.assertEqual(obj2.x, 1)

    # --- Mutable override ---

    def test_sandboxsetobjectmutable_overrides_global_freeze(self):
        """Mutable flag should override global frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        sys.sandboxsetobjectmutable(obj)

        obj.x = 42  # Should succeed
        self.assertEqual(obj.x, 42)

    def test_sandboxsetobjectmutable_clear(self):
        """sandboxsetobjectmutable(obj, False) should clear the mutable flag."""
        class Foo:
            pass
        obj = Foo()

        sys.sandboxsetobjectmutable(obj)
        sys.setsandboxfrozenmode(True)
        obj.x = 1  # Should succeed

        sys.sandboxsetobjectmutable(obj, False)
        with self.assertRaises(SandboxAttributeError):
            obj.y = 2

    def test_mutable_overrides_per_instance_freeze(self):
        """Mutable flag should override per-instance freeze."""
        class Foo:
            pass
        obj = Foo()

        sys.sandboxfreezeobject(obj)
        sys.sandboxsetobjectmutable(obj)

        obj.x = 1  # Should succeed despite frozen flag
        self.assertEqual(obj.x, 1)

    # --- Suspend/resume interaction ---

    def test_suspend_bypasses_global_frozen_mode(self):
        """Suspending sandbox should bypass global frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            obj.x = 1

        sys.suspendsandboxlimits()
        obj.x = 1  # Should succeed while suspended

        sys.resumesandboxlimits()
        with self.assertRaises(SandboxAttributeError):
            obj.y = 2
        self.assertEqual(obj.x, 1)

    def test_suspend_bypasses_per_instance_freeze(self):
        """Suspending sandbox should bypass per-instance freeze."""
        class Foo:
            pass
        obj = Foo()
        obj.a = 1

        sys.sandboxfreezeobject(obj)
        with self.assertRaises(SandboxAttributeError):
            obj.b = 2

        sys.suspendsandboxlimits()
        obj.b = 2  # Should succeed while suspended
        self.assertEqual(obj.b, 2)

        sys.resumesandboxlimits()
        with self.assertRaises(SandboxAttributeError):
            obj.c = 3

    def test_nested_suspend_with_frozen_mode(self):
        """Nested suspend/resume should work correctly with frozen mode."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)

        sys.suspendsandboxlimits()
        sys.suspendsandboxlimits()
        obj.x = 1  # Should succeed

        sys.resumesandboxlimits()
        obj.y = 2  # Should still succeed (still suspended once)

        sys.resumesandboxlimits()
        with self.assertRaises(SandboxAttributeError):
            obj.z = 3  # Should fail (fully resumed)

    # --- Error message distinction ---

    def test_global_freeze_error_message(self):
        """Global freeze should produce a specific error message."""
        class Foo:
            pass
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError) as cm:
            obj.x = 1
        msg = str(cm.exception)
        self.assertIn("frozen mode is active", msg)
        self.assertIn("Foo", msg)

    def test_per_instance_freeze_error_message(self):
        """Per-instance freeze should produce a specific error message."""
        class Foo:
            pass
        obj = Foo()
        sys.sandboxfreezeobject(obj)

        with self.assertRaises(SandboxAttributeError) as cm:
            obj.x = 1
        msg = str(cm.exception)
        self.assertIn("frozen object", msg)
        self.assertIn("Foo", msg)

    # --- Various object types ---

    def test_frozen_mode_blocks_module_attr(self):
        """Frozen mode should block setting attributes on modules."""
        import types
        mod = types.ModuleType('testmod')

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            mod.x = 1

    def test_frozen_mode_blocks_function_attr(self):
        """Frozen mode should block setting attributes on functions."""
        def func():
            pass

        sys.setsandboxfrozenmode(True)
        with self.assertRaises(SandboxAttributeError):
            func.custom_attr = 42

    def test_freeze_class_object(self):
        """Freezing a class should block setting class attributes."""
        class Foo:
            pass

        sys.sandboxfreezeobject(Foo)
        with self.assertRaises(SandboxAttributeError):
            Foo.class_var = 1

    # --- Edge cases ---

    def test_frozen_mode_allows_reading_attributes(self):
        """Frozen mode should not affect reading attributes."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 42

        sys.setsandboxfrozenmode(True)
        val = obj.x  # Reading should work
        self.assertEqual(val, 42)

    def test_frozen_mode_allows_method_calls(self):
        """Frozen mode should not block calling methods."""
        class Foo:
            def greet(self):
                return "hello"
        obj = Foo()

        sys.setsandboxfrozenmode(True)
        result = obj.greet()
        self.assertEqual(result, "hello")

    def test_mutable_object_in_global_freeze_can_delete(self):
        """Mutable objects should allow attribute deletion in frozen mode."""
        class Foo:
            pass
        obj = Foo()
        obj.x = 1
        sys.sandboxsetobjectmutable(obj)

        sys.setsandboxfrozenmode(True)
        del obj.x  # Should succeed
        self.assertFalse(hasattr(obj, 'x'))


class FrozenModeSubprocessTests(unittest.TestCase):
    """Subprocess tests for frozen mode to test scenarios that might
    interfere with the test runner itself.
    """

    def test_frozen_mode_blocks_dict_instance_storage(self):
        """Frozen mode should block _PyObject_StoreInstanceAttribute."""
        code = '''
import sys
sys.entersandboxscope()

class Foo:
    pass

obj = Foo()
sys.setsandboxfrozenmode(True)

try:
    obj.x = 1
    print("FAIL: should have raised")
    sys.exit(1)
except SandboxAttributeError as e:
    if "frozen mode" in str(e):
        print("PASS")
        sys.exit(0)
    print(f"FAIL: wrong message: {e}")
    sys.exit(1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Dict storage not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_frozen_mode_integration_with_exec(self):
        """Frozen mode should work in exec'd code."""
        code = '''
import sys
sys.entersandboxscope()

class Box:
    pass

box = Box()
box.value = 10
sys.sandboxsetobjectmutable(box)

sys.setsandboxfrozenmode(True)

# exec'd code should also be affected by frozen mode
exec("""
try:
    # New object - not mutable, should be blocked
    class Dummy:
        pass
    d = Dummy()
    d.x = 1
    print("FAIL")
    sys.exit(1)
except SandboxAttributeError:
    pass

# Mutable object should still work
box.value = 20
if box.value == 20:
    print("PASS")
else:
    print("FAIL: wrong value")
    sys.exit(1)
""")

sys.setsandboxfrozenmode(False)
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Exec integration failed: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_frozen_mode_exception_hierarchy(self):
        """SandboxAttributeError from frozen mode should be a SandboxError."""
        code = '''
import sys
sys.entersandboxscope()

class Foo:
    pass

obj = Foo()
sys.setsandboxfrozenmode(True)

try:
    obj.x = 1
    sys.exit(1)
except SandboxError:
    # Should be catchable as SandboxError (parent class)
    print("PASS")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Exception hierarchy wrong: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_frozen_mode_with_property_descriptor(self):
        """Frozen mode should block property setters."""
        code = '''
import sys
sys.entersandboxscope()

class Foo:
    def __init__(self):
        self._x = 0

    @property
    def x(self):
        return self._x

    @x.setter
    def x(self, value):
        self._x = value

obj = Foo()
obj.x = 10  # Works before freeze

sys.setsandboxfrozenmode(True)
try:
    obj.x = 20  # Should be blocked
    print("FAIL")
    sys.exit(1)
except SandboxAttributeError:
    print("PASS")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Property setter not blocked: stdout={result.stdout!r} stderr={result.stderr!r}")


if __name__ == '__main__':
    unittest.main()
