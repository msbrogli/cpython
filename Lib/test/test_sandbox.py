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
            'scope_max_iterations', 'allow_float', 'allow_complex'
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
        """Large integers exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_int_digits=TEST_INT_DIGITS_LIMIT)
        # 10^50 requires about 6 internal digits
        with self.assertRaises(OverflowError) as cm:
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
        """Large strings exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_str_length=TEST_STR_LIMIT)
        with self.assertRaises(OverflowError) as cm:
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
        """Large lists exceeding limit via append should raise OverflowError."""
        sys.setsandboxlimits(max_list_size=100)
        lst = []
        with self.assertRaises(OverflowError) as cm:
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
        """Large dicts exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_dict_size=TEST_DICT_LIMIT)
        d = {}
        with self.assertRaises(OverflowError) as cm:
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
        """Large sets exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_set_size=TEST_SET_LIMIT)
        s = set()
        with self.assertRaises(OverflowError) as cm:
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
        """Large tuples exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_tuple_size=TEST_TUPLE_LIMIT)
        with self.assertRaises(OverflowError) as cm:
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
        """Float creation should raise TypeError when disabled."""
        sys.setsandboxlimits(allow_float=False)
        with self.assertRaises(TypeError) as cm:
            f = float(1)
        self.assertIn("forbidden", str(cm.exception))

    def test_complex_allowed_by_default(self):
        """Complex creation should be allowed by default."""
        c = complex(1, 2)
        self.assertEqual(c, 1+2j)

    def test_complex_blocked_when_disabled(self):
        """Complex creation should raise TypeError when disabled."""
        sys.setsandboxlimits(allow_complex=False)
        with self.assertRaises(TypeError) as cm:
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
        with self.assertRaises(OverflowError):
            x = 10 ** 1000  # Requires ~110 internal digits

        # Should block very long strings
        with self.assertRaises(OverflowError):
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
        with self.assertRaises(OverflowError):
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
        with self.assertRaises(OverflowError):
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
        with self.assertRaises(OverflowError):
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
        """Exceeding global allocation limit should raise MemoryError."""
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
except MemoryError:
    sys.exit(0)  # Successfully caught MemoryError
'''
        result = _run_sandboxed_code(code)
        # The process should complete (not hang) and either:
        # - Return 0 (caught MemoryError successfully)
        # - Return non-zero with MemoryError indication (error handling failed)
        if result.returncode == 0:
            return  # Test passed
        if result.returncode == 2:
            self.fail("MemoryError was not raised")
        # If it exited with error, check that MemoryError was involved
        self.assertIn("MemoryError", result.stderr,
                      f"Expected MemoryError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

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
        """Exceeding statement limit should raise RuntimeError."""
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
except RuntimeError as e:
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
        """Exceeding scoped allocation limit should raise MemoryError."""
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
except MemoryError:
    sys.exit(0)  # Successfully caught MemoryError
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
            self.fail("MemoryError was not raised")
        # If it exited with error, check that MemoryError was involved
        self.assertIn("MemoryError", result.stderr,
                      f"Expected MemoryError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

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
except RuntimeError as e:
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
except MemoryError:
    sys.exit(0)  # Successfully caught MemoryError
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
            self.fail("MemoryError was not raised")
        # If it exited with error, check that MemoryError was involved
        self.assertIn("MemoryError", result.stderr,
                      f"Expected MemoryError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

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
        """Exceeding iteration limit should raise RuntimeError."""
        code = '''
import sys
from itertools import cycle

sys.setsandboxlimits(scope_max_iterations=1000)
sys.resetsandboxcounters()
sys.entersandboxscope()
try:
    # This should raise RuntimeError when iteration limit is exceeded
    sum(cycle([0, 1]))
    sys.exit(2)  # Should not reach here
except RuntimeError as e:
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
                        f"Expected RuntimeError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

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
except RuntimeError:
    print("PASS: RuntimeError raised")
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


if __name__ == '__main__':
    unittest.main()
