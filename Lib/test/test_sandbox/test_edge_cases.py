"""Tests for sandbox edge cases and boundary conditions."""

import sys
import unittest

from test.test_sandbox import SandboxTestCase, SandboxScopedTestCase, _run_sandboxed_code


# Filename used for scoped test code (distinct from test file)
SCOPED_FILENAME = "<test_edge_cases_scope>"


def _run_scoped(code_str, extra_globals=None):
    """Execute code within sandbox scope using a separate filename."""
    globs = {"sys": sys}
    if extra_globals:
        globs.update(extra_globals)
    code = compile(code_str, SCOPED_FILENAME, "exec")
    exec(code, globs)
    return globs


class LimitBoundaryTests(SandboxTestCase):
    """Test boundary conditions for limit values."""

    def tearDown(self):
        try:
            sys.sandbox.remove_filename(SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        super().tearDown()

    def test_limit_zero_allows_unlimited(self):
        """Setting limit to 0 should disable the limit (allow unlimited)."""
        # Zero means no limit
        sys.sandbox.set_limits(max_list_size=0)
        sys.sandbox.add_filename(SCOPED_FILENAME)
        # Should succeed with any size
        globs = _run_scoped("lst = list(range(10000))")
        self.assertEqual(len(globs['lst']), 10000)

    def test_limit_small_list_size(self):
        """Setting a small list size limit should block large lists."""
        sys.sandbox.set_limits(max_list_size=5)
        sys.sandbox.add_filename(SCOPED_FILENAME)
        # Creating a small list should work
        globs = _run_scoped("lst = [1, 2, 3]")
        self.assertEqual(len(globs['lst']), 3)
        # Creating a list beyond the limit should fail
        with self.assertRaises(SandboxOverflowError):
            _run_scoped("large_lst = list(range(100))")


    def test_limit_one_iteration(self):
        """Setting max_iterations to 1 should allow exactly one iteration."""
        code = '''
import sys
sys.sandbox.set_limits(max_iterations=1)
sys.sandbox.enter_scope()
try:
    for i in range(10):
        pass
    sys.exit(2)  # Should not reach here
except SandboxRuntimeError as e:
    if "iteration limit" in str(e):
        sys.exit(0)
    sys.exit(3)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Iteration limit=1 not enforced: {result.stderr}")


class NegativeLimitTests(SandboxTestCase):
    """Test behavior with negative limits.

    Note: The current implementation allows negative values for Py_ssize_t
    limits (max_int_digits, etc.) via set_limits(), but property setters
    reject them with ValueError. Negative values effectively act as no-limit
    since size comparisons will always be less than a negative limit.
    """

    def test_negative_property_assignment_rejected(self):
        """Negative values via property assignment should raise ValueError."""
        with self.assertRaises(ValueError):
            sys.sandbox.max_int_digits = -1

    def test_negative_property_assignment_str_rejected(self):
        """Negative max_str_length via property should raise ValueError."""
        with self.assertRaises(ValueError):
            sys.sandbox.max_str_length = -1

    def test_negative_property_assignment_list_rejected(self):
        """Negative max_list_size via property should raise ValueError."""
        with self.assertRaises(ValueError):
            sys.sandbox.max_list_size = -1


class OverflowProtectionTests(SandboxTestCase):
    """Test overflow protection for uint64_t limits."""

    def test_max_iterations_overflow_rejected(self):
        """Setting max_iterations near UINT64_MAX should raise OverflowError."""
        with self.assertRaises(OverflowError):
            sys.sandbox.max_iterations = (2**64 - 1)

    def test_max_operations_overflow_rejected(self):
        """Setting max_operations near UINT64_MAX should raise OverflowError."""
        with self.assertRaises(OverflowError):
            sys.sandbox.max_operations = (2**64 - 1)

    def test_set_limits_overflow_rejected(self):
        """set_limits() should reject overflow values."""
        with self.assertRaises(OverflowError):
            sys.sandbox.set_limits(max_iterations=(2**64 - 1))


class NestedScopeTests(SandboxTestCase):
    """Test nested scope handling."""

    def tearDown(self):
        try:
            sys.sandbox.remove_filename(SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        super().tearDown()

    def test_nested_enter_scope_blocked_from_scope(self):
        """Calling enter_scope() while in scope should raise SandboxSecurityError.

        Security feature: code running in sandbox scope cannot modify sandbox
        configuration, including calling enter_scope() again.
        """
        code = '''
import sys
sys.sandbox.set_limits(max_iterations=100000, max_operations=100000)
sys.sandbox.enter_scope()

# Do some work to increment counters
result = []
for _ in range(50):
    result.append([1, 2, 3])

# Try to enter scope again - should be blocked
try:
    sys.sandbox.enter_scope()
    sys.exit(2)  # Should not reach here
except SandboxSecurityError:
    sys.exit(0)  # Expected behavior
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Nested enter_scope should raise SandboxSecurityError: {result.stdout} {result.stderr}")

    def test_nested_scope_with_different_filenames(self):
        """Nested scopes with different filenames should work correctly."""
        code = '''
import sys
sys.sandbox.set_limits(max_operations=1000000)

# Register first filename
sys.sandbox.add_filename("<outer>")

# Run outer code
exec(compile("""
x = 0
for i in range(10):
    x += 1
""", "<outer>", "exec"))

outer_count = sys.sandbox.get_counts()['operation_count']

# Add inner filename (both should now be tracked)
sys.sandbox.add_filename("<inner>")

# Run inner code
exec(compile("""
y = 0
for i in range(10):
    y += 1
""", "<inner>", "exec"))

combined_count = sys.sandbox.get_counts()['operation_count']
sys.sandbox.clear_filenames()

# Both should have contributed
print(f"outer={outer_count}, combined={combined_count}")
sys.exit(0 if combined_count > outer_count > 0 else 1)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Nested filenames failed: {result.stdout} {result.stderr}")


class DeeplyNestedCodeTests(SandboxTestCase):
    """Test deeply nested code structures."""

    def tearDown(self):
        try:
            sys.sandbox.remove_filename(SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        super().tearDown()

    def test_deeply_nested_functions(self):
        """Deeply nested function definitions should work correctly."""
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # Create deeply nested functions
        globs = _run_scoped("""
def level1():
    def level2():
        def level3():
            def level4():
                return 42
            return level4()
        return level3()
    return level2()

result = level1()
""")
        self.assertEqual(globs['result'], 42)

    def test_deeply_nested_lambdas(self):
        """Deeply nested lambdas should work correctly."""
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # Create deeply nested lambdas
        globs = _run_scoped("""
f = lambda: (lambda: (lambda: (lambda: 42)())())()
result = f()
""")
        self.assertEqual(globs['result'], 42)



class ScopeContextManagerTests(SandboxTestCase):
    """Test scope context manager edge cases."""

    def test_scope_context_manager_exception_handling(self):
        """Scope context manager should properly exit on exception."""
        try:
            with sys.sandbox.scope():
                self.assertTrue(sys.sandbox.in_scope())
                raise ValueError("test exception")
        except ValueError:
            pass

        # Should be out of scope after exception
        self.assertFalse(sys.sandbox.in_scope())

    def test_nested_scope_context_managers(self):
        """Nested scope context managers should work correctly."""
        with sys.sandbox.scope():
            self.assertTrue(sys.sandbox.in_scope())
            # Can't really nest scopes since they share the same filename
            # but the context manager should still work
            count1 = sys.sandbox.get_counts()['operation_count']

        self.assertFalse(sys.sandbox.in_scope())


class SuspendedLimitsEdgeCases(SandboxTestCase):
    """Test edge cases for suspend/resume."""

    def tearDown(self):
        # Resume any suspended limits
        while sys.sandbox.suspended:
            sys.sandbox.resume()
        try:
            sys.sandbox.remove_filename(SCOPED_FILENAME)
        except (RuntimeError, KeyError):
            pass
        super().tearDown()

    def test_deeply_nested_suspend_resume(self):
        """Many levels of suspend/resume should work correctly."""
        sys.sandbox.set_limits(max_list_size=5)
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # Suspend 10 times
        for i in range(10):
            count = sys.sandbox.suspend()
            self.assertEqual(count, i + 1)

        # Should work while suspended
        globs = _run_scoped("lst = list(range(100))")
        self.assertEqual(len(globs['lst']), 100)

        # Resume 10 times
        for i in range(10, 0, -1):
            count = sys.sandbox.resume()
            self.assertEqual(count, i - 1)

        # Should fail now
        with self.assertRaises(SandboxOverflowError):
            _run_scoped("lst = list(range(100))")


if __name__ == '__main__':
    unittest.main()
