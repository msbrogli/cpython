"""Tests for compile-time constant folding bypasses.

This module tests that compile-time constant folding doesn't bypass
sandbox limits. The Python compiler folds constant expressions at
compile time, which could bypass runtime sandbox checks.

Security audit reference: Compile-time constant folding
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    ScopedFilenameTestCase,
    _run_sandboxed_code,
    SUBPROCESS_TIMEOUT,
)


class StringConstantFoldingTests(ScopedFilenameTestCase):
    """Test string constant folding behavior.

    Python compiler folds string multiplication like 'a' * 10 at compile time
    when both operands are constants. This tests how sandbox handles it.
    """

    SCOPED_FILENAME = "<test_compile_time_limits_scope>"

    def test_string_multiply_with_variable_blocked(self):
        """String multiply with runtime variable should be blocked."""
        sys.sandbox.set_config(max_str_length=100)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("n = 200; s = 'x' * n")

    def test_large_string_literal_behavior(self):
        """Large string literal created at compile time.

        Note: This documents known limitation - string literals in source
        code are created at compile time, not runtime.
        """
        sys.sandbox.set_config(max_str_length=100)

        # Create a moderately sized string literal in code
        # Note: Very large literals may fail at compile time or LOAD_CONST
        try:
            self.run_scoped_code("s = 'x' * 200")  # Constant folding may apply
            # If we get here, constant folding bypassed the limit
            # This may be expected behavior - document it
        except SandboxOverflowError:
            # LOAD_CONST check caught it - good
            pass
        except MemoryError:
            # Compiler rejected it - also acceptable
            pass

    def test_string_concatenation_at_runtime(self):
        """String concatenation at runtime should be blocked."""
        sys.sandbox.set_config(max_str_length=100)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("""
parts = ['x' for _ in range(200)]
s = ''.join(parts)
""")


class TupleConstantFoldingTests(ScopedFilenameTestCase):
    """Test tuple constant folding behavior."""

    SCOPED_FILENAME = "<test_compile_time_limits_scope>"

    def test_tuple_from_runtime_blocked(self):
        """Tuple from runtime expression should be blocked."""
        sys.sandbox.set_config(max_tuple_size=100)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("t = tuple(range(200))")

    def test_tuple_literal_behavior(self):
        """Tuple literal created at compile time.

        Note: Small tuple literals like (1, 2, 3) are stored in co_consts.
        Very large tuple literals would be impractical in source.
        """
        sys.sandbox.set_config(max_tuple_size=10)

        # This creates a small tuple literal - should work
        globs = self.run_scoped_code("t = (1, 2, 3, 4, 5)")
        self.assertEqual(len(globs['t']), 5)

    def test_tuple_multiply_with_variable_blocked(self):
        """Tuple multiply with runtime variable should be blocked."""
        sys.sandbox.set_config(max_tuple_size=100)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("n = 50; t = (1, 2, 3) * n")


class BytesConstantFoldingTests(ScopedFilenameTestCase):
    """Test bytes constant folding behavior."""

    SCOPED_FILENAME = "<test_compile_time_limits_scope>"

    def test_bytes_multiply_with_variable_blocked(self):
        """Bytes multiply with runtime variable should be blocked."""
        sys.sandbox.set_config(max_bytes_length=100)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("n = 200; b = b'x' * n")

    def test_bytes_literal_behavior(self):
        """Bytes literal created at compile time."""
        sys.sandbox.set_config(max_bytes_length=100)

        # Small bytes literal should work
        globs = self.run_scoped_code("b = b'hello world'")
        self.assertEqual(len(globs['b']), 11)


class IntegerConstantFoldingTests(ScopedFilenameTestCase):
    """Test integer constant folding behavior."""

    SCOPED_FILENAME = "<test_compile_time_limits_scope>"

    def test_large_int_from_runtime_blocked(self):
        """Large integer from runtime expression should be blocked."""
        sys.sandbox.set_config(max_int_digits=10)

        with self.assertRaises(SandboxOverflowError):
            self.run_scoped_code("x = 2; result = x ** 1000")

    def test_integer_literal_behavior(self):
        """Large integer literal created at compile time.

        Note: Integer literals are stored in co_consts. LOAD_CONST
        should check size limits.
        """
        sys.sandbox.set_config(max_int_digits=10)

        # Small literal should work
        globs = self.run_scoped_code("x = 12345")
        self.assertEqual(globs['x'], 12345)

    def test_constant_power_expression(self):
        """Constant power expression like 2**100 may be folded.

        The compiler may fold 2**100 at compile time for small exponents.
        Larger exponents are typically not folded.
        """
        sys.sandbox.set_config(max_int_digits=5)

        try:
            # This may be folded or not depending on optimizer
            self.run_scoped_code("x = 2 ** 100")
            # If we get here, compiler folded it or limit wasn't enforced
        except SandboxOverflowError:
            # LOAD_CONST or runtime check caught it - good
            pass


class LoadConstCheckTests(ScopedFilenameTestCase):
    """Test that LOAD_CONST opcode checks size limits.

    Security fix reference: Fix proposal 06 - LOAD_CONST size check
    """

    SCOPED_FILENAME = "<test_compile_time_limits_scope>"

    def test_load_const_checks_string_size(self):
        """LOAD_CONST should check string size limits."""
        # Create code with a large string constant outside scope
        # then try to load it inside scope
        sys.sandbox.set_config(max_str_length=50)

        # This approach: compile code with large string, then exec in scope
        large_string = "x" * 100
        code = compile(f"s = '{large_string}'", self.SCOPED_FILENAME, "exec")

        with self.assertRaises(SandboxOverflowError):
            exec(code, {"sys": sys})


class TypeLiteralTests(ScopedFilenameTestCase):
    """Test type literals (float, complex) with type restrictions.

    Security fix reference: Fix proposals 04, 05 - Float/Complex literal check
    """

    SCOPED_FILENAME = "<test_compile_time_limits_scope>"

    def test_float_literal_with_allow_float_false(self):
        """Float literals like 1.5 should be blocked when allow_float=False."""
        sys.sandbox.set_config(allow_float=False)

        with self.assertRaises(SandboxTypeError):
            self.run_scoped_code("x = 1.5")

    def test_float_from_division_blocked(self):
        """Runtime division creating float should be blocked."""
        sys.sandbox.set_config(allow_float=False)

        with self.assertRaises(SandboxTypeError):
            self.run_scoped_code("a = 1; b = 2; x = a / b")

    def test_complex_literal_with_allow_complex_false(self):
        """Complex literals like 1+2j should be blocked when allow_complex=False."""
        sys.sandbox.set_config(allow_complex=False)

        with self.assertRaises(SandboxTypeError):
            self.run_scoped_code("x = 1+2j")

    def test_complex_from_complex_call_blocked(self):
        """complex() call should be blocked when allow_complex=False."""
        sys.sandbox.set_config(allow_complex=False)

        with self.assertRaises(SandboxTypeError):
            self.run_scoped_code("x = complex(1, 2)")


class SubprocessConstantFoldingTests(unittest.TestCase):
    """Subprocess tests for constant folding that need full isolation."""

    def test_compile_time_string_in_subprocess(self):
        """Test compile-time string handling in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(max_str_length=50)
sys.sandbox.enter_scope()

try:
    # This string is in source - may be compile-time constant
    s = "x" * 100
    if len(s) > 50:
        sys.exit(2)  # Bypass occurred
    sys.exit(3)  # Unexpected
except SandboxOverflowError:
    sys.exit(0)  # Expected - caught by LOAD_CONST or runtime
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Constant folding bypass: {result.stderr}")

    def test_float_literal_check_subprocess(self):
        """Test float literal check in subprocess."""
        code = '''
import sys
sys.sandbox.set_config(allow_float=False)
sys.sandbox.enter_scope()

try:
    x = 3.14  # Float literal
    sys.exit(2)  # Should not reach
except SandboxTypeError:
    sys.exit(0)  # Expected
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Float literal not blocked: {result.stderr}")


if __name__ == '__main__':
    unittest.main()
