"""Tests for sandbox import restrictions."""

import sys
import unittest

from test.test_sandbox import SandboxTestCase, _run_sandboxed_code

# Filename used for scoped test code (distinct from test file)
SCOPED_FILENAME = "<test_imports_scope>"


def _run_scoped(code_str, extra_globals=None):
    """Execute code within sandbox scope using a separate filename."""
    globs = {"sys": sys}
    if extra_globals:
        globs.update(extra_globals)
    code = compile(code_str, SCOPED_FILENAME, "exec")
    exec(code, globs)
    return globs


class ImportRestrictionDefaultsTests(SandboxTestCase):
    """Test default values for import restriction settings."""

    def test_import_restrict_mode_default(self):
        """import_restrict_mode should default to True."""
        # Reset to defaults
        sys.sandbox.reset()
        self.assertTrue(sys.sandbox.import_restrict_mode)

    def test_import_allow_submodules_default(self):
        """import_allow_submodules should default to False."""
        sys.sandbox.reset()
        self.assertFalse(sys.sandbox.import_allow_submodules)

    def test_allowed_imports_default(self):
        """allowed_imports should default to empty frozenset."""
        sys.sandbox.reset()
        self.assertEqual(sys.sandbox.allowed_imports, frozenset())


class ImportRestrictionAPITests(SandboxTestCase):
    """Test API for import restriction settings."""

    def test_set_allowed_imports_with_set(self):
        """allowed_imports can be set with a set."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = {("json", ""), ("math", "sin")}
        result = sys.sandbox.allowed_imports
        self.assertIsInstance(result, frozenset)
        self.assertEqual(len(result), 2)
        self.assertIn(("json", ""), result)
        self.assertIn(("math", "sin"), result)

    def test_set_allowed_imports_with_frozenset(self):
        """allowed_imports can be set with a frozenset."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = frozenset({("json", "")})
        result = sys.sandbox.allowed_imports
        self.assertEqual(len(result), 1)
        self.assertIn(("json", ""), result)

    def test_set_allowed_imports_with_list(self):
        """allowed_imports can be set with a list."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = [("json", ""), ("math", "cos")]
        result = sys.sandbox.allowed_imports
        self.assertEqual(len(result), 2)

    def test_set_allowed_imports_none_clears(self):
        """Setting allowed_imports to None clears the set."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = {("json", "")}
        sys.sandbox.allowed_imports = None
        self.assertEqual(sys.sandbox.allowed_imports, frozenset())

    def test_allowed_imports_rejects_non_tuples(self):
        """allowed_imports rejects non-tuple items."""
        sys.sandbox.import_restrict_mode = True
        with self.assertRaises(TypeError):
            sys.sandbox.allowed_imports = {"json"}  # String, not tuple

    def test_allowed_imports_rejects_wrong_tuple_size(self):
        """allowed_imports rejects tuples with wrong size."""
        sys.sandbox.import_restrict_mode = True
        with self.assertRaises(TypeError):
            sys.sandbox.allowed_imports = {("json",)}  # 1-tuple
        with self.assertRaises(TypeError):
            sys.sandbox.allowed_imports = {("json", "", "extra")}  # 3-tuple

    def test_allowed_imports_rejects_non_strings(self):
        """allowed_imports rejects tuples with non-string elements."""
        sys.sandbox.import_restrict_mode = True
        with self.assertRaises(TypeError):
            sys.sandbox.allowed_imports = {(123, "")}

    def test_import_restrict_mode_toggle(self):
        """import_restrict_mode can be toggled."""
        sys.sandbox.import_restrict_mode = True
        self.assertTrue(sys.sandbox.import_restrict_mode)
        sys.sandbox.import_restrict_mode = False
        self.assertFalse(sys.sandbox.import_restrict_mode)

    def test_import_allow_submodules_toggle(self):
        """import_allow_submodules can be toggled."""
        sys.sandbox.import_allow_submodules = True
        self.assertTrue(sys.sandbox.import_allow_submodules)
        sys.sandbox.import_allow_submodules = False
        self.assertFalse(sys.sandbox.import_allow_submodules)


class ImportRestrictionEnforcementTests(SandboxTestCase):
    """Test enforcement of import restrictions in sandbox scope."""

    def setUp(self):
        super().setUp()
        # Re-enable import restrictions for these tests
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = None

    def test_bare_import_allowed(self):
        """Bare import should be allowed when module is in allowlist."""
        sys.sandbox.allowed_imports = {("json", "")}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import json")
        # Should not raise

    def test_bare_import_blocked(self):
        """Bare import should be blocked when module is not in allowlist."""
        sys.sandbox.allowed_imports = {("json", "")}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("import os")

    def test_from_import_allowed_by_module_wide(self):
        """from import should be allowed by module-wide allowance."""
        sys.sandbox.allowed_imports = {("json", "")}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("from json import loads, dumps")
        # Should not raise

    def test_from_import_allowed_by_specific(self):
        """from import should be allowed by specific allowance."""
        sys.sandbox.allowed_imports = {("math", "sin"), ("math", "cos")}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("from math import sin")
        _run_scoped("from math import cos")

    def test_from_import_blocked_by_missing_specific(self):
        """from import should be blocked when specific name is not allowed."""
        sys.sandbox.allowed_imports = {("math", "sin")}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("from math import sqrt")

    def test_from_import_multiple_blocked_if_any_missing(self):
        """from import with multiple names blocked if any name is not allowed."""
        sys.sandbox.allowed_imports = {("math", "sin")}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("from math import sin, sqrt")

    def test_aliased_import_checked_by_original_name(self):
        """Aliased imports should be checked by original name."""
        sys.sandbox.allowed_imports = {("json", "")}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import json as j")
        # Should not raise

        with self.assertRaises(SandboxImportError):
            _run_scoped("import os as operating_system")

    def test_aliased_from_import_checked_by_original_name(self):
        """Aliased from imports should be checked by original name."""
        sys.sandbox.allowed_imports = {("json", "dumps")}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("from json import dumps as d")
        # Should not raise

        sys.sandbox.allowed_imports = {("math", "sin")}
        with self.assertRaises(SandboxImportError):
            _run_scoped("from math import sqrt as s")

    def test_empty_allowlist_blocks_all(self):
        """Empty allowlist should block all imports."""
        sys.sandbox.allowed_imports = set()
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("import sys")

    def test_mode_off_allows_all(self):
        """Disabled import_restrict_mode should allow all imports."""
        sys.sandbox.import_restrict_mode = False
        sys.sandbox.allowed_imports = set()
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import json")
        _run_scoped("import os")
        # Should not raise

    def test_outside_scope_allows_all(self):
        """Imports outside scope should be allowed regardless of restrictions."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = set()
        # Don't add any filename to scope

        import json  # Should work - outside scope
        # Clean up
        sys.modules.pop('json', None)


class ImportSubmoduleTests(SandboxTestCase):
    """Test submodule handling for import restrictions."""

    def setUp(self):
        super().setUp()
        # Re-enable import restrictions for these tests
        sys.sandbox.import_restrict_mode = True

    def test_submodule_blocked_by_default(self):
        """Submodules should be blocked by default even if parent is allowed."""
        sys.sandbox.allowed_imports = {("json", "")}
        sys.sandbox.import_allow_submodules = False
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("import json.decoder")

    def test_submodule_allowed_with_flag(self):
        """Submodules should be allowed when import_allow_submodules is True."""
        sys.sandbox.allowed_imports = {("json", "")}
        sys.sandbox.import_allow_submodules = True
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import json.decoder")
        # Should not raise

    def test_submodule_requires_parent_allowed(self):
        """Submodule auto-allow requires parent to have module-wide allow."""
        sys.sandbox.allowed_imports = {("json", "loads")}  # Not module-wide
        sys.sandbox.import_allow_submodules = True
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("import json.decoder")

    def test_submodule_allowed_by_module_wide(self):
        """import a.b allowed by ("a", "") module-wide."""
        sys.sandbox.allowed_imports = {("json", "")}
        sys.sandbox.import_allow_submodules = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("import json.decoder")

    def test_submodule_allowed_by_specific_name(self):
        """import a.b allowed by ("a", "b") specific name."""
        sys.sandbox.allowed_imports = {("json", "decoder")}
        sys.sandbox.import_allow_submodules = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("import json.decoder")

    def test_deep_submodule_allowed_by_intermediate_specific(self):
        """import a.b.c allowed by ("a.b", "c") specific."""
        sys.sandbox.allowed_imports = {("xml.etree", "ElementTree")}
        sys.sandbox.import_allow_submodules = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("import xml.etree.ElementTree")

    def test_deep_submodule_allowed_by_toplevel_wide(self):
        """import a.b.c allowed by ("a", "") module-wide."""
        sys.sandbox.allowed_imports = {("xml", "")}
        sys.sandbox.import_allow_submodules = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("import xml.etree.ElementTree")

    def test_from_submodule_allowed_by_ancestor_specific(self):
        """from a.b import c allowed by ("a", "b") specific."""
        sys.sandbox.allowed_imports = {("os", "path")}
        sys.sandbox.import_allow_submodules = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("from os.path import join")

    def test_from_submodule_allowed_by_ancestor_wide(self):
        """from a.b import c allowed by ("a", "") module-wide."""
        sys.sandbox.allowed_imports = {("os", "")}
        sys.sandbox.import_allow_submodules = True
        sys.sandbox.add_filename(SCOPED_FILENAME)
        _run_scoped("from os.path import join")

    def test_submodule_not_allowed_without_flag(self):
        """Submodule NOT allowed without import_allow_submodules even with parent allowed."""
        sys.sandbox.allowed_imports = {("os", "")}
        sys.sandbox.import_allow_submodules = False
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxImportError):
            _run_scoped("import os.path")

    def test_from_submodule_not_allowed_without_flag(self):
        """from a.b import c NOT allowed without import_allow_submodules."""
        sys.sandbox.allowed_imports = {("os", "")}
        sys.sandbox.import_allow_submodules = False
        sys.sandbox.add_filename(SCOPED_FILENAME)
        with self.assertRaises(SandboxImportError):
            _run_scoped("from os.path import join")


class ImportSuspendedTests(SandboxTestCase):
    """Test import restrictions when sandbox is suspended."""

    def setUp(self):
        super().setUp()
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = set()

    def test_suspended_allows_imports(self):
        """Suspended sandbox should allow imports."""
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # Should be blocked normally
        with self.assertRaises(SandboxImportError):
            _run_scoped("import json")

        # Should be allowed when suspended
        sys.sandbox.suspend()
        try:
            _run_scoped("import json")
        finally:
            sys.sandbox.resume()


if __name__ == '__main__':
    unittest.main()
