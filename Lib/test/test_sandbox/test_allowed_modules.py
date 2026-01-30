"""Tests for sandbox module access restriction feature.

This tests the allowlist-based module access control that restricts
which modules can be accessed from within sandbox scope.
"""

import unittest
import sys


class TestModuleAccessRestriction(unittest.TestCase):
    """Test cases for sys.sandbox module access restriction."""

    def setUp(self):
        """Reset sandbox state before each test."""
        sys.sandbox.reset()

    def tearDown(self):
        """Clean up sandbox state after each test."""
        sys.sandbox.reset()

    def test_module_access_restrict_mode_default_on(self):
        """module_access_restrict_mode defaults to True."""
        self.assertTrue(sys.sandbox.module_access_restrict_mode)

    def test_allowed_modules_default_none(self):
        """allowed_modules defaults to None (no modules allowed when restriction on)."""
        self.assertIsNone(sys.sandbox.allowed_modules)

    def test_allow_submodules_default_true(self):
        """allow_submodules defaults to True."""
        self.assertTrue(sys.sandbox.allow_submodules)

    def test_allowed_modules_set_and_get(self):
        """Can set and get allowed_modules."""
        sys.sandbox.allowed_modules = {'json', 'math'}
        allowed = sys.sandbox.allowed_modules
        self.assertIn('json', allowed)
        self.assertIn('math', allowed)
        self.assertEqual(len(allowed), 2)

    def test_allowed_modules_accepts_various_iterables(self):
        """allowed_modules accepts sets, lists, tuples, frozensets."""
        # Set
        sys.sandbox.allowed_modules = {'json'}
        self.assertIn('json', sys.sandbox.allowed_modules)

        # List
        sys.sandbox.allowed_modules = ['math']
        self.assertIn('math', sys.sandbox.allowed_modules)

        # Tuple
        sys.sandbox.allowed_modules = ('collections',)
        self.assertIn('collections', sys.sandbox.allowed_modules)

        # Frozenset
        sys.sandbox.allowed_modules = frozenset({'datetime'})
        self.assertIn('datetime', sys.sandbox.allowed_modules)

    def test_allowed_modules_returns_frozenset(self):
        """allowed_modules getter returns a frozenset (immutable)."""
        sys.sandbox.allowed_modules = {'json'}
        allowed = sys.sandbox.allowed_modules
        self.assertIsInstance(allowed, frozenset)

    def test_allowed_modules_clear_with_none(self):
        """Setting allowed_modules to None clears it."""
        sys.sandbox.allowed_modules = {'json'}
        sys.sandbox.allowed_modules = None
        self.assertIsNone(sys.sandbox.allowed_modules)

    def test_module_access_outside_scope_allowed(self):
        """Accessing modules outside sandbox scope is always allowed."""
        import os
        # No scope registered, so any module should work
        result = os.getcwd()
        self.assertIsNotNone(result)

    def test_module_access_inside_scope_no_allowlist_blocked(self):
        """Accessing modules inside sandbox scope with no allowlist raises error."""
        import os
        # module_access_restrict_mode is True by default, allowed_modules is None
        sys.sandbox.add_filename('<test>')

        code = 'result = os.getcwd()'
        with self.assertRaises(SandboxSecurityError) as cm:
            exec(compile(code, '<test>', 'exec'), {'os': os})

        self.assertIn('os', str(cm.exception))
        self.assertIn('not allowed', str(cm.exception))

    def test_allowed_module_access_allowed(self):
        """Accessing allowed modules inside sandbox scope is allowed."""
        import json
        sys.sandbox.allowed_modules = {'json'}
        sys.sandbox.add_filename('<test>')

        code = 'result = json.dumps({"a": 1})'
        ns = {'json': json}
        exec(compile(code, '<test>', 'exec'), ns)
        self.assertEqual(ns['result'], '{"a": 1}')

    def test_non_allowed_module_access_blocked(self):
        """Accessing non-allowed modules inside sandbox scope raises error."""
        import os
        sys.sandbox.allowed_modules = {'json', 'math'}  # os not in list
        sys.sandbox.add_filename('<test>')

        code = 'result = os.getcwd()'
        with self.assertRaises(SandboxSecurityError) as cm:
            exec(compile(code, '<test>', 'exec'), {'os': os})

        self.assertIn('os', str(cm.exception))
        self.assertIn('not allowed', str(cm.exception))

    def test_submodule_allowed_when_parent_allowed(self):
        """Submodules are allowed when parent module is in allowlist."""
        import xml.etree.ElementTree
        sys.sandbox.allowed_modules = {'xml'}
        sys.sandbox.add_filename('<test>')

        code = 'result = ET.Element("root")'
        ns = {'ET': xml.etree.ElementTree}
        exec(compile(code, '<test>', 'exec'), ns)
        self.assertIsNotNone(ns['result'])

    def test_allow_submodules_false_blocks_submodules(self):
        """With allow_submodules=False, only exact matches are allowed."""
        import xml.etree.ElementTree
        sys.sandbox.allowed_modules = {'xml'}
        sys.sandbox.allow_submodules = False
        sys.sandbox.add_filename('<test>')

        # xml.etree.ElementTree should be blocked (not exact match)
        code = 'result = ET.Element("root")'
        with self.assertRaises(SandboxSecurityError):
            exec(compile(code, '<test>', 'exec'), {'ET': xml.etree.ElementTree})

    def test_allow_submodules_false_exact_match_still_works(self):
        """With allow_submodules=False, exact module names are still allowed."""
        import xml.etree.ElementTree
        sys.sandbox.allowed_modules = {'xml.etree.ElementTree'}
        sys.sandbox.allow_submodules = False
        sys.sandbox.add_filename('<test>')

        code = 'result = ET.Element("root")'
        ns = {'ET': xml.etree.ElementTree}
        exec(compile(code, '<test>', 'exec'), ns)
        self.assertIsNotNone(ns['result'])

    def test_reset_clears_allowed_modules(self):
        """sys.sandbox.reset() clears allowed_modules."""
        sys.sandbox.allowed_modules = {'json', 'math'}
        sys.sandbox.reset()
        self.assertIsNone(sys.sandbox.allowed_modules)

    def test_restriction_mode_off_allows_all(self):
        """With module_access_restrict_mode=False, all modules are accessible."""
        import os
        sys.sandbox.module_access_restrict_mode = False
        sys.sandbox.add_filename('<test>')

        code = 'result = os.getcwd()'
        ns = {'os': os}
        exec(compile(code, '<test>', 'exec'), ns)
        self.assertIsNotNone(ns['result'])

    def test_cannot_modify_allowed_modules_from_scope(self):
        """Cannot modify allowed_modules from within sandbox scope."""
        sys.sandbox.allowed_modules = {'sys'}  # Allow sys for this test
        sys.sandbox.add_filename('<test>')

        code = 'sys.sandbox.allowed_modules = None'
        with self.assertRaises(SandboxSecurityError):
            exec(compile(code, '<test>', 'exec'), {'sys': sys})

    def test_multiple_allowed_modules(self):
        """Can allow multiple modules at once."""
        import json
        import math

        sys.sandbox.allowed_modules = {'json', 'math'}
        sys.sandbox.add_filename('<test>')

        # json should work
        ns = {}
        exec(compile('result = json.dumps({})', '<test>', 'exec'), {'json': json}, ns)
        self.assertEqual(ns['result'], '{}')

        # math should work
        ns = {}
        exec(compile('result = math.sqrt(4)', '<test>', 'exec'), {'math': math}, ns)
        self.assertEqual(ns['result'], 2.0)


class TestUseDefaultAllowedModules(unittest.TestCase):
    """Test cases for sys.sandbox.use_default_allowed_modules()."""

    def setUp(self):
        sys.sandbox.reset()

    def tearDown(self):
        sys.sandbox.reset()

    def test_use_default_sets_allowed_modules(self):
        """use_default_allowed_modules() sets allowed_modules to default safe list."""
        sys.sandbox.use_default_allowed_modules()
        allowed = sys.sandbox.allowed_modules
        self.assertIsNotNone(allowed)
        self.assertIsInstance(allowed, frozenset)
        # Check some expected modules are present
        self.assertIn('json', allowed)
        self.assertIn('math', allowed)
        self.assertIn('datetime', allowed)
        self.assertIn('collections', allowed)

    def test_use_default_excludes_dangerous_modules(self):
        """use_default_allowed_modules() excludes dangerous modules."""
        sys.sandbox.use_default_allowed_modules()
        allowed = sys.sandbox.allowed_modules
        # Dangerous modules should NOT be in the default list
        self.assertNotIn('os', allowed)
        self.assertNotIn('subprocess', allowed)
        self.assertNotIn('socket', allowed)
        self.assertNotIn('ctypes', allowed)
        self.assertNotIn('gc', allowed)
        self.assertNotIn('sys', allowed)
        self.assertNotIn('threading', allowed)
        self.assertNotIn('pickle', allowed)
        self.assertNotIn('marshal', allowed)
        self.assertNotIn('random', allowed)  # Excluded per user requirement

    def test_default_allows_safe_modules_in_scope(self):
        """Default allowed modules can be used in sandbox scope."""
        import json
        import math

        sys.sandbox.use_default_allowed_modules()
        sys.sandbox.add_filename('<test>')

        # json should work
        code = 'result = json.dumps({"a": 1})'
        ns = {'json': json}
        exec(compile(code, '<test>', 'exec'), ns)
        self.assertEqual(ns['result'], '{"a": 1}')

        # math should work
        code = 'result = math.sqrt(16)'
        ns = {'math': math}
        exec(compile(code, '<test>', 'exec'), ns)
        self.assertEqual(ns['result'], 4.0)

    def test_default_blocks_dangerous_modules_in_scope(self):
        """Default blocks dangerous modules even with pre-imported references."""
        import os

        sys.sandbox.use_default_allowed_modules()
        sys.sandbox.add_filename('<test>')

        code = 'result = os.getcwd()'
        with self.assertRaises(SandboxSecurityError):
            exec(compile(code, '<test>', 'exec'), {'os': os})


class TestModuleAccessSecurityScenarios(unittest.TestCase):
    """Security-focused test scenarios for module access restriction."""

    def setUp(self):
        sys.sandbox.reset()

    def tearDown(self):
        sys.sandbox.reset()

    def test_preimported_module_blocked(self):
        """Pre-imported modules are blocked even if imported before sandbox setup."""
        # Import os before setting up sandbox
        import os

        # Now set up sandbox without os in allowlist
        sys.sandbox.allowed_modules = {'json'}
        sys.sandbox.add_filename('<test>')

        # Access should be blocked even though module was imported earlier
        code = 'result = os_module.getcwd()'
        with self.assertRaises(SandboxSecurityError):
            exec(compile(code, '<test>', 'exec'), {'os_module': os})

    def test_module_reference_in_variable_blocked(self):
        """Module stored in a variable is still blocked."""
        import os
        saved_os = os

        sys.sandbox.allowed_modules = {'json'}
        sys.sandbox.add_filename('<test>')

        code = 'saved.getcwd()'
        with self.assertRaises(SandboxSecurityError):
            exec(compile(code, '<test>', 'exec'), {'saved': saved_os})

    def test_sys_blocked_prevents_sys_modules_access(self):
        """Cannot access sys.modules when sys is not allowed."""
        sys.sandbox.allowed_modules = {'json'}  # sys not allowed
        sys.sandbox.add_filename('<test>')

        code = 'modules = sys.modules'
        with self.assertRaises(SandboxSecurityError):
            exec(compile(code, '<test>', 'exec'), {'sys': sys})

    def test_bypass_attempt_via_module_alias(self):
        """Cannot bypass restriction by aliasing module."""
        import os
        aliased = os

        sys.sandbox.allowed_modules = {'json'}
        sys.sandbox.add_filename('<test>')

        code = 'result = aliased.getcwd()'
        with self.assertRaises(SandboxSecurityError):
            exec(compile(code, '<test>', 'exec'), {'aliased': aliased})

    def test_bypass_attempt_via_getattr(self):
        """Cannot bypass restriction by using getattr."""
        import os

        sys.sandbox.allowed_modules = {'json'}
        sys.sandbox.add_filename('<test>')

        # Even getattr triggers module_getattro
        code = 'result = getattr(os, "getcwd")()'
        with self.assertRaises(SandboxSecurityError):
            exec(compile(code, '<test>', 'exec'), {'os': os, 'getattr': getattr})


if __name__ == '__main__':
    unittest.main()
