"""Tests for scoped allocation counting."""

import subprocess
import sys
import unittest

from test.test_sandbox import _run_sandboxed_code, _get_settable_limits


class ScopedAllocationCountTests(unittest.TestCase):
    """Test scoped allocation counting."""

    def setUp(self):
        # Ensure clean scope state from any previous tests
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass
        # Reset all counters for clean test state
        sys.sandbox.reset_counts()
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
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
        sys.sandbox.enter_scope()

        # Create many objects and KEEP REFERENCES so they don't get garbage collected
        # (getsandboxcounts() itself allocates, so we need significant margin)
        result = []
        for _ in range(100):
            result.append([1, 2, 3])
            result.append({'a': 1})

        count = sys.sandbox.get_counts()['allocation_count']
        # After 200 object creations, should have significant allocations
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
        if result.returncode == 0:
            return  # Test passed
        if result.returncode == 2:
            self.fail("SandboxMemoryError was not raised")
        # If it exited with error, check that SandboxMemoryError was involved
        self.assertIn("SandboxMemoryError", result.stderr,
                      f"Expected SandboxMemoryError, got: stdout={result.stdout!r} stderr={result.stderr!r}")

    def test_reset_allocation_count(self):
        """resetsandboxcounters should reset scope allocation counter."""
        sys.sandbox.set_limits(max_allocations=10000)
        sys.sandbox.enter_scope()

        # Create many objects and KEEP REFERENCES so they don't get garbage collected
        result = []
        for _ in range(100):
            result.append([1, 2, 3])

        counts_before = sys.sandbox.get_counts()
        self.assertGreater(counts_before['allocation_count'], 20)

        sys.sandbox.reset_counts()
        counts_after = sys.sandbox.get_counts()
        # Count may not be exactly 0 due to dict allocation in getsandboxcounts
        self.assertLess(counts_after['allocation_count'], 10)

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
