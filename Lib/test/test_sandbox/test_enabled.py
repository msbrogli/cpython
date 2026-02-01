"""Tests for sandbox enabled flag: enable/disable API."""

import sys
import unittest

from test.test_sandbox import SandboxTestCase, SandboxScopedTestCase


class EnabledFlagBasicTests(SandboxTestCase):
    """Test basic enabled flag functionality."""

    def test_enabled_default_is_false(self):
        """enabled should default to False."""
        sys.sandbox.reset()
        self.assertFalse(sys.sandbox.enabled)

    def test_enable_method_sets_true(self):
        """enable() should set enabled to True."""
        sys.sandbox.enable()
        self.assertTrue(sys.sandbox.enabled)

    def test_disable_method_sets_false(self):
        """disable() should set enabled to False."""
        sys.sandbox.enable()
        self.assertTrue(sys.sandbox.enabled)
        sys.sandbox.disable()
        self.assertFalse(sys.sandbox.enabled)

    def test_enabled_is_readonly(self):
        """enabled property should be read-only."""
        with self.assertRaises(AttributeError):
            sys.sandbox.enabled = True

    def test_reset_clears_enabled(self):
        """reset() should set enabled back to False."""
        sys.sandbox.enable()
        self.assertTrue(sys.sandbox.enabled)
        sys.sandbox.reset()
        self.assertFalse(sys.sandbox.enabled)


class EnabledFlagSecurityTests(SandboxScopedTestCase):
    """Test that enabled cannot be modified from within sandbox scope."""

    def test_enable_blocked_from_scope(self):
        """enable() should raise SandboxSecurityError from within scope."""
        sys.sandbox.enable()  # Enable before entering scope

        with self.assertRaises(SandboxSecurityError) as cm:
            self.run_scoped_code("sys.sandbox.disable()")
        self.assertIn("Cannot modify sandbox configuration", str(cm.exception))

    def test_disable_blocked_from_scope(self):
        """disable() should also be blocked from within scope."""
        # Start with scope registered (from setUp)
        with self.assertRaises(SandboxSecurityError) as cm:
            self.run_scoped_code("sys.sandbox.enable()")
        self.assertIn("Cannot modify sandbox configuration", str(cm.exception))


class EnabledPropertyInteractionTests(SandboxTestCase):
    """Test interaction of enabled with other sandbox properties."""

    def test_enabled_independent_of_limits(self):
        """enabled flag should be independent of limit values."""
        # Start with sandbox disabled
        sys.sandbox.disable()
        self.assertFalse(sys.sandbox.enabled)

        # Set some limits - this should NOT enable sandbox
        sys.sandbox.set_limits(max_list_size=100)
        self.assertFalse(sys.sandbox.enabled)  # Still disabled

        # Enable
        sys.sandbox.enable()
        self.assertTrue(sys.sandbox.enabled)

        # Limits should still be set
        limits = sys.sandbox.get_limits()
        self.assertEqual(limits['max_list_size'], 100)

    def test_enabled_independent_of_suspended(self):
        """enabled and suspended should be independent."""
        sys.sandbox.enable()
        self.assertTrue(sys.sandbox.enabled)
        self.assertFalse(sys.sandbox.suspended)

        # Suspend
        sys.sandbox.suspend()
        self.assertTrue(sys.sandbox.enabled)  # Still enabled
        self.assertTrue(sys.sandbox.suspended)

        # Resume
        sys.sandbox.resume()
        self.assertTrue(sys.sandbox.enabled)
        self.assertFalse(sys.sandbox.suspended)

        # Disable
        sys.sandbox.disable()
        self.assertFalse(sys.sandbox.enabled)
        self.assertFalse(sys.sandbox.suspended)


if __name__ == '__main__':
    unittest.main()
