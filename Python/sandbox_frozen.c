/* Sandbox frozen mode and auto-mutable functionality
 *
 * This file contains functions for frozen mode (blocking attribute mutations)
 * and auto-mutable mode (automatically marking new objects as mutable).
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"

/* ============ Frozen Mode Checking ============ */

/* Check if attribute mutation is blocked on an object.
 * Returns 0 if mutation is allowed, -1 if blocked (sets SandboxAttributeError).
 *
 * Check order:
 * 1. Per-instance mutable flag (fast exit - always allow)
 * 2. Suspend state (if suspended, allow all mutations)
 * 3. Fast path: no frozen restrictions exist
 * 4. Scope check: only enforce within sandbox scope
 * 5. Per-instance frozen flag
 * 6. Global frozen mode
 */
int
_PySandbox_CheckFrozen(PyObject *obj)
{
    /* NULL objects cannot be frozen - allow mutation */
    if (obj == NULL) {
        return 0;
    }
    /* Fast path: mutable objects are always allowed */
    if (Py_IS_MUTABLE(obj)) {
        return 0;
    }

    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL || interp->sandbox.suspended) {
        return 0;
    }

    /* Fast path: no frozen restrictions exist */
    int obj_frozen = Py_IS_FROZEN(obj);
    if (!obj_frozen && !interp->sandbox.frozen_mode) {
        return 0;
    }

    /* Frozen restrictions exist - only enforce within sandbox scope */
    _PySandboxState *sandbox = &interp->sandbox;
    _PyInterpreterFrame *frame = get_current_iframe(NULL);
    int in_scope = frame_in_sandbox_scope(sandbox->registered_filenames, frame);
    if (in_scope < 0) {
        return -1;
    }
    if (!in_scope) {
        return 0;  /* Not in scope - allow */
    }

    if (obj_frozen) {
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
    obj->ob_flags |= Py_OBJFLAGS_FROZEN;
}

int
PySandbox_IsObjectFrozen(PyObject *obj)
{
    return (obj->ob_flags & Py_OBJFLAGS_FROZEN) != 0;
}

void
PySandbox_SetObjectMutable(PyObject *obj, int mutable)
{
    if (mutable) {
        obj->ob_flags |= Py_OBJFLAGS_MUTABLE;
    } else {
        obj->ob_flags &= ~Py_OBJFLAGS_MUTABLE;
    }
}

/* ============ Auto-Mutable Mode ============ */

/* _PySandbox_MaybeMarkMutable - conditionally mark a newly created object
 * as mutable (Py_OBJFLAGS_MUTABLE) when auto_mutable and frozen_mode
 * are both active and the current frame is within sandbox scope.
 *
 * This is called from MAKE_FUNCTION (ceval.c) and type_call (typeobject.c)
 * to automatically allow freshly created functions, classes, and instances
 * to be mutated while keeping imported modules frozen.
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
    obj->ob_flags |= Py_OBJFLAGS_MUTABLE;
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
