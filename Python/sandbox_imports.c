/* Sandbox import restrictions
 *
 * This module implements the import restriction system for the sandbox.
 * When import_restrict_mode is enabled and code is executing in sandbox scope,
 * only imports matching entries in the allowed_imports set are permitted.
 *
 * Allowlist format: set of module path strings
 * - "json" allows `import json` and all submodules like `import json.decoder`
 * - "json.decoder" allows `import json.decoder` and `import json` (as dependency)
 *   but NOT `import json.encoder`
 *
 * Check algorithm (O(p) where p = number of parts in module path):
 * 1. Check each prefix of the module against allowed_imports
 * 2. If no prefix match, check exact module against allowed_ancestors
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"

#include <string.h>

/* Forward declaration */
static int compute_ancestors(_PySandboxState *sandbox);

/* Check if a module path is allowed.
 * Algorithm:
 * 1. Check if module or any of its prefixes is in allowed_imports
 *    (this handles: exact match and "module is submodule of allowed entry")
 * 2. Check if module is in allowed_ancestors
 *    (this handles: "module is a required dependency of an allowed entry")
 *
 * Returns: 1 if allowed, 0 if not allowed, -1 on error */
static int
is_module_allowed(_PySandboxState *sandbox, const char *module_str)
{
    if (sandbox->allowed_imports == NULL) {
        return 0;
    }

    size_t module_len = strlen(module_str);

    /* Check each prefix of the module (including the full module) */
    for (size_t i = 0; i <= module_len; i++) {
        if (i == module_len || module_str[i] == '.') {
            /* Build prefix string */
            PyObject *prefix = PyUnicode_FromStringAndSize(module_str, i);
            if (prefix == NULL) {
                return -1;
            }

            /* Check if prefix is in allowed_imports */
            int result = PySet_Contains(sandbox->allowed_imports, prefix);
            Py_DECREF(prefix);

            if (result < 0) {
                return -1;
            }
            if (result) {
                return 1;  /* Found: module or ancestor is directly allowed */
            }
        }
    }

    /* Check if module is a required dependency (in allowed_ancestors) */
    if (sandbox->allowed_ancestors != NULL) {
        PyObject *module_obj = PyUnicode_FromString(module_str);
        if (module_obj == NULL) {
            return -1;
        }

        int result = PySet_Contains(sandbox->allowed_ancestors, module_obj);
        Py_DECREF(module_obj);

        if (result < 0) {
            return -1;
        }
        if (result) {
            return 1;  /* Module is a required dependency */
        }
    }

    return 0;  /* Not allowed */
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
    if (!sandbox->config.import_restrict_mode) {
        return 0;
    }

    /* Fast exit: sandbox not enforced (disabled, suspended, or in error handling) */
    if (!_PySandbox_IsEnforced(sandbox)) {
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

    const char *abs_str = PyUnicode_AsUTF8(abs_name);
    if (abs_str == NULL) {
        return -1;
    }

    /* Check if base module is allowed */
    int base_allowed = is_module_allowed(sandbox, abs_str);
    if (base_allowed < 0) {
        return -1;
    }

    /* For "from X import a, b, c", we need to check each potential submodule.
     * Even if X is allowed (e.g., as an ancestor), we must verify that each
     * X.item is also allowed, since items might be submodules that bypass
     * the import check (e.g., 'from json import encoder' when only
     * 'json.decoder' is whitelisted should block json.encoder).
     *
     * However, items could also be functions/classes (e.g., 'from json import loads'),
     * so we only block if X.item looks like it would be blocked as a module import
     * AND the item appears to be a submodule (has a corresponding entry or prefix). */
    if (fromlist != NULL && fromlist != Py_None && PyTuple_Check(fromlist)) {
        Py_ssize_t n = PyTuple_GET_SIZE(fromlist);
        for (Py_ssize_t i = 0; i < n; i++) {
            PyObject *item = PyTuple_GET_ITEM(fromlist, i);
            if (!PyUnicode_Check(item)) {
                continue;
            }

            /* Skip wildcard imports - they import everything from __all__ */
            const char *item_str = PyUnicode_AsUTF8(item);
            if (item_str == NULL) {
                return -1;
            }
            if (strcmp(item_str, "*") == 0) {
                /* For wildcard imports, only allow if base module is directly allowed */
                PyObject *base_obj = PyUnicode_FromString(abs_str);
                if (base_obj == NULL) {
                    return -1;
                }
                int base_direct = PySet_Contains(sandbox->allowed_imports, base_obj);
                Py_DECREF(base_obj);
                if (base_direct < 0) {
                    return -1;
                }
                if (!base_direct) {
                    goto blocked;
                }
                continue;
            }

            /* Build full path: abs_name.item */
            PyObject *full_path = PyUnicode_FromFormat("%s.%U", abs_str, item);
            if (full_path == NULL) {
                return -1;
            }

            const char *full_str = PyUnicode_AsUTF8(full_path);
            if (full_str == NULL) {
                Py_DECREF(full_path);
                return -1;
            }

            /* Check if this full path is allowed.
             * If not allowed, this from-import should be blocked. */
            int item_allowed = is_module_allowed(sandbox, full_str);

            if (item_allowed < 0) {
                Py_DECREF(full_path);
                return -1;
            }

            /* If item is not allowed and base was allowed only as ancestor,
             * block the import. This prevents accessing sibling submodules
             * like 'from json import encoder' when only 'json.decoder' is allowed.
             * Note: If base is directly allowed (e.g., {"json"} in allowlist),
             * then all submodules are implicitly allowed. */
            if (!item_allowed) {
                /* Check if base is directly in allowed_imports (not just as ancestor) */
                PyObject *base_obj = PyUnicode_FromString(abs_str);
                if (base_obj == NULL) {
                    Py_DECREF(full_path);
                    return -1;
                }
                int base_direct = PySet_Contains(sandbox->allowed_imports, base_obj);
                Py_DECREF(base_obj);

                if (base_direct < 0) {
                    Py_DECREF(full_path);
                    return -1;
                }

                /* If base is not directly allowed, block this submodule access */
                if (!base_direct) {
                    sandbox->suppress_checks = 1;
                    PyErr_Format(PyExc_SandboxImportError,
                                 "Import of '%U' is not allowed in sandbox scope",
                                 full_path);
                    sandbox->suppress_checks = 0;
                    Py_DECREF(full_path);
                    return -1;
                }
            }

            Py_DECREF(full_path);
        }
    }

    /* If we get here, either:
     * 1. Base module is allowed (as direct entry or prefix of something allowed)
     * 2. All fromlist items are allowed
     * Either way, allow the import. */
    if (base_allowed) {
        return 0;
    }

blocked:
    sandbox->suppress_checks = 1;
    PyErr_Format(PyExc_SandboxImportError,
                 "Import of '%U' is not allowed in sandbox scope", abs_name);
    sandbox->suppress_checks = 0;
    return -1;
}

/* Compute allowed_ancestors from allowed_imports.
 * For each entry in allowed_imports, add all its parent prefixes to allowed_ancestors.
 * Example: "json.decoder.JSONDecoder" adds "json" and "json.decoder" to ancestors.
 * Returns: 0 on success, -1 on error */
static int
compute_ancestors(_PySandboxState *sandbox)
{
    /* Clear existing ancestors */
    Py_CLEAR(sandbox->allowed_ancestors);

    if (sandbox->allowed_imports == NULL) {
        return 0;
    }

    /* Create new ancestors set */
    PyObject *ancestors = PySet_New(NULL);
    if (ancestors == NULL) {
        return -1;
    }

    /* Iterate through allowed_imports */
    PyObject *iter = PyObject_GetIter(sandbox->allowed_imports);
    if (iter == NULL) {
        Py_DECREF(ancestors);
        return -1;
    }

    PyObject *entry;
    while ((entry = PyIter_Next(iter)) != NULL) {
        const char *entry_str = PyUnicode_AsUTF8(entry);
        if (entry_str == NULL) {
            Py_DECREF(entry);
            Py_DECREF(iter);
            Py_DECREF(ancestors);
            return -1;
        }

        /* Find each '.' and add the prefix as an ancestor */
        size_t len = strlen(entry_str);
        for (size_t i = 0; i < len; i++) {
            if (entry_str[i] == '.') {
                PyObject *prefix = PyUnicode_FromStringAndSize(entry_str, i);
                if (prefix == NULL) {
                    Py_DECREF(entry);
                    Py_DECREF(iter);
                    Py_DECREF(ancestors);
                    return -1;
                }

                int result = PySet_Add(ancestors, prefix);
                Py_DECREF(prefix);

                if (result < 0) {
                    Py_DECREF(entry);
                    Py_DECREF(iter);
                    Py_DECREF(ancestors);
                    return -1;
                }
            }
        }

        Py_DECREF(entry);
    }
    Py_DECREF(iter);

    if (PyErr_Occurred()) {
        Py_DECREF(ancestors);
        return -1;
    }

    /* Store the ancestors (or NULL if empty) */
    if (PySet_GET_SIZE(ancestors) == 0) {
        Py_DECREF(ancestors);
        sandbox->allowed_ancestors = NULL;
    } else {
        sandbox->allowed_ancestors = ancestors;
    }

    return 0;
}

/* Set the import allowlist.
 * Accepts: set, frozenset, or any iterable of module path strings.
 * Passing None clears the allowlist.
 * Internally stores a frozenset for O(1) lookup and computes ancestors. */
int
PySandbox_SetAllowedImports(PyObject *modules)
{
    /* Block from within sandbox scope. */
    if (_PySandbox_CheckConfigModification() < 0) {
        return -1;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return -1;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* None clears the allowlist */
    if (modules == Py_None) {
        Py_CLEAR(sandbox->allowed_imports);
        Py_CLEAR(sandbox->allowed_ancestors);
        return 0;
    }

    /* Create a temporary set from the iterable for validation */
    PyObject *temp_set = PySet_New(modules);
    if (temp_set == NULL) {
        return -1;
    }

    /* Validate all items are strings */
    PyObject *iter = PyObject_GetIter(temp_set);
    if (iter == NULL) {
        Py_DECREF(temp_set);
        return -1;
    }

    PyObject *item;
    while ((item = PyIter_Next(iter)) != NULL) {
        if (!PyUnicode_Check(item)) {
            PyErr_SetString(PyExc_TypeError,
                "allowed_imports must contain module path strings");
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

    /* Convert to frozenset for immutability and O(1) lookup */
    PyObject *new_frozenset = PyFrozenSet_New(temp_set);
    Py_DECREF(temp_set);
    if (new_frozenset == NULL) {
        return -1;
    }

    /* Replace the old frozenset */
    Py_XDECREF(sandbox->allowed_imports);
    sandbox->allowed_imports = new_frozenset;

    /* Compute ancestors */
    if (compute_ancestors(sandbox) < 0) {
        Py_CLEAR(sandbox->allowed_imports);
        return -1;
    }

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
