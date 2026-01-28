"""Tests for scoped allocation counting."""

import subprocess
import sys
import unittest

from test.test_sandbox import _run_sandboxed_code, _get_settable_limits


# Filename used for scoped test code (distinct from test file)
SCOPED_FILENAME = "<test_allocations_scope>"


def _run_scoped(code_str, extra_globals=None):
    """Execute code within sandbox scope using a separate filename."""
    globs = {"sys": sys}
    if extra_globals:
        globs.update(extra_globals)
    code = compile(code_str, SCOPED_FILENAME, "exec")
    exec(code, globs)
    return globs


class ScopedAllocationCountTests(unittest.TestCase):
    """Test scoped allocation counting."""

    def setUp(self):
        # Reset all counters for clean test state
        sys.sandbox.reset_counts()
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.remove_filename(SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        sys.sandbox.set_limits(**self.original_limits)
        sys.sandbox.reset_counts()

    def test_set_and_get_scope_max_allocations(self):
        """Setting and getting scope_max_allocations should work."""
        sys.sandbox.set_limits(max_allocations=5000)
        limits = sys.sandbox.get_limits()
        self.assertEqual(limits['max_allocations'], 5000)

    def test_scoped_allocation_count_tracked(self):
        """Scoped allocation count should be tracked when in scope."""
        sys.sandbox.set_limits(max_allocations=10000)
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # Create many objects and KEEP REFERENCES so they don't get garbage collected
        # (getsandboxcounts() itself allocates, so we need significant margin)
        globs = _run_scoped("""
result = []
for _ in range(100):
    result.append([1, 2, 3])
    result.append({'a': 1})
""")

        count = sys.sandbox.get_counts()['allocation_count']
        # After 200 object creations (100 lists + 100 dicts), expect at least
        # some allocations. Using a threshold of 50 because:
        # 1. Some small objects may use cached/interned instances
        # 2. Containers may reuse pre-allocated memory
        # 3. The exact count depends on Python's memory management
        # The key behavior is that allocations ARE being counted (count > 0)
        self.assertGreater(count, 50)

    def test_exceeding_scoped_allocation_limit_raises_memory_error(self):
        """Exceeding scoped allocation limit should raise SandboxMemoryError."""
        code = '''
import sys
sys.sandbox.set_limits(max_allocations=100)
sys.sandbox.enter_scope()
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
        # Exit codes: 0 = success (caught SandboxMemoryError), 2 = error not raised
        # Any other code indicates unexpected behavior
        if result.returncode == 0:
            return  # Test passed - SandboxMemoryError was raised and caught
        elif result.returncode == 2:
            self.fail("SandboxMemoryError was not raised - loop completed without limit")
        elif result.returncode == 1:
            # Uncaught exception - check if it was SandboxMemoryError
            self.assertIn("SandboxMemoryError", result.stderr,
                          f"Unexpected error: stdout={result.stdout!r} stderr={result.stderr!r}")
        else:
            self.fail(f"Unexpected exit code {result.returncode}: "
                     f"stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_reset_allocation_count(self):
        """resetsandboxcounters should reset scope allocation counter."""
        sys.sandbox.set_limits(max_allocations=10000)
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # Create many objects and KEEP REFERENCES so they don't get garbage collected
        globs = _run_scoped("""
result = []
for _ in range(100):
    result.append([1, 2, 3])
""")

        counts_before = sys.sandbox.get_counts()
        # After 100 list creations, expect at least some allocations.
        # Using threshold of 10 because the exact count varies based on
        # Python's memory management and object caching strategies.
        # The key behavior is that allocations ARE being counted (count > 0).
        self.assertGreater(counts_before['allocation_count'], 10)

        # Remove the filename first so reset_counts() works
        sys.sandbox.remove_filename(SCOPED_FILENAME)
        sys.sandbox.reset_counts()
        counts_after = sys.sandbox.get_counts()
        # Count should be close to 0 after reset. A few allocations may occur
        # from the get_counts() call itself (creates dict). Using threshold of 5
        # to allow for the dict allocation plus any internal bookkeeping.
        self.assertLess(counts_after['allocation_count'], 5)

    def test_allocations_outside_scope_dont_count_scoped(self):
        """Allocations outside scope should not count toward scoped limit."""
        sys.sandbox.set_limits(max_allocations=10000)
        sys.sandbox.reset_counts()

        # Not in scope - create many objects and KEEP REFERENCES
        result = []
        for _ in range(100):
            result.append([1, 2, 3])

        counts = sys.sandbox.get_counts()
        # Scoped should not count (not in scope)
        self.assertEqual(counts['allocation_count'], 0)


if __name__ == '__main__':
    unittest.main()
