/* Sandbox import restrictions
 *
 * This module implements the import restriction system for the sandbox.
 * When import_restrict_mode is enabled and code is executing in sandbox scope,
 * only imports matching entries in the allowed_imports set are permitted.
 *
 * Allowlist format: set of tuples (module_name, import_name)
 * - ("json", "") allows `import json` and all `from json import X`
 * - ("json", "loads") allows only `from json import loads`
 * - ("json", "*") allows `from json import *`
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"

/* Pre-allocated empty string for building keys */
static PyObject *_empty_str = NULL;

/* Ensure the empty string is initialized */
static PyObject *
get_empty_str(void)
{
    if (_empty_str == NULL) {
        _empty_str = PyUnicode_InternFromString("");
        if (_empty_str == NULL) {
            return NULL;
        }
    }
    return _empty_str;
}

/* Check if a specific (module, name) pair is allowed.
 * Returns: 1 if allowed, 0 if not allowed, -1 on error */
static int
check_import_allowed(_PySandboxState *sandbox, PyObject *module_name, PyObject *import_name)
{
    if (sandbox->allowed_imports == NULL) {
        return 0;
    }

    PyObject *key = PyTuple_Pack(2, module_name, import_name);
    if (key == NULL) {
        return -1;
    }

    int result = PySet_Contains(sandbox->allowed_imports, key);
    Py_DECREF(key);
    return result;
}

/* Check if module-wide access is allowed (module, "").
 * This allows both `import module` and all `from module import X` forms.
 * Returns: 1 if allowed, 0 if not allowed, -1 on error */
static int
check_module_wide_allowed(_PySandboxState *sandbox, PyObject *module_name)
{
    PyObject *empty = get_empty_str();
    if (empty == NULL) {
        return -1;
    }
    return check_import_allowed(sandbox, module_name, empty);
}

/* Check if any submodule entry exists for a module.
 * This checks if there's ANY:
 *   - ("module", X) where X is non-empty, OR
 *   - ("module.Y", X) for any Y (indicating a nested submodule)
 * Used to allow parent imports when a specific submodule is allowed.
 * Returns: 1 if any entry exists, 0 if none, -1 on error */
static int
check_has_any_submodule_entry(_PySandboxState *sandbox, PyObject *module_name)
{
    if (sandbox->allowed_imports == NULL) {
        return 0;
    }

    if (!sandbox->limits.import_allow_submodules) {
        return 0;
    }

    const char *module_str = PyUnicode_AsUTF8(module_name);
    if (module_str == NULL) {
        return -1;
    }
    Py_ssize_t module_len = (Py_ssize_t)strlen(module_str);

    /* Iterate through allowed_imports */
    PyObject *iter = PyObject_GetIter(sandbox->allowed_imports);
    if (iter == NULL) {
        return -1;
    }

    PyObject *item;
    while ((item = PyIter_Next(iter)) != NULL) {
        if (!PyTuple_Check(item) || PyTuple_GET_SIZE(item) != 2) {
            Py_DECREF(item);
            continue;
        }

        PyObject *mod = PyTuple_GET_ITEM(item, 0);
        PyObject *name = PyTuple_GET_ITEM(item, 1);

        if (!PyUnicode_Check(mod)) {
            Py_DECREF(item);
            continue;
        }

        const char *mod_str = PyUnicode_AsUTF8(mod);
        if (mod_str == NULL) {
            Py_DECREF(item);
            Py_DECREF(iter);
            return -1;
        }
        Py_ssize_t mod_len = (Py_ssize_t)strlen(mod_str);

        /* Check if module matches exactly and name is non-empty */
        if (mod_len == module_len && memcmp(mod_str, module_str, module_len) == 0) {
            if (PyUnicode_Check(name) && PyUnicode_GET_LENGTH(name) > 0) {
                /* Found ("module", "submodule") entry */
                Py_DECREF(item);
                Py_DECREF(iter);
                return 1;
            }
        }

        /* Check if mod starts with "module." (nested submodule) */
        if (mod_len > module_len + 1 &&
            memcmp(mod_str, module_str, module_len) == 0 &&
            mod_str[module_len] == '.') {
            /* Found ("module.something", X) entry */
            Py_DECREF(item);
            Py_DECREF(iter);
            return 1;
        }

        Py_DECREF(item);
    }
    Py_DECREF(iter);

    if (PyErr_Occurred()) {
        return -1;
    }

    return 0;
}

/* Check if any ancestor allows this submodule import.
 * For "a.b.c", checks in order:
 *   ("a.b", "c"), ("a.b", ""), ("a", "b"), ("a", "")
 * Returns: 1 if any ancestor allowed, 0 if none allowed, -1 on error */
static int
check_submodule_allowed(_PySandboxState *sandbox, PyObject *abs_name)
{
    if (!sandbox->limits.import_allow_submodules) {
        return 0;
    }

    const char *name_str = PyUnicode_AsUTF8(abs_name);
    if (name_str == NULL) {
        return -1;
    }

    Py_ssize_t name_len = (Py_ssize_t)strlen(name_str);

    /* Find the last dot - if none, not a submodule */
    Py_ssize_t dot_pos = name_len - 1;
    while (dot_pos >= 0 && name_str[dot_pos] != '.') {
        dot_pos--;
    }
    if (dot_pos < 0) {
        return 0;
    }

    /* Walk up the module hierarchy checking each level */
    while (dot_pos >= 0) {
        Py_ssize_t parent_len = dot_pos;
        const char *child_start = name_str + dot_pos + 1;

        /* Find end of child component (next dot or end of string) */
        const char *child_end = strchr(child_start, '.');
        Py_ssize_t child_len = child_end ? (child_end - child_start) : (Py_ssize_t)strlen(child_start);

        PyObject *parent_name = PyUnicode_FromStringAndSize(name_str, parent_len);
        if (parent_name == NULL) {
            return -1;
        }

        PyObject *child_name = PyUnicode_FromStringAndSize(child_start, child_len);
        if (child_name == NULL) {
            Py_DECREF(parent_name);
            return -1;
        }

        /* Check ("parent", "child") - specific submodule access */
        int result = check_import_allowed(sandbox, parent_name, child_name);
        Py_DECREF(child_name);

        if (result < 0) {
            Py_DECREF(parent_name);
            return -1;
        }
        if (result) {
            Py_DECREF(parent_name);
            return 1;  /* Specific submodule access allowed */
        }

        /* Check ("parent", "") - module-wide access */
        result = check_module_wide_allowed(sandbox, parent_name);
        Py_DECREF(parent_name);

        if (result < 0) {
            return -1;
        }
        if (result) {
            return 1;  /* Module-wide access allowed */
        }

        /* Move to next ancestor: find previous dot */
        dot_pos--;
        while (dot_pos >= 0 && name_str[dot_pos] != '.') {
            dot_pos--;
        }
    }

    return 0;  /* No ancestor allowed */
}

/* Main import check function.
 * Returns: 0 if import is allowed, -1 if blocked (sets SandboxImportError) */
int
_PySandbox_CheckImport(PyObject *abs_name, PyObject *fromlist)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL || tstate->interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &tstate->interp->sandbox;

    /* Fast exit: mode off */
    if (!sandbox->limits.import_restrict_mode) {
        return 0;
    }

    /* Fast exit: suspended or suppress_checks */
    if (sandbox->suspended || sandbox->suppress_checks) {
        return 0;
    }

    /* Fast exit: not in sandbox scope */
    if (sandbox->registered_filenames == NULL) {
        return 0;
    }

    _PyInterpreterFrame *frame = get_current_iframe(tstate);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;
    }
    if (!in_scope) {
        return 0;
    }

    /* Now we're in sandbox scope with import restrictions enabled */

    /* If no allowed_imports set, block everything */
    if (sandbox->allowed_imports == NULL) {
        goto blocked;
    }

    int allowed;

    /* For bare import (fromlist is NULL or empty):
     * Check ("module", "") */
    if (fromlist == NULL || fromlist == Py_None ||
        (PyTuple_Check(fromlist) && PyTuple_GET_SIZE(fromlist) == 0)) {

        /* Check exact module-wide match */
        allowed = check_module_wide_allowed(sandbox, abs_name);
        if (allowed < 0) {
            return -1;
        }
        if (allowed) {
            return 0;
        }

        /* Check submodule allowance */
        allowed = check_submodule_allowed(sandbox, abs_name);
        if (allowed < 0) {
            return -1;
        }
        if (allowed) {
            return 0;
        }

        /* Check if this module has any allowed submodule entries.
         * This allows importing parent modules as dependencies, e.g.,
         * ("json", "decoder") allows `import json` as part of `import json.decoder` */
        allowed = check_has_any_submodule_entry(sandbox, abs_name);
        if (allowed < 0) {
            return -1;
        }
        if (allowed) {
            return 0;
        }

        goto blocked;
    }

    /* For "from X import a, b, c":
     * First check if ("module", "") allows everything */
    allowed = check_module_wide_allowed(sandbox, abs_name);
    if (allowed < 0) {
        return -1;
    }
    if (allowed) {
        return 0;  /* Module-wide allow covers all from imports */
    }

    /* Check submodule allowance (for from a.b import c) */
    allowed = check_submodule_allowed(sandbox, abs_name);
    if (allowed < 0) {
        return -1;
    }
    if (allowed) {
        return 0;  /* Ancestor module allows this submodule */
    }

    /* Check each item in fromlist */
    if (!PyTuple_Check(fromlist)) {
        /* Unexpected fromlist type, be conservative and block */
        goto blocked;
    }

    Py_ssize_t n = PyTuple_GET_SIZE(fromlist);
    for (Py_ssize_t i = 0; i < n; i++) {
        PyObject *item = PyTuple_GET_ITEM(fromlist, i);

        allowed = check_import_allowed(sandbox, abs_name, item);
        if (allowed < 0) {
            return -1;
        }
        if (!allowed) {
            goto blocked;
        }
    }

    return 0;  /* All items in fromlist are allowed */

blocked:
    sandbox->suppress_checks = 1;
    PyErr_Format(PyExc_SandboxImportError,
                 "Import of '%U' is not allowed in sandbox scope", abs_name);
    sandbox->suppress_checks = 0;
    return -1;
}

/* Set the import allowlist.
 * Accepts: set, frozenset, or any iterable of (module, name) tuples.
 * Passing None clears the allowlist.
 * Internally stores a frozenset for O(1) getter and immutability. */
int
PySandbox_SetAllowedImports(PyObject *modules)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* None clears the allowlist */
    if (modules == Py_None) {
        Py_CLEAR(sandbox->allowed_imports);
        return 0;
    }

    /* Create a temporary set from the iterable for validation */
    PyObject *temp_set = PySet_New(modules);
    if (temp_set == NULL) {
        return -1;
    }

    /* Validate all items are 2-tuples of strings */
    PyObject *iter = PyObject_GetIter(temp_set);
    if (iter == NULL) {
        Py_DECREF(temp_set);
        return -1;
    }

    PyObject *item;
    while ((item = PyIter_Next(iter)) != NULL) {
        if (!PyTuple_Check(item) || PyTuple_GET_SIZE(item) != 2) {
            PyErr_SetString(PyExc_TypeError,
                "allowed_imports must contain 2-tuples of (module_name, import_name)");
            Py_DECREF(item);
            Py_DECREF(iter);
            Py_DECREF(temp_set);
            return -1;
        }

        PyObject *mod = PyTuple_GET_ITEM(item, 0);
        PyObject *name = PyTuple_GET_ITEM(item, 1);

        if (!PyUnicode_Check(mod) || !PyUnicode_Check(name)) {
            PyErr_SetString(PyExc_TypeError,
                "allowed_imports tuples must contain strings");
            Py_DECREF(item);
            Py_DECREF(iter);
            Py_DECREF(temp_set);
            return -1;
        }

        Py_DECREF(item);
    }
    Py_DECREF(iter);

    if (PyErr_Occurred()) {
        Py_DECREF(temp_set);
        return -1;
    }

    /* Convert to frozenset for immutability and O(1) getter */
    PyObject *new_frozenset = PyFrozenSet_New(temp_set);
    Py_DECREF(temp_set);
    if (new_frozenset == NULL) {
        return -1;
    }

    /* Replace the old frozenset */
    Py_XDECREF(sandbox->allowed_imports);
    sandbox->allowed_imports = new_frozenset;
    return 0;
}

/* Get the import allowlist as a frozenset (O(1), returns new reference). */
PyObject *
PySandbox_GetAllowedImports(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return NULL;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    if (sandbox->allowed_imports == NULL) {
        /* Return empty frozenset */
        return PyFrozenSet_New(NULL);
    }

    /* Return new reference to the stored frozenset */
    Py_INCREF(sandbox->allowed_imports);
    return sandbox->allowed_imports;
}
