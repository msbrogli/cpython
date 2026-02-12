"""Tests for sys.sandbox.add_counts() method.

This module tests the add_counts() method which allows incrementing
sandbox counters by specified amounts with overflow and limit checking.
"""

import subprocess
import sys
import unittest


def run_sandbox_test(code: str) -> tuple[int, str, str]:
    """Run a sandbox test in a subprocess.

    Returns (returncode, stdout, stderr).
    """
    result = subprocess.run(
        [sys.executable, '-c', code],
        capture_output=True,
        text=True,
        timeout=10
    )
    return result.returncode, result.stdout, result.stderr


class AddCountsBasicTest(unittest.TestCase):
    """Test basic add_counts functionality."""

    def test_add_counts_requires_enabled_sandbox(self):
        """add_counts should raise RuntimeError when sandbox is disabled."""
        code = '''
import sys
sys.sandbox.disable()
try:
    sys.sandbox.add_counts(operation_count=10)
    print("FAIL: no exception raised")
except RuntimeError as e:
    if "disabled" in str(e):
        print("PASS")
    else:
        print(f"FAIL: wrong error: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_works_when_enabled(self):
        """add_counts should work when sandbox is enabled."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=10, iteration_count=5)
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 10 and counts['iteration_count'] == 5:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_keyword_only_operation(self):
        """add_counts should work with only operation_count keyword."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=100)
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 100 and counts['iteration_count'] == 0:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_keyword_only_iteration(self):
        """add_counts should work with only iteration_count keyword."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(iteration_count=50)
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 0 and counts['iteration_count'] == 50:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_accumulates(self):
        """Multiple add_counts calls should accumulate."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=10)
sys.sandbox.add_counts(operation_count=20)
sys.sandbox.add_counts(iteration_count=5)
sys.sandbox.add_counts(iteration_count=10)
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 30 and counts['iteration_count'] == 15:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_zero_is_noop(self):
        """Adding 0 should not change counters."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=5)
sys.sandbox.add_counts(operation_count=0, iteration_count=0)
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 5 and counts['iteration_count'] == 0:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_no_args_is_noop(self):
        """Calling add_counts with no arguments should be a no-op."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=5)
sys.sandbox.add_counts()  # No arguments
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 5:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class AddCountsValidationTest(unittest.TestCase):
    """Test add_counts input validation."""

    def test_add_counts_rejects_negative_operation(self):
        """add_counts should reject negative operation_count."""
        code = '''
import sys
sys.sandbox.enable()
try:
    sys.sandbox.add_counts(operation_count=-1)
    print("FAIL: no exception")
except ValueError as e:
    if "non-negative" in str(e):
        print("PASS")
    else:
        print(f"FAIL: wrong error: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_rejects_negative_iteration(self):
        """add_counts should reject negative iteration_count."""
        code = '''
import sys
sys.sandbox.enable()
try:
    sys.sandbox.add_counts(iteration_count=-1)
    print("FAIL: no exception")
except ValueError as e:
    if "non-negative" in str(e):
        print("PASS")
    else:
        print(f"FAIL: wrong error: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_rejects_negative_both(self):
        """add_counts should reject negative values for both counters."""
        code = '''
import sys
sys.sandbox.enable()
try:
    sys.sandbox.add_counts(operation_count=-5, iteration_count=-10)
    print("FAIL: no exception")
except ValueError as e:
    if "non-negative" in str(e):
        print("PASS")
    else:
        print(f"FAIL: wrong error: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class AddCountsLimitTest(unittest.TestCase):
    """Test add_counts limit enforcement."""

    def test_add_counts_exceeds_operation_limit(self):
        """add_counts should raise SandboxOverflowError when exceeding max_operations."""
        code = '''
import sys
sys.sandbox.max_operations = 100
sys.sandbox.enable()
sys.sandbox.reset_counts()
try:
    sys.sandbox.add_counts(operation_count=200)
    print("FAIL: no exception")
except SandboxOverflowError as e:
    if "operation_count" in str(e) and "exceeds" in str(e):
        print("PASS")
    else:
        print(f"FAIL: wrong error: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_exceeds_iteration_limit(self):
        """add_counts should raise SandboxOverflowError when exceeding max_iterations."""
        code = '''
import sys
sys.sandbox.max_iterations = 100
sys.sandbox.enable()
sys.sandbox.reset_counts()
try:
    sys.sandbox.add_counts(iteration_count=200)
    print("FAIL: no exception")
except SandboxOverflowError as e:
    if "iteration_count" in str(e) and "exceeds" in str(e):
        print("PASS")
    else:
        print(f"FAIL: wrong error: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_at_exact_limit(self):
        """add_counts should work when reaching exactly the limit."""
        code = '''
import sys
sys.sandbox.max_operations = 100
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=100)  # Exactly at limit
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 100:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_just_above_limit(self):
        """add_counts should fail when going just above the limit."""
        code = '''
import sys
sys.sandbox.max_operations = 100
sys.sandbox.enable()
sys.sandbox.reset_counts()
try:
    sys.sandbox.add_counts(operation_count=101)  # One above limit
    print("FAIL: no exception")
except SandboxOverflowError:
    print("PASS")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_incremental_exceeds_limit(self):
        """add_counts should fail when incremental adds exceed the limit."""
        code = '''
import sys
sys.sandbox.max_operations = 100
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=60)  # OK
try:
    sys.sandbox.add_counts(operation_count=50)  # Would make 110, exceeds limit
    print("FAIL: no exception")
except SandboxOverflowError:
    # Counter should be at 110 (increment happened before check)
    counts = sys.sandbox.get_counts()
    if counts['operation_count'] == 110:
        print("PASS")
    else:
        print(f"FAIL: unexpected counter value: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_no_limit_allows_large_values(self):
        """add_counts should allow large values when no limit is set."""
        code = '''
import sys
sys.sandbox.max_operations = 0  # No limit
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=999999999)
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 999999999:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class AddCountsOverflowTest(unittest.TestCase):
    """Test add_counts overflow protection.

    Note: The API uses long long (signed 64-bit) for parsing, so max input
    per call is 2^63-1 (LLONG_MAX). The overflow check protects against
    cases where repeated additions would exceed UINT64_MAX.
    """

    def test_add_counts_overflow_operation_count(self):
        """add_counts should raise SandboxOverflowError on uint64 overflow."""
        code = '''
import sys
sys.sandbox.max_operations = 0  # No limit, but overflow still checked
sys.sandbox.enable()
sys.sandbox.reset_counts()

# LLONG_MAX = 2^63 - 1 = 9223372036854775807
# UINT64_MAX = 2^64 - 1 = 18446744073709551615
# LLONG_MAX + LLONG_MAX = 18446744073709551614 (UINT64_MAX - 1, still valid!)
# So we need to add LLONG_MAX twice, then add more to overflow
llong_max = (1 << 63) - 1

sys.sandbox.add_counts(operation_count=llong_max)  # counter = LLONG_MAX
sys.sandbox.add_counts(operation_count=llong_max)  # counter = UINT64_MAX - 1

try:
    sys.sandbox.add_counts(operation_count=2)  # Would exceed UINT64_MAX
    print("FAIL: no exception on overflow")
except SandboxOverflowError as e:
    if "overflow" in str(e).lower():
        print("PASS")
    else:
        print(f"FAIL: wrong error message: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_overflow_iteration_count(self):
        """add_counts should raise SandboxOverflowError on iteration_count overflow."""
        code = '''
import sys
sys.sandbox.max_iterations = 0  # No limit, but overflow still checked
sys.sandbox.enable()
sys.sandbox.reset_counts()

# LLONG_MAX = 2^63 - 1, need to add twice then more to overflow
llong_max = (1 << 63) - 1

sys.sandbox.add_counts(iteration_count=llong_max)  # counter = LLONG_MAX
sys.sandbox.add_counts(iteration_count=llong_max)  # counter = UINT64_MAX - 1

try:
    sys.sandbox.add_counts(iteration_count=2)  # Would exceed UINT64_MAX
    print("FAIL: no exception on overflow")
except SandboxOverflowError as e:
    if "overflow" in str(e).lower():
        print("PASS")
    else:
        print(f"FAIL: wrong error message: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_incremental_overflow(self):
        """add_counts should detect overflow from incremental additions."""
        code = '''
import sys
sys.sandbox.max_operations = 0  # No limit
sys.sandbox.enable()
sys.sandbox.reset_counts()

# LLONG_MAX = 2^63 - 1
llong_max = (1 << 63) - 1

# Add LLONG_MAX
sys.sandbox.add_counts(operation_count=llong_max)

# Add a smaller amount that still causes overflow
# llong_max + llong_max > UINT64_MAX, so even adding 1 more after
# the counter is at llong_max and we try to add llong_max again
# should fail

# First verify we can add smaller amounts
sys.sandbox.add_counts(operation_count=1000)  # Should work

counts = sys.sandbox.get_counts()
expected = llong_max + 1000
if counts["operation_count"] == expected:
    # Now try to overflow
    try:
        sys.sandbox.add_counts(operation_count=llong_max)
        print("FAIL: should have overflowed")
    except SandboxOverflowError:
        print("PASS")
else:
    print(f"FAIL: unexpected count: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_value_too_large_for_longlong(self):
        """Values > LLONG_MAX should raise OverflowError at parsing."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()

# Value larger than LLONG_MAX (2^63 - 1)
too_large = (1 << 63)  # 2^63, one more than LLONG_MAX

try:
    sys.sandbox.add_counts(operation_count=too_large)
    print("FAIL: should have raised OverflowError")
except OverflowError:
    print("PASS")  # Expected - value too large for long long
except Exception as e:
    print(f"FAIL: wrong exception type: {type(e).__name__}: {e}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


class AddCountsInteractionTest(unittest.TestCase):
    """Test add_counts interaction with other sandbox features."""

    def test_add_counts_with_reset(self):
        """reset_counts should clear counts added by add_counts."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=100, iteration_count=50)
sys.sandbox.reset_counts()
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 0 and counts['iteration_count'] == 0:
    print("PASS")
else:
    print(f"FAIL: {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_combined_with_natural_counting(self):
        """add_counts should combine with natural operation counting."""
        code = '''
import sys

PyCF_SANDBOX_COUNT = 0x8000

sys.sandbox.max_operations = 1000
sys.sandbox.enable()
sys.sandbox.add_filename("<sandbox>")
sys.sandbox.reset_counts()

# Pre-add some counts
sys.sandbox.add_counts(operation_count=50)

# Execute code that also counts operations
code = compile("x = 1 + 2", "<sandbox>", "exec", flags=PyCF_SANDBOX_COUNT)
exec(code)

counts = sys.sandbox.get_counts()
# Should have 50 + operations from compiled code
if counts['operation_count'] > 50:
    print("PASS")
else:
    print(f"FAIL: expected > 50, got {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")

    def test_add_counts_preserves_other_counter(self):
        """Adding to one counter should not affect the other."""
        code = '''
import sys
sys.sandbox.enable()
sys.sandbox.reset_counts()
sys.sandbox.add_counts(operation_count=100)
counts = sys.sandbox.get_counts()
if counts['operation_count'] == 100 and counts['iteration_count'] == 0:
    sys.sandbox.add_counts(iteration_count=50)
    counts = sys.sandbox.get_counts()
    if counts['operation_count'] == 100 and counts['iteration_count'] == 50:
        print("PASS")
    else:
        print(f"FAIL: second check {counts}")
else:
    print(f"FAIL: first check {counts}")
'''
        rc, out, err = run_sandbox_test(code)
        self.assertIn("PASS", out, f"Output: {out}\nStderr: {err}")


if __name__ == '__main__':
    unittest.main()
