"""Tests for dunder attribute blocking."""

import sys
import unittest

from test.test_sandbox import _run_sandboxed_code, _get_settable_limits


class DunderAccessBlockingTests(unittest.TestCase):
    """Test dunder attribute blocking."""

    def setUp(self):
        self.original_limits = _get_settable_limits()

    def tearDown(self):
        sys.sandbox.set_limits(**self.original_limits)
        try:
            sys.sandbox.exit_scope()
        except RuntimeError:
            pass

    def test_default_allows_dunder(self):
        """Default should allow dunder access."""
        limits = sys.sandbox.get_limits()
        self.assertTrue(limits['allow_dunder_access'])

    def test_dunder_read_blocked(self):
        """Reading dunder attributes blocked when configured."""
        code = '''
import sys
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.enter_scope()
x = {}
try:
    d = x.__class__
    print("ERROR: should have raised")
    sys.exit(1)
except SandboxAttributeError as e:
    print("OK:", e)
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected exit code 0, got {result.returncode}: {result.stderr}")
        self.assertIn("OK:", result.stdout)
        self.assertNotIn("ERROR:", result.stdout)

    def test_dunder_write_blocked(self):
        """Writing dunder attributes blocked when configured."""
        code = '''
import sys
# Define class BEFORE entering sandbox scope
class Foo:
    pass
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.enter_scope()
try:
    Foo.__doc__ = "hacked"
    print("ERROR: should have raised")
    sys.exit(1)
except SandboxAttributeError as e:
    print("OK:", e)
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected exit code 0, got {result.returncode}: {result.stderr}")
        self.assertIn("OK:", result.stdout)
        self.assertNotIn("ERROR:", result.stdout)

    def test_dunder_delete_blocked(self):
        """Deleting dunder attributes blocked when configured."""
        code = '''
import sys
# Define class BEFORE entering sandbox scope
class Foo:
    __doc__ = "test"
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.enter_scope()
try:
    del Foo.__doc__
    print("ERROR: should have raised")
    sys.exit(1)
except SandboxAttributeError as e:
    print("OK:", e)
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected exit code 0, got {result.returncode}: {result.stderr}")
        self.assertIn("OK:", result.stdout)
        self.assertNotIn("ERROR:", result.stdout)

    def test_normal_attr_allowed(self):
        """Normal attributes still allowed when dunder blocked."""
        code = '''
import sys
# Define class BEFORE entering sandbox scope
class Foo:
    pass
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.enter_scope()
Foo.bar = 42
print("OK:", Foo.bar)
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected exit code 0, got {result.returncode}: {result.stderr}")
        self.assertIn("OK: 42", result.stdout)

    def test_outside_scope_allowed(self):
        """Dunder access allowed outside sandbox scope."""
        code = '''
import sys
sys.sandbox.set_limits(allow_dunder_access=False)
# NOT entering sandbox scope
x = {}
print("OK:", x.__class__.__name__)
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected exit code 0, got {result.returncode}: {result.stderr}")
        self.assertIn("OK: dict", result.stdout)

    def test_dunder_blocked_with_filename_scope(self):
        """Dunder blocking should work with filename-based scope tracking."""
        code = '''
import sys
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.add_filename("<sandbox>")

try:
    exec(compile("""
x = {}
d = x.__class__
""", "<sandbox>", "exec"))
    print("ERROR: should have raised")
    sys.exit(1)
except SandboxAttributeError as e:
    print("OK:", e)
    sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected exit code 0, got {result.returncode}: {result.stderr}")
        self.assertIn("OK:", result.stdout)
        self.assertNotIn("ERROR:", result.stdout)

    def test_dunder_allowed_when_enabled(self):
        """Dunder access allowed when allow_dunder_access is True."""
        code = '''
import sys
sys.sandbox.set_limits(allow_dunder_access=True)
sys.sandbox.enter_scope()
x = {}
print("OK:", x.__class__.__name__)
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected exit code 0, got {result.returncode}: {result.stderr}")
        self.assertIn("OK: dict", result.stdout)

    def test_single_underscore_allowed(self):
        """Single underscore attributes should still be allowed."""
        code = '''
import sys
# Define class BEFORE entering sandbox scope
class Foo:
    pass
sys.sandbox.set_limits(allow_dunder_access=False)
sys.sandbox.enter_scope()
Foo._private = 42
print("OK:", Foo._private)
sys.exit(0)
'''
        result = _run_sandboxed_code(code)
        self.assertEqual(result.returncode, 0,
                        f"Expected exit code 0, got {result.returncode}: {result.stderr}")
        self.assertIn("OK: 42", result.stdout)


if __name__ == '__main__':
    unittest.main()
