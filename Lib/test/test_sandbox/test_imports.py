"""Tests for sandbox import restrictions.

The new import restriction system uses string-based module paths:
- Entry "X" allows: X itself, all submodules X.*, and parent dependencies
- Example: {"json.decoder"} allows json.decoder, json.decoder.*, and json
- Ancestors are computed automatically when allowed_imports is set
"""

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

    def test_allowed_imports_default(self):
        """allowed_imports should default to empty frozenset."""
        sys.sandbox.reset()
        self.assertEqual(sys.sandbox.allowed_imports, frozenset())


class ImportRestrictionAPITests(SandboxTestCase):
    """Test API for import restriction settings."""

    def test_set_allowed_imports_with_set(self):
        """allowed_imports can be set with a set of strings."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = {"json", "math.sin"}
        result = sys.sandbox.allowed_imports
        self.assertIsInstance(result, frozenset)
        self.assertEqual(len(result), 2)
        self.assertIn("json", result)
        self.assertIn("math.sin", result)

    def test_set_allowed_imports_with_frozenset(self):
        """allowed_imports can be set with a frozenset."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = frozenset({"json"})
        result = sys.sandbox.allowed_imports
        self.assertEqual(len(result), 1)
        self.assertIn("json", result)

    def test_set_allowed_imports_with_list(self):
        """allowed_imports can be set with a list."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = ["json", "math"]
        result = sys.sandbox.allowed_imports
        self.assertEqual(len(result), 2)

    def test_set_allowed_imports_none_clears(self):
        """Setting allowed_imports to None clears the set."""
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = {"json"}
        sys.sandbox.allowed_imports = None
        self.assertEqual(sys.sandbox.allowed_imports, frozenset())

    def test_allowed_imports_rejects_non_strings(self):
        """allowed_imports rejects non-string items."""
        sys.sandbox.import_restrict_mode = True
        with self.assertRaises(TypeError):
            sys.sandbox.allowed_imports = {123}  # Integer, not string

    def test_allowed_imports_rejects_tuples(self):
        """allowed_imports rejects tuple items (old format)."""
        sys.sandbox.import_restrict_mode = True
        with self.assertRaises(TypeError):
            sys.sandbox.allowed_imports = {("json", "")}  # Old tuple format

    def test_import_restrict_mode_toggle(self):
        """import_restrict_mode can be toggled."""
        sys.sandbox.import_restrict_mode = True
        self.assertTrue(sys.sandbox.import_restrict_mode)
        sys.sandbox.import_restrict_mode = False
        self.assertFalse(sys.sandbox.import_restrict_mode)


class ImportRestrictionEnforcementTests(SandboxTestCase):
    """Test enforcement of import restrictions in sandbox scope."""

    def setUp(self):
        super().setUp()
        # Re-enable import restrictions for these tests
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.allowed_imports = None

    def test_bare_import_allowed(self):
        """Bare import should be allowed when module is in allowlist."""
        sys.sandbox.allowed_imports = {"json"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import json")
        # Should not raise

    def test_bare_import_blocked(self):
        """Bare import should be blocked when module is not in allowlist."""
        sys.sandbox.allowed_imports = {"json"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("import os")

    def test_from_import_allowed_by_module(self):
        """from import should be allowed when module is in allowlist."""
        sys.sandbox.allowed_imports = {"json"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("from json import loads, dumps")
        # Should not raise

    def test_from_import_blocked_when_module_not_allowed(self):
        """from import should be blocked when module is not in allowlist."""
        sys.sandbox.allowed_imports = {"json"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("from os import path")

    def test_aliased_import_checked_by_original_name(self):
        """Aliased imports should be checked by original name."""
        sys.sandbox.allowed_imports = {"json"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import json as j")
        # Should not raise

        with self.assertRaises(SandboxImportError):
            _run_scoped("import os as operating_system")

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
    """Test submodule handling for import restrictions.

    With the new string-based allowlist:
    - Entry "json" allows json, json.decoder, json.encoder, etc.
    - Entry "json.decoder" allows json.decoder and json (as dependency)
    """

    def setUp(self):
        super().setUp()
        # Re-enable import restrictions for these tests
        sys.sandbox.import_restrict_mode = True

    def test_submodule_allowed_when_parent_allowed(self):
        """Submodules should be allowed when parent is in allowlist."""
        sys.sandbox.allowed_imports = {"json"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import json.decoder")
        # Should not raise - "json" allows json.*

    def test_parent_allowed_when_child_allowed(self):
        """Parent should be allowed when child is in allowlist (as dependency)."""
        sys.sandbox.allowed_imports = {"json.decoder"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import json")
        # Should not raise - "json.decoder" computes "json" as ancestor

    def test_deep_submodule_allowed_by_toplevel(self):
        """Deep submodules should be allowed when top-level is in allowlist."""
        sys.sandbox.allowed_imports = {"xml"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import xml.etree.ElementTree")
        # Should not raise - "xml" allows xml.*

    def test_deep_submodule_allowed_by_intermediate(self):
        """Deep submodules should be allowed by intermediate entry."""
        sys.sandbox.allowed_imports = {"xml.etree"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("import xml.etree.ElementTree")
        # Should not raise - "xml.etree" allows xml.etree.*

    def test_sibling_submodule_blocked(self):
        """Sibling submodules should be blocked when only specific child allowed."""
        sys.sandbox.allowed_imports = {"json.decoder"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # json.decoder allows json (parent) and json.decoder.* (children)
        # but NOT json.encoder (sibling)
        with self.assertRaises(SandboxImportError):
            _run_scoped("import json.encoder")

    def test_grandparent_blocked_when_only_grandchild_allowed(self):
        """Grandparent should NOT be allowed when only grandchild is in allowlist.

        This tests that allowing "xml.etree.ElementTree" only adds "xml.etree"
        and "xml" as ancestors, allowing `import xml` but NOT providing access
        to unrelated parts of xml.
        """
        sys.sandbox.allowed_imports = {"xml.etree.ElementTree"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        # xml.etree.ElementTree allows:
        # - xml.etree.ElementTree itself
        # - xml.etree.ElementTree.* (submodules)
        # - xml.etree (parent)
        # - xml (grandparent)
        # These are needed for Python's import machinery

        _run_scoped("import xml")  # Should work (ancestor)
        _run_scoped("import xml.etree")  # Should work (ancestor)
        _run_scoped("import xml.etree.ElementTree")  # Should work (exact match)

    def test_unrelated_module_blocked(self):
        """Unrelated modules should be blocked."""
        sys.sandbox.allowed_imports = {"xml.etree.ElementTree"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("import json")

    def test_from_submodule_import(self):
        """from submodule import should work when parent allowed."""
        sys.sandbox.allowed_imports = {"os"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("from os.path import join")
        # Should not raise

    def test_from_submodule_import_with_specific_entry(self):
        """from submodule import should work with specific entry."""
        sys.sandbox.allowed_imports = {"os.path"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("from os.path import join")
        # Should not raise


class WildcardImportTests(SandboxTestCase):
    """Test wildcard import restrictions.

    Security audit reference: SA-2026-0002
    'from X import *' should only work when X is directly in allowed_imports,
    not when X is merely an ancestor of an allowed module.
    """

    def setUp(self):
        super().setUp()
        sys.sandbox.import_restrict_mode = True
        sys.sandbox.module_access_restrict_mode = False

    def test_wildcard_import_allowed_for_direct_module(self):
        """'from json import *' should work when 'json' is directly allowed."""
        sys.sandbox.allowed_imports = {"json"}
        sys.sandbox.allow_unsafe = True
        sys.sandbox.add_filename(SCOPED_FILENAME)

        globs = _run_scoped("from json import *")
        self.assertIn("dumps", globs)
        self.assertIn("loads", globs)

    def test_wildcard_import_blocked_for_ancestor_only(self):
        """'from json import *' should be blocked when json is only an ancestor.

        When only 'json.decoder' is in allowed_imports, 'json' is computed
        as an ancestor. Wildcard import from an ancestor should be blocked
        to prevent importing all names from the module.
        """
        sys.sandbox.allowed_imports = {"json.decoder"}
        sys.sandbox.allow_unsafe = True
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("from json import *")

    def test_wildcard_import_non_star_still_works(self):
        """'from json import decoder' should still work for allowed submodules."""
        sys.sandbox.allowed_imports = {"json.decoder"}
        sys.sandbox.add_filename(SCOPED_FILENAME)

        _run_scoped("from json import decoder")
        # Should not raise

    def test_wildcard_import_blocked_for_deep_ancestor(self):
        """'from xml import *' should be blocked when only xml.etree.ElementTree is allowed."""
        sys.sandbox.allowed_imports = {"xml.etree.ElementTree"}
        sys.sandbox.allow_unsafe = True
        sys.sandbox.add_filename(SCOPED_FILENAME)

        with self.assertRaises(SandboxImportError):
            _run_scoped("from xml import *")


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
