"""Dangerous iteration tests that could hang if limits fail.

This module contains tests for iterator wrapper protection that
intentionally use infinite iterators. These tests rely on sandbox
iteration limits to prevent hangs.

These tests are separated from the main test suite to allow running
"safe" tests without risk of hangs during development.

Security audit reference: Iterator protection tests (dangerous subset)
"""

import sys
import unittest

from test.test_sandbox import _run_sandboxed_code


# Filename used for scoped test code (distinct from test file)
SCOPED_FILENAME = "<test_iterations_scope>"


class IteratorWrapperProtectionTests(unittest.TestCase):
    """Test iterator wrapper protection for direct tp_iternext callers.

    These tests verify that builtins like list(), tuple(), set() that
    call tp_iternext directly are now protected by the iterator wrapper
    approach. The wrapper is applied in PyObject_GetIter() and checks
    iteration limits on each step.
    """

    def setUp(self):
        pass

    def tearDown(self):
        try:
            sys.sandbox.remove_filename(SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        sys.sandbox.reset()

    def test_list_iteration_protected(self):
        """list() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"list() not protected: {result.stdout!r} {result.stderr!r}")

    def test_tuple_iteration_protected(self):
        """tuple() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"tuple() not protected: {result.stdout!r} {result.stderr!r}")

    def test_set_iteration_protected(self):
        """set() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import count

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"set() not protected: {result.stdout!r} {result.stderr!r}")

    def test_frozenset_iteration_protected(self):
        """frozenset() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import count

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"frozenset() not protected: {result.stdout!r} {result.stderr!r}")

    def test_all_iteration_protected(self):
        """all() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"all() not protected: {result.stdout!r} {result.stderr!r}")

    def test_any_with_all_false_iteration_protected(self):
        """any() of infinite iterator (all False) is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"any() not protected: {result.stdout!r} {result.stderr!r}")

    def test_for_loop_iteration_protected(self):
        """for loop over infinite iterator is protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"for loop not protected: {result.stdout!r} {result.stderr!r}")

    def test_enumerate_iteration_protected(self):
        """enumerate() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"enumerate() not protected: {result.stdout!r} {result.stderr!r}")

    def test_zip_iteration_protected(self):
        """zip() of infinite iterators is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"zip() not protected: {result.stdout!r} {result.stderr!r}")

    def test_map_iteration_protected(self):
        """map() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"map() not protected: {result.stdout!r} {result.stderr!r}")

    def test_filter_iteration_protected(self):
        """filter() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"filter() not protected: {result.stdout!r} {result.stderr!r}")

    def test_sorted_iteration_protected(self):
        """sorted() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import count

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"sorted() not protected: {result.stdout!r} {result.stderr!r}")

    def test_min_iteration_protected(self):
        """min() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"min() not protected: {result.stdout!r} {result.stderr!r}")

    def test_max_iteration_protected(self):
        """max() of infinite iterator is now protected."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_config(max_iterations=100)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"max() not protected: {result.stdout!r} {result.stderr!r}")

    def test_normal_iteration_still_works(self):
        """Normal iteration with finite iterables should still work."""
        code = '''
import sys

sys.sandbox.set_config(max_iterations=1000)
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Normal iteration broken: {result.stdout!r} {result.stderr!r}")

    def test_wrapper_not_applied_outside_scope(self):
        """Iterator wrapper should not be applied outside sandbox scope."""
        from itertools import islice, cycle

        # Outside sandbox scope, iteration should work without limit check
        sys.sandbox.set_config(max_iterations=10)
        # NOT entering scope

        # This should work even though limit is 10, because we're not in scope
        result = list(islice(cycle([1]), 100))
        self.assertEqual(len(result), 100)


if __name__ == '__main__':
    unittest.main()
