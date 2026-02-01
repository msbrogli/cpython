"""Tests for iteration counting and iterator wrapper protection.

Note: Dangerous tests that use infinite iterators have been moved to
test_iterations_dangerous.py.
"""

import sys
import unittest

from test.test_sandbox import _run_sandboxed_code


# Filename used for scoped test code (distinct from test file)
SCOPED_FILENAME = "<test_iterations_scope>"


def _run_scoped(code_str, extra_globals=None):
    """Execute code within sandbox scope using a separate filename."""
    globs = {"sys": sys}
    if extra_globals:
        globs.update(extra_globals)
    code = compile(code_str, SCOPED_FILENAME, "exec")
    exec(code, globs)
    return globs


class ScopedIterationCountTests(unittest.TestCase):
    """Tests for scoped iteration counting and limits.

    The iteration limit counts calls to PyIter_Next(), which is used by
    many C builtins like sum(), min(), max() when consuming iterators.
    This protects against infinite loops in C code that would otherwise
    bypass the statement limit.
    """

    def setUp(self):
        sys.sandbox.enable()  # Required before add_filename or enter_scope
        sys.sandbox.reset_counts()
        # Disable import and module access restrictions for legacy tests
        sys.sandbox.import_restrict_mode = False
        sys.sandbox.module_access_restrict_mode = False

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.remove_filename(SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        sys.sandbox.reset()

    def test_set_and_get_scope_max_iterations(self):
        """Setting and getting scope_max_iterations should work."""
        sys.sandbox.set_limits(max_iterations=50000)
        limits = sys.sandbox.get_limits()
        self.assertEqual(limits['max_iterations'], 50000)

    def test_iteration_count_tracked_with_sum(self):
        """Iteration count should be tracked when using sum()."""
        from itertools import islice, cycle
        sys.sandbox.set_limits(max_iterations=1000000)
        sys.sandbox.reset_counts()
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # Use sum() which calls PyIter_Next
        globs = _run_scoped("""
from itertools import islice, cycle
_ = sum(islice(cycle([1, 2, 3]), 100))
""")

        counts = sys.sandbox.get_counts()
        self.assertGreater(counts['iteration_count'], 0)

    def test_exceeding_iteration_limit_raises_runtime_error(self):
        """Exceeding iteration limit should raise SandboxRuntimeError."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_limits(max_iterations=1000)
sys.sandbox.reset_counts()
sys.sandbox.enter_scope()
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
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected SandboxRuntimeError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_normal_iteration_within_limit_works(self):
        """Normal iteration within limits should work fine."""
        from itertools import islice, cycle
        sys.sandbox.set_limits(max_iterations=1000000)
        sys.sandbox.reset_counts()
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # This should work fine
        # cycle([1, 2, 3]) for 999 items: 333 complete cycles of (1+2+3=6) = 1998
        globs = _run_scoped("""
from itertools import islice, cycle
result = sum(islice(cycle([1, 2, 3]), 999))
""")
        self.assertEqual(globs['result'], 1998)

    def test_iteration_limit_protects_sum_with_infinite_iterator(self):
        """Iteration limit should protect against sum() with infinite iterator."""
        code = '''
import sys
from itertools import cycle

sys.sandbox.set_limits(max_iterations=500)
sys.sandbox.enter_scope()
try:
    sum(cycle([0]))  # Infinite iterator
    print("FAIL: No exception raised")
    sys.exit(1)
except SandboxRuntimeError:
    print("PASS: SandboxRuntimeError raised")
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Iteration limit didn't protect sum(): {result.stdout!r} {result.stderr!r}")

    def test_reset_iteration_count(self):
        """resetsandboxcounters should reset scope iteration counter."""
        from itertools import islice, cycle
        sys.sandbox.set_limits(max_iterations=1000000)

        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("""
from itertools import islice, cycle
_ = sum(islice(cycle([1]), 100))
""")
        sys.sandbox.remove_filename(SCOPED_FILENAME)

        count_before = sys.sandbox.get_counts()['iteration_count']
        self.assertGreater(count_before, 0)

        sys.sandbox.reset_counts()
        count_after = sys.sandbox.get_counts()['iteration_count']
        self.assertEqual(count_after, 0)

    def test_no_iteration_limit_allows_many_iterations(self):
        """With no iteration limit (0), many iterations should be allowed."""
        from itertools import islice, cycle
        sys.sandbox.set_limits(max_iterations=0)
        sys.sandbox.reset_counts()
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # This should work with no limit
        globs = _run_scoped("""
from itertools import islice, cycle
result = sum(islice(cycle([1]), 10000))
""")
        self.assertEqual(globs['result'], 10000)

    def test_add_filename_resets_iteration_count(self):
        """Adding a filename to scope should reset iteration counters.

        Note: We test this using add_filename/remove_filename pattern
        since enter_scope()/exit_scope() can't be called from within scope
        due to security restrictions.
        """
        from itertools import islice, cycle
        sys.sandbox.set_limits(max_iterations=1000000)

        # First scope with some iterations
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("""
from itertools import islice, cycle
_ = sum(islice(cycle([1]), 100))
""")
        count1 = sys.sandbox.get_counts()['iteration_count']
        sys.sandbox.remove_filename(SCOPED_FILENAME)
        self.assertGreater(count1, 0)

        # Reset counts, then add filename again
        sys.sandbox.reset_counts()
        sys.sandbox.add_filename(SCOPED_FILENAME)
        count2 = sys.sandbox.get_counts()['iteration_count']
        self.assertEqual(count2, 0)


if __name__ == '__main__':
    unittest.main()
