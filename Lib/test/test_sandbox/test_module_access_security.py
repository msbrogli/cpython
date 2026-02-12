"""Tests for sys.modules access restrictions in sandbox.

This module tests that access to dangerous modules through sys.modules
is properly restricted when module_access_restrict_mode is enabled.

Security audit reference: Module access security
"""

import subprocess
import sys
import unittest

from test.test_sandbox import (
    ScopedFilenameTestCase,
    SUBPROCESS_TIMEOUT,
)


class SysModulesAccessTests(ScopedFilenameTestCase):
    """Test sys.modules access is properly restricted."""

    SCOPED_FILENAME = "<test_module_access_security_scope>"

    def test_sys_modules_access_allowed_when_unrestricted(self):
        """sys.modules should be accessible when restrictions disabled."""
        sys.sandbox.module_access_restrict_mode = False
        sys.sandbox.set_config(max_operations=10000)

        # Should work
        globs = self.run_scoped_code("mods = sys.modules")
        self.assertIsInstance(globs['mods'], dict)

    def test_sys_modules_blocked_when_restricted(self):
        """sys.modules access should be blocked when restrictions enabled."""
        sys.sandbox.module_access_restrict_mode = True
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises((AttributeError, SandboxSecurityError)):
            self.run_scoped_code("mods = sys.modules")


class ModuleImportRestrictionTests(ScopedFilenameTestCase):
    """Test import restrictions in sandbox scope."""

    SCOPED_FILENAME = "<test_module_access_security_scope>"

    def test_os_import_blocked_when_restricted(self):
        """os module import should be blocked when import_restrict_mode enabled."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises((ImportError, SandboxSecurityError, SandboxImportError)):
            self.run_scoped_code("import os")

    def test_os_import_allowed_when_unrestricted(self):
        """os module import should work when import_restrict_mode disabled."""
        sys.sandbox.import_restrict_mode = False
        sys.sandbox.set_config(max_operations=10000)

        # Should work
        globs = self.run_scoped_code("import os")
        self.assertIn('os', globs)


class AllowedModulesTests(ScopedFilenameTestCase):
    """Test allowed_modules configuration."""

    SCOPED_FILENAME = "<test_module_access_security_scope>"

    def tearDown(self):
        # Clear allowed modules
        try:
            sys.sandbox.allowed_modules = set()
        except:
            pass
        super().tearDown()

    def test_allowed_module_access_works(self):
        """Modules in allowed_modules can be accessed when passed in.

        Note: Import statements inside scope are blocked by import_restrict_mode.
        To use allowed modules, import them before entering scope and pass them in.
        """
        import json
        sys.sandbox.allowed_modules = {'json'}
        sys.sandbox.set_config(max_operations=10000)

        # Pass the pre-imported module to the scoped code
        globs = self.run_scoped_code("x = json.loads('[1, 2, 3]')", {"json": json})
        self.assertEqual(globs['x'], [1, 2, 3])

    def test_non_allowed_module_access_blocked(self):
        """Modules not in allowed_modules cannot be accessed even if passed in."""
        import os
        sys.sandbox.module_access_restrict_mode = True  # Enable restriction
        sys.sandbox.allowed_modules = {'json'}  # os not in allowed list
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("x = os.getcwd()", {"os": os})


class SubprocessModuleAccessTests(unittest.TestCase):
    """Subprocess tests for module access that need full isolation."""

    def test_os_system_blocked_in_restricted_mode(self):
        """os.system should not be accessible in restricted mode."""
        code = '''
import sys
sys.sandbox.enable()  # Required before entering scope
sys.sandbox.import_restrict_mode = True
sys.sandbox.module_access_restrict_mode = True
sys.sandbox.enter_scope()
# Try to import os - should raise SandboxImportError
import os
os.system("echo pwned")
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT
        )
        # Should fail with import error
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxImportError", result.stderr)

    def test_subprocess_blocked_in_restricted_mode(self):
        """subprocess module should not be accessible in restricted mode."""
        code = '''
import sys
sys.sandbox.enable()  # Required before entering scope
sys.sandbox.import_restrict_mode = True
sys.sandbox.module_access_restrict_mode = True
sys.sandbox.enter_scope()
# Try to import subprocess - should raise SandboxImportError
import subprocess
subprocess.run(["echo", "pwned"])
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT
        )
        # Should fail with import error
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxImportError", result.stderr)

    def test_builtins_open_blocked_when_io_disabled(self):
        """open() should be blocked when allow_io is False."""
        code = '''
import sys
sys.sandbox.set_config(allow_io=False)
sys.sandbox.enter_scope()
# Try to open a file - should raise SandboxSecurityError
f = open("/etc/passwd", "r")
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT
        )
        # Should fail with sandbox security error
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SandboxSecurityError", result.stderr)

    def test_preimported_module_accessible_when_unrestricted(self):
        """Pre-imported modules should be accessible when unrestricted."""
        code = '''
import sys
import os  # Pre-import before sandbox

sys.sandbox.enable()  # Required before entering scope
sys.sandbox.import_restrict_mode = False
sys.sandbox.module_access_restrict_mode = False
sys.sandbox.enter_scope()
try:
    # os is already imported
    cwd = os.getcwd()
    sys.exit(0)  # Expected to succeed
except Exception as e:
    print(f"Unexpected: {type(e).__name__}: {e}", file=sys.stderr)
    sys.exit(2)
'''
        result = subprocess.run(
            [sys.executable, '-c', code],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT
        )
        self.assertEqual(result.returncode, 0,
                        f"Test failed with stderr: {result.stderr}")


class BuiltinFunctionRestrictionTests(ScopedFilenameTestCase):
    """Test restrictions on dangerous builtin functions."""

    SCOPED_FILENAME = "<test_module_access_security_scope>"

    def test_compile_blocked_in_scope(self):
        """compile() is blocked in sandbox scope for security.

        Note: compile() and exec() are blocked to prevent code generation
        that could bypass sandbox restrictions.
        """
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("code = compile('x = 1', '<test>', 'exec')")

    def test_eval_blocked_in_scope(self):
        """eval() is blocked in sandbox scope for security.

        Note: eval() is blocked to prevent code execution that could
        bypass sandbox restrictions.
        """
        sys.sandbox.set_config(max_operations=10000)

        with self.assertRaises(SandboxSecurityError):
            self.run_scoped_code("result = eval('1 + 2')")


if __name__ == '__main__':
    unittest.main()
