"""Tests for sandbox limits: API basics, type/size limits, suspend/resume."""

import sys
import unittest

from test.test_sandbox import (
    _get_settable_limits,
    TEST_INT_DIGITS_LIMIT,
    TEST_STR_LIMIT,
    TEST_LIST_LIMIT,
    TEST_DICT_LIMIT,
    TEST_SET_LIMIT,
    TEST_TUPLE_LIMIT,
)


class SandboxLimitsTests(unittest.TestCase):
    """Test sandbox limits functionality."""

    def setUp(self):
        # Save original limits (excluding read-only fields)
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        # Restore original limits
        sys.sandbox.set_limits(**self.original_limits)
        # Exit scope if entered
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def test_getsandboxlimits_returns_dict(self):
        """getsandboxlimits should return a dictionary with all limit keys."""
        limits = sys.sandbox.get_limits()
        self.assertIsInstance(limits, dict)
        expected_keys = {
            'max_int_digits', 'max_str_length', 'max_bytes_length',
            'max_list_size', 'max_dict_size', 'max_set_size', 'max_tuple_size',
            'max_statements', 'max_allocations',
            'max_iterations', 'max_operations',
            'allow_float', 'allow_complex', 'allow_dunder_access',
            'count_iterations_as_operations',
        }
        self.assertEqual(set(limits.keys()), expected_keys)

    def test_getsandboxcounts_returns_dict(self):
        """getsandboxcounts should return a dictionary with count keys."""
        counts = sys.sandbox.get_counts()
        self.assertIsInstance(counts, dict)
        expected_keys = {'allocation_count', 'statement_count', 'iteration_count', 'operation_count'}
        self.assertEqual(set(counts.keys()), expected_keys)

    def test_default_limits_are_zero(self):
        """Default limits should be 0 (no limit) and types allowed."""
        limits = sys.sandbox.get_limits()
        self.assertEqual(limits['max_int_digits'], 0)
        self.assertEqual(limits['max_str_length'], 0)
        self.assertEqual(limits['max_bytes_length'], 0)
        self.assertEqual(limits['max_list_size'], 0)
        self.assertEqual(limits['max_dict_size'], 0)
        self.assertEqual(limits['max_set_size'], 0)
        self.assertEqual(limits['max_tuple_size'], 0)
        self.assertEqual(limits['max_statements'], 0)
        self.assertEqual(limits['max_allocations'], 0)
        self.assertTrue(limits['allow_float'])
        self.assertTrue(limits['allow_complex'])
        self.assertTrue(limits['allow_dunder_access'])

    def test_setsandboxlimits_updates_limits(self):
        """setsandboxlimits should update the limits."""
        sys.sandbox.set_limits(max_int_digits=100, max_str_length=1000)
        limits = sys.sandbox.get_limits()
        self.assertEqual(limits['max_int_digits'], 100)
        self.assertEqual(limits['max_str_length'], 1000)


class IntegerLimitsTests(unittest.TestCase):
    """Test integer size limits.

    Note: max_int_digits is in internal digits (each ~30 bits = ~9 decimal digits),
    not decimal digits.
    """

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.sandbox.enter_scope()

    def tearDown(self):
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_small_integers_allowed(self):
        """Small integers should always be allowed."""
        sys.sandbox.set_limits(max_int_digits=TEST_INT_DIGITS_LIMIT)
        x = 12345
        self.assertEqual(x, 12345)

    def test_large_integers_blocked(self):
        """Large integers exceeding limit should raise SandboxOverflowError."""
        sys.sandbox.set_limits(max_int_digits=TEST_INT_DIGITS_LIMIT)
        # 10^50 requires about 6 internal digits
        with self.assertRaises(SandboxOverflowError) as cm:
            x = 10 ** 50
        self.assertIn("sandbox limit", str(cm.exception))

    def test_no_limit_allows_large_integers(self):
        """With no limit (0), large integers should be allowed."""
        sys.sandbox.set_limits(max_int_digits=0)
        x = 10 ** 100  # Should work
        self.assertIsInstance(x, int)


class StringLimitsTests(unittest.TestCase):
    """Test string length limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.sandbox.enter_scope()

    def tearDown(self):
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_small_strings_allowed(self):
        """Small strings should always be allowed."""
        sys.sandbox.set_limits(max_str_length=TEST_STR_LIMIT)
        s = "hello world"
        self.assertEqual(s, "hello world")

    def test_large_strings_blocked(self):
        """Large strings exceeding limit should raise SandboxOverflowError."""
        sys.sandbox.set_limits(max_str_length=TEST_STR_LIMIT)
        with self.assertRaises(SandboxOverflowError) as cm:
            # Use join to trigger PyUnicode_New
            s = ''.join(['x' for _ in range(200)])
        self.assertIn("sandbox limit", str(cm.exception))


class ListLimitsTests(unittest.TestCase):
    """Test list size limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.sandbox.enter_scope()

    def tearDown(self):
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_small_lists_allowed(self):
        """Small lists should always be allowed."""
        sys.sandbox.set_limits(max_list_size=100)
        lst = [1, 2, 3, 4, 5]
        self.assertEqual(len(lst), 5)

    def test_large_lists_blocked(self):
        """Large lists exceeding limit via append should raise SandboxOverflowError."""
        sys.sandbox.set_limits(max_list_size=100)
        lst = []
        with self.assertRaises(SandboxOverflowError) as cm:
            for i in range(150):
                lst.append(i)
        self.assertIn("sandbox limit", str(cm.exception))


class DictLimitsTests(unittest.TestCase):
    """Test dict size limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.sandbox.enter_scope()

    def tearDown(self):
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_small_dicts_allowed(self):
        """Small dicts should always be allowed."""
        sys.sandbox.set_limits(max_dict_size=TEST_DICT_LIMIT)
        d = {'a': 1, 'b': 2}
        self.assertEqual(len(d), 2)

    def test_large_dicts_blocked(self):
        """Large dicts exceeding limit should raise SandboxOverflowError."""
        sys.sandbox.set_limits(max_dict_size=TEST_DICT_LIMIT)
        d = {}
        with self.assertRaises(SandboxOverflowError) as cm:
            for i in range(600):
                d[i] = i
        self.assertIn("sandbox limit", str(cm.exception))


class SetLimitsTests(unittest.TestCase):
    """Test set size limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.sandbox.enter_scope()

    def tearDown(self):
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_small_sets_allowed(self):
        """Small sets should always be allowed."""
        sys.sandbox.set_limits(max_set_size=TEST_SET_LIMIT)
        s = {1, 2, 3}
        self.assertEqual(len(s), 3)

    def test_large_sets_blocked(self):
        """Large sets exceeding limit should raise SandboxOverflowError."""
        sys.sandbox.set_limits(max_set_size=TEST_SET_LIMIT)
        s = set()
        with self.assertRaises(SandboxOverflowError) as cm:
            for i in range(600):
                s.add(i)
        self.assertIn("sandbox limit", str(cm.exception))


class TupleLimitsTests(unittest.TestCase):
    """Test tuple size limits."""

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.sandbox.enter_scope()

    def tearDown(self):
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_small_tuples_allowed(self):
        """Small tuples should always be allowed."""
        sys.sandbox.set_limits(max_tuple_size=TEST_TUPLE_LIMIT)
        t = (1, 2, 3, 4, 5)
        self.assertEqual(len(t), 5)

    def test_large_tuples_blocked(self):
        """Large tuples exceeding limit should raise SandboxOverflowError."""
        sys.sandbox.set_limits(max_tuple_size=TEST_TUPLE_LIMIT)
        with self.assertRaises(SandboxOverflowError) as cm:
            t = tuple(range(600))
        self.assertIn("sandbox limit", str(cm.exception))


class TypeRestrictionTests(unittest.TestCase):
    """Test type restriction (float, complex)."""

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.sandbox.enter_scope()

    def tearDown(self):
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_float_allowed_by_default(self):
        """Float creation should be allowed by default."""
        f = float(1)
        self.assertEqual(f, 1.0)

    def test_float_blocked_when_disabled(self):
        """Float creation should raise SandboxTypeError when disabled."""
        sys.sandbox.set_limits(allow_float=False)
        with self.assertRaises(SandboxTypeError) as cm:
            f = float(1)
        self.assertIn("forbidden", str(cm.exception))

    def test_complex_allowed_by_default(self):
        """Complex creation should be allowed by default."""
        c = complex(1, 2)
        self.assertEqual(c, 1+2j)

    def test_complex_blocked_when_disabled(self):
        """Complex creation should raise SandboxTypeError when disabled."""
        sys.sandbox.set_limits(allow_complex=False)
        with self.assertRaises(SandboxTypeError) as cm:
            c = complex(1, 2)
        self.assertIn("forbidden", str(cm.exception))


class MinimalSafeLimitsTests(unittest.TestCase):
    """Test that minimal safe limits don't interfere with Python internals."""

    # Recommended minimal limits
    MINIMAL_LIMITS = {
        'max_int_digits': 100,       # ~10^900
        'max_str_length': 100000,    # 100KB
        'max_bytes_length': 100000,  # 100KB
        'max_list_size': 20000,
        'max_dict_size': 20000,
        'max_set_size': 20000,
        'max_tuple_size': 20000,
    }

    def setUp(self):
        self.original_limits = _get_settable_limits()
        sys.sandbox.enter_scope()

    def tearDown(self):
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_minimal_limits_allow_imports(self):
        """Minimal limits should allow standard library imports."""
        sys.sandbox.set_limits(**self.MINIMAL_LIMITS)

        # These imports use internal strings, dicts, lists
        import json
        import re
        import collections
        import functools
        import urllib.parse

    def test_minimal_limits_allow_basic_operations(self):
        """Minimal limits should allow basic Python operations."""
        sys.sandbox.set_limits(**self.MINIMAL_LIMITS)

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
        sys.sandbox.set_limits(**self.MINIMAL_LIMITS)

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
        sys.sandbox.enter_scope()

    def tearDown(self):
        # Ensure limits are resumed
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        sys.sandbox.exit_scope()
        sys.sandbox.set_limits(**self.original_limits)

    def test_suspend_bypasses_limits(self):
        """Suspended limits should allow exceeding normal limits."""
        sys.sandbox.set_limits(max_list_size=10)

        # Should fail with limits active
        with self.assertRaises(SandboxOverflowError):
            list(range(20))

        # Suspend and try again
        sys.sandbox.suspend()
        self.assertTrue(sys.sandbox.suspended)

        # Should succeed while suspended
        lst = list(range(20))
        self.assertEqual(len(lst), 20)

    def test_resume_reactivates_limits(self):
        """Resumed limits should block operations again."""
        sys.sandbox.set_limits(max_list_size=10)
        sys.sandbox.suspend()

        # Works while suspended
        lst = list(range(20))
        self.assertEqual(len(lst), 20)

        # Resume limits
        sys.sandbox.resume()
        self.assertFalse(sys.sandbox.suspended)

        # Should fail again
        with self.assertRaises(SandboxOverflowError):
            list(range(20))

    def test_nested_suspend_resume(self):
        """Nested suspend/resume should work correctly."""
        sys.sandbox.set_limits(max_list_size=10)

        # First suspend
        count1 = sys.sandbox.suspend()
        self.assertEqual(count1, 1)
        self.assertTrue(sys.sandbox.suspended)

        # Nested suspend
        count2 = sys.sandbox.suspend()
        self.assertEqual(count2, 2)

        # First resume - still suspended
        count3 = sys.sandbox.resume()
        self.assertEqual(count3, 1)
        self.assertTrue(sys.sandbox.suspended)

        # Should still work
        lst = list(range(20))
        self.assertEqual(len(lst), 20)

        # Second resume - now active
        count4 = sys.sandbox.resume()
        self.assertEqual(count4, 0)
        self.assertFalse(sys.sandbox.suspended)

        # Should fail now
        with self.assertRaises(SandboxOverflowError):
            list(range(20))

    def test_unpaired_resume_raises_error(self):
        """Resume without matching suspend should raise RuntimeError."""
        # Ensure we're not suspended
        while sys.sandbox.suspended:
            sys.sandbox.resume()

        # Now try to resume without suspend - should raise
        with self.assertRaises(RuntimeError) as cm:
            sys.sandbox.resume()
        self.assertIn("without matching suspend", str(cm.exception))

    def test_extra_resume_after_balanced_pairs_raises_error(self):
        """Extra resume after balanced suspend/resume pairs should raise."""
        # Do a balanced suspend/resume
        sys.sandbox.suspend()
        sys.sandbox.resume()

        # Extra resume should fail
        with self.assertRaises(RuntimeError) as cm:
            sys.sandbox.resume()
        self.assertIn("without matching suspend", str(cm.exception))

    def test_suspended_limits_context_manager(self):
        """suspended_limits() context manager should bypass limits."""
        sys.sandbox.set_limits(max_list_size=5)

        # Should fail without suspension
        with self.assertRaises(SandboxOverflowError):
            list(range(10))

        # Should succeed inside context manager
        with sys.sandbox.suspended_limits():
            self.assertTrue(sys.sandbox.suspended)
            large_list = list(range(100))
            self.assertEqual(len(large_list), 100)

        # Should fail again after context
        self.assertFalse(sys.sandbox.suspended)
        with self.assertRaises(SandboxOverflowError):
            list(range(10))

    def test_suspended_limits_context_manager_with_exception(self):
        """suspended_limits() should restore state even on exception."""
        sys.sandbox.set_limits(max_list_size=5)

        try:
            with sys.sandbox.suspended_limits():
                self.assertTrue(sys.sandbox.suspended)
                raise ValueError("test exception")
        except ValueError:
            pass

        # Should be resumed after exception
        self.assertFalse(sys.sandbox.suspended)


class ResetLimitsTests(unittest.TestCase):
    """Test reset() functionality."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        # Exit scope if entered
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.set_limits(**self.original_limits)

    def test_reset_clears_all_state(self):
        """reset() should clear all limits, counters, and modes."""
        # Set some limits
        sys.sandbox.set_limits(max_list_size=100, max_statements=1000)
        sys.sandbox.frozen_mode = True
        sys.sandbox.auto_mutable = True

        # Do some operations to increment counters
        with sys.sandbox.scope():
            _ = [1, 2, 3]

        # Reset
        sys.sandbox.reset()

        # Verify limits cleared
        limits = sys.sandbox.get_limits()
        self.assertEqual(limits['max_list_size'], 0)
        self.assertEqual(limits['max_statements'], 0)

        # Verify counters cleared
        counts = sys.sandbox.get_counts()
        self.assertEqual(counts['allocation_count'], 0)
        self.assertEqual(counts['statement_count'], 0)
        self.assertEqual(counts['iteration_count'], 0)
        self.assertEqual(counts['operation_count'], 0)

        # Verify modes cleared
        self.assertFalse(sys.sandbox.frozen_mode)
        self.assertFalse(sys.sandbox.auto_mutable)


class OutOfScopeLimitsTests(unittest.TestCase):
    """Test that limits do NOT apply outside sandbox scope."""

    def setUp(self):
        self.original_limits = _get_settable_limits()
        # Ensure not in scope
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def tearDown(self):
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        sys.sandbox.set_limits(**self.original_limits)

    def test_int_limit_not_enforced_outside_scope(self):
        """Integer limits should not apply outside sandbox scope."""
        sys.sandbox.set_limits(max_int_digits=TEST_INT_DIGITS_LIMIT)
        # Should succeed - not in scope
        x = 10 ** 50
        self.assertIsInstance(x, int)

    def test_str_limit_not_enforced_outside_scope(self):
        """String limits should not apply outside sandbox scope."""
        sys.sandbox.set_limits(max_str_length=TEST_STR_LIMIT)
        # Should succeed - not in scope
        s = ''.join(['x' for _ in range(200)])
        self.assertEqual(len(s), 200)

    def test_list_limit_not_enforced_outside_scope(self):
        """List limits should not apply outside sandbox scope."""
        sys.sandbox.set_limits(max_list_size=100)
        # Should succeed - not in scope
        lst = list(range(200))
        self.assertEqual(len(lst), 200)

    def test_float_restriction_not_enforced_outside_scope(self):
        """Float restriction should not apply outside sandbox scope."""
        sys.sandbox.set_limits(allow_float=False)
        # Should succeed - not in scope
        f = float(1)
        self.assertEqual(f, 1.0)

    def test_complex_restriction_not_enforced_outside_scope(self):
        """Complex restriction should not apply outside sandbox scope."""
        sys.sandbox.set_limits(allow_complex=False)
        # Should succeed - not in scope
        c = complex(1, 2)
        self.assertEqual(c, 1+2j)


if __name__ == '__main__':
    unittest.main()
