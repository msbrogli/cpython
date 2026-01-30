/* Sandbox frozen mode and auto-mutable functionality
 *
 * This file contains functions for frozen mode (blocking attribute mutations)
 * and auto-mutable mode (automatically marking new objects as mutable).
 *
 * Implementation uses side tables (mutable_objects, frozen_objects sets)
 * instead of per-object flags to avoid ABI changes to PyObject.
 *
 * Objects are tracked using weak references where possible, allowing them
 * to be garbage collected when no other references exist. Objects that don't
 * support weak references (e.g., built-in type instances) fall back to
 * strong references.
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"

/* ============ Weak Reference Helpers ============ */

/* Add an object to a tracking set using weak references where possible.
 * Falls back to strong references for objects that don't support weakrefs.
 *
 * Returns 0 on success, -1 on error (but errors are typically cleared). */
static int
add_to_weak_set(PyObject **setp, PyObject *obj)
{
    /* Lazy-init the set */
    if (*setp == NULL) {
        *setp = PySet_New(NULL);
        if (*setp == NULL) {
            return -1;
        }
    }

    /* Try to create a weak reference (no callback needed) */
    PyObject *ref = PyWeakref_NewRef(obj, NULL);
    if (ref != NULL) {
        /* Object supports weak references - add the weakref */
        int rc = PySet_Add(*setp, ref);
        Py_DECREF(ref);
        return rc;
    }

    /* Object doesn't support weak references - clear error and use strong ref */
    PyErr_Clear();
    return PySet_Add(*setp, obj);
}

/* Check if an object is in a tracking set (handles both weak and strong refs).
 *
 * Returns 1 if found, 0 if not found, -1 on error (errors typically cleared). */
static int
in_weak_set(PyObject *set, PyObject *obj)
{
    if (set == NULL) {
        return 0;
    }

    /* Try weak reference lookup first */
    PyObject *ref = PyWeakref_NewRef(obj, NULL);
    if (ref != NULL) {
        int result = PySet_Contains(set, ref);
        Py_DECREF(ref);
        if (result >= 0) {
            return result;
        }
        /* Error in lookup - clear and try direct */
        PyErr_Clear();
    } else {
        /* Object doesn't support weakrefs - clear error */
        PyErr_Clear();
    }

    /* Fall back to direct lookup (for non-weakrefable objects) */
    int result = PySet_Contains(set, obj);
    if (result < 0) {
        PyErr_Clear();
        return 0;
    }
    return result;
}

/* Remove an object from a tracking set (handles both weak and strong refs).
 *
 * Returns 1 if removed, 0 if not found, -1 on error (errors typically cleared). */
static int
remove_from_weak_set(PyObject *set, PyObject *obj)
{
    if (set == NULL) {
        return 0;
    }

    /* Try weak reference removal first */
    PyObject *ref = PyWeakref_NewRef(obj, NULL);
    if (ref != NULL) {
        int result = PySet_Discard(set, ref);
        Py_DECREF(ref);
        if (result >= 0) {
            return result;
        }
        /* Error in discard - clear and try direct */
        PyErr_Clear();
    } else {
        /* Object doesn't support weakrefs - clear error */
        PyErr_Clear();
    }

    /* Fall back to direct removal (for non-weakrefable objects) */
    int result = PySet_Discard(set, obj);
    if (result < 0) {
        PyErr_Clear();
        return 0;
    }
    return result;
}

/* ============ Frozen Mode Checking ============ */

/* Check if attribute mutation is blocked on an object.
 * Returns 0 if mutation is allowed, -1 if blocked (sets SandboxAttributeError).
 *
 * Check order:
 * 1. Suspend state (if suspended, allow all mutations)
 * 2. Mutable set check (fast exit - always allow if in mutable set)
 * 3. Fast path: no frozen restrictions exist
 * 4. Scope check: only enforce within sandbox scope
 * 5. Frozen set check (individually frozen objects)
 * 6. Global frozen mode
 */
int
_PySandbox_CheckFrozen(PyObject *obj)
{
    /* NULL objects cannot be frozen - allow mutation */
    if (obj == NULL) {
        return 0;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL || interp->sandbox.suspended) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* Fast path: check mutable set first */
    if (sandbox->mutable_objects != NULL) {
        int in_mutable = in_weak_set(sandbox->mutable_objects, obj);
        if (in_mutable > 0) {
            return 0;  /* Allow - object is in mutable set */
        }
    }

    /* Check if object is individually frozen */
    int is_frozen = 0;
    if (sandbox->frozen_objects != NULL) {
        int in_frozen = in_weak_set(sandbox->frozen_objects, obj);
        if (in_frozen > 0) {
            is_frozen = 1;
        }
    }

    /* Fast path: no frozen restrictions exist */
    if (!is_frozen && !sandbox->frozen_mode) {
        return 0;
    }

    /* Frozen restrictions exist - only enforce within sandbox scope */
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;
    }
    if (!in_scope) {
        return 0;  /* Not in scope - allow */
    }

    if (is_frozen) {
        PyErr_Format(PyExc_SandboxAttributeError,
                     "cannot modify frozen object '%.100s'",
                     Py_TYPE(obj)->tp_name);
        return -1;
    }

    /* Global frozen mode (already checked it's true above) */
    PyErr_Format(PyExc_SandboxAttributeError,
                 "cannot modify '%.100s' object: sandbox frozen mode is active",
                 Py_TYPE(obj)->tp_name);
    return -1;
}

/* ============ Frozen Mode Get/Set ============ */

void
PySandbox_SetFrozenMode(int mode)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.frozen_mode = mode ? 1 : 0;
    }
}

int
PySandbox_GetFrozenMode(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }
    return interp->sandbox.frozen_mode;
}

/* ============ Per-Object Freeze/Mutable ============ */

void
PySandbox_FreezeObject(PyObject *obj)
{
    if (obj == NULL) {
        return;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    if (add_to_weak_set(&sandbox->frozen_objects, obj) < 0) {
        PyErr_Clear();
    }
}

int
PySandbox_IsObjectFrozen(PyObject *obj)
{
    if (obj == NULL) {
        return 0;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;
    return in_weak_set(sandbox->frozen_objects, obj);
}

void
PySandbox_SetObjectMutable(PyObject *obj, int mutable)
{
    if (obj == NULL) {
        return;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    if (mutable) {
        if (add_to_weak_set(&sandbox->mutable_objects, obj) < 0) {
            PyErr_Clear();
        }
    } else {
        remove_from_weak_set(sandbox->mutable_objects, obj);
    }
}

/* ============ Auto-Mutable Mode ============ */

/* _PySandbox_MaybeMarkMutable - conditionally add a newly created object
 * to the mutable_objects set when auto_mutable and frozen_mode are both
 * active and the current frame is within sandbox scope.
 *
 * This is called from MAKE_FUNCTION (ceval.c) and type_call (typeobject.c)
 * to automatically allow freshly created functions, classes, and instances
 * to be mutated while keeping imported modules frozen.
 *
 * Uses weak references where possible to allow garbage collection.
 */
void
_PySandbox_MaybeMarkMutable(PyObject *obj)
{
    assert(obj != NULL);
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return;
    }
    /* Fast path: both flags must be on */
    if (!interp->sandbox.auto_mutable || !interp->sandbox.frozen_mode) {
        return;
    }
    if (interp->sandbox.suspended) {
        return;
    }
    if (interp->sandbox.registered_filenames == NULL) {
        return;
    }
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    if (frame == NULL) {
        return;
    }
    int in_scope = frame_in_sandbox_scope(interp->sandbox.registered_filenames, frame);
    if (in_scope <= 0) {
        /* Not in scope or error - just return (void function) */
        if (in_scope < 0) {
            PyErr_Clear();
        }
        return;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    if (add_to_weak_set(&sandbox->mutable_objects, obj) < 0) {
        PyErr_Clear();
    }
}

void
PySandbox_SetAutoMutableMode(int mode)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp != NULL) {
        interp->sandbox.auto_mutable = mode ? 1 : 0;
    }
}

int
PySandbox_GetAutoMutableMode(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }
    return interp->sandbox.auto_mutable;
}
