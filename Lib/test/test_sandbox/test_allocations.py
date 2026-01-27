"""Tests for global and scoped allocation counting."""

import subprocess
import sys
import unittest

from test.test_sandbox import _run_sandboxed_code, _get_settable_limits


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


if __name__ == '__main__':
    unittest.main()
