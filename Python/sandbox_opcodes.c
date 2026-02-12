/* Sandbox opcode restriction functionality
 *
 * This file contains functions for allowing specific opcodes to execute
 * within sandbox scope (allowlist model).
 */

#include "Python.h"
#include "pycore_interp.h"
#include "pycore_pystate.h"
#include "pycore_sandbox.h"
#include "pycore_sandbox_impl.h"

/* ============ Opcode Checking ============ */

/* _PySandbox_CheckOpcode - Check if an opcode is allowed in sandbox scope
 *
 * Called from _PySandbox_CheckOpcodeDispatch() in ceval.c DISPATCH() macro
 * when the opcode is not in the allowed_opcodes bitmap.
 *
 * Fast exits:
 * - opcode_restrict_mode == 0 (not active)
 * - suspended or suppress_checks (recursion/error handling)
 * - opcode in allowed_opcodes bitmap
 * - current frame not in sandbox scope
 *
 * Returns: 0 if opcode allowed, -1 if not allowed (SandboxRuntimeError set)
 */
int
_PySandbox_CheckOpcode(int opcode)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return 0;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* Fast exit: mode not active */
    if (!sandbox->opcode_restrict_mode) {
        return 0;
    }

    /* Fast exit: sandbox not enforced (disabled, suspended, or in error handling) */
    if (!_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }

    /* Fast exit: opcode is allowed */
    if (_PySandbox_OpcodeSet_HAS(&sandbox->allowed_opcodes, opcode)) {
        return 0;
    }

    /* Opcode is not allowed - check if we're in sandbox scope */
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

    /* Disallowed opcode in sandbox scope - raise error */
    sandbox->suppress_checks = 1;
    PyErr_Format(PyExc_SandboxRuntimeError,
                 "Opcode %d is not allowed in sandbox scope", opcode);
    sandbox->suppress_checks = 0;
    return -1;
}

/* _PySandbox_BlockSpecializedOpcode - Block a specialized opcode in sandbox scope
 *
 * Called when allow_specialized_opcodes is False and a specialized opcode is
 * encountered. Unlike _PySandbox_CheckOpcode, this does NOT check the
 * allowed_opcodes bitmap - specialized opcodes are blocked regardless of
 * whether their numeric value happens to be in the allowed set.
 *
 * Returns: 0 if not in scope (allowed), -1 if in scope (error set)
 */
int
_PySandbox_BlockSpecializedOpcode(int opcode)
{
    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return 0;
    }

    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return 0;
    }

    _PySandboxState *sandbox = &interp->sandbox;

    /* Fast exit: sandbox not enforced (disabled, suspended, or in error handling) */
    if (!_PySandbox_IsEnforced(sandbox)) {
        return 0;
    }

    /* Check if we're in sandbox scope */
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

    /* Specialized opcode in sandbox scope - raise error */
    sandbox->suppress_checks = 1;
    PyErr_Format(PyExc_SandboxRuntimeError,
                 "Specialized opcode %d is not allowed in sandbox scope "
                 "(allow_specialized_opcodes is False)", opcode);
    sandbox->suppress_checks = 0;
    return -1;
}

/* ============ Opcode Restriction Mode Get/Set ============ */

void
PySandbox_SetOpcodeRestrictMode(int mode)
{
    /* Block from within sandbox scope. */
    if (_PySandbox_CheckConfigModification() < 0) {
        return;
    }

    PyThreadState *tstate = _PyThreadState_GET();
    if (tstate == NULL) {
        return;
    }
    PyInterpreterState *interp = tstate->interp;
    if (interp == NULL) {
        return;
    }
    interp->sandbox.opcode_restrict_mode = mode ? 1 : 0;
}

int
PySandbox_GetOpcodeRestrictMode(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        return 0;
    }
    return interp->sandbox.opcode_restrict_mode;
}

/* ============ Allowed Opcodes Get/Set ============ */

int
PySandbox_SetAllowedOpcodes(PyObject *opcode_set)
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

    _PySandboxOpcodeSet *allowed = &interp->sandbox.allowed_opcodes;

    /* None or empty -> clear all */
    if (opcode_set == Py_None) {
        _PySandbox_OpcodeSet_ZERO(allowed);
        return 0;
    }

    /* Must be an iterable of ints */
    PyObject *iter = PyObject_GetIter(opcode_set);
    if (iter == NULL) {
        return -1;
    }

    _PySandbox_OpcodeSet_ZERO(allowed);

    PyObject *item;
    while ((item = PyIter_Next(iter)) != NULL) {
        long op = PyLong_AsLong(item);
        Py_DECREF(item);
        if (op == -1 && PyErr_Occurred()) {
            Py_DECREF(iter);
            return -1;
        }
        if (op < 0 || op > 255) {
            PyErr_Format(PyExc_ValueError,
                         "opcode must be in range 0..255, got %ld", op);
            Py_DECREF(iter);
            return -1;
        }
        _PySandbox_OpcodeSet_SET(allowed, (int)op);
    }
    Py_DECREF(iter);

    if (PyErr_Occurred()) {
        return -1;  /* Error during iteration */
    }
    return 0;
}

PyObject *
PySandbox_GetAllowedOpcodes(void)
{
    PyInterpreterState *interp = _PyInterpreterState_GET();
    if (interp == NULL) {
        PyErr_SetString(PyExc_RuntimeError, "No interpreter state");
        return NULL;
    }

    _PySandboxOpcodeSet *allowed = &interp->sandbox.allowed_opcodes;

    PyObject *result = PySet_New(NULL);
    if (result == NULL) {
        return NULL;
    }

    for (int op = 0; op < 256; op++) {
        if (_PySandbox_OpcodeSet_HAS(allowed, op)) {
            PyObject *val = PyLong_FromLong(op);
            if (val == NULL) {
                Py_DECREF(result);
                return NULL;
            }
            if (PySet_Add(result, val) < 0) {
                Py_DECREF(val);
                Py_DECREF(result);
                return NULL;
            }
            Py_DECREF(val);
        }
    }

    PyObject *frozen = PyFrozenSet_New(result);
    Py_DECREF(result);
    return frozen;
}
