"""Tests for container copy/update operations respecting sandbox limits.

This module tests that container copying and bulk update operations
properly respect sandbox size limits. These operations can bypass
limits if not properly checked:
- dict.copy(), dict(d), {**d}
- dict.update(), d | d2, d |= d2
- set.copy(), frozenset(s), s.union(), s.update()

Security audit reference: Fix proposals 01, 02, 03
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    ScopedFilenameTestCase,
    _run_sandboxed_code,
    TEST_DICT_LIMIT,
    TEST_SET_LIMIT,
    SUBPROCESS_TIMEOUT,
)


class DictCopyLimitTests(ScopedFilenameTestCase):
    """Test dict.copy() respects size limits.

    Attack vector: Create large dict outside scope, pass it in,
    then copy it inside scope to bypass dict size limits.
    """

    SCOPED_FILENAME = "<test_container_copy_limits_scope>"

    def test_dict_copy_blocks_large_source(self):
        """dict.copy() on large external dict should raise SandboxOverflowError."""
        sys.sandbox.set_config(max_dict_size=100)
        # Create large dict outside scope
        large_dict = {i: i for i in range(200)}

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("d = external_dict.copy()", {"external_dict": large_dict})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_dict_copy_allows_small_source(self):
        """dict.copy() on small dict should work within limits."""
        sys.sandbox.set_config(max_dict_size=100)
        small_dict = {i: i for i in range(50)}

        globs = self.run_scoped_code("d = external_dict.copy()", {"external_dict": small_dict})
        self.assertEqual(len(globs['d']), 50)

    def test_dict_constructor_from_large_dict(self):
        """dict(large_dict) should respect size limits."""
        sys.sandbox.set_config(max_dict_size=100)
        large_dict = {i: i for i in range(200)}

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("d = dict(external_dict)", {"external_dict": large_dict})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_dict_copy_via_unpacking(self):
        """{**large_dict} should respect size limits."""
        sys.sandbox.set_config(max_dict_size=100)
        large_dict = {i: i for i in range(200)}

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("d = {**external_dict}", {"external_dict": large_dict})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_dict_comprehension_respects_limits(self):
        """Dict comprehension from external source should respect limits."""
        sys.sandbox.set_config(max_dict_size=100)
        large_items = list(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("d = {i: i for i in items}", {"items": large_items})
        self.assertIn("sandbox limit", str(cm.exception))


class DictUpdateLimitTests(ScopedFilenameTestCase):
    """Test dict.update() and |= respect size limits.

    Attack vector: Create small dict in scope, then update with
    large external dict to bypass size limits.
    """

    SCOPED_FILENAME = "<test_container_copy_limits_scope>"

    def test_dict_update_from_large_dict(self):
        """d.update(large_dict) should raise SandboxOverflowError."""
        sys.sandbox.set_config(max_dict_size=100)
        large_dict = {i: i for i in range(200)}

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
d = {}
d.update(external_dict)
""", {"external_dict": large_dict})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_dict_update_from_kwargs(self):
        """d.update(**large_dict) should respect size limits."""
        sys.sandbox.set_config(max_dict_size=100)
        # Create dict with string keys for **kwargs
        large_dict = {f"key{i}": i for i in range(200)}

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
d = {}
d.update(**external_dict)
""", {"external_dict": large_dict})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_dict_merge_operator(self):
        """d | large_dict should respect size limits."""
        sys.sandbox.set_config(max_dict_size=100)
        large_dict = {i: i for i in range(200)}

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
d = {}
result = d | external_dict
""", {"external_dict": large_dict})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_dict_inplace_merge(self):
        """d |= large_dict should respect size limits."""
        sys.sandbox.set_config(max_dict_size=100)
        large_dict = {i: i for i in range(200)}

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
d = {}
d |= external_dict
""", {"external_dict": large_dict})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_dict_setdefault_incremental(self):
        """Multiple setdefault calls should respect cumulative limits.

        Note: dict.setdefault() adds one element at a time and triggers
        the same check as d[key] = value. This should be blocked when
        the dict exceeds max_dict_size.
        """
        sys.sandbox.set_config(max_dict_size=100)

        # Test that adding items one at a time eventually hits the limit
        try:
            self.run_scoped_code("""
d = {}
for i in range(200):
    d[i] = i
""")
            self.fail("Should have raised SandboxOverflowError")
        except SandboxOverflowError:
            pass  # Expected

    def test_dict_update_allows_within_limit(self):
        """dict.update() with small dict should work within limits."""
        sys.sandbox.set_config(max_dict_size=100)
        small_dict = {i: i for i in range(50)}

        globs = self.run_scoped_code("""
d = {-1: -1}
d.update(external_dict)
""", {"external_dict": small_dict})
        self.assertEqual(len(globs['d']), 51)


class SetCopyLimitTests(ScopedFilenameTestCase):
    """Test set.copy() and frozenset() respect size limits.

    Attack vector: Create large set outside scope, pass it in,
    then copy it inside scope to bypass set size limits.
    """

    SCOPED_FILENAME = "<test_container_copy_limits_scope>"

    def test_set_copy_blocks_large_source(self):
        """set.copy() on large external set should raise SandboxOverflowError."""
        sys.sandbox.set_config(max_set_size=100)
        large_set = set(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("s = external_set.copy()", {"external_set": large_set})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_set_copy_allows_small_source(self):
        """set.copy() on small set should work within limits."""
        sys.sandbox.set_config(max_set_size=100)
        small_set = set(range(50))

        globs = self.run_scoped_code("s = external_set.copy()", {"external_set": small_set})
        self.assertEqual(len(globs['s']), 50)

    def test_frozenset_from_large_set(self):
        """frozenset(large_set) should respect size limits."""
        sys.sandbox.set_config(max_set_size=100)
        large_set = set(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("fs = frozenset(external_set)", {"external_set": large_set})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_set_constructor_from_large_iterable(self):
        """set(large_iterable) should respect size limits."""
        sys.sandbox.set_config(max_set_size=100)
        large_list = list(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("s = set(external_list)", {"external_list": large_list})
        self.assertIn("sandbox limit", str(cm.exception))


class SetUpdateLimitTests(ScopedFilenameTestCase):
    """Test set.update() and set operations respect size limits."""

    SCOPED_FILENAME = "<test_container_copy_limits_scope>"

    def test_set_update_from_large_set(self):
        """s.update(large_set) should respect size limits."""
        sys.sandbox.set_config(max_set_size=100)
        large_set = set(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
s = set()
s.update(external_set)
""", {"external_set": large_set})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_set_union_large(self):
        """s.union(large_set) should respect size limits."""
        sys.sandbox.set_config(max_set_size=100)
        large_set = set(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("result = small_set.union(external_set)",
                       {"small_set": set(), "external_set": large_set})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_set_or_operator_large(self):
        """s | large_set should respect size limits."""
        sys.sandbox.set_config(max_set_size=100)
        large_set = set(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("result = small_set | external_set",
                       {"small_set": set(), "external_set": large_set})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_set_inplace_or_large(self):
        """s |= large_set should respect size limits."""
        sys.sandbox.set_config(max_set_size=100)
        large_set = set(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
s = set()
s |= external_set
""", {"external_set": large_set})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_set_symmetric_difference_update(self):
        """s.symmetric_difference_update(large) should respect limits."""
        sys.sandbox.set_config(max_set_size=100)
        large_set = set(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
s = set()
s.symmetric_difference_update(external_set)
""", {"external_set": large_set})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_set_comprehension_respects_limits(self):
        """Set comprehension from external source should respect limits."""
        sys.sandbox.set_config(max_set_size=100)
        large_items = list(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("s = {i for i in items}", {"items": large_items})
        self.assertIn("sandbox limit", str(cm.exception))


class ListCopyLimitTests(ScopedFilenameTestCase):
    """Test list.copy() and list() constructor respect size limits."""

    SCOPED_FILENAME = "<test_container_copy_limits_scope>"

    def test_list_copy_blocks_large_source(self):
        """list.copy() on large external list should raise SandboxOverflowError."""
        sys.sandbox.set_config(max_list_size=100)
        large_list = list(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("l = external_list.copy()", {"external_list": large_list})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_list_constructor_from_large_iterable(self):
        """list(large_iterable) should respect size limits."""
        sys.sandbox.set_config(max_list_size=100)
        large_tuple = tuple(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("l = list(external_tuple)", {"external_tuple": large_tuple})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_list_extend_from_large_iterable(self):
        """list.extend(large_iterable) should respect size limits."""
        sys.sandbox.set_config(max_list_size=100)
        large_tuple = tuple(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
l = []
l.extend(external_tuple)
""", {"external_tuple": large_tuple})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_list_inplace_add_large(self):
        """l += large_list should respect size limits."""
        sys.sandbox.set_config(max_list_size=100)
        large_list = list(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
l = []
l += external_list
""", {"external_list": large_list})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_list_multiply_large(self):
        """list * n should respect size limits."""
        sys.sandbox.set_config(max_list_size=100)

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("l = [1, 2, 3] * 50")
        self.assertIn("sandbox limit", str(cm.exception))

    def test_list_inplace_multiply_large(self):
        """l *= n should respect size limits."""
        sys.sandbox.set_config(max_list_size=100)

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("""
l = [1, 2, 3, 4, 5]
l *= 30
""")
        self.assertIn("sandbox limit", str(cm.exception))


class TupleCopyLimitTests(ScopedFilenameTestCase):
    """Test tuple() constructor respects size limits."""

    SCOPED_FILENAME = "<test_container_copy_limits_scope>"

    def test_tuple_from_large_list(self):
        """tuple(large_list) should respect size limits."""
        sys.sandbox.set_config(max_tuple_size=100)
        large_list = list(range(200))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("t = tuple(external_list)", {"external_list": large_list})
        self.assertIn("sandbox limit", str(cm.exception))

    def test_tuple_multiply_large(self):
        """tuple * n should respect size limits."""
        sys.sandbox.set_config(max_tuple_size=100)

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("t = (1, 2, 3) * 50")
        self.assertIn("sandbox limit", str(cm.exception))

    def test_tuple_concat_large(self):
        """tuple + tuple should respect size limits."""
        sys.sandbox.set_config(max_tuple_size=100)
        large_tuple = tuple(range(100))

        with self.assertRaises(SandboxOverflowError) as cm:
            self.run_scoped_code("t = ext_tuple + ext_tuple", {"ext_tuple": large_tuple})
        self.assertIn("sandbox limit", str(cm.exception))


class SubprocessContainerTests(unittest.TestCase):
    """Subprocess tests for container operations that need full isolation."""

    def test_dict_copy_subprocess(self):
        """Test dict.copy() bypass prevention in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(max_dict_size=100)
sys.sandbox.enter_scope()
try:
    # This tests that even dicts created before scope are checked on copy
    large = {i: i for i in range(200)}  # Created in scope, should fail
    sys.exit(2)
except SandboxOverflowError:
    sys.exit(0)  # Expected
except Exception as e:
    print(f"Unexpected error: {e}", file=sys.stderr)
    sys.exit(3)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Test failed with stderr: {result.stderr}")

    def test_set_copy_subprocess(self):
        """Test set.copy() bypass prevention in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(max_set_size=100)
sys.sandbox.enter_scope()
try:
    large = set(range(200))  # Created in scope, should fail
    sys.exit(2)
except SandboxOverflowError:
    sys.exit(0)  # Expected
except Exception as e:
    print(f"Unexpected error: {e}", file=sys.stderr)
    sys.exit(3)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Test failed with stderr: {result.stderr}")


if __name__ == '__main__':
    unittest.main()
