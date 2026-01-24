"""Tests for the sandbox functionality in sys module."""

import sys
import unittest


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

    def test_getsandboxlimits_returns_dict(self):
        """getsandboxlimits should return a dictionary with all limit keys."""
        limits = sys.getsandboxlimits()
        self.assertIsInstance(limits, dict)
        expected_keys = {
            'max_int_digits', 'max_str_length', 'max_bytes_length',
            'max_list_size', 'max_dict_size', 'max_set_size', 'max_tuple_size',
            'max_allocations', 'allow_float', 'allow_complex'
        }
        self.assertEqual(set(limits.keys()), expected_keys)

    def test_getsandboxcounts_returns_dict(self):
        """getsandboxcounts should return a dictionary with count keys."""
        counts = sys.getsandboxcounts()
        self.assertIsInstance(counts, dict)
        expected_keys = {'allocation_count'}
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
        self.assertEqual(limits['max_allocations'], 0)
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
        sys.setsandboxlimits(max_int_digits=5)
        x = 12345
        self.assertEqual(x, 12345)

    def test_large_integers_blocked(self):
        """Large integers exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_int_digits=5)  # ~45 decimal digits
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
        sys.setsandboxlimits(max_str_length=100)
        s = "hello world"
        self.assertEqual(s, "hello world")

    def test_large_strings_blocked(self):
        """Large strings exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_str_length=100)
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
        sys.setsandboxlimits(max_dict_size=500)
        d = {'a': 1, 'b': 2}
        self.assertEqual(len(d), 2)

    def test_large_dicts_blocked(self):
        """Large dicts exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_dict_size=500)
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
        sys.setsandboxlimits(max_set_size=500)
        s = {1, 2, 3}
        self.assertEqual(len(s), 3)

    def test_large_sets_blocked(self):
        """Large sets exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_set_size=500)
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
        sys.setsandboxlimits(max_tuple_size=500)
        t = (1, 2, 3, 4, 5)
        self.assertEqual(len(t), 5)

    def test_large_tuples_blocked(self):
        """Large tuples exceeding limit should raise OverflowError."""
        sys.setsandboxlimits(max_tuple_size=500)
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


class AllocationCountLimitsTests(unittest.TestCase):
    """Test allocation counting limits for GC-tracked objects."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        # Ensure limits are resumed
        while sys.issandboxsuspended():
            sys.resumesandboxlimits()
        sys.setsandboxlimits(**self.original_limits)
        sys.resetsandboxallocationcount()

    def test_set_and_get_max_allocations(self):
        """Setting and getting max_allocations should work."""
        sys.setsandboxlimits(max_allocations=10000)
        limits = sys.getsandboxlimits()
        self.assertEqual(limits['max_allocations'], 10000)

    def test_allocation_count_tracked(self):
        """Allocation count should be tracked."""
        sys.resetsandboxallocationcount()
        initial = sys.getsandboxcounts()['allocation_count']
        self.assertEqual(initial, 0)

        # Create some objects
        _ = [1, 2, 3]
        _ = {'a': 1}
        _ = (1, 2)

        count = sys.getsandboxcounts()['allocation_count']
        self.assertGreater(count, 0)

    def test_exceeding_allocation_limit_raises_memory_error(self):
        """Exceeding allocation limit should raise MemoryError."""
        import subprocess
        # Use a higher limit to allow for error handling allocations
        code = '''
import sys
sys.setsandboxlimits(max_allocations=1000)
sys.resetsandboxallocationcount()
a = []
try:
    for i in range(2000):
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

    def test_reset_allocation_count(self):
        """resetsandboxallocationcount should reset counter to 0."""
        sys.setsandboxlimits(max_allocations=1000)

        # Create some objects
        for _ in range(10):
            _ = [1, 2, 3]

        count_before = sys.getsandboxcounts()['allocation_count']
        self.assertGreater(count_before, 0)

        sys.resetsandboxallocationcount()
        count_after = sys.getsandboxcounts()['allocation_count']
        self.assertEqual(count_after, 0)

    def test_allocations_while_suspended_dont_count(self):
        """Allocations while suspended should not count toward limit."""
        sys.setsandboxlimits(max_allocations=100)
        sys.resetsandboxallocationcount()

        # Suspend and create lots of objects
        sys.suspendsandboxlimits()
        for _ in range(200):
            _ = [1, 2, 3]
        count_suspended = sys.getsandboxcounts()['allocation_count']

        sys.resumesandboxlimits()

        # Should still be at a low count (suspended allocations didn't count)
        self.assertLess(count_suspended, 100)

    def test_no_limit_allows_many_allocations(self):
        """With no limit (0), many allocations should be allowed."""
        sys.setsandboxlimits(max_allocations=0)
        sys.resetsandboxallocationcount()

        # Create many objects - should not raise
        for _ in range(1000):
            _ = [1, 2, 3]

    def test_different_object_types_all_count(self):
        """Lists, dicts, sets, tuples, and user classes all count."""
        sys.setsandboxlimits(max_allocations=1000)
        sys.resetsandboxallocationcount()

        # Create different types
        _ = [1, 2, 3]       # list
        _ = {'a': 1}        # dict
        _ = {1, 2, 3}       # set
        # Note: small tuples may be cached and not allocate new memory

        class MyClass:
            pass

        _ = MyClass()       # user class instance

        count = sys.getsandboxcounts()['allocation_count']
        # At least 4 objects were created (list, dict, set, class instance)
        # Small tuples may be cached so we don't count them
        self.assertGreaterEqual(count, 4)


if __name__ == '__main__':
    unittest.main()
